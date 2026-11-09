"""Per-agency metrics and indicators for the public site. Writes data/derived/indicators.json.

Hospice indicators are only the checks that held up in scripts/backtest_indicators.py (rules and results in
out/indicator_backtest.md), applied to the latest data with the same definitions. Home health checks did not hold up,
so home health agencies get metrics and national percentiles but no indicators.

No combined score. A missing value is "not assessed". Indicators apply to agencies, never to people.

Usage: .venv/bin/python -I scripts/build_indicators.py [project_dir]
"""
import bisect
import json
import sys
from pathlib import Path

import duckdb

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
db = duckdb.connect(str(root / "data" / "fraud.duckdb"), read_only=True)
db.execute("SET threads=2; SET memory_limit='1500MB'")
LATEST, YEAR_AGO = "2026.09.29", "2025.10.01"

METRICS = {
    "days_per_patient": {"label": "Days of care per patient", "src": "pac"},
    "paid_per_patient": {"label": "Medicare paid per patient", "src": "pac", "money": True},
    "nurse_min_per_day": {"label": "Nursing minutes per day of care", "src": "pac"},
    "aide_visits_per_day": {"label": "Aide visits per day of care", "src": "pac"},
    "avg_daily_patients": {"label": "Average patients per day", "src": "pac"},
    "routine_days_pct": {"label": "Routine home care share of days (%)", "src": "pac"},
    "spend_per_patient_cc": {"label": "Medicare spending per patient (Care Compare)", "src": "cc", "money": True},
    "visits_near_death_pct": {"label": "Visits near death (% of decedents)", "src": "cc"},
    "live_early_pct": {"label": "Early live discharges (% of live discharges)", "src": "cc"},
    "live_late_pct": {"label": "Late live discharges (% of live discharges)", "src": "cc"},
    "nursing_gaps_pct": {"label": "Gaps in nursing visits (% of elections)", "src": "cc"},
    "episodes_per_patient": {"label": "Episodes per patient", "src": "pac"},
    "lupa_share_pct": {"label": "Low-visit (LUPA) episodes (%)", "src": "pac"},
    "visits_per_episode": {"label": "Nurse, aide and social work visits per episode", "src": "pac"},
    "nurse_min_per_episode": {"label": "Nursing minutes per episode", "src": "pac"},
    "outlier_share_pct": {"label": "Outlier share of payments (%)", "src": "pac"},
}
# id: (label, what it means, metric or None, tail). Same cuts as the backtest: national 95th / 5th percentile.
INDICATORS = {
    "long_stay": ("Long stays", "Days of care per patient at or above the national 95th percentile for hospices.", "days_per_patient", 1),
    "high_paid": ("High payment per patient", "Medicare paid per patient at or above the national 95th percentile.", "paid_per_patient", 1),
    "high_spend_cc": ("High spending per patient (Care Compare)", "Care Compare spending per patient at or above the national 95th percentile.", "spend_per_patient_cc", 1),
    "low_nursing": ("Few nursing minutes", "Nursing minutes per day of care at or below the national 5th percentile.", "nurse_min_per_day", -1),
    "low_aide": ("Few aide visits", "Aide visits per day of care at or below the national 5th percentile.", "aide_visits_per_day", -1),
    "low_near_death": ("Few visits near death", "Care Compare visits near death (share of decedents) at or below the national 5th percentile.", "visits_near_death_pct", -1),
    "new_biller": ("Recently began billing", "No Medicare hospice claims two years before the latest claims year.", None, 0),
    "owner_added": ("Owner or controller added", "A new owner or person with operational control was listed in the last four quarterly files.", None, 0),
    "busy_building": ("Five or more agencies in the building", "Five or more hospices and home health agencies are listed in this building. It may be an ordinary office building.", None, 0),
}


def rows(q):
    cur = db.execute(q)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def div(a, b, k=1.0):
    return None if a is None or not b else a / b * k


def pac_rows(cur_table, hist):
    latest = {r["PRVDR_ID"]: r for r in rows(f"SELECT * FROM {cur_table} WHERE SMRY_CTGRY = 'PROVIDER'")}
    years = {}
    for table in (hist, cur_table):
        for r in rows(f"SELECT PRVDR_ID, YEAR, BENE_DSTNCT_CNT, TOT_SRVC_DAYS, TOT_MDCR_PYMT_AMT FROM {table} WHERE SMRY_CTGRY = 'PROVIDER'"):
            years.setdefault(r["PRVDR_ID"], {})[int(r["YEAR"])] = [num(r["BENE_DSTNCT_CNT"]), num(r["TOT_MDCR_PYMT_AMT"]), num(r["TOT_SRVC_DAYS"])]
    return latest, years


H, Hy = pac_rows("hospice_pac_2024", "hist_hospice_pac")
A, Ay = pac_rows("hha_pac_2024", "hist_hha_pac")
cc = {r["ccn"]: r for r in rows("SELECT * FROM hospice_scores")}
metrics = {}
for c in set(H) | set(cc):
    r = H.get(c, {})
    days, benes, paid = num(r.get("TOT_SRVC_DAYS")), num(r.get("BENE_DSTNCT_CNT")), num(r.get("TOT_MDCR_PYMT_AMT"))
    s = cc.get(c, {})
    metrics[c] = ("hospice", {"days_per_patient": div(days, benes), "paid_per_patient": div(paid, benes),
                              "nurse_min_per_day": div(num(r.get("TOT_NRSNG_MNTS")), days), "aide_visits_per_day": div(num(r.get("AIDE_VISITS_CNT")), days),
                              "avg_daily_patients": div(days, 366), "routine_days_pct": num(r.get("HOSPC_RHC_DAYS_PCT")),
                              "spend_per_patient_cc": s.get("spend_per_bene"), "visits_near_death_pct": s.get("pct_visits_near_death"),
                              "live_early_pct": s.get("pct_early_live_discharge"), "live_late_pct": s.get("pct_late_live_discharge"),
                              "nursing_gaps_pct": s.get("pct_nursing_gaps")})
