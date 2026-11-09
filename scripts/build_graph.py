"""Build an interactive hospice/HHA network as out/graph.html (v2, 2026-11-03).

Nodes: hospice and HHA enrollments; people and organizations listed on them in any role
(owners, officers, directors, managing employees); practice addresses shared by 2+ enrollments.
All CMS All Owners releases 2023-03-31..2026-09-29 are used, and every link carries the first and
last release it appears in.

Identity: a person/org node is one CMS associate ID (leading zeros stripped). Names are never used
to merge IDs; same-name / different-ID pairs get a dotted "same name, unconfirmed" link that does
not join networks.

Weak nodes (shown, but never used to join networks; copied into each network they touch):
  - IDs listed on more than GENERIC_ENROLLMENTS enrollments (chain officers, consultants)
  - executive-suite / virtual-office addresses ('OFFICE n' after a suite, 8925 S Pecos Rd 16A);
    'Office n' variants are merged into one suite node
  - addresses with more than GENERIC_ADDRESS enrollments
Networks = connected groups of 2+ enrollments over strong links, containing at least one hospice.

Status per enrollment: revocation row in the CMS Revocation Extract 2026-10-21 (date, reason),
else listed in the 2026-09-29 enrollment file, else "not in latest file (no revocation row)".
That last status is not a closure finding. "Carrier" = enrollment without a revocation row whose
2026-09-29 owner file lists an ID that was on another enrollment revoked within 365 days after
that ID's last listing there (same rule as scripts/revoked_carrier_screen.py).

Usage: .venv/bin/python -I scripts/build_graph.py [project_dir]
"""
import csv
import functools
import glob
import json
import re
import sys
import datetime as dt
from collections import defaultdict
from pathlib import Path

import duckdb

GENERIC_ENROLLMENTS = 25
GENERIC_ADDRESS = 10
GENERIC_ORG = 5
LATEST = "2026-09-29"
root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
db = duckdb.connect(str(root / "data" / "fraud.duckdb"), read_only=True)
db.execute("SET memory_limit='700MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='/tmp/caregraph_duckdb'")   # the site build runs under a 2.5 GB cap
SRC_HOS = "CMS Hospice All Owners"
SRC_HHA = "CMS HHA All Owners"
SRC_ENR = "CMS Hospice / HHA Enrollments 2023-03-31..2026-09-29"
SRC_REV = "CMS Revocation Extract 2026-10-21"
CMS_FILES = json.loads((root / "scripts" / "cms_files.json").read_text())   # scripts/cms_files.py
FILES = list(CMS_FILES)
FIDX = {f: i for i, f in enumerate(FILES)}
ALIASES = defaultdict(list)   # building key -> merged spellings with rule and Census check (scripts/check_address_aliases.py)
for x in json.loads((root / "scripts" / "address_aliases.json").read_text())["aliases"]:
    ALIASES[x["canon"]].append({"spelling": x["raw_line"], "rule": x["rule"], "census": x["census"]})
MULTITENANT = {x["key"]: x for x in json.loads((root / "scripts" / "address_multitenant.json").read_text())["addresses"]}
VIRTUAL = re.compile(r"\b(OFFICE|OFC|OFF)\s*#?\s*\d+\b", re.I)


def rel(name):
    m = re.search(r"(20\d\d)[._-](\d\d)[._-](\d\d)", name)
    return f"{m[1]}-{m[2]}-{m[3]}"


def fidx(name):
    """File index in FILES for a snapshot / file name."""
    return FIDX[name if name.endswith(".csv") else name.replace("HHA_", "HHA_Enrollments_") + ".csv"]


def iso(s):
    d = pdate(s) if s and "/" in s else None
    return str(d) if d else (s or None)


def pdate(s):
    try:
        m, d, y = s.split("/")
        return dt.date(int(y), int(m), int(d))
    except Exception:
        return None


