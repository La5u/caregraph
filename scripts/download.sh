#!/usr/bin/env bash
# Downloads the raw datasets into data/raw/<name>/ (one directory per dataset).
# URLs come from the CMS catalog (https://data.cms.gov/data.json), latest versions as of 2026-10-25.
set -euo pipefail
# Usage: scripts/download.sh [--history]
cd "$(dirname "$0")/.."
fetch() { # name url
  mkdir -p "data/raw/$1"
  local out="data/raw/$1/$(basename "$2")"
  [ -s "$out" ] && { echo "have $out"; return; }
  echo "get  $out"; curl -fsSL --retry 3 --max-time 1800 -o "$out.part" "$2" && mv "$out.part" "$out"
}
fetch hospice_owners      https://data.cms.gov/sites/default/files/2026-10/6dd81674-c8fa-4314-9023-eb24163e9353/Hospice_All_Owners_2026.09.29.csv
fetch hospice_enrollments https://data.cms.gov/sites/default/files/2026-10/e9ba26c4-dca7-4c06-8ab8-06521b46bd4f/Hospice_Enrollments_2026.09.29.csv
fetch hospice_pac_2024    https://data.cms.gov/sites/default/files/2026-07/11d13c2a-ceb3-4104-af58-5dea5ef2c28c/RY26_PACPUF_HOS_2024_main_S.csv
fetch hha_owners          https://data.cms.gov/sites/default/files/2026-10/6d2a7d24-bae8-4b7a-a963-c2780958ae87/HHA_All_Owners_2026.09.29.csv
fetch hha_enrollments     https://data.cms.gov/sites/default/files/2026-10/0089fc1e-f43a-4c6d-b50c-8f1a208c1c7c/HHA_Enrollments_2026.09.29.csv
fetch hha_pac_2024        https://data.cms.gov/sites/default/files/2026-07/839da318-d963-435c-8709-35c5820c50a4/RY26_PACPUF_HH_2024_main_S.csv
fetch hospice_general     https://data.cms.gov/provider-data/sites/default/files/resources/18afea60c672e37d2f0d6e8ed984eaa6_1787169953/Hospice_General-Information_Aug2026_2.csv
fetch hospice_measures    https://data.cms.gov/provider-data/sites/default/files/resources/55feed84280900d392830eea2f2426de_1786385144/Hospice_Provider_Aug2026.csv
fetch leie                https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv

