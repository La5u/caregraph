"""Public table exports and release comparisons. Only explicitly selected CMS fields leave this module."""
from collections import defaultdict
import base64
import hashlib
import hmac
import json
import os
import re
from pathlib import Path


def words(value):
    return re.findall(r"[^\W_]+", str(value or "").upper(), re.UNICODE)


def name_pairs(first, last):
    return tuple(words(first) + words(last))


def contains_name(text, names):
    """Word-bigram lookup, including complete multiword first/last names; no per-name scan."""
    tokens = words(text)
    for i in range(len(tokens) - 1):
        for candidate in names.get(tuple(tokens[i:i + 2]), ()):
            if tuple(tokens[i:i + len(candidate)]) == candidate:
                return True
    return False


def owner_identities(db):
    """Read only distinct identity columns, in batches, from all four owner tables."""
    names, ids, orgs, individual_orgs = defaultdict(set), set(), set(), set()
    for table in ("hist_hospice_owners", "hist_hha_owners", "hospice_owners", "hha_owners"):
        cols = {r[0] for r in db.execute(f'DESCRIBE {table}').fetchall()}
        type_cols = [c for c in cols if c in ("OTHER TYPE TEXT - OWNER", "ORGANIZATION TYPE - OWNER")]
        extra = [f'"{c}"' for c in type_cols]
        query = ', '.join(f'"{c}"' for c in ("TYPE - OWNER", "ASSOCIATE ID - OWNER", "FIRST NAME - OWNER", "LAST NAME - OWNER", "ORGANIZATION NAME - OWNER"))
        cur = db.execute(f'SELECT DISTINCT {query}' + (', ' + ', '.join(extra) if extra else '') + f' FROM {table}')
        while batch := cur.fetchmany(8192):
            for typ, aid, first, last, org, *other in batch:
                if typ == "I":
                    if aid:
                        ids.update((str(aid), str(aid).lstrip("0")))
                    nm = name_pairs(first, last)
                    if first and last and len(nm) >= 2:
                        names[nm[:2]].add(nm)
                elif org:
                    orgs.add(org)
                    if re.search(r"\b(SOLE PROPRIETOR(?:SHIP)?|INDIVIDUAL)\b", ' '.join(str(x or '') for x in other), re.I):
                        individual_orgs.add(org)
    return names, ids, orgs, individual_orgs


def person_like(name, names, individual_orgs=()):
    return name in individual_orgs or bool((re.search(r"\b(ESTATE OF|TRUST|TRUSTEE|REVOCABLE)\b", name or '', re.I) and not re.search(r"\b(BANK|TRUST (COMPANY|CO)\b|N\.?A\.?$)", name or '', re.I))) or contains_name(name, names)


def public_token(key, secret):
    return base64.b32encode(hmac.new(secret, key.encode(), hashlib.sha256).digest()).decode()[:16]


def person_secret(path=None):
    path = Path(path) if path else Path.home() / '.config/caregraph/person_hmac_key'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(os.urandom(32))
    if path.stat().st_mode & 0o077:
        raise SystemExit('person_hmac_key must have mode 600: ' + str(path))
    secret = path.read_bytes()
    if len(secret) < 32:
        raise SystemExit('person_hmac_key must contain at least 32 secret bytes')
    return secret


# Optional local suppression: data/suppress.txt, one enrollment ID, CCN or person token per line; # comments.
def suppressions(path):
    return {line.split('#', 1)[0].strip() for line in path.read_text().splitlines() if line.split('#', 1)[0].strip()} if path.exists() else set()


def public_reason(reason):
    """Replace the 42 CFR 424.535(a)(2) and (a)(3) segments; the other grounds keep CMS's words."""
    replacement = 'Other grounds; see the CMS record'
    parts = []
    for segment in (reason or '').split(';'):
        hidden = re.search(r'\(a\)\s*\(0?[23]\)|FELON|CONVICT|EXCLU(?:DED|SION)|DEBARR|SUSPEN(?:DED|SION)', segment, re.I)
        text = replacement if hidden else segment.strip()
        if text and text not in parts:
            parts.append(text)
    return '; '.join(parts)


