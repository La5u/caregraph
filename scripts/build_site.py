"""Build both CareGraph sites from the same data as scripts/build_graph.py:
  - private/site_dist/: the private real-name site for local investigation (gitignored, never deployed);
  - site/dist/: the public pseudonymized site, the only directory that is ever deployed.

Differences of the public site from out/graph.html:
  - Only whitelisted fields from public CMS files are published. Derived flags are dropped: "carrier",
    same-name/different-ID links, CMS beneficiary risk score, NPPES official phone.
  - Node positions are precomputed (a numpy port of the original page's vis-network physics), so the page opens
    frozen; the browser draws with site/renderer.js (WebGL) and runs a layout only on request.
  - Every link has deferred source records (one per distinct CMS row, with the release files it appears in) and every
    agency its NPI and enrollment-file releases; index.json lists those files with their data.cms.gov API endpoints
    (scripts/cms_files.json), so the page can link each record to the exact rows.
  - Data is split into content-versioned table, network, search, path and record files,
    loaded on demand, so the page stays small.

Usage: .venv/bin/python -I scripts/build_site.py [--private | --public] [project_dir]

No flag: builds the private site, then the public site, each in its own child process run one after the other (the
build mutates the graph in place and memory is tight); stops with a non-zero exit if either fails.
--private: only private/site_dist/ (never site/dist). It skips the publication boundary below (person/entity tokens,
agency renaming, revocation reason rewriting, record name stripping, data/suppress.txt), so it shows the real names and
IDs the private graph has, and marks the page as private.
--public: only site/dist/, with the publication boundary applied.
"""
import gc
import csv
import hashlib
import gzip
import json
import math
import runpy
import shutil
import sys
import subprocess
from collections import defaultdict
from pathlib import Path

MODES = [a for a in sys.argv[1:] if a in ("--private", "--public")]
if len(MODES) > 1:
    raise SystemExit("Use at most one of --private / --public")
if not MODES:   # both, private first; each child exits (and frees its memory) before the next starts
    for mode in ("--private", "--public"):
        if subprocess.run([sys.executable, "-I", __file__, mode, *sys.argv[1:]]).returncode:
            raise SystemExit(f"build_site.py {mode} failed")
    raise SystemExit(0)
PRIVATE = MODES[0] == "--private"
sys.argv.remove(MODES[0])   # build_graph.py, run below with this sys.argv, reads sys.argv[1] as the project dir

import igraph
import numpy as np

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
# Fail before loading the graph if the separate metrics input is unavailable.
helpers = runpy.run_path(str(root / "scripts" / "site_tables.py"))
indicator_path = root / "data/derived/indicators.json"
if not indicator_path.is_file():
    raise SystemExit("Missing data/derived/indicators.json; run scripts/build_indicators.py first")
indicators = json.loads(indicator_path.read_text())
for field in ("agencies", "metrics", "indicators"):
    if not isinstance(indicators.get(field), dict):
        raise SystemExit("Invalid indicators.json: missing " + field)
graph = runpy.run_path(str(root / "scripts" / "build_graph.py"), run_name="build_graph")
data = graph["data"]

ENR_KEEP = ["id", "kind", "name", "dba", "state", "city", "ccn", "address", "first_seen", "last_seen", "status",
            "rev_date", "rev_reason", "benes_2024", "paid",
            "certified", "benes_prev", "paid_prev", "paid_year", "pf", "hci_score", "pct_early_live_discharge", "pct_late_live_discharge", "group", "npi", "ef", "rev_bar"] + (["phone"] if PRIVATE else [])   # a small agency's phone is often its owner's mobile: private build only
OTHER_KEEP = ["id", "kind", "name", "group", "weak", "weak_reason", "n_enrollments", "n_here", "building",
              "other_networks", "virtual", "merged", "multitenant"]
EDGE_KEEP = ["from", "to", "roles", "cat", "first", "last", "pct", "weak", "recs"]
GROUP_KEEP = ["id", "n", "n_hospice", "n_hha", "paid", "states", "n_revoked", "n_affil", "n_gone"]


