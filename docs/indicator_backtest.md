# Indicator backtest

Backtest candidate agency indicators against LATER CMS revocations. Writes out/indicator_backtest.md and .json.

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

| type | check | cut | outcome window | assessed | flagged | outcome: flagged | outcome: others | state-adjusted RR (95% CI) | verdict |
|---|---|---|---|---|---|---|---|---|---|
| hha | suite2 | fixed | 2024-26 | 8272 | 830 | 0.4% (3) | 0.4% | 2.96 (0.90-9.67) | drop |
| hha | eps_per_bene | >= 6.72 | 2024-26 | 8272 | 413 | 0.7% (3) | 0.3% | 2.23 (0.65-7.61) | drop |
| hha | paid_per_bene | >= 1.23e+04 | 2024-26 | 8272 | 414 | 1.7% (7) | 0.3% | 2.21 (0.95-5.13) | drop |
| hha | lupa_share | <= 0 | 2024-26 | 5719 | 524 | 1.0% (5) | 0.1% | 2.13 (0.63-7.22) | drop |
| hha | nurse_min_per_ep | <= 79.3 | 2024-26 | 8258 | 413 | 0.2% (1) | 0.4% | 1.78 (0.25-12.47) | drop |
| hha | bldg5 | fixed | 2024-26 | 8272 | 591 | 1.4% (8) | 0.3% | 1.38 (0.62-3.07) | drop |
| hha | outlier_share | >= 0.0935 | 2024-26 | 8272 | 415 | 0.7% (3) | 0.3% | 1.34 (0.41-4.35) | drop |
| hha | bldg10 | fixed | 2024-26 | 8272 | 199 | 1.0% (2) | 0.3% | 0.83 (0.20-3.50) | drop |
| hha | new | fixed | 2024-26 | 8272 | 921 | 0.5% (5) | 0.3% | 0.57 (0.21-1.51) | drop |
| hha | visits_per_ep | <= 2.04 | 2024-26 | 8258 | 413 | 0.0% (0) | 0.4% | n/a | drop |
| hha | own_add | fixed | 2024-26 | 8272 | 1231 | 0.0% (0) | 0.4% | n/a | drop |
| hha | affil | fixed | 2024-26 | 8272 | 4 | 0.0% (0) | 0.2% | n/a | drop |
| hha | suite3 | fixed | 2024-26 | 8272 | 9 | 0.0% (0) | 0.4% | n/a | drop |
| hha | growth | fixed | 2024-26 | 8272 | 263 | 0.0% (0) | 0.4% | n/a | drop |
| hospice | cc_spend | >= 3.34e+04 | 2025-26 | 4888 | 241 | 15.4% (37) | 1.1% | 3.49 (2.32-5.24) | strong |
| hospice | aide | <= 0.0204 | 2024-26 | 5564 | 279 | 23.3% (65) | 3.2% | 2.87 (2.23-3.68) | strong |
| hospice | bldg5 | fixed | 2024-26 | 5609 | 488 | 23.0% (112) | 2.6% | 2.73 (2.16-3.45) | strong |
| hospice | new | fixed | 2024-26 | 5609 | 1154 | 14.1% (163) | 1.9% | 2.70 (2.11-3.45) | strong |
| hospice | cc_near_death | <= 66.7 | 2025-26 | 4862 | 246 | 8.9% (22) | 1.4% | 2.41 (1.53-3.80) | strong |
| hospice | bldg10 | fixed | 2024-26 | 5609 | 223 | 25.6% (57) | 3.5% | 2.40 (1.85-3.11) | strong |
| hospice | nurse_min | <= 7.09 | 2024-26 | 5605 | 280 | 11.8% (33) | 4.0% | 2.25 (1.62-3.12) | strong |
| hospice | paid_per_bene | >= 2.78e+04 | 2024-26 | 5609 | 282 | 24.1% (68) | 3.4% | 2.16 (1.68-2.78) | strong |
| hospice | long_stay | >= 142 | 2024-26 | 5609 | 282 | 18.8% (53) | 3.6% | 2.15 (1.65-2.82) | strong |
| hospice | affil | fixed | 2024-26 | 5609 | 11 | 18.2% (2) | 3.1% | 2.08 (0.60-7.25) | drop |
| hospice | own_add | fixed | 2024-26 | 5609 | 820 | 5.7% (47) | 4.2% | 1.64 (1.24-2.19) | strong |
| hospice | cc_gaps | >= 90.3 | 2025-26 | 4888 | 242 | 5.8% (14) | 1.6% | 1.61 (0.93-2.78) | drop |
| hospice | small_census | fixed | 2024-26 | 5609 | 489 | 10.0% (49) | 3.9% | 1.28 (0.96-1.71) | drop |
| hospice | growth | fixed | 2024-26 | 5609 | 431 | 7.0% (30) | 4.2% | 1.01 (0.70-1.44) | drop |
| hospice | cc_late | >= 63.6 | 2025-26 | 4887 | 246 | 3.7% (9) | 1.7% | 0.83 (0.42-1.63) | drop |
| hospice | suite2 | fixed | 2024-26 | 5609 | 829 | 0.8% (7) | 5.0% | 0.71 (0.34-1.45) | drop |
| hospice | cc_early | >= 17.7 | 2025-26 | 4887 | 247 | 1.2% (3) | 1.9% | 0.70 (0.23-2.15) | drop |
| hospice | suite3 | fixed | 2024-26 | 5609 | 8 | 0.0% (0) | 4.4% | n/a | drop |

## Hospices by number of kept checks (in-sample, CMS-claims and structural checks only)

| checks | hospices | revoked later | rate |
|---|---|---|---|
| 0 | 3325 | 35 | 1.1% |
| 1 | 1499 | 46 | 3.1% |
| 2 | 445 | 64 | 14.4% |
| 3 | 198 | 57 | 28.8% |
| 4+ | 142 | 45 | 31.7% |
