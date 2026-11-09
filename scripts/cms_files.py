"""Write scripts/cms_files.json: for each local CMS file the site cites, its data.cms.gov dataset page, CSV URL and
per-release data API endpoint (taken from the CMS catalog, https://data.cms.gov/data.json).

The API endpoint accepts column filters, so a link can open exactly the rows behind a record, e.g.
  <api>?filter%5BENROLLMENT%20ID%5D=O20XXXXXXXXXXXX&filter%5BASSOCIATE%20ID%20-%20OWNER%5D=XXXXXXXXXX
(checked against the live API on 2026-11-04).

Usage: python3 -I scripts/cms_files.py [catalog.json]   (downloads the catalog, ~18 MB, if no path is given)
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
DIRS = ["hist_hospice_owners", "hist_hha_owners", "hist_hospice_enrollments", "hist_hha_enrollments", "cms_revoked",
        "hospice_pac_2024", "hha_pac_2024", "hist_hospice_pac", "hist_hha_pac"]
DS = [("Hospice_All_Owners", "Hospice All Owners"), ("HHA_All_Owners", "HHA All Owners"),
      ("Hospice_Enrollments", "Hospice Enrollments"), ("HHA_Enrollments", "HHA Enrollments"),
      ("Revocation_Extract", "Revoked Medicare Providers and Suppliers"),
      ("PACPUF_HOS", "Post-Acute Care Utilization: Hospice by Provider 2024"),
      ("PACPUF_HH", "Post-Acute Care Utilization: Home Health by Provider 2024"),
      ("PAC_PUF_HOS", "Post-Acute Care Utilization: Hospice by Provider"),
      ("PAC_PUF_HH_", "Post-Acute Care Utilization: Home Health by Provider")]

if len(sys.argv) > 1:
    catalog = json.loads(Path(sys.argv[1]).read_text())
else:
    with urllib.request.urlopen("https://data.cms.gov/data.json", timeout=300) as r:
        catalog = json.load(r)
by_file = {}
for ds in catalog["dataset"]:
    page = ds.get("landingPage")
    page = page.get("accessURL") if isinstance(page, dict) else page
    apis = {x.get("title"): x.get("accessURL") for x in ds.get("distribution", []) if x.get("format") == "API"}
    for x in ds.get("distribution", []):
        if x.get("format") == "CSV" and x.get("downloadURL"):
            by_file[os.path.basename(x["downloadURL"])] = {"csv": x["downloadURL"], "api": apis.get(x.get("title")), "page": page}

out, missing = {}, []
for d in DIRS:
    for f in sorted((root / "data" / "raw" / d).glob("*.csv")):
        hit = by_file.get(f.name)
        if not hit or not hit["api"]:
            missing.append(f.name)
            continue
        m = re.search(r"(20\d\d)[._-](\d\d)[._-](\d\d)", f.name)
        name = next(label for key, label in DS if key in f.name)
        y = re.search(r"_(20\d\d)_main", f.name)
        out[f.name] = {"ds": name, "rel": f"{m[1]}-{m[2]}-{m[3]}" if m else y[1] if y else "2024", **hit}
(root / "scripts" / "cms_files.json").write_text(json.dumps(out, indent=1) + "\n")
print(f"{len(out)} files mapped" + (f"; not in catalog: {missing}" if missing else ""))