def pick(d, keys):
    return {k: d[k] for k in keys if d.get(k) not in (None, "", [])}


# The bar is a public field from the same revocation extract. Do not infer one from dates/reason.
bar_fields = helpers["BAR_FIELDS"]
with open(root / "data/raw/cms_revoked/Revocation_Extract_2026.10.21.csv", encoding="cp1252", newline="") as fh:
    for row in csv.DictReader(fh):
        if row["ENRLMT_ID"] in graph["enr"]:
            values = [f"{key}: {row[key]}" for key in bar_fields if row.get(key)]
            if values: graph["enr"][row["ENRLMT_ID"]]["rev_bar"] = "; ".join(values)

nodes = defaultdict(list)
for n in data["nodes"]:
    enr = n["kind"] in ("hospice", "hha")
    public = pick(n, ENR_KEEP if enr else OTHER_KEEP)
    if enr and graph["enr"][n["id"]].get("rev_bar"):
        public["rev_bar"] = graph["enr"][n["id"]]["rev_bar"]
    nodes[n["group"]].append(public)
group_of = {n["id"]: n["group"] for n in data["nodes"]}
edges = defaultdict(list)
for e in data["edges"]:
    if e["cat"] == "samename":
        continue
    edges[group_of[e["to"]]].append(pick(e, EDGE_KEEP))
groups, releases, sources = data["groups"], data["releases"],data["sources"]
files = [{k: f[k] for k in ("ds", "rel", "api", "page", "csv")} for f in data["files"]]
ext = {key: next(i for i, f in enumerate(data["files"]) if pat in f["name"])
       for key, pat in (("rev", "Revocation_Extract"), ("pac_hospice", "PACPUF_HOS"), ("pac_hha", "PACPUF_HH_"))}
# Include every enrollment, plus people listed only on one agency (available through Advanced).
# Enrollments outside a multi-agency network get a single-agency drill-down, not a new network.
for eid, raw in graph["enr"].items():
    gid_ = group_of.get(eid, "solo-" + eid)
    if eid not in group_of:
        nodes[gid_].append({**pick(raw, ENR_KEEP), "group": gid_})
    group_of[eid] = gid_
known = {gid_: {n["id"] for n in ns} for gid_, ns in nodes.items()}
for (key, eid), link in graph["links"].items():
    gid_ = group_of[eid]
    nid = f"{key}@{gid_}"
    if nid in known[gid_]:
        continue
    raw = {"id": nid, "kind": {"I": "person", "O": "org", "A": "address"}[graph["ntype"][key]],
           "name": graph["names"][key], "group": gid_, "n_enrollments": len(graph["per"][key]), "n_here": 1,
           "building": graph["bldg"].get(key), "virtual": key in graph["virt_addr"],
           "multitenant": graph["MULTITENANT"].get(key[1:]) if key[0] == "a" else None}
    # Existing shared nodes already have all their edges; these are the previously omitted nodes.
    nodes[gid_].append(pick(raw, OTHER_KEEP)); known[gid_].add(nid)
    cat = next(c for c in ("owner", "control", "manager", "officer", "address", "other") if c in link["cats"])
    edges[gid_].append({"from": nid, "to": eid, "roles": sorted(link["roles"]), "cat": cat,
                       "first": link["first"], "last": link["last"], "pct": link["pct"],
                       "weak": (key, eid) not in graph["joins"],
                       "recs": graph["recs_of"](link["recs"])})
