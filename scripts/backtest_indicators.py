"""Backtest candidate agency indicators against LATER CMS revocations. Writes out/indicator_backtest.md and .json (copied to docs/indicator_backtest.md).

Rules fixed before any result was seen (2026-11-09):
  Cohort     Hospices and HHAs with a CCN in the 2024-01-05 enrollment file, CMS claims in CY2023, not revoked before.
             Care Compare hospice measures cover 2023-24, so they are tested only on revocations from 2025-01-01,
             on hospices not revoked before that date.
  Outcome    Any revocation (CMS Revocation Extract) effective after the cohort date. A revocation is an administrative
             action and a biased, partial proxy: CMS finds what it looks for, and most improper billing never gets one.
  Flag       Metric at or beyond the national 95th (or 5th) percentile of assessed agencies of the same type, or the
             fixed cut named below. A missing value is "not assessed": it is left out, never counted as not flagged.
  Statistic  Risk ratio flagged vs. not flagged, stratified by state (Mantel-Haenszel), with a 95% CI.
  Keep       MH risk ratio lower limit > 1 and at least 5 flagged agencies with the outcome.
             "Strong" also survives Bonferroni over all tests. Anything else stays off the site.
  Affiliation check: outcome excludes revocations whose only ground is 424.535(a)(19), which is defined by affiliation.
Thresholds are not tuned. Nothing here shows that any agency did anything wrong.

Usage: .venv/bin/python -I scripts/backtest_indicators.py [project_dir]
"""
import json
import math
import sys
from pathlib import Path

import duckdb

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
db = duckdb.connect(str(root / "data" / "fraud.duckdb"), read_only=True)
db.execute("SET threads=2; SET memory_limit='1500MB'")
ASOF, CC_START = "2024-01-06", "2025-01-01"

db.execute(f"""
CREATE TEMP TABLE enr AS
  SELECT DISTINCT "ENROLLMENT ID" eid, "CCN" ccn FROM hist_hospice_enrollments WHERE "CCN" <> ''
  UNION SELECT DISTINCT "ENROLLMENT ID", "CCN" FROM hist_hha_enrollments WHERE "CCN" <> '';
CREATE TEMP TABLE rev AS
  SELECT e.ccn, r.ENRLMT_ID eid, strptime(r.REVOCATION_EFCTV_DT, '%m/%d/%Y')::date d, upper(r.REVOCATION_RSN) why
  FROM cms_revoked r JOIN enr e ON e.eid = r.ENRLMT_ID;
CREATE TEMP TABLE snap AS
  SELECT 'hospice' kind, "ENROLLMENT ID" eid, "CCN" ccn, "STATE" state, "ADDRESS LINE 1" a1, "ADDRESS LINE 2" a2, "ZIP CODE" zip
    FROM hist_hospice_enrollments WHERE snapshot LIKE '%2024.01.05%' AND "CCN" <> ''
  UNION ALL
  SELECT 'hha', "ENROLLMENT ID", "CCN", "STATE", "ADDRESS LINE 1", "ADDRESS LINE 2", "ZIP CODE"
    FROM hist_hha_enrollments WHERE snapshot LIKE '%2024.01.05%' AND "CCN" <> '';
CREATE TEMP TABLE suite AS
  SELECT ccn, count(*) OVER (PARTITION BY k) n FROM (
    SELECT DISTINCT ccn, regexp_replace(upper(coalesce(a1,'') || coalesce(a2,'')), '[^A-Z0-9]', '', 'g') || left(zip, 5) k FROM snap);
CREATE TEMP TABLE own AS
  SELECT "ENROLLMENT ID" eid, "ASSOCIATE ID - OWNER" oid, snapshot s, "ROLE CODE - OWNER" r FROM hist_hospice_owners
  UNION ALL SELECT "ENROLLMENT ID", "ASSOCIATE ID - OWNER", snapshot, "ROLE CODE - OWNER" FROM hist_hha_owners;
""")

own_add = {r[0] for r in db.execute("""
  WITH a AS (SELECT DISTINCT eid, oid FROM own WHERE s LIKE '%2023.03.31%' AND r IN ('34','35','38','43')),
       b AS (SELECT DISTINCT eid, oid FROM own WHERE s LIKE '%2024.01.05%' AND r IN ('34','35','38','43'))
  SELECT DISTINCT e.ccn FROM b JOIN enr e USING (eid)
  WHERE b.eid IN (SELECT eid FROM a) AND NOT EXISTS (SELECT 1 FROM a WHERE a.eid = b.eid AND a.oid = b.oid)""").fetchall()}
