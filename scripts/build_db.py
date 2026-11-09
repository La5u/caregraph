"""Load data/raw/*/ CSVs into data/fraud.duckdb and create starter analysis views.

Usage: .venv/bin/python -I scripts/build_db.py [project_dir]
"""
import glob
import json
import sys
from pathlib import Path

import duckdb

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
db = duckdb.connect(str(root / "data" / "fraud.duckdb"))

# One table per data/raw/<name>/ directory. Everything is loaded as text so CCNs, NPIs
# and ZIPs keep their leading zeros; numeric columns are cast in the views below.
SKIP = {"prov_svc_2024"}  # 3 GB; read from data/derived/prov_svc_2024.parquet instead (scripts/load_prov_svc.py)
for d in sorted((root / "data" / "raw").iterdir()):
    files = glob.glob(str(d / "*.csv"))
    if not files or d.name in SKIP:
        continue
    srcs = []
    for f in sorted(files):
        src = Path(f)
        try:
            src.read_bytes().decode("utf-8")
        except UnicodeDecodeError:  # some CMS files are Windows-1252; convert a copy to UTF-8
            clean = root / "data" / "clean" / src.name
            clean.parent.mkdir(exist_ok=True)
            if not clean.exists():
                clean.write_text(src.read_bytes().decode("cp1252", errors="replace"), encoding="utf-8")
            src = clean
        srcs.append(str(src))
    # hist_* directories hold several snapshots: stack them, with the source file name as `snapshot`.
    db.execute(
        f"CREATE OR REPLACE TABLE {d.name} AS SELECT * FROM read_csv(?, all_varchar=true, header=true, "
        f"union_by_name=true, filename='snapshot')",
        [srcs if d.name.startswith("hist_") else srcs[:1]],
    )
    if d.name.startswith("hist_"):
        db.execute(f"UPDATE {d.name} SET snapshot = regexp_extract(snapshot, '[^/]+$')")
    else:
        db.execute(f"ALTER TABLE {d.name} DROP COLUMN snapshot")
    print(f"{d.name:22} {db.execute(f'SELECT count(*) FROM {d.name}').fetchone()[0]:>8} rows")