for c, r in A.items():
    eps, benes, paid = num(r["TOT_EPSD_STAY_CNT"]), num(r["BENE_DSTNCT_CNT"]), num(r["TOT_MDCR_PYMT_AMT"])
    nv = num(r["NRSNG_VISITS_CNT"])
    visits = None if nv is None else nv + (num(r["AIDE_VISITS_CNT"]) or 0) + (num(r["MSW_VISITS_CNT"]) or 0)
    metrics[c] = ("hha", {"paid_per_patient": div(paid, benes), "episodes_per_patient": div(eps, benes),
                          "lupa_share_pct": div(num(r["TOT_HH_LUPA_EPSDS_CNT"]), eps, 100), "visits_per_episode": div(visits, eps),
                          "nurse_min_per_episode": div(num(r["TOT_NRSNG_MNTS"]), eps), "outlier_share_pct": div(num(r["TOT_OUTLIER_PYMT_AMT"]), paid, 100)})

dist = {}
for kind, m in metrics.values():
    for k, v in m.items():
        if v is not None:
            dist.setdefault((kind, k), []).append(v)
for v in dist.values():
    v.sort()


def pctile(kind, k, v):
    d = dist[kind, k]
    return round(100 * bisect.bisect_right(d, v) / len(d))


def cut(kind, k, tail):
    d = dist[kind, k]
    return d[int((0.95 if tail > 0 else 0.05) * (len(d) - 1))]


cuts = {i: cut("hospice", x[2], x[3]) for i, x in INDICATORS.items() if x[2]}

owner_added = {r[0] for r in db.execute(f"""
  WITH o AS (SELECT "ENROLLMENT ID" eid, "ASSOCIATE ID - OWNER" oid, snapshot s, "ROLE CODE - OWNER" r FROM hist_hospice_owners WHERE "ROLE CODE - OWNER" IN ('34','35','38','43')),
       a AS (SELECT DISTINCT eid, oid FROM o WHERE s LIKE '%{YEAR_AGO}%'),
       b AS (SELECT DISTINCT eid, oid FROM o WHERE s LIKE '%{LATEST}%')
  SELECT DISTINCT b.eid FROM b WHERE b.eid IN (SELECT eid FROM a)
    AND NOT EXISTS (SELECT 1 FROM a WHERE a.eid = b.eid AND a.oid = b.oid)""").fetchall()}
snap = rows(f"""SELECT 'hospice' kind, "ENROLLMENT ID" eid, "CCN" ccn, raw_building_key_of("ADDRESS LINE 1", "ADDRESS LINE 2", left("ZIP CODE", 5)) k
  FROM hist_hospice_enrollments WHERE snapshot LIKE '%{LATEST}%' AND "CCN" <> ''
  UNION ALL SELECT 'hha', "ENROLLMENT ID", "CCN", raw_building_key_of("ADDRESS LINE 1", "ADDRESS LINE 2", left("ZIP CODE", 5))
  FROM hist_hha_enrollments WHERE snapshot LIKE '%{LATEST}%' AND "CCN" <> ''""")
assert snap, "latest snapshot not found"
bldg, of = {}, {}
for r in snap:
    of.setdefault(r["ccn"], []).append(r)
    if r["k"]:
        bldg.setdefault(r["k"], set()).add(r["ccn"])

out = {}
for c, (kind, m) in metrics.items():
    rec = {"k": kind, "m": {k: [round(v, 2), pctile(kind, k, v)] for k, v in m.items() if v is not None}, "na": [k for k, v in m.items() if v is None]}
    ys = (Hy if kind == "hospice" else Ay).get(c, {})
    rec["y"] = {str(y): v for y, v in sorted(ys.items())}
    if kind == "hospice":
        flags, na = [], []
        for i, (_, _, metric, tail) in INDICATORS.items():
            if not metric:
                continue
            v = m.get(metric)
            if v is None:
                na.append(i)
            elif (v >= cuts[i]) if tail > 0 else (v <= cuts[i]):
                flags.append(i)
        if c in H and 2022 not in ys:
            flags.append("new_biller")
        snaps = of.get(c, [])
        if not snaps:
            na += ["owner_added", "busy_building"]
        else:
            if any(s["eid"] in owner_added for s in snaps):
                flags.append("owner_added")
            n = max((len(bldg.get(s["k"], ())) for s in snaps), default=0)
            if n >= 5:
                flags.append("busy_building")
                rec["bldg_n"] = n
        rec["ind"], rec["ind_na"] = flags, na
    out[c] = rec

path = root / "data" / "derived" / "indicators.json"
path.write_text(json.dumps({"metrics": METRICS, "indicators": {i: {"label": x[0], "means": x[1]} for i, x in INDICATORS.items()},
                            "cuts": {i: round(v, 3) for i, v in cuts.items()}, "agencies": out}, separators=(",", ":")))
from collections import Counter
n = sum(1 for r in out.values() if r["k"] == "hospice")
print(path, path.stat().st_size, "hospices", n, "of which with any indicator", sum(1 for r in out.values() if r.get("ind")))
print(Counter(i for r in out.values() for i in r.get("ind", [])))
print(Counter(len(r["ind"]) for r in out.values() if r["k"] == "hospice"))
print("cuts", cuts)