affil = {r[0] for r in db.execute(f"""
  WITH cur AS (SELECT DISTINCT eid, oid FROM own WHERE s LIKE '%2024.01.05%' AND r IN ('34','35','38','43')),
       sz AS (SELECT oid FROM cur GROUP BY oid HAVING count(DISTINCT eid) <= 5),
       r0 AS (SELECT DISTINCT eid, ccn FROM rev WHERE d < DATE '{ASOF}'),
       bad AS (SELECT DISTINCT o.oid, r0.ccn FROM own o JOIN r0 USING (eid) WHERE o.r IN ('34','35','38','43'))
  SELECT DISTINCT e.ccn FROM cur JOIN sz USING (oid) JOIN bad USING (oid) JOIN enr e ON e.eid = cur.eid WHERE e.ccn <> bad.ccn""").fetchall()}
revs = {}
for ccn, d, why in db.execute("SELECT ccn, d, why FROM rev").fetchall():
    revs.setdefault(ccn, []).append((str(d), why))
snap = {r[0]: (r[1], r[2], r[3]) for r in db.execute("SELECT ccn, any_value(kind), any_value(state), any_value(eid) FROM snap GROUP BY 1").fetchall()}
n_suite = dict(db.execute("SELECT ccn, max(n) FROM suite GROUP BY 1").fetchall())
# Added after the first run showed exact-suite groups of 3+ are almost empty (8 hospices), while the California auditor's
# pattern is many agencies in one building, each in its own suite. Not part of the pre-declared set.
n_bldg = dict(db.execute("""SELECT ccn, max(n) FROM (SELECT ccn, count(*) OVER (PARTITION BY k) n FROM (
    SELECT DISTINCT ccn, raw_building_key_of(a1, a2, left(zip, 5)) k FROM snap WHERE raw_building_key_of(a1, a2, left(zip, 5)) IS NOT NULL)) GROUP BY 1""").fetchall())


def pac(table, year):
    q = f"SELECT * FROM {table} WHERE SMRY_CTGRY = 'PROVIDER' AND YEAR = '{year}'"
    cur = db.execute(q)
    cols = [c[0] for c in cur.description]
    return {r[cols.index("PRVDR_ID")]: dict(zip(cols, r)) for r in cur.fetchall()}


def num(row, *names):
    """First usable value, or None (not assessed). Commas are removed; CMS suppresses small cells."""
    for k in names:
        v = row.get(k) if row else None
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def ratio(a, b):
    return None if a is None or not b else a / b


H23, H22, H21 = (pac("hist_hospice_pac", y) for y in ("2023", "2022", "2021"))
A23, A22, A21 = (pac("hist_hha_pac", y) for y in ("2023", "2022", "2021"))
scores = {r[0]: dict(zip(("early", "late", "gaps", "near_death", "spend"), r[1:])) for r in db.execute(
    "SELECT ccn, pct_early_live_discharge, pct_late_live_discharge, pct_nursing_gaps, pct_visits_near_death, spend_per_bene FROM hospice_scores").fetchall()}


def growth(cur, prev):
    p, c = num(prev, "TOT_MDCR_PYMT_AMT"), num(cur, "TOT_MDCR_PYMT_AMT")
    if c is None:
        return None
    return bool(p and c >= 2 * p and c >= 500000)


def common(c, kind, cur, prev, old):
    return {"own_add": c in own_add, "affil": c in affil, "suite3": n_suite.get(c, 1) >= 3, "suite2": n_suite.get(c, 1) >= 2, "bldg5": n_bldg.get(c, 1) >= 5, "bldg10": n_bldg.get(c, 1) >= 10,
            "new": old is None, "growth": growth(cur, prev)}