db.execute(r"""
-- Address normalization. Suites appear in ADDRESS LINE 2 (usually) or at the end of line 1.
-- "STE160" (no space before the number) is a suite too.
-- OFFICE/BLDG/FLOOR/ROOM count only before a unit ("BLDG 2", "2ND FLOOR"), not in a street name ("OFFICE PARK DR").
CREATE OR REPLACE MACRO suite_re() AS '(\b[0-9]+(ST|ND|RD|TH)\s+(FL|FLOOR)\b|\b(STE|SUITE|SUIT|UNIT|APT)\b|\b(RM|ROOM|OFC|OFFICE|FL|FLOOR|BLDG|BUILDING)\b[\s.:,#-]*([0-9]|[A-Z]\b|$)|#|\b(STE|SUITE|UNIT|APT)[0-9])';
-- When line 1 holds a company name ("SC House Calls Inc") and line 2 the street, use line 2.
CREATE OR REPLACE MACRO street_line(a1, a2) AS
  CASE WHEN NOT regexp_matches(coalesce(a1, ''), '\d') AND regexp_matches(coalesce(a2, ''), '^\s*\d') THEN a2 ELSE a1 END;
-- A bare unit number after the street type ("11755 Victory Blvd 103") is a suite too.
CREATE OR REPLACE MACRO tail_unit_re() AS
  '(?i)\b(ST|STREET|AVE|AVENUE|BLVD|BOULEVARD|RD|ROAD|DR|DRIVE|CIR|CIRCLE|LN|LANE|CT|COURT|PL|PLACE|PKWY|PARKWAY|WAY|TER|TERRACE|TRL|TRAIL|PLZ|PLAZA|LOOP|FWY|FREEWAY)\.?,?\s+([0-9]+[A-Z]?|[A-DF-MO-RT-VX-Z])\s*$';   -- a lone N/S/E/W there is a direction, not a unit
-- ...except where the number is part of the road name: LOOP 410, STATE ROAD 7, COUNTY ROAD 48, ROAD 12, AVENUE U.
CREATE OR REPLACE MACRO numbered_road_re() AS
  '(?i)(\bLOOP\s+[0-9]+[A-Z]?|\b(STATE|COUNTY|CO|FM|RANCH|TOWN|TOWNSHIP|TWP|FOREST|PARISH|US)\s+(ROAD|RD|ROUTE|RTE)\s+[0-9]+[A-Z]?|^\s*[0-9]+[A-Z]?\s+((N|S|E|W|NORTH|SOUTH|EAST|WEST)\s+)?(ROAD|RD|AVENUE|AVE|AV|WAY)\s+([0-9]+[A-Z]?|[A-Z]))\.?,?\s*$';
CREATE OR REPLACE MACRO tail_unit(a1) AS
  CASE WHEN regexp_matches(coalesce(a1, ''), numbered_road_re()) THEN NULL ELSE nullif(regexp_extract(a1, tail_unit_re(), 2), '') END;
CREATE OR REPLACE MACRO no_suite(a1) AS regexp_replace(a1, '\s*' || suite_re() || '.*$', '', 'i');
CREATE OR REPLACE MACRO street_of(a1) AS
  upper(trim(CASE WHEN regexp_matches(coalesce(no_suite(a1), ''), numbered_road_re()) THEN no_suite(a1)
                  ELSE regexp_replace(no_suite(a1), tail_unit_re(), '\1') END));
CREATE OR REPLACE MACRO suite_of(a1, a2) AS
  nullif(regexp_replace(regexp_replace(upper(coalesce(CASE WHEN street_line(a1, a2) = a2 THEN NULL ELSE nullif(trim(a2), '') END,
                                       nullif(regexp_extract(street_line(a1, a2), suite_re() || '.*$', 0, 'i'), ''),
                                       tail_unit(street_line(a1, a2)))),
                        '\bFLOOR\b', 'FL', 'g'), '\b(STE|SUITE|SUIT|UNIT|RM|ROOM|APT|OFC|OFFICE)\b|\b(STE|SUITE|UNIT|APT)([0-9])|[#\s.,-]', '\3', 'g'), '');
-- Canonical street: house number split from a glued direction ("1711W TEMPLE ST"), USPS abbreviations, no punctuation, plural name words made singular ("DOCTORS CIRCLE" = "DOCTOR CIR").
CREATE OR REPLACE MACRO norm_street(a1) AS
  nullif(array_to_string(list_transform(
    string_split(trim(regexp_replace(regexp_replace(regexp_replace(replace(street_of(a1), '.', ''), '^([0-9]+)([NSEW]) ', '\1 \2 '), '[^A-Z0-9 ]', ' ', 'g'), '\s+', ' ', 'g')), ' '),
    lambda w: CASE WHEN MAP{'STREET': 'ST', 'STR': 'ST', 'AVENUE': 'AVE', 'AV': 'AVE', 'AVN': 'AVE', 'BOULEVARD': 'BLVD', 'BLV': 'BLVD', 'ROAD': 'RD', 'DRIVE': 'DR', 'DRV': 'DR', 'CIRCLE': 'CIR', 'CIRCL': 'CIR', 'LANE': 'LN', 'COURT': 'CT', 'PLACE': 'PL', 'PARKWAY': 'PKWY', 'PKY': 'PKWY', 'PKW': 'PKWY', 'HIGHWAY': 'HWY', 'HIWAY': 'HWY', 'HGWY': 'HWY', 'HIGHWY': 'HWY', 'HIGWAY': 'HWY', 'HIGHWAYS': 'HWY', 'FREEWAY': 'FWY', 'FRWY': 'FWY', 'EXPRESSWAY': 'EXPY', 'EXPWY': 'EXPY', 'TERRACE': 'TER', 'TRAIL': 'TRL', 'SQUARE': 'SQ', 'CENTER': 'CTR', 'CENTRE': 'CTR', 'PLAZA': 'PLZ', 'POINT': 'PT', 'MOUNT': 'MT', 'MOUNTAIN': 'MTN', 'ROUTE': 'RTE', 'TURNPIKE': 'TPKE', 'CROSSING': 'XING', 'HEIGHTS': 'HTS', 'JUNCTION': 'JCT', 'LOOP': 'LOOP', 'NORTH': 'N', 'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W', 'NORTHEAST': 'NE', 'NORTHWEST': 'NW', 'SOUTHEAST': 'SE', 'SOUTHWEST': 'SW', 'FIRST': '1ST', 'SECOND': '2ND', 'THIRD': '3RD', 'FOURTH': '4TH', 'FIFTH': '5TH', 'SIXTH': '6TH', 'SEVENTH': '7TH', 'EIGHTH': '8TH', 'NINTH': '9TH', 'TENTH': '10TH', 'ONE': '1', 'TWO': '2', 'THREE': '3', 'FOUR': '4', 'FIVE': '5'}[w] IS NOT NULL THEN MAP{'STREET': 'ST', 'STR': 'ST', 'AVENUE': 'AVE', 'AV': 'AVE', 'AVN': 'AVE', 'BOULEVARD': 'BLVD', 'BLV': 'BLVD', 'ROAD': 'RD', 'DRIVE': 'DR', 'DRV': 'DR', 'CIRCLE': 'CIR', 'CIRCL': 'CIR', 'LANE': 'LN', 'COURT': 'CT', 'PLACE': 'PL', 'PARKWAY': 'PKWY', 'PKY': 'PKWY', 'PKW': 'PKWY', 'HIGHWAY': 'HWY', 'HIWAY': 'HWY', 'HGWY': 'HWY', 'HIGHWY': 'HWY', 'HIGWAY': 'HWY', 'HIGHWAYS': 'HWY', 'FREEWAY': 'FWY', 'FRWY': 'FWY', 'EXPRESSWAY': 'EXPY', 'EXPWY': 'EXPY', 'TERRACE': 'TER', 'TRAIL': 'TRL', 'SQUARE': 'SQ', 'CENTER': 'CTR', 'CENTRE': 'CTR', 'PLAZA': 'PLZ', 'POINT': 'PT', 'MOUNT': 'MT', 'MOUNTAIN': 'MTN', 'ROUTE': 'RTE', 'TURNPIKE': 'TPKE', 'CROSSING': 'XING', 'HEIGHTS': 'HTS', 'JUNCTION': 'JCT', 'LOOP': 'LOOP', 'NORTH': 'N', 'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W', 'NORTHEAST': 'NE', 'NORTHWEST': 'NW', 'SOUTHEAST': 'SE', 'SOUTHWEST': 'SW', 'FIRST': '1ST', 'SECOND': '2ND', 'THIRD': '3RD', 'FOURTH': '4TH', 'FIFTH': '5TH', 'SIXTH': '6TH', 'SEVENTH': '7TH', 'EIGHTH': '8TH', 'NINTH': '9TH', 'TENTH': '10TH', 'ONE': '1', 'TWO': '2', 'THREE': '3', 'FOUR': '4', 'FIVE': '5'}[w]
                   WHEN length(w) > 3 AND w LIKE '%S' AND w NOT LIKE '%SS' AND NOT regexp_matches(w, '^\d') THEN left(w, -1)
                   ELSE w END), ' '), '');
-- Canonical organization name: no punctuation, legal suffixes, leading THE or DBA tail; & = AND.
CREATE OR REPLACE MACRO norm_org(n) AS
  nullif(trim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
    upper(replace(regexp_replace(coalesce(n, ''), '\s+(D/?B/?A|DOING BUSINESS AS)\s.*$', '', 'i'), '.', '')), '&', ' AND ', 'g'),
    '[^A-Z0-9 ]', ' ', 'g'),
    '\b(THE|LLC|L L C|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PC|P C|PLLC|PA|P A|LP|LLP|PLC|APC|APMC|MD PA)\b', ' ', 'g'),
    '\s+', ' ', 'g')), '');
-- building_key = canonical street + ZIP (office towers hold many tenants); addr_key = building + suite (same office).
-- building_alias (filled below) maps spelling variants of one building to a single key: missing street type, typos,
-- DR/RD mix-ups. raw_building_key_of skips that lookup, for big tables.
CREATE OR REPLACE TABLE building_alias (raw VARCHAR PRIMARY KEY, canon VARCHAR);
CREATE OR REPLACE MACRO raw_building_key_of(a1, a2, zip) AS norm_street(street_line(a1, a2)) || ' ' || left(zip, 5);
CREATE OR REPLACE MACRO building_key_of(a1, a2, zip) AS
  coalesce((SELECT canon FROM building_alias WHERE raw = raw_building_key_of(a1, a2, zip)), raw_building_key_of(a1, a2, zip));
CREATE OR REPLACE MACRO addr_key_of(a1, a2, zip) AS building_key_of(a1, a2, zip) || coalesce(' #' || suite_of(a1, a2), '');

-- Hospices with their 2024 Medicare payments (PAC PUF provider rows, joined on CCN).
CREATE OR REPLACE VIEW hospice AS
SELECT e."ENROLLMENT ID" AS enrollment_id, e."ASSOCIATE ID" AS associate_id, e.NPI AS npi, e.CCN AS ccn,
       e."ORGANIZATION NAME" AS org_name, e."DOING BUSINESS AS NAME" AS dba,
       e."INCORPORATION DATE" AS incorporated, e.PROPRIETARY_NONPROFIT AS prop_nonprofit,
       e."ADDRESS LINE 1" AS address, e."ADDRESS LINE 2" AS address2, e.CITY AS city, e.STATE AS state,
       left(e."ZIP CODE", 5) AS zip5, suite_of(e."ADDRESS LINE 1", e."ADDRESS LINE 2") AS suite,
       building_key_of(e."ADDRESS LINE 1", e."ADDRESS LINE 2", e."ZIP CODE") AS building_key,
       addr_key_of(e."ADDRESS LINE 1", e."ADDRESS LINE 2", e."ZIP CODE") AS addr_key,
       try_cast(p.BENE_DSTNCT_CNT AS INT) AS benes_2024,
       try_cast(p.TOT_SRVC_DAYS AS BIGINT) AS days_2024,
       try_cast(p.TOT_MDCR_PYMT_AMT AS DOUBLE) AS paid_2024,
       try_cast(p.TOT_SRVC_DAYS AS DOUBLE) / nullif(try_cast(p.BENE_DSTNCT_CNT AS DOUBLE), 0) AS days_per_bene,
       try_cast(p.NRSNG_VISITS_CNT AS DOUBLE) / nullif(try_cast(p.TOT_SRVC_DAYS AS DOUBLE), 0) AS nurse_visits_per_day,
       try_cast(p.BENE_AVG_RISK_SCRE AS DOUBLE) AS risk_score
FROM hospice_enrollments e
LEFT JOIN hospice_pac_2024 p ON p.PRVDR_ID = e.CCN AND p.SMRY_CTGRY = 'PROVIDER';

-- Same for home health agencies.
CREATE OR REPLACE VIEW hha AS
SELECT e."ENROLLMENT ID" AS enrollment_id, e."ASSOCIATE ID" AS associate_id, e.NPI AS npi, e.CCN AS ccn,
       e."ORGANIZATION NAME" AS org_name, e."DOING BUSINESS AS NAME" AS dba,
       e."INCORPORATION DATE" AS incorporated, e.PROPRIETARY_NONPROFIT AS prop_nonprofit,
       e."ADDRESS LINE 1" AS address, e."ADDRESS LINE 2" AS address2, e.CITY AS city, e.STATE AS state,
       left(e."ZIP CODE", 5) AS zip5, suite_of(e."ADDRESS LINE 1", e."ADDRESS LINE 2") AS suite,
       building_key_of(e."ADDRESS LINE 1", e."ADDRESS LINE 2", e."ZIP CODE") AS building_key,
       addr_key_of(e."ADDRESS LINE 1", e."ADDRESS LINE 2", e."ZIP CODE") AS addr_key,
       try_cast(p.BENE_DSTNCT_CNT AS INT) AS benes_2024,
       try_cast(p.TOT_EPSD_STAY_CNT AS INT) AS episodes_2024,
       try_cast(p.TOT_MDCR_PYMT_AMT AS DOUBLE) AS paid_2024,
       try_cast(p.TOT_OUTLIER_PYMT_AMT AS DOUBLE) AS outlier_paid_2024,
       try_cast(p.BENE_AVG_RISK_SCRE AS DOUBLE) AS risk_score
FROM hha_enrollments e
LEFT JOIN hha_pac_2024 p ON p.PRVDR_ID = e.CCN AND p.SMRY_CTGRY = 'PROVIDER';

-- Owners/managers of both provider types in one long table.
CREATE OR REPLACE VIEW owners AS
SELECT 'hospice' AS kind, * FROM hospice_owners
UNION ALL BY NAME
SELECT 'hha' AS kind, * FROM hha_owners;

-- One key per real-world owner. Organizations: canonical name, so "CENTERWELL HEALTH SERVICES, INC" and
-- "...SERVICES INC" under two PECOS IDs are one node. People: PECOS associate ID, except identical first + full middle
-- + last names (e.g. two IDs for Wilford Albert Payne); same name without a full middle name is not merged.
CREATE OR REPLACE VIEW owner_key AS
SELECT DISTINCT "ASSOCIATE ID - OWNER" AS owner_id, "TYPE - OWNER" AS owner_type,
       CASE WHEN "TYPE - OWNER" = 'O' THEN 'c' || coalesce(norm_org("ORGANIZATION NAME - OWNER"), "ASSOCIATE ID - OWNER")
            WHEN length(trim(coalesce("MIDDLE NAME - OWNER", ''))) > 1
                 THEN 'p' || upper(concat_ws(' ', trim("FIRST NAME - OWNER"), trim("MIDDLE NAME - OWNER"), trim("LAST NAME - OWNER")))
            ELSE 'o' || "ASSOCIATE ID - OWNER" END AS owner_key
FROM owners;

-- Owners (keyed by their PECOS associate ID) linked to more than one agency.
CREATE OR REPLACE VIEW multi_owners AS
SELECT o."ASSOCIATE ID - OWNER" AS owner_id, any_value(o."TYPE - OWNER") AS owner_type,
       any_value(coalesce(o."ORGANIZATION NAME - OWNER",
                          concat_ws(' ', o."FIRST NAME - OWNER", o."LAST NAME - OWNER"))) AS owner_name,
       count(DISTINCT o."ENROLLMENT ID") FILTER (WHERE kind = 'hospice') AS n_hospice,
       count(DISTINCT o."ENROLLMENT ID") FILTER (WHERE kind = 'hha') AS n_hha,
       list(DISTINCT o."ROLE TEXT - OWNER") AS roles,
       list(DISTINCT o."ORGANIZATION NAME") AS agencies
FROM owners o
GROUP BY 1
HAVING count(DISTINCT o."ENROLLMENT ID") > 1;

-- Practice addresses (same building and suite) shared by more than one hospice/HHA enrollment.
CREATE OR REPLACE VIEW shared_addresses AS
SELECT addr_key, any_value(upper(city)) AS city, any_value(state) AS state,
       count(*) AS n, list(kind || ': ' || org_name) AS agencies
FROM (SELECT 'hospice' AS kind, * FROM hospice UNION ALL BY NAME SELECT 'hha' AS kind, * FROM hha)
WHERE addr_key IS NOT NULL
GROUP BY addr_key HAVING count(DISTINCT enrollment_id) > 1;

-- LEIE exclusions matched to enrolled agencies by NPI (strong match).
CREATE OR REPLACE VIEW leie_npi_hits AS
SELECT x.*, l.EXCLTYPE AS excl_type, l.EXCLDATE AS excl_date, l.REINDATE AS rein_date
FROM (SELECT 'hospice' AS kind, enrollment_id, npi, org_name, state FROM hospice
      UNION ALL SELECT 'hha', enrollment_id, npi, org_name, state FROM hha) x
JOIN leie l ON l.NPI = x.npi AND l.NPI <> '0000000000';

-- LEIE exclusions matched to individual owners by first+last name and the agency's state
-- (CMS publishes no address for individual owners). WEAK: common names collide, verify by hand.
CREATE OR REPLACE VIEW leie_owner_name_hits AS
SELECT o.kind, o."ORGANIZATION NAME" AS agency, a.state AS agency_state, o."ROLE TEXT - OWNER" AS role,
       o."FIRST NAME - OWNER" AS first, o."MIDDLE NAME - OWNER" AS middle, o."LAST NAME - OWNER" AS last,
       l.MIDNAME AS excl_middle, l.EXCLTYPE AS excl_type, l.EXCLDATE AS excl_date, l.REINDATE AS rein_date,
       l.GENERAL AS excl_general, l.CITY AS excl_city,
       left(upper(o."MIDDLE NAME - OWNER"), 1) = left(upper(l.MIDNAME), 1) AS middle_initial_match
FROM owners o
JOIN (SELECT enrollment_id, state FROM hospice UNION ALL SELECT enrollment_id, state FROM hha) a
  ON a.enrollment_id = o."ENROLLMENT ID"
JOIN leie l ON upper(l.LASTNAME) = upper(o."LAST NAME - OWNER")
           AND upper(l.FIRSTNAME) = upper(o."FIRST NAME - OWNER")
           AND l.STATE = a.state
WHERE o."TYPE - OWNER" = 'I';
""")