def public_records(records, private=True):
    # Owner associate IDs ("aid") and names as listed identify people, so they are dropped for every record: source
    # links filter on the agency's enrollment ID. "assoc" is the association date. Union identical rows' releases.
    keep = ('f', 'code', 'role', 'pct', 'assoc', 'addr')
    result = {}
    for record in records:
        row = {k: record[k] for k in keep if record.get(k) not in (None, '', [])}
        fs = row.pop('f', [])
        key = json.dumps(row, sort_keys=True)
        if key not in result:
            result[key] = {**row, 'f': []}
        result[key]['f'] = sorted(set(result[key]['f']) | set(fs))
    return list(result.values())


def shard_key(value):
    number = 2166136261
    for c in value:
        number = ((number ^ ord(c)) * 16777619) & 0xffffffff
    return f'{number % 256:02x}'


def metric_record(source, n):
    rec = source.get(n.get('ccn'), {})
    if rec and rec.get('k') != n['kind']:
        return {}
    return {k: v for k, v in rec.items() if k not in ('ind', 'ind_na', 'bldg_n') or n['kind'] == 'hospice'}

TABLE_FIELDS = ("id", "name", "dba", "kind", "city", "state", "ccn", "status", "paid", "benes_2024", "first_seen")
BAR_FIELDS = ("RE_ENRLMT_BAR_YRS", "REENRLMT_BAR_YRS", "RE_ENRLMT_BAR", "REENRLMT_BAR", "RE_ENROLLMENT_BAR", "RE_ENRLMT_BAR_END_DT")


def release_pairs(files, dataset):
    """Compare consecutive releases of the same dataset, never infer absence from an unavailable file."""
    dates = sorted({f["rel"] for f in files if f["ds"] == dataset})
    return list(zip(dates, dates[1:]))


def changes_for(enrollments, links, files, names):
    events = []
    calendars = {ds: release_pairs(files, ds) for ds in {f["ds"] for f in files}}
    # Enrollment and owner datasets have different calendars. Compare each to its own previous file.
    def emit(eid, before, after, event, detail=""):
        events.append({"id": eid, "before": before, "release": after, "event": event, "detail": detail})
    for eid, n in enrollments.items():
        present = {files[i]["rel"] for i in n.get("ef", [])}
        datasets = {files[i]["ds"] for i in n.get("ef", [])}
        for ds in datasets:
            for before, after in calendars[ds]:
                if after in present and before not in present: emit(eid, before, after, "New enrollment")
                if before in present and after not in present: emit(eid, before, after, "Enrollment no longer listed")
    # Set comparisons ignore row formatting, percentage and association-date corrections.
    listed = defaultdict(lambda: defaultdict(set))
    for (key, eid), link in links.items():
        if key.endswith(" *"): continue  # building copies are not a second address change
        for record, indexes in link["recs"].items():
            address = isinstance(record, str)
            if not address and record[1] not in ("34", "35", "38", "43"): continue
            role = "Address" if address else record[2]
            for i in indexes:
                f = files[i]; ds = f["ds"]
                listed[(eid, ds)][f["rel"]].add((key, role))
    for (eid, ds), by_release in listed.items():
        for before, after in calendars[ds]:
            old, new = by_release[before], by_release[after]
            removed, added = old - new, new - old
            for key, role in sorted(removed):
                if key.startswith("a"): continue  # folded into an address moved row below
                emit(eid, before, after, "Owner/control removed", f"{names[key]} · {role}")
            for key, role in sorted(added):
                if key.startswith("a"): continue
                emit(eid, before, after, "Owner/control added", f"{names[key]} · {role}")
            old_a = {key for key, _ in old if key.startswith("a")}
            new_a = {key for key, _ in new if key.startswith("a")}
            if new_a - old_a:
                moved = bool(old_a - new_a)
                detail = ("; ".join(names[k] for k in sorted(old_a - new_a)) + " → " if moved else "")
                detail += "; ".join(names[k] for k in sorted(new_a - old_a))
                emit(eid, before, after, "Address moved" if moved else "Address added", detail)
    # The extract has one observation date. Report effective dates as event dates; do not imply we saw
    # a new revocation row in a historic quarterly file that we do not have.
    rev_file = next((f for f in files if "Revoked" in f["ds"]), None)
    if rev_file:
        for eid, n in enrollments.items():
            if n.get("rev_date") and n["rev_date"] != "None":
                emit(eid, "", rev_file["rel"], "Revocation", "Effective " + n["rev_date"] + "; CMS extract observation")
    return sorted(events, key=lambda e: (e["release"], e["id"], e["event"], e["detail"]), reverse=True)