def money(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rcat(reason):
    r = reason.upper()
    if "(A)(19)" in r: return "affiliation"
    if "(A)(8)" in r: return "billing"
    return "other"


def rolecat(code):
    return {"34": "owner", "35": "owner", "38": "owner", "43": "control", "40": "officer", "41": "officer",
            "42": "manager", "25": "manager"}.get(code, "other")


# ---------- enrollments ----------
enr = {}
for e, name, dba, st, city, ccn, a1, a2, npi, snap in db.execute("""
        SELECT "ENROLLMENT ID", "ORGANIZATION NAME", "DOING BUSINESS AS NAME", STATE, CITY, CCN,
               "ADDRESS LINE 1", "ADDRESS LINE 2", NPI, snapshot FROM hist_hospice_enrollments ORDER BY snapshot""").fetchall():
    r = rel(snap)
    x = enr.setdefault(e, {"id": e, "kind": "hospice", "first_seen": r, "ef": []})
    x.update(name=name, dba=dba, state=st, city=city, ccn=ccn, address=" ".join(filter(None, [a1, a2])), last_seen=r,
             npi=npi or x.get("npi"))
    if fidx(snap) not in x["ef"]: x["ef"].append(fidx(snap))
for e, name, dba, st, city, ccn, a1, a2, npi, snap in db.execute("""
        SELECT "ENROLLMENT ID", "ORGANIZATION NAME", "DOING BUSINESS AS NAME", STATE, CITY, CCN,
               "ADDRESS LINE 1", "ADDRESS LINE 2", NPI, snapshot FROM hist_hha_enrollments ORDER BY snapshot""").fetchall():
    r = rel(snap)
    x = enr.setdefault(e, {"id": e, "kind": "hha", "first_seen": r, "ef": []})
    if x["kind"] == "hospice":   # listed in the HHA files before CMS moved it to the hospice files: keep the newer hospice row
        x["first_seen"] = min(x["first_seen"], r)
    else:
        x.update(name=name, dba=dba, state=st, city=city, ccn=ccn, address=" ".join(filter(None, [a1, a2])), last_seen=r,
                 npi=npi or x.get("npi"))
    if fidx(snap) not in x["ef"]: x["ef"].append(fidx(snap))
pay = {}
for t in ("hospice_pac_2024", "hha_pac_2024"):
    for ccn, b, p in db.execute(f"SELECT PRVDR_ID, BENE_DSTNCT_CNT, TOT_MDCR_PYMT_AMT FROM {t} WHERE SMRY_CTGRY = 'PROVIDER'").fetchall():
        pay[(t[:3], ccn)] = (b, money(p))
pay_prev = {}   # agencies without 2024 claims: latest earlier year 2021-2023 (CMS PAC files by provider)
for t in ("hist_hospice_pac", "hist_hha_pac"):
    for ccn, b, p, snap in db.execute(f"SELECT PRVDR_ID, BENE_DSTNCT_CNT, TOT_MDCR_PYMT_AMT, snapshot FROM {t} "
                                      "WHERE SMRY_CTGRY = 'PROVIDER' ORDER BY snapshot").fetchall():
        pay_prev[(t[5:8], ccn)] = {"benes_prev": b, "paid_prev": money(p), "paid_year": re.search(r"_(20\d\d)_main", snap)[1],
                                   "pf": FIDX[snap]}
prof = db.execute("SELECT * FROM hospice_profile").df()
prof = prof.astype(object).where(prof.notna(), None)
profile = {r["enrollment_id"]: r for r in prof.to_dict("records")}
rev = {}
with open(root / "data/raw/cms_revoked/Revocation_Extract_2026.10.21.csv", encoding="cp1252", newline="") as fh:
    for r in csv.DictReader(fh):
        rev[r["ENRLMT_ID"]] = (pdate(r["REVOCATION_EFCTV_DT"]), r["REVOCATION_RSN"], r["ORG_NAME"], r["STATE_CD"])

# ---------- people/org listings (all releases) ----------
links = {}      # (node, enrollment) -> {roles, first, last, pct, src}
names, ntype, pname = {}, {}, {}
latest_listed = defaultdict(set)   # enrollment -> node ids in 2026-09-29 owner file


mids = defaultdict(set)   # person node -> middle names listed (for the merge rule)


def add(node, e, role, code, r, pct, src, ename, otype, nm, first_last, fname, aid, assoc, full=None, mid=None):
    k = (node, e)
    x = links.get(k)
    if x is None:
        x = links[k] = {"roles": set(), "cats": set(), "first": r, "last": r, "pct": pct, "src": src, "recs": {}}
    x["recs"].setdefault((aid, code, role, pct if pct and pct.strip("0.") else None, iso(assoc), " ".join((full or nm).upper().split())),
                         []).append(FIDX[fname])
    if mid and mid.strip(): mids[node].add(mid.strip().upper().rstrip("."))
    x["roles"].add(role.replace("CORPORATE ", "").replace("W-2 MANAGING EMPLOYEE", "MANAGING EMPLOYEE (W-2)"))
    x["cats"].add(rolecat(code))
    if r < x["first"]: x["first"] = r
    if r >= x["last"]: x["last"], x["pct"] = r, pct or x["pct"]
    names[node], ntype[node] = nm, otype
    if first_last: pname[node] = first_last
    if r == LATEST: latest_listed[e].add(node)
    if e not in enr:
        enr[e] = {"id": e, "kind": "hospice" if src == SRC_HOS else "hha", "name": ename, "state": None}


q = """SELECT "ENROLLMENT ID", "ORGANIZATION NAME", "ASSOCIATE ID - OWNER", "TYPE - OWNER",
              "ROLE CODE - OWNER", "ROLE TEXT - OWNER", "FIRST NAME - OWNER", "LAST NAME - OWNER", "MIDDLE NAME - OWNER",
              "ORGANIZATION NAME - OWNER", "PERCENTAGE OWNERSHIP", "ASSOCIATION DATE - OWNER", snapshot
       FROM hist_hospice_owners"""
for e, ename, raw, t, code, role, fn, ln, mn, on, pct, assoc, snap in db.execute(q).fetchall():
    a = (raw or "").lstrip("0")
    if not a: continue
    nm = (on or f"{fn or ''} {ln or ''}").strip()
    fl = f"{(fn or '').strip().upper()} {(ln or '').strip().upper()}" if t == "I" else None
    add(("p" if t == "I" else "o") + a, e, role, code, rel(snap), pct, SRC_HOS, ename, t, nm, fl, snap, raw, assoc,
        on or " ".join(filter(None, (fn, mn, ln))), mn)
seen_hha = set()
for f in sorted(glob.glob(str(root / "data/raw/hist_hha_owners/*.csv"))):
    r = rel(Path(f).name)
    if r in seen_hha: continue
    seen_hha.add(r)
    with open(f, encoding="cp1252", newline="") as fh:
        for row in csv.DictReader(fh):
            a = row["ASSOCIATE ID - OWNER"].lstrip("0")
            if not a: continue
            t = row["TYPE - OWNER"]
            fn, ln = row.get("FIRST NAME - OWNER", ""), row.get("LAST NAME - OWNER", "")
            nm = (row.get("ORGANIZATION NAME - OWNER") or f"{fn} {ln}").strip()
            fl = f"{fn.strip().upper()} {ln.strip().upper()}" if t == "I" else None
            add(("p" if t == "I" else "o") + a, row["ENROLLMENT ID"], row["ROLE TEXT - OWNER"], row["ROLE CODE - OWNER"],
                r, row["PERCENTAGE OWNERSHIP"], SRC_HHA, row["ORGANIZATION NAME"], t, nm, fl, Path(f).name,
                row["ASSOCIATE ID - OWNER"], row.get("ASSOCIATION DATE - OWNER"),
                row.get("ORGANIZATION NAME - OWNER") or " ".join(filter(None, (fn, row.get("MIDDLE NAME - OWNER"), ln))),
                row.get("MIDDLE NAME - OWNER"))
for x in links.values():
    x["src"] = f'{x["src"]} {x["first"]}..{x["last"]}'

# ---------- merging CMS IDs ----------
# Two associate IDs become one node only if both are listed on at least one same enrollment and have the same name:
# organizations the full name with legal form (punctuation ignored); people the same first, last and full middle
# name (not just an initial: two IDs with the same first and last name on one agency can be father and son). The rule and both IDs are
# published. Same-name people that do not qualify stay separate; the node notes the other ID on the same agency.
def org_key(nm):
    w = re.sub(r"[^A-Z0-9 ]", " ", nm.upper().replace(".", "").replace("L L C", "LLC")).split()
    return " ".join(x for x in w if x != "THE")


def mids_ok(a, b):
    ma, mb = {m for m in mids.get(a, ()) if len(m) > 1}, {m for m in mids.get(b, ()) if len(m) > 1}
    return bool(ma & mb) and len(ma) == 1 and len(mb) == 1


enr_of = defaultdict(set)
for n, e in links: enr_of[n].add(e)
same = defaultdict(list)
for n in enr_of:
    if n[0] == "p" and pname.get(n, "").strip(): same["p" + pname[n]].append(n)
    elif n[0] == "o": same["o" + org_key(names[n])].append(n)
merge_to, merged_ids, same_agency_other = {}, defaultdict(list), {}
for k, ids in same.items():
    if len(ids) < 2: continue
    ids.sort(key=lambda n: (-len(enr_of[n]), n))
    comps = []                                    # each: list of IDs; join only if compatible with every member
    for n in ids:
        hit = next((c for c in comps if any(enr_of[m] & enr_of[n] for m in c)
                    and (n[0] == "o" or all(mids_ok(m, n) for m in c))), None)
        if hit: hit.append(n)
        else: comps.append([n])
    if ids[0][0] == "p":
        for c in comps:
            for n in c:
                o = [m[1:] for m in ids if m not in c and enr_of[m] & enr_of[n]]
                if o: same_agency_other[n] = o
    for c in comps:
        for n in c[1:]:
            merge_to[n] = c[0]
            merged_ids[c[0]].append({"cms_id": n[1:], "shared": sorted({enr[e]["name"] if e in enr else e
                                                                        for e in enr_of[n] & set().union(*(enr_of[m] for m in c if m != n))})[:3]})
for (n, e) in [k for k in links if k[0] in merge_to]:
    x, c = links.pop((n, e)), merge_to[n]
    y = links.get((c, e))
    if y is None:
        links[(c, e)] = x
        continue
    y["roles"] |= x["roles"]; y["cats"] |= x["cats"]
    for rk, fs in x["recs"].items(): y["recs"].setdefault(rk, []).extend(fs)
    if x["first"] < y["first"]: y["first"] = x["first"]
    if x["last"] > y["last"]: y["last"], y["pct"] = x["last"], x["pct"]
for e, ns_ in latest_listed.items():
    latest_listed[e] = {merge_to.get(n, n) for n in ns_}
print(f"merged {len(merge_to)} CMS IDs into {len(merged_ids)} nodes (same name + same enrollment)")

# ---------- addresses (hospice and HHA enrollment history) ----------
addr_links = {}
for akey, label, e, snap, virt, raw in db.execute(r"""
        WITH a AS (
          SELECT "ENROLLMENT ID" e, "ADDRESS LINE 1" a1, "ADDRESS LINE 2" a2, "ZIP CODE" z, CITY c, STATE s, snapshot FROM hist_hospice_enrollments
          UNION ALL SELECT "ENROLLMENT ID", "ADDRESS LINE 1", "ADDRESS LINE 2", "ZIP CODE", CITY, STATE, snapshot FROM hist_hha_enrollments),
        b AS (SELECT *, regexp_matches(upper(a1 || ' ' || coalesce(a2, '')), '\b(OFFICE|OFC|OFF)\s*#?\s*\d+\b') OR upper(a1) LIKE '8925 S PECOS%' AS virt,
                     regexp_replace(upper(a1), '\b(OFFICE|OFC|OFF)\s*#?\s*\d+\b', '', 'g') a1s,
                     nullif(trim(regexp_replace(upper(coalesce(a2, '')), '\b(OFFICE|OFC|OFF)\s*#?\s*\d+\b', '', 'g')), '') a2s FROM a)
        SELECT addr_key_of(a1s, a2s, z), any_value(trim(concat_ws(' ', a1s, a2s)) || ', ' || upper(c) || ' ' || s), e, list(snapshot), bool_or(virt),
               list([snapshot, concat_ws(' ', a1, a2) || ', ' || concat_ws(' ', c, s, z)])
        FROM b WHERE a1 IS NOT NULL AND addr_key_of(a1s, a2s, z) IS NOT NULL GROUP BY 1, 3""").fetchall():
    rs = sorted(rel(s) for s in snap)
    recs = {}
    for sn, line in raw: recs.setdefault(line, []).append(fidx(sn))
    addr_links[("a" + akey, e)] = {"first": rs[0], "last": rs[-1], "label": label, "virt": virt, "recs": recs}
virt_addr = {n for (n, e), x in addr_links.items() if x["virt"]}
# Whole buildings: a node per building whose agencies use two or more different suites (or suite and no suite), linking
# every agency there. Different suites are usually separate tenants, so building nodes are shown but never join networks;
# a building with many agencies is itself worth seeing (14545 Friar St, Van Nuys: 184 across the releases).
fam = defaultdict(dict)
for (n, e), x in addr_links.items():
    fam[n[1:].split(" #")[0]].setdefault(n[1:].split(" #")[1] if " #" in n else "", {})[e] = x
suite_fam, bldg = {}, {}
for b, units in fam.items():
    agencies = {e for u in units.values() for e in u}
    if len(units) < 2 or len(agencies) < 2: continue
    n = f"a{b} *"
    city = next(iter(next(iter(units.values())).values()))["label"].rsplit(", ", 1)[-1]
    suite_fam[n] = sorted(units)
    bldg[n] = {"agencies": len(agencies), "suites": len(units)}
    names[n] = f"{b.rsplit(' ', 1)[0]}, {city}"
    ntype[n] = "A"
    for u, es in units.items():
        for e, x in es.items():
            y = addr_links.get((n, e))
            if y is None: addr_links[(n, e)] = {**x, "recs": {k: list(v) for k, v in x["recs"].items()}, "unit": u or "no suite"}
            else:
                y["first"], y["last"], y["unit"] = min(y["first"], x["first"]), max(y["last"], x["last"]), y["unit"] + "/" + (u or "no suite")
                for line, fs in x["recs"].items(): y["recs"].setdefault(line, []).extend(fs)
print(f"{len(suite_fam)} buildings with agencies in two or more suites")
addr_enr = defaultdict(set)
for (n, e), x in addr_links.items():
    addr_enr[n].add(e)
    if n not in suite_fam: names[n] = x["label"]
    ntype[n] = "A"
for (n, e), x in addr_links.items():
    links[(n, e)] = {"roles": {f"practice address, suite {x['unit']}" if n in suite_fam else "practice address"}, "cats": {"address"}, "first": x["first"], "last": x["last"],
                     "pct": None, "src": f"{SRC_ENR} {x['first']}..{x['last']}", "recs": x["recs"]}

# ---------- weak / strong ----------
per = defaultdict(set)
for n, e in links: per[n].add(e)
weak = {n for n, es in per.items() if (n[0] != "a" and len(es) > GENERIC_ENROLLMENTS)
        or (n[0] == "a" and (n in virt_addr or n in suite_fam or len(es) > GENERIC_ADDRESS))}

# ---------- status, payments, carriers ----------
for e, x in enr.items():
    if e in rev:
        d, reason, *_ = rev[e]
        x.update(status="revoked", rev_date=str(d), rev_reason=reason, rev_cat=rcat(reason))
    elif x.get("last_seen") == LATEST:
        x["status"] = "active"
    else:
        x["status"] = "not in latest file (no revocation row)"
    b, p = pay.get(("hos" if x["kind"] == "hospice" else "hha", x.get("ccn")), (None, None))
    x["benes_2024"], x["paid"] = b, p
    if p is None: x.update(pay_prev.get(("hos" if x["kind"] == "hospice" else "hha", x.get("ccn")), {}))
    if e in profile:
        x.update({k: v for k, v in profile[e].items() if k not in x or x[k] is None})
    if x.get("state") is None and e in rev: x["state"] = rev[e][3]
for e, nodes_now in latest_listed.items():
    if e in rev or enr[e].get("status") != "active": continue
    hits = []
    for n in nodes_now:
        if len(per[n]) > GENERIC_ENROLLMENTS: continue
        for x in per[n]:
            if x == e or x not in rev or not rev[x][0]: continue
            gap = (rev[x][0] - dt.date.fromisoformat(links[(n, x)]["last"])).days
            if gap <= 365:
                hits.append(f"{names[n]} ({n[1:]}) was on {rev[x][2]} {rev[x][3]}, revoked {rev[x][0]} {rcat(rev[x][1])}, {gap} d after last listing")
    if hits: enr[e]["carrier"] = sorted(set(hits))

# ---------- networks ----------
# Networks are joined only by ownership (34/35/38), operational control (43) and shared practice address
# links. Managing employees, officers and directors are drawn inside networks but never join them (they
# move between many unrelated companies). Weak (never joining) nodes also include IDs on more than
# GENERIC_ENROLLMENTS enrollments, organizations on more than GENERIC_ORG enrollments (holding companies of
# chains), virtual-office addresses, and addresses with more than GENERIC_ADDRESS enrollments.
weak |= {n for n, es in per.items() if n[0] == "o" and len(es) > GENERIC_ORG}
mt = {n for n in per if n[0] == "a" and n[1:] in MULTITENANT}
weak |= mt
weak_reason = {n: ("executive-suite / virtual office" if n in virt_addr
                   else f"whole building: {bldg[n]['agencies']} agencies in {bldg[n]['suites']} different suites across the releases; agencies in different suites are usually separate tenants" if n in suite_fam
                   else f"shared office center ({MULTITENANT[n[1:]]['what']}): tenants use the same suite number" if n in mt and "#" in n
                   else f"multi-tenant building ({MULTITENANT[n[1:]]['what']}) and no suite number in CMS files" if n in mt
                   else f"generic: on {len(per[n])} enrollments") for n in weak}
parent = {}


def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


joins = {(n, e) for (n, e), x in links.items() if n not in weak and len(per[n]) > 1 and x["cats"] & {"owner", "control"}}
for n, e in joins: parent[find(n)] = find(e)
# A shared practice address joins two agencies only if CMS lists both there in overlapping release ranges: a later
# tenant of the same suite is drawn at the address but does not join the earlier one's network.
for n, es in per.items():
    if n[0] != "a" or n in weak or len(es) < 2: continue
    es = sorted(es)
    span = {e: (addr_links[(n, e)]["first"], addr_links[(n, e)]["last"]) for e in es}
    for i, a in enumerate(es):
        for b in es[i + 1:]:
            if span[a][0] <= span[b][1] and span[b][0] <= span[a][1]:
                joins |= {(n, a), (n, b)}
                parent[find(a)] = find(b)
members = defaultdict(set)
for e in enr: members[find(e)].add(e)
keep = {g: es for g, es in members.items() if len(es) > 1 and any(enr[e]["kind"] == "hospice" for e in es)}
order = sorted(keep, key=lambda g: -len(keep[g]))
gid = {g: i for i, g in enumerate(order, 1)}   # network #1 = largest
enr_group = {e: gid[g] for g, es in keep.items() for e in es}

def recs_of(recs, show_names=False):
    """Per-record source rows: one entry per distinct row content, with every release file it appears in."""
    out = []
    for k, fs in recs.items():
        fs = sorted(set(fs))
        if isinstance(k, str):
            out.append({"f": fs, "addr": k})
        else:
            aid, code, role, pct, assoc, nm = k
            out.append({k2: v for k2, v in (("f", fs), ("aid", aid), ("code", code), ("role", role), ("pct", pct), ("assoc", assoc),
                                            ("nm", nm if show_names else None)) if v})
    return sorted(out, key=lambda r: (r["f"][0], r.get("code", "")))


nodes, edges = {}, []
elsewhere = defaultdict(list)   # node -> [(enrollment, group)] across all networks
for (n, e), x in links.items():
    if e in enr_group and len(per[n]) > 1: elsewhere[n].append(e)
# Every name CMS listed under a node's ID(s), with the releases it was listed in; shown when they differ beyond
# punctuation, or the node merges several IDs.
listed = defaultdict(lambda: defaultdict(set))
for (n, e), x in links.items():
    if n[0] == "a": continue
    for k, fs in x["recs"].items(): listed[n][k[5]].update(fs)


@functools.lru_cache(maxsize=None)
def listed_names(n):
    d = listed.get(n, {})
    if len({org_key(k) for k in d}) < 2 and n not in merged_ids: return None
    out = []
    for nm, fs in d.items():
        rs = sorted(rel(FILES[i]) for i in fs)
        out.append({"nm": nm, "first": rs[0], "last": rs[-1], "n": len(set(rs))})
    return sorted(out, key=lambda r: (r["first"], r["nm"]))


leie = {r[0] for r in db.execute("SELECT DISTINCT upper(first || ' ' || last) FROM leie_owner_name_hits").fetchall()}
for (n, e), x in links.items():
    if e not in enr_group or len(per[n]) < 2: continue
    g = enr_group[e]
    nid = f"{n}@{g}"
    joining = (n, e) in joins
    if nid not in nodes:
        here = sum(enr_group.get(y) == g for y in per[n])
        why = weak_reason.get(n) or (None if any((n, y) in joins for y in per[n]) else "manager/officer/director links only")
        nodes[nid] = {"id": nid, "key": n, "cms_id": n[1:] if n[0] != "a" else None,
                      "kind": {"I": "person", "O": "org", "A": "address"}[ntype[n]], "name": names[n], "group": g,
                      "weak": why is not None, "weak_reason": why, "n_enrollments": len(per[n]), "n_here": here,
                      "other_networks": sorted({enr_group[y] for y in elsewhere[n]} - {g}),
                      "virtual": n in virt_addr, "building": bldg.get(n), "leie_name_match": pname.get(n, "~") in leie}
        if listed_names(n): nodes[nid]["listed_names"] = listed_names(n)
        if merged_ids.get(n): nodes[nid]["merged_ids"] = merged_ids[n]
        if same_agency_other.get(n): nodes[nid]["same_name_ids"] = same_agency_other[n]
        if n in mt: nodes[nid]["multitenant"] = MULTITENANT[n[1:]]
        if n[0] == "a" and ALIASES.get(n[1:].split(" #")[0]):
            nodes[nid]["merged"] = ALIASES[n[1:].split(" #")[0]]
    if e not in nodes:
        nodes[e] = {**enr[e], "group": g}
    cat = next(c for c in ("owner", "control", "manager", "officer", "address", "other") if c in x["cats"])
    edges.append({"from": nid, "to": e, "roles": sorted(x["roles"]), "cat": cat, "first": x["first"], "last": x["last"],
                  "pct": x["pct"], "weak": not joining, "src": x["src"], "recs": recs_of(x["recs"], bool(listed_names(n)))})

# same name, different CMS ID (never joins networks). Published on both nodes with the facts that bear on it, and as
# an optional "unconfirmed" hop in Find connection, so a name that recurs across networks under several IDs stays
# findable without being asserted to be one person.
members = defaultdict(set)   # enrollment -> node keys listed on it
for (n, e) in links: members[e].add(n)
enr_of_m = defaultdict(set)
for (n, e) in links: enr_of_m[n].add(e)
colisted = {}
def co(n):
    if n not in colisted: colisted[n] = set().union(*(members[e] for e in enr_of_m[n])) - {n}
    return colisted[n]
def middles(n):
    return sorted({m for m in mids.get(n, ()) if m})
by_name = defaultdict(set)
for nid, x in nodes.items():
    if x["kind"] == "person" and pname.get(x["key"], "").strip(): by_name["p" + pname[x["key"]]].add(x["key"])
    elif x["kind"] == "org": by_name["o" + org_key(names[x["key"]])].add(x["key"])
copies = defaultdict(list)
for nid, x in nodes.items():
    if x["kind"] in ("person", "org"): copies[x["key"]].append(nid)
samename_pairs = []
for k, keys in by_name.items():
    if len(keys) < 2: continue
    for a in keys:
        out = []
        for b in sorted(keys - {a}):
            ma, mb = middles(a), middles(b)
            out.append({"cms_id": b[1:], "name": names[b], "groups": sorted({nodes[c]["group"] for c in copies[b]}),
                        "shared_colisted": len(co(a) & co(b)), "shared_agencies": len(enr_of_m[a] & enr_of_m[b]),
                        **({"middle": mb} if mb else {}), **({"own_middle": ma} if ma else {})})
            if a < b: samename_pairs.append((a, b))
        for c in copies[a]: nodes[c]["same_name"] = sorted(out, key=lambda o: -o["shared_colisted"])
for a, b in samename_pairs:
    for i in copies[a]:
        for j in copies[b]:
            if nodes[i]["group"] == nodes[j]["group"]:
                edges.append({"from": i, "to": j, "cat": "samename", "roles": ["same name, different CMS ID (unconfirmed)"],
                              "first": None, "last": None, "weak": True, "src": "name comparison only"})

groups = []
for g in order:
    es = [enr[e] for e in keep[g]]
    groups.append({"id": gid[g], "n": len(es), "n_hospice": sum(e["kind"] == "hospice" for e in es),
                   "n_hha": sum(e["kind"] == "hha" for e in es), "paid": sum(e["paid"] or 0 for e in es),
                   "states": sorted({e["state"] for e in es if e.get("state")}),
                   "n_revoked": sum(e["status"] == "revoked" for e in es),
                   "n_affil": sum(e.get("rev_cat") == "affiliation" for e in es),
                   "n_carrier": sum(bool(e.get("carrier")) for e in es),
                   "n_gone": sum(e["status"].startswith("not in") for e in es)})
releases = sorted({x["first"] for x in links.values()} | {x["last"] for x in links.values()})
data = {"nodes": list(nodes.values()), "edges": edges, "samename_pairs": samename_pairs, "groups": groups, "releases": releases,
        "files": [{"name": f, **CMS_FILES[f]} for f in FILES],
        "sources": [f"{SRC_HOS} / {SRC_HHA} releases {releases[0]}..{releases[-1]}", SRC_ENR, SRC_REV,
                    "CMS PAC PUF Hospice and HHA 2024", "OIG LEIE (name match only)"]}
vendor = root / "scripts" / "vendor" / "vis-network-9.1.2.min.js"  # vis-network 9.1.2 (Apache-2.0 / MIT)
html = (root / "scripts" / "graph_template.html").read_text()
html = html.replace("__VIS__", vendor.read_text().replace("</script", "<\\/script"))
slim = {**data, "edges": [{k: v for k, v in e.items() if k != "recs"} for e in edges]}   # graph.html keeps its old size
html = html.replace("__DATA__", json.dumps(slim, default=str).replace("</", "<\\/"))
out = root / "out" / "graph.html"
out.write_text(html)
sizes = sorted((g["n"] for g in groups), reverse=True)
print(f"{out}: {len(nodes)} nodes, {len(edges)} edges, {len(groups)} networks; largest {sizes[:8]}; "
      f"{sum(g['n_revoked'] for g in groups)} revoked, {sum(g['n_carrier'] for g in groups)} carriers; {len(weak)} weak nodes; "
      f"{len(html) / 1e6:.1f} MB")