# Publication boundary: graph construction and its canonical merge keys stay private and unchanged.
if not PRIVATE:
    name_index, individual_ids, org_names, individual_orgs = helpers["owner_identities"](graph["db"])
    secret = helpers["person_secret"]()
    private_keys = {key for key, typ in graph["ntype"].items() if typ == "I"}
    org_keys = {key for key, typ in graph["ntype"].items() if typ == "O" and
                helpers["person_like"](graph["names"][key], name_index, individual_orgs)}
    # Check every historic spelling, including names hidden by the private graph's display-name choice.
    for (key, eid), link in graph["links"].items():
        if graph["ntype"][key] == "O" and any(helpers["person_like"](r[5], name_index, individual_orgs) for r in link["recs"]):
            org_keys.add(key)
    private_keys |= org_keys
    tokens = {key: helpers["public_token"](key, secret) for key in private_keys}
    assert len(set(tokens.values())) == len(tokens), "Public person/entity token collision"
    assert not set(tokens.values()).intersection(graph["enr"]), "Token/enrollment collision"
    public_names = {key: ("Entity " if key in org_keys else "Person ") + token for key, token in tokens.items()}
    print(f"Person-like organizations tokenized: {len(org_keys)}; sample: " +
          repr([graph["names"][k] for k in sorted(org_keys)[:10]]))
    print("Agency names containing a listed person's full name:", sum(
        any(helpers["contains_name"](n.get(f), name_index) for f in ("name", "dba")) for n in graph["enr"].values()))
    # A type field is not present in every CMS enrollment release. Count only explicit individual classifications.
    individual_enrollments = set()
    for table in ("hist_hospice_enrollments", "hist_hha_enrollments", "hospice_enrollments", "hha_enrollments"):
        columns = {r[0] for r in graph["db"].execute(f'DESCRIBE {table}').fetchall()}
        for col in sorted(columns & {"PROVIDER TYPE", "ORGANIZATION TYPE", "ENTITY TYPE", "IS SOLE PROPRIETOR"}):
            individual_enrollments.update(r[0] for r in graph["db"].execute(
                f'SELECT DISTINCT "ENROLLMENT ID" FROM {table} WHERE upper("{col}") IN (\'I\', \'INDIVIDUAL\', \'SOLE PROPRIETOR\', \'SOLE PROPRIETORSHIP\', \'YES\', \'Y\')').fetchall())
    print("Agency enrollments explicitly classified as individuals (CMS business name retained):", len(individual_enrollments))
    suppressed = helpers["suppressions"](root / "data/suppress.txt")
    suppressed_keys = {k for k, t in tokens.items() if t in suppressed or public_names[k] in suppressed}
    suppressed_enr = {eid for eid, n in graph["enr"].items() if eid in suppressed or n.get("ccn") in suppressed}
    print(f"Suppression: {len(suppressed_enr)} enrollments, {len(suppressed_keys)} person/entity nodes")
    for eid in suppressed_enr:
        del graph["enr"][eid]
    graph["links"] = {(k, e): v for (k, e), v in graph["links"].items() if e not in suppressed_enr and k not in suppressed_keys}
    graph["addr_enr"] = {k: set(es) - suppressed_enr for k, es in graph["addr_enr"].items()}
    graph["names"].update(public_names)
    def is_person_name(text):
        """The whole field is exactly a listed person's name: a sole proprietor's agency under the owner's own name."""
        t = tuple(helpers["words"](text))
        return len(t) >= 2 and t in name_index.get(t[:2], ())
    # Names of the people CMS lists on each enrollment, so "JANE DOE HOSPICE LLC" is caught on Jane Doe's own agency.
    listed_on = defaultdict(set)
    for table in ("hist_hospice_owners", "hist_hha_owners", "hospice_owners", "hha_owners"):
        cur = graph["db"].execute(f'SELECT DISTINCT "ENROLLMENT ID", "FIRST NAME - OWNER", "LAST NAME - OWNER" FROM {table} WHERE "TYPE - OWNER" = \'I\'')
        while batch := cur.fetchmany(8192):
            for eid, first, last in batch:
                if first and last:
                    listed_on[eid].add(frozenset(helpers["name_pairs"](first, last)))
    def names_listed_person(text, eid):
        t = set(helpers["words"](text))
        return is_person_name(text) or any(len(c) >= 2 and c <= t for c in listed_on.get(eid, ()))
    def public_agency_names(n, eid):
        if names_listed_person(n.get("dba"), eid):
            n.pop("dba")
        if names_listed_person(n.get("name"), eid):
            n["name"] = n.pop("dba", None) or ("Hospice" if n["kind"] == "hospice" else "Home health agency") + " (individual owner)"
            return True
        return False
    renamed = 0
    for eid, n in graph["enr"].items():
        renamed += public_agency_names(n, eid)
        if n.get("rev_reason"):
            n["rev_reason"] = helpers["public_reason"](n["rev_reason"])
    for ns in nodes.values():
        for n in ns:
            if n["kind"] in ("hospice", "hha"):
                public_agency_names(n, n["id"])
    print("Agencies named after a person listed on them, published under a trade or generic name:", renamed)
    for gid_, ns in list(nodes.items()):
        old_keys = {n["id"]: n["id"].split("@")[0] for n in ns}
        ns = [n for n in ns if n["id"] not in suppressed_enr and old_keys[n["id"]] not in suppressed_keys]
        kept_ids = {n["id"] for n in ns}
        es = [e for e in edges[gid_] if e["from"] in kept_ids and e["to"] in kept_ids]
        for e in es:
            key = old_keys[e["from"]]
            e["recs"] = helpers["public_records"](e.get("recs", []))
            e["from"] = tokens.get(key, e["from"])
        for n in ns:
            key = old_keys[n["id"]]
            if key in tokens:
                n["id"], n["name"] = tokens[key], public_names[key]
            if n.get("rev_reason"):
                n["rev_reason"] = helpers["public_reason"](n["rev_reason"])
        nodes[gid_], edges[gid_] = ns, es
        if not any(n["kind"] in ("hospice", "hha") for n in ns):
            del nodes[gid_]; del edges[gid_]
