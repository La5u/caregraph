# CareGraph

Who owns America's hospices? CareGraph maps the ownership networks of Medicare-enrolled hospices and home health
agencies from public CMS data: who owns or runs each agency, which agencies share owners or buildings, and how that
changed across CMS's quarterly releases. Live site: https://caregraph.lasu.dev (preview).

This repository holds the code that builds the site and the methodology behind its indicators. It contains no data:
everything is downloaded from data.cms.gov and oig.hhs.gov.

## What it shows, and what it does not
- **People are pseudonymized.** Each person in the CMS owner files gets a code (`Person XXXXXXXXXXXXXXXX`), an
  HMAC-SHA256 of their CMS associate ID under a secret key that is not in this repository. The same person keeps the
  same code across agencies, so shared owners stay visible without names. Companies whose names reveal a person
  (trusts, estates) get `Entity` codes. See `scripts/site_tables.py`.
- **No criminal-ground text.** Revocation reasons that refer to felonies or exclusions are replaced with
  "Other grounds; see the CMS record".
- **Indicators apply to agencies, never to people**, and only those that held up in a backtest against later CMS
  revocations are used. There is no combined score. A link, metric or indicator is not evidence of wrongdoing.
- `scripts/site_sanity.py` checks every published file for any owner's name, CMS ID or criminal-ground text before
  publication.

## Methodology
- **Networks** (`scripts/build_graph.py`): agencies are linked through owners and managing employees (by CMS associate
  ID) and through shared building addresses. Address merges and their reasons are in `scripts/address_aliases.json`
  (checked with the U.S. Census geocoder, `scripts/check_address_aliases.py`); multi-tenant buildings that should not
  join networks are listed in `scripts/address_multitenant.json`.
- **Indicators** (`scripts/backtest_indicators.py`, results in `docs/indicator_backtest.md`): candidate checks were
  declared before any result was seen and tested on the January 2024 cohort against revocations that came later,
  using a Mantel-Haenszel risk ratio stratified by state and a Bonferroni-adjusted threshold. Only hospice checks
  passed; home health agencies get metrics and national percentiles but no indicators.
- **Metrics and indicators for the latest data** (`scripts/build_indicators.py`) use the same definitions.

## Build
Requires Python 3.12+, Node 22, `brotli`, and about 3 GB of free RAM.

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    scripts/download.sh && scripts/download.sh --history     # CMS and OIG files into data/raw/
    .venv/bin/python -I scripts/build_db.py                  # data/fraud.duckdb
    python3 -I scripts/cms_files.py                          # data.cms.gov API endpoint per release (source links)
    mkdir -p out && .venv/bin/python -I scripts/backtest_indicators.py   # out/indicator_backtest.md
    .venv/bin/python -I scripts/build_indicators.py          # data/derived/indicators.json
    .venv/bin/python -I scripts/build_site.py                # site/dist/ (creates ~/.config/caregraph/person_hmac_key on first run)
    .venv/bin/python -I scripts/site_sanity.py               # publication check
    node site/test_logic.js && node site/test_loading.js     # unit tests

Keep the key secret and backed up: anyone with it can recompute codes from CMS IDs, and a new key changes every code.
Your key gives every person different codes from the live site.

## Data sources
CMS Hospice and Home Health Agency All Owners and Enrollments files (quarterly, 2023 to 2026), CMS Revocation
Extract, CMS Post-Acute Care Utilization by Provider (2021 to 2024), Care Compare hospice data, and the HHS-OIG
List of Excluded Individuals/Entities. Exact URLs are in `scripts/download.sh`.

## Report fraud
This project does not take tips. Report suspected Medicare fraud to the HHS Office of Inspector General:
https://oig.hhs.gov/fraud/report-fraud/ or 1-800-HHS-TIPS.

## Corrections and privacy
Corrections, removal requests and privacy questions: lasushin@proton.me. Privacy notice: https://caregraph.lasu.dev/about.html#privacy

## License
MIT (code). The CMS and OIG data are U.S. government works.