# History (one directory, many snapshots) and owners of other provider types. Pass --history to fetch.
if [ "${1:-}" = "--history" ]; then
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/337c2f2c-ff95-4123-b80d-903290f6331b/Hospice_All_Owners_2023.03.31.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/689c952e-531d-43e6-a7bf-928ca1707175/Hospice_All_Owners_2023.07.06..csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/1e0afa8a-8fc1-4b4c-995c-59459c221f45/Hospice_All_Owners_2023.10.02.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/4f54febf-e5a5-4a29-9e97-d21f704f4029/Hospice_All_Owners_2024.01.05.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/48296231-beed-4ea3-84c3-9e3d89e5ac34/Hospice_All_Owners_2024.04.01.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/46769a98-fd4d-496e-85a9-5e187f4745d4/Hospice_All_Owners_2024.07.01.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/30a9239a-3ce8-4ba4-a7a6-f3861f5891b4/Hospice_All_Owners_2024.10.07.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-05/e9b55b35-4da0-4161-8af2-fb9ebf8d3368/Hospice_All_Owners_2025.01.02.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-06/56ab135d-f256-4b45-b64d-84e7afbe19a3/Hospice_All_Owners_2025.04.01.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-06/29e8a57e-075d-465c-ab9c-d3f0609c6cf6/Hospice_All_Owners_2025.07.01.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-06/29dad873-b3c0-4b00-ac2e-8a848fa5b143/Hospice_All_Owners_2025.10.01.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-06/e62d5ad0-1ee3-49ec-a15b-01267068f86b/Hospice_All_Owners_2026.01.02.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-06/4495340f-f768-48fc-a4ae-f1cb43020d25/Hospice_All_Owners_2026.04.01.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-07/a3952548-ee89-4165-90c8-36fd8a09c872/Hospice_All_Owners_2026.07.17.csv
  fetch hist_hospice_owners  https://data.cms.gov/sites/default/files/2026-10/6dd81674-c8fa-4314-9023-eb24163e9353/Hospice_All_Owners_2026.09.29.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2023-04/f8b05c50-76a4-4501-878e-a65fa9321f20/Hospice_Enrollments_2023.03.31.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2023-07/85103729-a6b5-460d-93f7-20cd055a74d1/Hospice_Enrollments_2023.07.06.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2023-10/9df81161-c7ff-471b-8329-efb2c7d36929/Hospice_Enrollments_2023.10.02.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2024-01/071c9976-59e6-46d4-9809-53454a1ced07/Hospice_Enrollments_2024.01.05.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2024-04/072ab653-71b7-454c-b3ed-2c0ee7a8455b/Hospice_Enrollments_2024.04.01.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2024-07/e51b5573-9e8e-49ad-9a48-7d2425a70a50/Hospice_Enrollments_2024.07.01.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2024-10/92a4fe1f-34a9-4d07-97d7-278bc2ca3f1a/Hospice_Enrollments_2024.10.07.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2025-01/afd62e57-8a99-4c49-a0b5-358a25ce39dd/Hospice_Enrollments_2025.01.02.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2025-05/211d1216-e745-44f7-b717-724d04f78dbd/Hospice_Enrollments_2025.04.01.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2025-07/30719e52-511a-46fa-81d9-f09b6be5966b/Hospice_Enrollments_2025.07.01.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2025-10/8a3ac547-fe30-4cf7-80aa-d623734a6675/Hospice_Enrollments_2025.10.01.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2026-01/adf86a27-5387-44b9-85c6-72e7c4ea5342/Hospice_Enrollments_2026.01.21.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2026-04/2e809a47-65a1-4f8d-977e-6d9dc7d42e29/Hospice_Enrollments_2026.04.01.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2026-07/b2fd9bf2-4ea5-40b9-9e72-0e015c92ad02/Hospice_Enrollments_2026.07.17.csv
  fetch hist_hospice_enrollments https://data.cms.gov/sites/default/files/2026-10/e9ba26c4-dca7-4c06-8ab8-06521b46bd4f/Hospice_Enrollments_2026.09.29.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2023-04/f719af15-7eab-42c6-a28e-6fd960193edb/HHA_Enrollments_2023.03.31.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2023-07/45afd42e-9416-41e3-b2d0-0e70ce793a52/HHA_Enrollments_2023.07.06.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2023-10/82964b76-66b6-463a-aef1-dff4ae766f9a/HHA_Enrollments_2023.10.02.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2024-01/00ea617a-7f11-45ef-a49c-89ed8dff5945/HHA_Enrollments_2024.01.05.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2024-04/85f0a6c7-c068-40fa-962d-dbf05aa93944/HHA_Enrollments_2024.04.01.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2024-07/b8e87685-b941-4e88-aa45-b2cfe3db42a4/HHA_Enrollments_2024.07.01.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2024-10/6f0ae716-79df-45e0-8fcf-5ef1d12727b3/HHA_Enrollments_2024.10.07.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2025-01/c133f82f-5635-47d3-b85f-364b379a322a/HHA_Enrollments_2025.01.02.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2025-05/9c3b2573-1efb-4249-963c-9341d9f0d186/HHA_Enrollments_2025.04.01.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2025-07/64e9fe1b-9edf-44ad-8ce9-7b7c1cc17f72/HHA_Enrollments_2025.07.01.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2025-10/95c1cb50-ddce-4bae-8f18-b040113fd830/HHA_Enrollments_2025.10.01.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2026-01/ba21a4f0-b9e2-418c-b927-f94697045a69/HHA_Enrollments_2026.01.21.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2026-04/2cca6c3e-e662-48ad-b151-5b0340cb877a/HHA_Enrollments_2026.04.01.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2026-07/4f7949bd-151d-4974-b16b-ff2a39c86282/HHA_Enrollments_2026.07.17.csv
  fetch hist_hha_enrollments https://data.cms.gov/sites/default/files/2026-10/0089fc1e-f43a-4c6d-b50c-8f1a208c1c7c/HHA_Enrollments_2026.09.29.csv
  fetch hist_hospice_pac     https://data.cms.gov/sites/default/files/2025-08/1ca73c58-9d07-482e-9f76-708bb446b3e6/RY_2025_RY_25_PAC_PUF_HOS_2021_main_final_unformatted.csv
  fetch hist_hospice_pac     https://data.cms.gov/sites/default/files/2025-08/8336ff27-0000-4f02-8fd5-8d3c4fd8a439/RY_2025_RY_25_PAC_PUF_HOS_2022_main_final_unformatted.csv
  fetch hist_hospice_pac     https://data.cms.gov/sites/default/files/2025-08/7c92ef92-85ff-4f2a-a1a6-b1f4f25210e4/RY_2025_RY_25_PAC_PUF_HOS_2023_main_final_unformatted.csv
  fetch hist_hha_pac         https://data.cms.gov/sites/default/files/2025-08/139cec5d-4333-45bc-9b3c-d2cddad8456a/RY_2025_RY_25_PAC_PUF_HH_2022_main_final_unformatted.csv
  fetch hist_hha_pac         https://data.cms.gov/sites/default/files/2025-08/1d04af0f-9173-47b0-b5f8-26df7722247c/RY_2025_RY_25_PAC_PUF_HH_2023_main_final_unformatted.csv
  fetch hist_hha_pac         https://data.cms.gov/sites/default/files/2025-08/5233f231-a935-4649-bc14-89a92849b52a/RY_2025_RY_25_PAC_PUF_HH_2021_main_final_unformatted.csv
  fetch fqhc_owners          https://data.cms.gov/sites/default/files/2026-10/9cbc7db8-1bef-492f-a72f-ca13d9f76cfb/FQHC_All_Owners_2026.09.29.csv
  fetch hospital_owners      https://data.cms.gov/sites/default/files/2026-10/2517a8c1-44a2-4620-8d65-c72bfae27c3c/Hospital_All_Owners_2026.09.29.csv
  fetch rhc_owners           https://data.cms.gov/sites/default/files/2026-10/810cb456-60a6-40dc-900c-25cf7d1caac4/RHC_All_Owners_2026.09.29.csv
  fetch snf_owners           https://data.cms.gov/sites/default/files/2026-10/f60332c1-eab0-49b8-a4be-55c1b3da4449/SNF_All_Owners_2026.09.29.csv