groups = [grp for grp in groups if grp["id"] in nodes]
if not PRIVATE and suppressed_enr:
    for grp in groups:
        agencies = [n for n in nodes[grp["id"]] if n["kind"] in ("hospice", "hha")]
        grp.update(n=len(agencies), n_hospice=sum(n["kind"] == "hospice" for n in agencies),
                   n_hha=sum(n["kind"] == "hha" for n in agencies), paid=sum(n.get("paid") or 0 for n in agencies),
                   states=sorted({n["state"] for n in agencies if n.get("state")}),
                   n_revoked=sum(n.get("status") == "revoked" for n in agencies),
                   n_affil=sum("(a)(19)" in n.get("rev_reason", "").lower() for n in agencies),
                   n_gone=sum(n.get("status", "").startswith("not in") for n in agencies))
for ns in nodes.values():
    for n in ns:
        if "other_networks" in n:
            n["other_networks"] = [g for g in n["other_networks"] if g in nodes]
catalog = helpers["make_catalog"](graph, files, group_of, indicators)
# Metrics are stored once per CCN, rather than repeated in every network and enrollment row.
public_ccns = {n.get("ccn") for n in graph["enr"].values()}
catalog["metrics"] = {c: r for c, r in indicators["agencies"].items() if c in public_ccns}
for c, rec in catalog["metrics"].items():
    if rec.get("k") == "hha":
        for field in ("ind", "ind_na", "bldg_n"):
            rec.pop(field, None)
if not PRIVATE:
    del secret, tokens, public_names, name_index, individual_ids, org_names, individual_orgs, private_keys

del data, graph, group_of, known
gc.collect()

dist = root / "site" / "dist"
if PRIVATE:   # real names: never the deployable site/dist, always the gitignored private/ tree
    dist = root / "private" / "site_dist"
assert PRIVATE == (dist.parent.name == "private") and PRIVATE != (dist.parent.name == "site"), dist
if dist.exists():
    shutil.rmtree(dist)
payload = dist / "data" / "pending"
for folder in ("g", "r", "a"):
    (payload / folder).mkdir(parents=True)

