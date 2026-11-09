"""Record why each building-address merge in data/fraud.duckdb (table building_alias, built by scripts/build_db.py)
was made, and check it independently with the U.S. Census Bureau geocoder. Writes scripts/address_aliases.json,
which scripts/build_graph.py attaches to address nodes so the site shows every merged spelling with its reason.

Rule (same as build_db.py, which merges only within one ZIP and house number, never across N/S/E/W):
  "same street name ignoring street type / direction"  e.g. 4444 CORONA = 4444 CORONA DR
  "near-identical spelling (similarity 0.9x)"           e.g. DUBLUN = DUBLIN
  "via another spelling"                                 joined through a third variant
Census verdict: "same address" (both spellings match the same Census address, or the same street and house number
differing only in city name or a missing direction), "one spelling found", "not found" (neither spelling is in the
Census address ranges, so unverified), "different" (would mean two real places: split them in build_db.py).

Usage: .venv/bin/python -I scripts/check_address_aliases.py [previous address_aliases.json, reused as geocode cache]
"""
import difflib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import duckdb

root = Path(__file__).resolve().parent.parent
DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}   # as in build_db.py
TYPES = {"ST", "AVE", "BLVD", "RD", "DR", "CIR", "LN", "CT", "PL", "PKWY", "HWY", "FWY", "EXPY", "TER", "TRL", "SQ", "CTR",
         "PLZ", "PT", "WAY", "LOOP", "XING", "TPKE", "RTE", "BL", "HWAY"}


def name_of(key):
    toks = key.split()
    m = re.match(r"^(\d+)([NSEW])$", toks[0])
    toks = [m.group(2)] + toks[1:-1] if m else toks[1:-1]
    return " ".join(t for t in toks if t not in DIRS and t not in TYPES)


def rule(raw, canon):
    a, b = name_of(raw), name_of(canon)
    if a == b:
        return "same street name ignoring street type / direction"
    r = difflib.SequenceMatcher(None, a, b).ratio()
    return f"near-identical spelling (similarity {r:.2f})" if r >= 0.9 else "via another spelling"


def geocode(line):
    q = urllib.parse.quote(line)
    url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address={q}&benchmark=Public_AR_Current&format=json"
    for _ in range(3):
        try:
            return [m["matchedAddress"] for m in json.load(urllib.request.urlopen(url, timeout=60))["result"]["addressMatches"]]
        except Exception:
            time.sleep(2)
    return None


def street_part(matched):   # "1020W ATHERTON DR, TAYLORSVILLE, UT, 84123" -> ("1020", "ATHERTON DR")
    street = matched.split(",")[0]
    m = re.match(r"^(\d+)\s*(?:[NSEW]\b)?\s*(.*)$", street)
    return (m[1], " ".join(t for t in m[2].split() if t not in DIRS)) if m else (street, "")


def verdict(g1, g2):
    if g1 is None or g2 is None: return "geocoder error"
    if not g1 and not g2: return "not found"
    if not g1 or not g2: return "one spelling found"
    if set(g1) & set(g2) or {street_part(x) for x in g1} & {street_part(x) for x in g2}: return "same address"
    return "different"


db = duckdb.connect(str(root / "data" / "fraud.duckdb"), read_only=True)
aliases = db.execute("SELECT raw, canon FROM building_alias ORDER BY canon, raw").fetchall()
lines = dict(db.execute("""
    SELECT raw_building_key_of(a1, a2, z), any_value(a1 || ', ' || c || ', ' || s || ' ' || left(z, 5)) FROM (
      SELECT "ADDRESS LINE 1" a1, "ADDRESS LINE 2" a2, "ZIP CODE" z, CITY c, STATE s FROM hist_hospice_enrollments UNION ALL
      SELECT "ADDRESS LINE 1", "ADDRESS LINE 2", "ZIP CODE", CITY, STATE FROM hist_hha_enrollments) GROUP BY 1""").fetchall())
cache = {}
if len(sys.argv) > 1:
    for x in json.loads(Path(sys.argv[1]).read_text())["aliases"]:   # a previous scripts/address_aliases.json
        cache[x["raw"]], cache[x["canon"]] = x["census_raw"], x["census_canon"]
out = []
for raw, canon in aliases:
    g = [cache[k] if k in cache else geocode(lines[k]) for k in (raw, canon)]
    out.append({"raw": raw, "canon": canon, "raw_line": lines[raw], "canon_line": lines[canon], "rule": rule(raw, canon),
                "census_raw": g[0], "census_canon": g[1], "census": verdict(*g)})
(root / "scripts" / "address_aliases.json").write_text(json.dumps({"checked": str(date.today()), "aliases": out}, indent=1) + "\n")
counts = {}
for x in out: counts[x["census"]] = counts.get(x["census"], 0) + 1
print(f"{len(out)} merged spellings; Census: {counts}")
bad = [x for x in out if x["census"] == "different"]
for x in bad: print("DIFFERENT:", x["raw_line"], "|", x["canon_line"], x["census_raw"], x["census_canon"])
