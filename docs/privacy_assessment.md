# CareGraph: privacy assessment

Record of processing (GDPR Art. 30), legitimate-interest balancing test (Art. 6(1)(f)) and data protection impact
assessment (Art. 35) for https://caregraph.lasu.dev. Written 2026-11-09; reviewed at every change of purpose, data
source or published field, and at least once a year.

## 1. Record of processing

| | |
|---|---|
| Controller | Lasu Shin, private individual, France. Contact: lasushin@proton.me |
| Purpose | Public transparency about who owns and runs Medicare-enrolled hospices and home health agencies, to help the public, journalists, researchers and oversight bodies spot ownership patterns associated with fraud |
| Legal basis | Legitimate interest, Art. 6(1)(f) (section 2) |
| People concerned | Individuals listed by CMS as owners, partners, officers, directors or managing employees of U.S. hospices and home health agencies (about 73,000 in the 2023-2026 CMS files, 67,748 of them on the site as built 2026-11-09); site visitors (network data only) |
| Data | Per person: a pseudonymous code, role(s), ownership percentage, the agencies listed against them, the association date CMS reports, the CMS release dates they were listed in. No names, CMS IDs, addresses, contact details or dates of birth. No special-category data (Art. 9). No criminal-offence data (Art. 10): revocation reasons citing felonies or exclusions are replaced with "Other grounds; see the CMS record", and indicators apply to agencies, never people |
| Source | Public U.S. government files: CMS Hospice and Home Health Agency All Owners and Enrollments, CMS Revocation Extract, CMS Post-Acute Care Utilization, Care Compare, NPPES (agency records only). Not collected from the people concerned |
| Recipients | The public (anyone visiting the site). Processor: Cloudflare, Inc. (hosting and delivery) |
| Transfers | Cloudflare, Inc., USA: EU-U.S. Data Privacy Framework certification and the standard contractual clauses in Cloudflare's data processing addendum |
| Retention | A person is published while CMS lists them on any agency in a release from the last six years (`RETAIN_YEARS` in `scripts/build_graph.py`); each update replaces the previous one, and old deployments are deleted. Removal requests are kept in a local suppression list for as long as the site exists, so removed entries stay removed |
| Security | Pseudonymous codes are HMAC-SHA256 of the CMS associate ID under a secret key that never leaves the controller's machine (mode 600, not in any repository); a publication check (`scripts/site_sanity.py`) scans every published file for any owner's name, CMS ID or criminal-ground text and blocks publication on a match; the site is static, sets no cookies and has no analytics |

## 2. Legitimate-interest balancing test

**Interest.** Ownership transparency in hospice and home health care is a recognised public interest. HHS-OIG, the
GAO and CMS have repeatedly reported hidden and shifting ownership as a driver of hospice fraud, and CMS publishes the
owner files precisely so the public can see who is behind each agency. The controller has a legitimate interest, shared
with the public, in making those files usable: the raw quarterly CSVs cannot show that the same person sits behind
several agencies, or that agencies changed hands before a revocation.

**Necessity.** The purpose needs the links between people and agencies; agency-only data cannot show common ownership.
It does not need names, so people are pseudonymized. Less intrusive alternatives were considered:

- Agencies only, no people: loses the cross-agency connections that are the point of the site. Rejected.
- Per-agency random codes: hides that one person is behind several agencies. Rejected.
- Same code across agencies, no names (chosen): keeps the connections, removes direct identification.

Re-identification remains possible, and the site does not prevent it: each source record links to the agency's rows in
the CMS data API, which show the names of everyone listed on that agency. For an agency with one listed owner, that is
one click from code to name. These links are kept deliberately, because investigators, journalists and the people
concerned must be able to check every link against the source, and a claim that cannot be checked is itself an accuracy
risk (Art. 5(1)(d)). They are filtered by enrollment, never by person. What pseudonymization does achieve: nobody can
search the site by name, names and CMS IDs are not on the site, and neither pages nor data files are indexed by search
engines, so a person's name does not lead to the site.

**Balance.**

- *Nature of the data:* professional-capacity data (business ownership and management roles) that the people concerned
  already had to disclose to CMS, which publishes it. Nothing about their private or family life.
- *Reasonable expectations:* people who enrol as owners or managing employees of a Medicare provider know that CMS
  publishes these roles for public scrutiny.
- *Impact:* the main risk is reputational, through association with an agency that has indicators or a revocation.
  Mitigations: indicators are on agencies only; each indicator is stated as a measurable fact with its national cut;
  the indicator panels, the About page and every export say a link, metric or indicator is not evidence of wrongdoing and that revocations can be
  appealed; there is no combined score and no ranking of people.
- *Safeguards and rights:* contact address, removal and objection on request (the suppression list keeps entries out of
  later updates), answers within one month, CNIL complaint route, open-source code and method.

**Conclusion.** With pseudonymization, no criminal-offence data, agency-level indicators and the safeguards above, the
public-interest purpose is not overridden by the interests or rights of the people concerned.