# NPPES registry records (from scripts/fetch_nppes.py), flattened to one row per NPI.
nppes_file = root / "data" / "raw" / "nppes" / "nppes.jsonl"
if nppes_file.exists():
    rows = []
    for line in nppes_file.open():
        r = json.loads(line)
        if r.get("missing"):
            continue
        b = r.get("basic", {})
        addr = {a["address_purpose"]: a for a in r.get("addresses", [])}
        loc, mail = addr.get("LOCATION", {}), addr.get("MAILING", {})
        rows.append((
            r["number"], b.get("organization_name"), b.get("status"), b.get("enumeration_date"), b.get("last_updated"),
            " ".join(filter(None, [b.get("authorized_official_name_prefix"), b.get("authorized_official_first_name"),
                                   b.get("authorized_official_middle_name"), b.get("authorized_official_last_name")])),
            b.get("authorized_official_title_or_position"), b.get("authorized_official_telephone_number"),
            loc.get("address_1"), loc.get("city"), loc.get("state"), (loc.get("postal_code") or "")[:5], loc.get("telephone_number"),
            mail.get("address_1"), mail.get("city"), mail.get("state"), (mail.get("postal_code") or "")[:5],
            "; ".join(o.get("organization_name", "") for o in r.get("other_names", [])),
        ))
    db.execute("""CREATE OR REPLACE TABLE nppes (npi VARCHAR, org_name VARCHAR, status VARCHAR, enumerated VARCHAR,
        last_updated VARCHAR, official VARCHAR, official_title VARCHAR, official_phone VARCHAR,
        loc_address VARCHAR, loc_city VARCHAR, loc_state VARCHAR, loc_zip5 VARCHAR, loc_phone VARCHAR,
        mail_address VARCHAR, mail_city VARCHAR, mail_state VARCHAR, mail_zip5 VARCHAR, other_names VARCHAR)""")
    db.executemany("INSERT INTO nppes VALUES (" + ",".join("?" * 18) + ")", rows)
    print(f"{'nppes':22} {len(rows):>8} rows")