fi

# Growth analysis: physician/practitioner services by state and HCPCS/CPT code, and Medicare enrollment. Pass --growth.
if [ "${1:-}" = "--growth" ]; then
  fetch hist_phys_geo         https://data.cms.gov/sites/default/files/2021-08/MUP_PHY_R21_P04_V10_D19_Geo.csv
  fetch hist_phys_geo         https://data.cms.gov/sites/default/files/2023-05/0a47308e-812e-42cb-8ecf-0c1f457ab849/MUP_PHY_R23_P05_V10_D21_Geo.csv
  fetch hist_phys_geo         https://data.cms.gov/sites/default/files/2026-05/e534c74b-79b8-4892-8a95-5a17e2dfec9f/MUP_PHY_R26_P05_V10_D24_Geo.csv
  fetch medicare_enrollment   "https://data.cms.gov/sites/default/files/2026-10/c41a8ac2-8229-4f3b-a4cb-423d9cd5328a/Medicare%20Monthly%20Enrollment%20Data_July%202026.csv"
fi

# Provider screen: every practitioner x HCPCS/CPT code, 2024 (~3 GB). Pass --provider, then run scripts/load_prov_svc.py.
if [ "${1:-}" = "--provider" ]; then
  fetch prov_svc_2024         https://data.cms.gov/sites/default/files/2026-05/b5ebab5a-f490-418a-9bce-4b9f31419356/PHY_R26_P05_V10_D24_Prov_Svc.csv
fi