def make_catalog(graph, files, group_of, indicators=None):
    enr = graph["enr"]
    indicators = indicators or {"agencies": {}, "metrics": {}, "indicators": {}}
    rows, ind_of = [], {}
    for eid, n in enr.items():
        row = {k: n[k] for k in TABLE_FIELDS if n.get(k) is not None}
        row["group"] = group_of[eid] if isinstance(group_of[eid], int) else None
        # Indicators are not in the table rows; they load lazily from metrics.json (keyed by CCN).
        ind_of[eid] = metric_record(indicators["agencies"], n).get("ind", [])
        rows.append(row)
    rows.sort(key=lambda n: (not bool(n.get("name")), (n.get("name") or "").upper(), n["id"]))
    changes = changes_for(enr, graph["links"], files, graph["names"])
    address_rows, details = [], {}
    virtual_buildings = {key.split(" #")[0] + " *" for key in graph["virt_addr"]}
    for key, ids in graph["addr_enr"].items():
        if len(ids) < 2: continue
        aid = hashlib.sha256(key.encode()).hexdigest()[:20]
        current = set()
        listings = []
        for eid in sorted(ids):
            x = graph["addr_links"][(key, eid)]
            for raw, fs in x["recs"].items():
                rs = sorted({files[i]["rel"] for i in fs})
                # Current means listed at this address in the latest enrollment file of its own type.
                ds = {files[i]["ds"] for i in fs}
                latest = max(f["rel"] for f in files if f["ds"] in ds)
                if latest in rs: current.add(eid)
                listings.append({"id": eid, "address": raw, "first": rs[0], "last": rs[-1], "files": sorted(set(fs))})
        mt = graph["MULTITENANT"].get(key[1:]) or graph["MULTITENANT"].get(key[1:].removesuffix(" *"))
        flags = (["Multi-tenant checked"] if mt else []) + (["Executive suite"] if key in graph["virt_addr"] or key in virtual_buildings else [])
        address_rows.append({"id": aid, "address": graph["names"][key], "building": key in graph["bldg"],
                             "ever": len(ids), "current": len(current), "revoked": sum(enr[e]["status"] == "revoked" for e in ids),
                             "paid": sum(enr[e].get("paid") or 0 for e in ids) if any(enr[e].get("paid") is not None for e in ids) else None, "flags": flags})
        details["a/" + aid] = listings
    address_rows.sort(key=lambda n: (-n["current"], n["address"]))
    return {"agencies": rows, "agencies-first": rows[:100], "addresses": address_rows, "changes": changes,
            "tables": {"count": len(rows), "states": sorted({n["state"] for n in rows if n.get("state")}),
                       "pairs": sorted({(e["before"], e["release"]) for e in changes}, reverse=True),
                       "events": sorted({e["event"] for e in changes}), "latest": graph["LATEST"],
                       "metrics": indicators["metrics"], "indicators": indicators["indicators"],
                       "indicator_counts": {key: sum(key in ind for ind in ind_of.values()) for key in indicators["indicators"]}}, **details}