# Merge spelling variants of the same building (same ZIP and house number). Two keys merge when their street names
# match after dropping directionals and street types ("4444 CORONA" = "4444 CORONA DR"), or are near-identical
# (similarity >= 0.9: "DUBLUN" = "DUBLIN", "LAUREL CANTON" = "LAUREL CANYON"). Conflicting directionals (N vs S) and
# conflicting street types (EMPIRE CENTRAL DR vs EMPIRE CENTRAL PL: often two real streets) never merge.
import difflib
import re

DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
TYPES = {"ST", "AVE", "BLVD", "RD", "DR", "CIR", "LN", "CT", "PL", "PKWY", "HWY", "FWY", "EXPY", "TER", "TRL", "SQ", "CTR",
         "PLZ", "PT", "WAY", "LOOP", "XING", "TPKE", "RTE", "BL", "HWAY"}
keys = [r[0] for r in db.execute("""
    SELECT DISTINCT raw_building_key_of("ADDRESS LINE 1", "ADDRESS LINE 2", "ZIP CODE") FROM (
      SELECT "ADDRESS LINE 1", "ADDRESS LINE 2", "ZIP CODE" FROM hist_hospice_enrollments UNION ALL
      SELECT "ADDRESS LINE 1", "ADDRESS LINE 2", "ZIP CODE" FROM hist_hha_enrollments) WHERE "ADDRESS LINE 1" IS NOT NULL""").fetchall() if r[0]]