hospice, hha = {}, {}
for c, (kind, state, _) in snap.items():
    if kind == "hospice" and c in H23:
        r = H23[c]
        days, benes = num(r, "TOT_SRVC_DAYS"), num(r, "BENE_DSTNCT_CNT")
        hospice[c] = {"state": state, "m": {"long_stay": ratio(days, benes), "nurse_min": ratio(num(r, "TOT_NRSNG_MNTS"), days),
                                            "aide": ratio(num(r, "AIDE_VISITS_CNT"), days), "paid_per_bene": ratio(num(r, "TOT_MDCR_PYMT_AMT"), benes)},
                      "f": {**common(c, kind, r, H22.get(c), H21.get(c)), "small_census": None if days is None else days / 365 < 5}}
    if kind == "hha" and c in A23:
        r = A23[c]
        eps, benes = num(r, "TOT_EPSD_STAY_CNT"), num(r, "BENE_DSTNCT_CNT")
        v = [num(r, x) for x in ("NRSNG_VISITS_CNT", "AIDE_VISITS_CNT", "MSW_VISITS_CNT")]
        hha[c] = {"state": state, "m": {"lupa_share": ratio(num(r, "TOT_HH_LUPA_EPSDS_CNT"), eps), "eps_per_bene": ratio(eps, benes),
                                        "paid_per_bene": ratio(num(r, "TOT_MDCR_PYMT_AMT"), benes), "nurse_min_per_ep": ratio(num(r, "TOT_NRSNG_MNTS"), eps),
                                        "visits_per_ep": ratio(sum(x for x in v if x is not None), eps) if v[0] is not None else None,
                                        "outlier_share": ratio(num(r, "TOT_OUTLIER_PYMT_AMT"), num(r, "TOT_MDCR_PYMT_AMT"))},
                  "f": common(c, kind, r, A22.get(c), A21.get(c))}

HIGH, LOW = 1, -1
TAILS = {"hospice": {"long_stay": HIGH, "nurse_min": LOW, "aide": LOW, "paid_per_bene": HIGH},
         "hha": {"lupa_share": LOW, "eps_per_bene": HIGH, "paid_per_bene": HIGH, "nurse_min_per_ep": LOW, "visits_per_ep": LOW, "outlier_share": HIGH}}
CC_TAILS = {"early": HIGH, "late": HIGH, "gaps": HIGH, "near_death": LOW, "spend": HIGH}


def cut(values, tail):
    v = sorted(values)
    return v[int(0.95 * (len(v) - 1))] if tail == HIGH else v[int(0.05 * (len(v) - 1))]


def outcome(c, start, drop_19=False):
    """True / False, or None when the agency left the cohort by an earlier revocation."""
    rows = revs.get(c, [])
    if any(d < start for d, _ in rows):
        return None
    later = [(d, w) for d, w in rows if d >= start]
    if drop_19:
        later = [(d, w) for d, w in later if w.replace("424.535(A)(19) AFFILIATION THAT POSES AN UNDUE RISK", "").strip(" ;")]
    return bool(later)


def mh(rows):
    """rows: (state, flagged, event). Mantel-Haenszel RR, Greenland-Robins variance. Returns counts, RR, CI, se."""
    st = {}
    for s, f, e in rows:
        x = st.setdefault(s, [0, 0, 0, 0])   # a events flagged, n1 flagged, c events other, n0 other
        x[0 if f else 2] += e
        x[1 if f else 3] += 1
    R = S = P = 0.0
    for a, n1, c, n0 in st.values():
        t = n1 + n0
        if not t:
            continue
        R += a * n0 / t
        S += c * n1 / t
        P += ((a + c) * n1 * n0 - a * c * t) / (t * t)
    A = sum(x[0] for x in st.values()); N1 = sum(x[1] for x in st.values())
    C = sum(x[2] for x in st.values()); N0 = sum(x[3] for x in st.values())
    if R == 0 or S == 0:
        return A, N1, C, N0, None, None, None, None
    rr = R / S
    se = math.sqrt(max(P, 0) / (R * S))
    return A, N1, C, N0, rr, rr * math.exp(-1.96 * se), rr * math.exp(1.96 * se), se