shards = defaultdict(dict)
def write_json(path, value):
    # Bound file count: tiny per-agency graphs/records and address details used to produce thousands of files.
    if path.parent.name in ("g", "r", "a"):
        shards[(path.parent.name, helpers["shard_key"](path.stem))][path.stem] = value
    else:
        path.write_text(json.dumps(value, default=str, separators=(",", ":")))

for name, value in catalog.items():
    write_json(payload / (name + ".json"), value)
del catalog


# Layout: a numpy port of the vis-network 9 physics the original live page (out/graph.html) used, so the frozen
# layout looks like what that page settled into: Barnes-Hut defaults (computed exactly here, no quadtree),
# springLength 130, smooth "dynamic" edges (one hidden support node per edge, two half-length springs),
# 300 stabilization steps, Kamada-Kawai start like vis's improvedLayout.
G_CONST, CENTRAL, SPRING_LEN, SPRING_K, DAMPING = -2000.0, 0.3, 130.0, 0.04, 0.09
MAX_V, MIN_V, TIMESTEP, ITERATIONS, KK_EDGE = 50.0, 0.1, 0.5, 300, 150.0
BLOCK = 256


def vis_layout(n, pairs):
    if n < 2:
        return [[0, 0]] * n
    pairs = [(a, b) for a, b in pairs if a != b]
    gr = igraph.Graph(n=n, edges=pairs)
    xy = np.array(gr.layout_kamada_kawai(maxiter=50 * n).coords) * KK_EDGE
    a = np.array([p[0] for p in pairs], dtype=int)
    b = np.array([p[1] for p in pairs], dtype=int)
    via = np.arange(n, n + len(pairs))
    P = (np.vstack([xy, (xy[a] + xy[b]) / 2]) if len(pairs) else xy).astype(np.float32)   # support nodes start mid-edge
    V = np.zeros_like(P)
    s_from = np.concatenate([a, via])            # springs: node1 -> via, via -> node2, each half length
    s_to = np.concatenate([via, b])
    m = len(P)
    for _ in range(ITERATIONS):
        F = np.zeros_like(P)
        for i in range(0, m, BLOCK):              # repulsion in row blocks: memory stays ~BLOCK x m, not m x m
            dx = P[None, :, 0] - P[i:i + BLOCK, None, 0]   # other - self
            dy = P[None, :, 1] - P[i:i + BLOCK, None, 1]
            d2 = np.maximum(dx * dx + dy * dy, 0.01)
            f = G_CONST / (d2 * np.sqrt(d2))
            f[np.arange(len(f)), np.arange(i, i + len(f))] = 0
            F[i:i + BLOCK, 0] = (dx * f).sum(1)
            F[i:i + BLOCK, 1] = (dy * f).sum(1)
        r = np.maximum(np.sqrt((P ** 2).sum(1)), 1e-9)   # central gravity: constant pull toward the origin
        F -= P * (CENTRAL / r)[:, None]
        if len(pairs):
            d = P[s_from] - P[s_to]
            L = np.maximum(np.sqrt((d ** 2).sum(1)), 0.01)
            fs = d * (SPRING_K * (SPRING_LEN / 2 - L) / L)[:, None]
            np.add.at(F, s_from, fs)
            np.add.at(F, s_to, -fs)
        V = np.clip(V + (F - DAMPING * V) * TIMESTEP, -MAX_V, MAX_V)
        P += V * TIMESTEP
        if np.abs(V).max() < MIN_V:
            break
    return np.round(P[:n]).astype(int).tolist()


def alt_names(n):
    return []


def core_of(ns, es):
    core = [n["id"] for n in ns if n["kind"] in ("hospice", "hha") or n.get("n_here", 0) > 1]
    pos = {i: k for k, i in enumerate(core)}
    pairs = sorted({(pos[e["from"]], pos[e["to"]]) for e in es if e["from"] in pos and e["to"] in pos})
    return core, pairs