parsed = {}
for k in keys:
    toks = k.split()
    if len(toks) < 3 or not re.match(r"^\d", toks[0]):
        continue
    m = re.match(r"^(\d+)([NSEW])$", toks[0])  # "1720E LOS ANGELES AVE"
    num, toks = (m.group(1), [m.group(2)] + toks[1:-1]) if m else (toks[0], toks[1:-1])
    dirs = frozenset(t for t in toks if t in DIRS)
    types = frozenset(t for t in toks if t in TYPES)
    name = " ".join(t for t in toks if t not in DIRS and t not in TYPES)
    parsed.setdefault((k.split()[-1], num), []).append((k, dirs, types, name))
parent = {}
def find(x):
    while parent.get(x, x) != x:
        x = parent[x]
    return x
for group in parsed.values():
    for i, (k1, d1, t1, n1) in enumerate(group):
        for k2, d2, t2, n2 in group[i + 1:]:
            if (d1 and d2 and d1 != d2) or (t1 and t2 and t1 != t2):
                continue
            if n1 and n2 and (n1 == n2 or (min(len(n1), len(n2)) >= 5 and difflib.SequenceMatcher(None, n1, n2).ratio() >= 0.9)):
                a, b = find(k1), find(k2)
                if a != b:
                    parent[a] = b