def tests():
    for kind, pop in (("hospice", hospice), ("hha", hha)):
        cuts = {m: cut([a["m"][m] for a in pop.values() if a["m"][m] is not None], t) for m, t in TAILS[kind].items()}
        for m, t in TAILS[kind].items():
            rows = [(a["state"], (a["m"][m] >= cuts[m]) if t == HIGH else (a["m"][m] <= cuts[m]), outcome(c, ASOF))
                    for c, a in pop.items() if a["m"][m] is not None]
            yield kind, m, f"{'>=' if t == HIGH else '<='} {cuts[m]:.3g}", "2024-26", rows
        for f in next(iter(pop.values()))["f"]:
            rows = [(a["state"], a["f"][f], outcome(c, ASOF, drop_19=f == "affil")) for c, a in pop.items() if a["f"][f] is not None]
            yield kind, f, "fixed", "2024-26", rows
    cc = {c: scores[c] for c in hospice if c in scores}
    for m, t in CC_TAILS.items():
        vals = [a[m] for a in cc.values() if a[m] is not None]
        k = cut(vals, t)
        rows = [(hospice[c]["state"], (a[m] >= k) if t == HIGH else (a[m] <= k), outcome(c, CC_START)) for c, a in cc.items() if a[m] is not None]
        yield "hospice", "cc_" + m, f"{'>=' if t == HIGH else '<='} {k:.3g}", "2025-26", rows


results = []
for kind, name, rule, window, rows in tests():
    rows = [r for r in rows if r[2] is not None]
    a, n1, c, n0, rr, lo, hi, se = mh(rows)
    results.append({"kind": kind, "name": name, "rule": rule, "window": window, "assessed": n1 + n0, "flagged": n1, "events_flagged": a,
                    "rate_flagged": a / n1 if n1 else None, "rate_other": c / n0 if n0 else None, "mh_rr": rr, "lo": lo, "hi": hi, "se": se})
B = len(results)
for r in results:
    r["keep"] = bool(r["lo"] and r["lo"] > 1 and r["events_flagged"] >= 5)
    # two-sided Bonferroni z, by bisection on the normal tail
    lo_z, hi_z = 0.0, 10.0
    for _ in range(60):
        z = (lo_z + hi_z) / 2
        if math.erfc(z / math.sqrt(2)) > 0.05 / B:
            lo_z = z
        else:
            hi_z = z
    r["strong"] = bool(r["keep"] and r["mh_rr"] * math.exp(-z * r["se"]) > 1)

# Would a count of checks add anything? Descriptive and in-sample: the checks were kept on this same outcome.
KEEP = [r["name"] for r in results if r["strong"] and r["kind"] == "hospice" and not r["name"].startswith("cc_") and r["name"] != "bldg10"]
keep_cuts = {m: cut([a["m"][m] for a in hospice.values() if a["m"][m] is not None], TAILS["hospice"][m]) for m in TAILS["hospice"]}
by = {}
for c, a in hospice.items():
    e = outcome(c, ASOF)
    if e is None:
        continue
    k = sum(1 for n in KEEP if ((a["m"][n] is not None and (a["m"][n] >= keep_cuts[n] if TAILS["hospice"][n] == HIGH else a["m"][n] <= keep_cuts[n])) if n in a["m"] else bool(a["f"].get(n))))
    x = by.setdefault(min(k, 4), [0, 0]); x[0] += 1; x[1] += e
count_lines = ["", "## Hospices by number of kept checks (in-sample, CMS-claims and structural checks only)", "", "| checks | hospices | revoked later | rate |", "|---|---|---|---|"] + [
    f"| {k}{'+' if k == 4 else ''} | {n} | {e} | {e / n * 100:.1f}% |" for k, (n, e) in sorted(by.items())]

out = root / "out"
(out / "indicator_backtest.json").write_text(json.dumps(results, indent=1))
L = ["# Indicator backtest", "", __doc__.split("Usage:")[0].strip(), "", "| type | check | cut | outcome window | assessed | flagged | outcome: flagged | outcome: others | state-adjusted RR (95% CI) | verdict |", "|" + "---|" * 10]
for r in sorted(results, key=lambda x: (x["kind"], -(x["mh_rr"] or 0))):
    f = lambda v: "n/a" if v is None else f"{v * 100:.1f}%"
    g = "n/a" if r["mh_rr"] is None else f"{r['mh_rr']:.2f} ({r['lo']:.2f}-{r['hi']:.2f})"
    L.append(f"| {r['kind']} | {r['name']} | {r['rule']} | {r['window']} | {r['assessed']} | {r['flagged']} | {f(r['rate_flagged'])} ({r['events_flagged']}) | {f(r['rate_other'])} | {g} | {'strong' if r['strong'] else 'keep' if r['keep'] else 'drop'} |")
L += count_lines
(out / "indicator_backtest.md").write_text("\n".join(L) + "\n")
print("\n".join(L[L.index("| type | check | cut | outcome window | assessed | flagged | outcome: flagged | outcome: others | state-adjusted RR (95% CI) | verdict |"):]))