## 3. Data protection impact assessment

**Why one was done.** Two of the EDPB/CNIL criteria apply: datasets matched and combined (quarterly owner, enrollment,
payment and revocation files), and large scale (tens of thousands of people). Evaluation or scoring applies only to
agencies, not people. Tracking listings quarterly may also count as systematic monitoring, which is a further reason.

**Data protection officer (Art. 37).** Not appointed. The controller is not a public body (Art. 37(1)(a)) and
publishes no special-category or offence data (Art. 37(1)(c)). Art. 37(1)(b) requires a DPO where core activities
consist of regular and systematic monitoring of people on a large scale. The scale is large, but the processing is not
monitoring in the sense of the EDPB guidelines on DPOs (WP 243), whose examples are tracking and profiling of behaviour
(location tracking, behavioural advertising, loyalty programmes, fitness devices):

- The site observes nothing about what a person does. It republishes registry entries that the people concerned filed
  with CMS themselves (a role on an agency, a percentage, a date).
- It collects nothing of its own. Updates follow the quarterly publication of the source and only replace one copy of
  the registry with the next.
- It builds no profile of a person: no score, indicator or ranking applies to people, and nobody can be looked up by
  name.

The quarterly comparison of releases is the closest point to monitoring, and it records changes in filings, not
behaviour. A DPO must be appointed if the site ever adds person-level indicators, name search, or data about people from
sources other than the CMS registry files.

**Journalism exemption (Art. 85).** Not relied on; this assessment applies the GDPR in full.

**Processing.** Public CMS files are downloaded and loaded into a local DuckDB database. Agencies are linked by shared
owner or managing-employee IDs and shared building addresses. People are replaced by keyed codes, then a static site
is built and checked by `scripts/site_sanity.py`. The site is published on Cloudflare Pages. Code and method are public
at https://github.com/La5u/caregraph; the data and the key are not.

**Risks and measures.**

| Risk | Likelihood / severity before | Measures | Residual |
|---|---|---|---|
| Person wrongly perceived as a fraudster through an agency link | Possible / significant | Pseudonymization; indicators on agencies only; neutral wording ("indicator", never "fraud" or "suspicious" about an agency); disclaimers in indicator panels, About and exports; revocations described as appealable administrative actions | Low |
| Re-identification through the CMS file | Likely for anyone following a source link / limited (the same data is already public with names at CMS) | No names, no IDs, no search by name; no search-engine indexing; codes not reversible without the key; source links filtered by enrollment, not person | Accepted: verifiable sources and connections require it |
| Identifying agency details (a small agency's practice address may be its owner's home; surnames in business names) | Possible / limited | Only details CMS publishes about the enrollment; agency phone numbers are not published (a small agency's number may be its owner's personal one); agencies whose name contains the full name of a person listed on them are shown under a trade or generic name; About says an address may be a residence. Surname-only business names (about 270) are kept as the agency's public trading identity | Accepted |
| Wrong links (two people merged, address merged wrongly) | Possible / significant | IDs merged only with same full name on a shared agency; address merges recorded with reason and Census check; corrections address | Low |
| Exposure of criminal-offence data | Possible / severe | Felony and exclusion reasons removed; publication check fails on any such text | Low |
| Leak of real names (sole proprietorships, trusts, estates) | Possible / significant | Agencies named after a listed person shown under a trade name; person-revealing companies coded as "Entity"; publication check scans every published file for every owner name | Low |
| Key compromise (codes linkable to CMS IDs by brute force over IDs) | Unlikely / limited | Key never in any repository or deployment; mode 600; rotation possible (changes all codes) | Low |
| Old copies after an update or removal | Possible / limited | Previous Cloudflare deployments deleted after each update and Cloudflare cache purged after a removal; site not archived (checked 2026-11-09). Versioned files may remain in a past visitor's own browser cache for up to a year, outside the controller's reach | Low |
| Visitor data | Unlikely / minimal | No cookies, analytics or third-party requests; case notes stay in the visitor's browser | Minimal |

## 4. Handling requests

1. A request may give a code, or a name and an agency. For a name, open the agency in the local database, then find the
   person's code on that agency's site panel by role, percentage and date. Ask for identity documents only if there is
   reasonable doubt that the requester is the person listed (Art. 12(6)), and delete them after the check.
2. Reply within one month. Under Art. 14(5)(b) people are informed through the published notice, because CMS publishes
   no contact details for them.
3. Removal or objection: add the code, enrollment ID or CCN to `data/suppress.txt`, rebuild, run `scripts/site_sanity.py`,
   deploy, delete the previous deployment and purge the Cloudflare cache.
4. Errors in the source file are for CMS (PECOS); errors from matching are corrected here.

## 5. Conclusion

Residual risks are low or accepted with justification; prior consultation with the CNIL (Art. 36) is not
required. Review when published fields, data sources or indicators change.