# Prefer the most complete spelling (longest key) as the canonical one within each merged set.
sets = {}
for k in keys:
    sets.setdefault(find(k), []).append(k)
best = {root_: max(members, key=len) for root_, members in sets.items()}
aliases = [(k, best[find(k)]) for k in keys if best[find(k)] != k]
db.executemany("INSERT INTO building_alias VALUES (?, ?)", aliases)
print(f"building_alias: {len(aliases)} spellings merged into {len({c for _, c in aliases})} buildings")

db.execute(r"""
-- Selected Care Compare measures, one row per CCN. HCI = Hospice Care Index (10 = best).
CREATE OR REPLACE VIEW hospice_scores AS
SELECT "CMS Certification Number (CCN)" AS ccn,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'Average_Daily_Census') AS avg_daily_census,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'H_012_00_OBSERVED') AS hci_score,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'H_012_02_OBSERVED') AS pct_nursing_gaps,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'H_012_03_OBSERVED') AS pct_early_live_discharge,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'H_012_04_OBSERVED') AS pct_late_live_discharge,
       max(try_cast(replace(Score, ',', '') AS DOUBLE)) FILTER (WHERE "Measure Code" = 'H_012_07_OBSERVED') AS spend_per_bene,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'H_012_10_OBSERVED') AS pct_visits_near_death,
       max(try_cast(Score AS DOUBLE)) FILTER (WHERE "Measure Code" = 'Pct_Pts_w_Dementia') AS pct_dementia
FROM hospice_measures GROUP BY 1;

-- Everything known about each hospice in one row.
CREATE OR REPLACE VIEW hospice_profile AS
WITH per_owner AS (  -- one row per (hospice, owner): all their roles, and ownership % from ownership roles only
  SELECT "ENROLLMENT ID" AS enrollment_id, "TYPE - OWNER" AS typ,
         any_value(CASE WHEN "TYPE - OWNER" = 'I' THEN concat_ws(' ', "FIRST NAME - OWNER", "LAST NAME - OWNER")
                        ELSE "ORGANIZATION NAME - OWNER" END) AS name,
         string_agg(DISTINCT lower(replace("ROLE TEXT - OWNER", '5% OR GREATER ', '')), ', ') AS roles,
         max(try_cast(nullif("PERCENTAGE OWNERSHIP", '0.00') AS DOUBLE))
           FILTER (WHERE "ROLE CODE - OWNER" IN ('34', '35', '36', '37', '38', '39')) AS pct
  FROM hospice_owners GROUP BY "ENROLLMENT ID", "TYPE - OWNER", "ASSOCIATE ID - OWNER"),
ppl AS (
  SELECT enrollment_id,
         string_agg(name || ': ' || roles || coalesce(' (' || pct || '%)', ''), '; ' ORDER BY pct DESC NULLS LAST, name)
           FILTER (WHERE typ = 'I') AS people,
         string_agg(name || ': ' || roles || coalesce(' (' || pct || '%)', ''), '; ' ORDER BY pct DESC NULLS LAST, name)
           FILTER (WHERE typ = 'O') AS owner_orgs
  FROM per_owner GROUP BY 1),
same_addr AS (
  SELECT enrollment_id, count(*) OVER (PARTITION BY addr_key) AS n_at_address,
         count(*) OVER (PARTITION BY building_key) AS n_in_building FROM hospice WHERE addr_key IS NOT NULL)
SELECT h.*, g."Telephone Number" AS phone, g."County/Parish" AS county, g."Ownership Type" AS ownership_type,
       g."Certification Date" AS certified,
       n.official, n.official_title, n.official_phone, n.loc_phone AS npi_phone,
       concat_ws(', ', n.mail_address, n.mail_city, n.mail_state) AS mailing_address, n.enumerated AS npi_enumerated,
       n.other_names AS npi_other_names, ppl.people, ppl.owner_orgs, sa.n_at_address, sa.n_in_building,
       s.* EXCLUDE (ccn),
       (SELECT count(*) FROM leie_owner_name_hits x WHERE x.kind = 'hospice' AND x.agency = h.org_name) AS leie_name_hits
FROM hospice h
LEFT JOIN hospice_general g ON g."CMS Certification Number (CCN)" = h.ccn
LEFT JOIN nppes n ON n.npi = h.npi
LEFT JOIN ppl USING (enrollment_id)
LEFT JOIN same_addr sa USING (enrollment_id)
LEFT JOIN hospice_scores s ON s.ccn = h.ccn;
""")