def place(ns, es, core, xy):
    """Core nodes at the computed positions; nodes with one link here go in a ring around their neighbour."""
    at = dict(zip(core, map(tuple, xy)))
    nb = {}
    for e in es:
        for a_, b_ in ((e["from"], e["to"]), (e["to"], e["from"])):
            if a_ not in at and b_ in at: nb.setdefault(a_, b_)
    ring = defaultdict(int)
    for n in ns:
        if n["id"] in at:
            n["x"], n["y"] = at[n["id"]]
            continue
        c = nb.get(n["id"])
        k = ring[c]; ring[c] += 1
        cx, cy = at[c] if c else (0, 0)
        r = 60 + 20 * (k // 12)
        n["x"], n["y"] = int(cx + r * math.cos(k * 0.52)), int(cy + r * math.sin(k * 0.52))


cores = {i: core_of(ns, edges[i]) for i, ns in nodes.items()}
xys = {i: vis_layout(len(c), p) for i, (c, p) in cores.items()}

index, searches = [], {}
for i, ns in nodes.items():
    place(ns, edges[i], cores[i][0], xys[i])
    records = []
    for e in edges[i]:
        recs = e.pop("recs", [])
        records.append(recs)
        # Exact release membership remains available without downloading source records.
        e["fs"] = sorted({f for r in recs for f in r["f"]})
    write_json(payload / "g" / f"{i}.json", {"nodes": ns, "edges": edges[i]})
    write_json(payload / "r" / f"{i}.json", records)
for grp in groups:
    i = grp["id"]; ns = nodes[i]
    search = " ".join(sorted({str(n.get(k)) for n in ns for k in ("name", "dba", "city", "ccn", "id") if n.get(k)}
                             | {a for n in ns for a in alt_names(n)}))
    searches[i] = search.upper()
    index.append({**pick(grp, GROUP_KEEP), "n_people": sum(n["kind"] == "person" for n in ns), "n_orgs": sum(n["kind"] == "org" for n in ns)})
write_json(payload / "search.json", searches)
# Path finder names load on typing, adjacency loads only on Find: one node per enrollment / CMS associate ID /
# address across all networks (the per-network copies "key@group" merged), one edge per published link with its
# network and position in that network's file, so a path step can open the exact link.
CATS = {"owner": "o", "control": "c", "officer": "f", "manager": "m", "address": "a", "other": "x"}
pkey, pnames, pkinds, psearch, psub, pedges, pcat, pweak = {}, [], [], [], [], [], [], []
for grp in groups:
    gid_ = grp["id"]
    byid = {n["id"]: n for n in nodes[gid_]}
    for k, e in enumerate(edges[gid_]):
        ends = []
        for nid in (e["from"], e["to"]):
            key = nid.split("@")[0]
            if key not in pkey:
                n = byid[nid]
                pkey[key] = len(pnames)
                pnames.append(n.get("dba") or n.get("name") or key)
                psub.append(" ".join(filter(None, [n.get("city"), n.get("state")])) if n["kind"] in ("hospice", "hha")
                            else "")
                pkinds.append({"hospice": "h", "hha": "H", "person": "p", "org": "o", "address": "a"}[n["kind"]])
                psearch.append(" ".join([str(n[f]) for f in ("name", "dba", "city", "state", "ccn") if n.get(f)] + alt_names(n)).upper()
                               + (" " + key if n["kind"] in ("hospice", "hha") else ""))
            ends.append(pkey[key])
        pedges += [ends[0], ends[1], gid_, k]
        pcat.append(CATS.get(e["cat"], "x"))
        pweak.append("1" if e.get("weak") else "0")
write_json(payload / "path-names.json", {"names": pnames, "sub": psub, "kinds": "".join(pkinds), "search": psearch})
write_json(payload / "path-edges.json", {"edges": pedges, "cat": "".join(pcat), "weak": "".join(pweak)})
write_json(payload / "index.json", {"groups": index, "releases": releases, "sources": sources, "files": files, "ext": ext})
for (folder, bucket), values in shards.items():
    (payload / folder / (bucket + ".json")).write_text(json.dumps(values, default=str, separators=(",", ":")))
del shards
# Hash every published data byte and runtime source: a new version invalidates data and JS together.
runtime = ("index.html", "about.html", "renderer.js", "graph_logic.js", "tables.js", "case.js", "_headers", "robots.txt")
hash_ = hashlib.sha256()
for f in sorted(payload.rglob("*.json")):
    hash_.update(str(f.relative_to(payload)).encode()); hash_.update(f.read_bytes())
for name in runtime:
    hash_.update(name.encode()); hash_.update((root / "site" / name).read_bytes())
version = hash_.hexdigest()[:20]
payload.rename(dist / "data" / version)
for name in runtime:
    text = (root / "site" / name).read_text().replace("__VERSION__", version)
    (dist / name).write_text(text)
if PRIVATE:   # data-private on <body> makes the page drop its "pseudonymized" wording (index.html, case.js)
    badge = '<span id="private-badge" style="background:#b00020;color:white;font-weight:700;padding:2px 8px;border-radius:3px">PRIVATE · real names · local only</span>'
    marks = {"index.html": [('<body data-view=', '<body data-private data-view='),
                            ('<nav id="topnav" aria-label="Views"><b>CareGraph</b>', '<nav id="topnav" aria-label="Views"><b>CareGraph</b>' + badge)],
             "about.html": [('<body>', '<body data-private><p>' + badge + ' This local build shows the real names and IDs in the CMS files; '
                             'the text below describes the public, pseudonymized site.</p>')]}
    for name, pairs in marks.items():
        text = (dist / name).read_text()
        for old, new in pairs:
            assert text.count(old) == 1, (name, old)
            text = text.replace(old, new)
        (dist / name).write_text(text)
    (dist / "PRIVATE_DO_NOT_DEPLOY.txt").write_text("Private CareGraph build with real names (scripts/build_site.py --private).\n"
                                                    "Local investigation use only: never deploy, upload or copy to the public repo.\n")
# Cloudflare rules match actual hashed JS paths (query-string rules do not select cache headers).
for name in ("renderer.js", "graph_logic.js", "tables.js", "case.js"):
    (dist / f"{name[:-3]}.{version}.js").write_text((root / "site" / name).read_text())
    (dist / name).unlink()
published = [f for f in dist.rglob("*") if f.is_file()]
assert len(published) < 20_000, "Cloudflare Pages: too many files"
assert all(f.stat().st_size <= 25 * 1024 * 1024 for f in published), "Cloudflare Pages: file exceeds 25 MiB"
size = sum(f.stat().st_size for f in published)
print(f"{dist}: {len(index)} networks, version {version}, {size / 1e6:.1f} MB total")
# These are exactly the default Agencies route's resources, including its first 100 rows.
initial = [dist / "index.html", *(dist / f"{n}.{version}.js" for n in ("graph_logic", "renderer", "tables", "case")),
           dist / "data" / version / "tables.json", dist / "data" / version / "agencies-first.json"]
try:
    import brotli
    compress, codec = brotli.compress, "brotli"
except ImportError:
    if shutil.which("brotli"):
        def compress(raw):
            return subprocess.run(["brotli", "-c"], input=raw, capture_output=True, check=True).stdout
        codec = "brotli"
    else:
        compress, codec = gzip.compress, "gzip"
raw_total = compressed_total = 0
for f in initial:
    raw = f.read_bytes(); packed = compress(raw)
    raw_total += len(raw); compressed_total += len(packed)
    print(f"  {f.relative_to(dist)}: {len(raw):,} raw / {len(packed):,} {codec} bytes")
print(f"Default page total: {raw_total:,} raw / {compressed_total:,} {codec} bytes")
if compressed_total > 500_000:
    raise SystemExit("Default page exceeds the 500 KB compressed budget")