db.execute(r"""
-- Hospice Medicare billing per provider (PROVIDER rows), state and nation, 2021-2024.
CREATE OR REPLACE VIEW hospice_billing AS
SELECT try_cast(YEAR AS INT) AS year, SMRY_CTGRY AS level, PRVDR_ID AS ccn, PRVDR_NAME AS name, STATE AS state,
       try_cast(BENE_DSTNCT_CNT AS INT) AS benes, try_cast(TOT_SRVC_DAYS AS BIGINT) AS days,
       try_cast(TOT_MDCR_PYMT_AMT AS DOUBLE) AS paid,
       try_cast(TOT_SRVC_DAYS AS DOUBLE) / nullif(try_cast(BENE_DSTNCT_CNT AS DOUBLE), 0) AS days_per_bene,
       try_cast(NRSNG_VISITS_CNT AS DOUBLE) / nullif(try_cast(TOT_SRVC_DAYS AS DOUBLE), 0) AS nurse_visits_per_day,
       try_cast(TOT_NRSNG_MNTS AS DOUBLE) / nullif(try_cast(TOT_SRVC_DAYS AS DOUBLE), 0) AS nurse_min_per_day,
       try_cast(AIDE_VISITS_CNT AS DOUBLE) / nullif(try_cast(TOT_SRVC_DAYS AS DOUBLE), 0) AS aide_visits_per_day,
       try_cast(HOSPC_RHC_DAYS_PCT AS DOUBLE) AS rhc_days_pct
FROM (SELECT * FROM hist_hospice_pac UNION ALL BY NAME SELECT * FROM hospice_pac_2024);

-- When each owner/manager appeared on and disappeared from each hospice, across the quarterly snapshots.
CREATE OR REPLACE VIEW owner_history AS
WITH s AS (
  SELECT *, strptime(regexp_extract(snapshot, '(\d{4}\.\d{2}\.\d{2})', 1), '%Y.%m.%d')::DATE AS snap FROM hist_hospice_owners),
bounds AS (SELECT min(snap) AS first_snap, max(snap) AS last_snap FROM s)
SELECT "ENROLLMENT ID" AS enrollment_id, any_value("ORGANIZATION NAME") AS hospice, "ASSOCIATE ID - OWNER" AS owner_id,
       any_value("TYPE - OWNER") AS owner_type,
       any_value(coalesce("ORGANIZATION NAME - OWNER", concat_ws(' ', "FIRST NAME - OWNER", "LAST NAME - OWNER"))) AS owner,
       string_agg(DISTINCT lower("ROLE TEXT - OWNER"), ', ') AS roles, max("PERCENTAGE OWNERSHIP") AS pct,
       min("ASSOCIATION DATE - OWNER") AS association_date, min(snap) AS first_seen, max(snap) AS last_seen,
       min(snap) > any_value(b.first_snap) AS added_later, max(snap) < any_value(b.last_snap) AS removed
FROM s, bounds b GROUP BY "ENROLLMENT ID", "ASSOCIATE ID - OWNER";

-- Hospice enrollments across snapshots: when each first and last appeared.
CREATE OR REPLACE VIEW enrollment_history AS
SELECT "ENROLLMENT ID" AS enrollment_id, any_value("ORGANIZATION NAME") AS org_name, any_value(CCN) AS ccn,
       any_value(STATE) AS state, list(DISTINCT "ADDRESS LINE 1" || coalesce(' ' || "ADDRESS LINE 2", '')) AS addresses,
       min(strptime(regexp_extract(snapshot, '(\d{4}\.\d{2}\.\d{2})', 1), '%Y.%m.%d'))::DATE AS first_seen,
       max(strptime(regexp_extract(snapshot, '(\d{4}\.\d{2}\.\d{2})', 1), '%Y.%m.%d'))::DATE AS last_seen
FROM hist_hospice_enrollments GROUP BY 1;

-- Every provider (any CMS type with an All Owners file) each owner ID is attached to.
CREATE OR REPLACE VIEW owner_holdings AS
SELECT 'hospice' AS type, "ASSOCIATE ID - OWNER" AS owner_id, "ORGANIZATION NAME" AS provider, "ROLE TEXT - OWNER" AS role FROM hospice_owners
UNION ALL SELECT 'home health', "ASSOCIATE ID - OWNER", "ORGANIZATION NAME", "ROLE TEXT - OWNER" FROM hha_owners
UNION ALL SELECT 'nursing home', "ASSOCIATE ID - OWNER", "ORGANIZATION NAME", "ROLE TEXT - OWNER" FROM snf_owners
UNION ALL SELECT 'hospital', "ASSOCIATE ID - OWNER", "ORGANIZATION NAME", "ROLE TEXT - OWNER" FROM hospital_owners
UNION ALL SELECT 'FQHC', "ASSOCIATE ID - OWNER", "ORGANIZATION NAME", "ROLE TEXT - OWNER" FROM fqhc_owners
UNION ALL SELECT 'rural clinic', "ASSOCIATE ID - OWNER", "ORGANIZATION NAME", "ROLE TEXT - OWNER" FROM rhc_owners;
""")
print("views: owner_key, hospice_billing, owner_history, enrollment_history, owner_holdings, hospice_profile, hospice_scores, hospice, hha, owners, multi_owners, shared_addresses, leie_npi_hits, leie_owner_name_hits")
