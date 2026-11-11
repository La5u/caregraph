"use strict";
const assert = require("node:assert/strict");
const {shardKey, shardPath, apiUrl, enrollmentUrl, recordUrl, revocationUrl, paymentsUrl, careCompareUrl, nppesUrl,
  datasetUrl, latestFile, latestRecord, separateDots, buildAdjacency, shortestPath, matchNames, compareTableValues, csvRows, edgeInRelease, timelineDateKey, ringPositions, nodeMarkdown} = require("./graph_logic.js");

const files = [
  {ds: "Hospice All Owners", rel: "2026-01-21", api: "https://data.cms.gov/data-api/v1/dataset/owners-old/data", page: "https://data.cms.gov/owners"},
  {ds: "Hospice All Owners", rel: "2026-09-29", api: "https://data.cms.gov/data-api/v1/dataset/owners/data", page: "https://data.cms.gov/owners"},
  {ds: "Hospice Enrollments", rel: "2026-09-29", api: "https://data.cms.gov/data-api/v1/dataset/enrollments/data"},
  {api: "https://data.cms.gov/data-api/v1/dataset/revocations/data"},
  {api: "https://data.cms.gov/data-api/v1/dataset/hospice-payments/data"},
  {api: "https://data.cms.gov/data-api/v1/dataset/hha-payments/data"},
];
const ext = {rev: 3, pac_hospice: 4, pac_hha: 5};
const n = {id: "O20210217001849", kind: "hospice", ccn: "001234", npi: "0123456789", ef: [2]};
const owner = {f: [1, 0], code: "34", role: "5% OR GREATER OWNER", pct: "15", assoc: "2024-07-12"};
const address = {f: [2], addr: "6671 LAS VEGAS BLVD S STE 210, LAS VEGAS NV"};
const edge = {from: "person", to: n.id, recs: [owner]};
// A person link filters on the agency's enrollment ID only, never on an owner ID or name, even for old records.
assert.equal(recordUrl(files, 1, edge, owner), files[1].api + "?filter%5BENROLLMENT%20ID%5D=O20210217001849");
assert.equal(recordUrl(files, 1, edge, {...owner, aid: "0012", nm: "A B"}), recordUrl(files, 1, edge, owner));
assert.ok(!recordUrl(files, 1, edge, owner).includes("OWNER"));
// Same vectors as scripts/test_site_tables.py: the browser must find the Python shard.
assert.deepEqual(["1", "solo-O2021", "abc", "0f3a"].map(shardKey), ["1c", "81", "0b", "cb"]);
assert.equal(shardPath("g", "1"), "g/1c");
assert.equal(recordUrl(files, 2, edge, address), files[2].api + "?filter%5BENROLLMENT%20ID%5D=O20210217001849");
assert.equal(enrollmentUrl(files, n.ef[0], n.id), files[2].api + "?filter%5BENROLLMENT%20ID%5D=O20210217001849");
assert.equal(revocationUrl(files, ext, n.id), files[3].api + "?filter%5BENRLMT_ID%5D=O20210217001849");
assert.equal(paymentsUrl(files, ext, n), files[4].api + "?filter%5BPRVDR_ID%5D=001234&filter%5BSMRY_CTGRY%5D=PROVIDER");
assert.equal(paymentsUrl(files, ext, {...n, kind: "hha"}), files[5].api + "?filter%5BPRVDR_ID%5D=001234&filter%5BSMRY_CTGRY%5D=PROVIDER");
assert.equal(careCompareUrl(n), "https://www.medicare.gov/care-compare/details/hospice/001234");
assert.equal(careCompareUrl({...n, kind: "hha"}), "https://www.medicare.gov/care-compare/details/home-health/001234");
assert.equal(nppesUrl(n), "https://npiregistry.cms.hhs.gov/provider-view/0123456789");
assert.equal(careCompareUrl({...n, ccn: "a /&"}), "https://www.medicare.gov/care-compare/details/hospice/a%20%2F%26");
assert.equal(nppesUrl({npi: "a /&"}), "https://npiregistry.cms.hhs.gov/provider-view/a%20%2F%26");
assert.equal(datasetUrl(files, 1), files[1].page);
assert.equal(latestFile(files, [1, 0]), 1);
assert.deepEqual(latestRecord(files, edge), {record: owner, i: 1});
assert.deepEqual(latestRecord(files, {...edge, recs: [{...owner, f: [0]}, owner]}), {record: owner, i: 1});
assert.equal(latestRecord(undefined, edge), null);
assert.equal(latestRecord(files, {src: "old source"}), null);
assert.equal(latestFile(files), null);
assert.equal(apiUrl(undefined, {}), null);
assert.equal(enrollmentUrl(undefined, 0, n.id), null);
assert.equal(recordUrl(undefined, 0, edge, owner), null);
assert.equal(revocationUrl(files, undefined, n.id), null);
assert.equal(paymentsUrl(files, ext, {kind: "hha"}), null);
assert.equal(paymentsUrl(undefined, ext, n), null);
assert.equal(careCompareUrl({kind: "hospice"}), null);
assert.equal(nppesUrl({}), null);
assert.equal(datasetUrl(undefined, 0), null);

const points = [{x: 0, y: 0, radius: 38}, {x: 0, y: 0, radius: 10},
  {x: 2, y: 1, radius: 7}, {x: 5, y: 0, radius: 25}, {x: 900, y: 700, radius: 10}];
assert.equal(separateDots(points, 12), true);
for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) {
  const a = points[i], b = points[j];
  assert.ok(Math.hypot(a.x - b.x, a.y - b.y) >= a.radius + b.radius + 12, `overlap ${i},${j}`);
}
assert.deepEqual(points[4], {x: 900, y: 700, radius: 10});
assert.equal(separateDots(points, 12), false);
assert.equal(separateDots([], 12), false);

const paths = {names: ["JOHN SMITH JR", "JOHN SMITH", "A JOHN SMITH", "JOHN SMITH", "ISOLATED", "OFFICER"],
  kinds: "ppppop", search: ["JOHN SMITH JR TX", "JOHN SMITH 123", "A JOHN SMITH CA", "JOHN SMITH 456", "ISOLATED", "OFFICER"],
  edges: [0, 1, 4, 0, 1, 2, 8, 3, 2, 3, 9, 2, 0, 5, 4, 1, 5, 3, 9, 4], cat: "ooafm", weak: "01000"};
const adj = buildAdjacency(paths), strong = buildAdjacency(paths, true);
assert.ok(adj.every(a => a instanceof Uint32Array));
assert.deepEqual(shortestPath(adj, paths, 0, 3), [3, 4]); // Fewest hops, crossing networks.
assert.deepEqual(shortestPath(adj, paths, 3, 1), [2, 1]); // Undirected.
assert.deepEqual(shortestPath(adj, paths, 1, 2), [1]);
assert.equal(shortestPath(strong, paths, 1, 2), null);
assert.equal(buildAdjacency({...paths, cat: "ooass", weak: "00000"}).flatMap(a => [...a]).length, 10); // Weak owner and officer/manager route excluded.
assert.deepEqual([...strong[0]], [0]);
assert.deepEqual([...strong[2]], [2]); // Strong address link retained.
assert.equal(shortestPath(adj, paths, 0, 4), null);
assert.deepEqual(shortestPath(adj, paths, 2, 2), []);
assert.deepEqual(shortestPath(adj, paths, 4, 4), []);
assert.equal(shortestPath(adj, paths, -1, 0), null);
assert.deepEqual(matchNames(paths, " john smith ", 12), [1, 3, 0, 2]);
assert.deepEqual(matchNames(paths, "JOHN SMITH", 2), [1, 3]);
assert.deepEqual(matchNames(paths, "456", 12), [3]);
assert.deepEqual(matchNames(paths, "CA", 12), []);
assert.deepEqual(matchNames(paths, "missing", 12), []);
// Exact release membership must survive moving source records to a deferred file.
const releaseFiles = [{ds: "Owners", rel: "2024-01-01"}, {ds: "Owners", rel: "2024-07-01"},
  {ds: "Owners", rel: "2024-04-01"}, {ds: "Enrollments", rel: "2024-05-01"}];
const released = {first: "2024-01-01", last: "2024-07-01", fs: [0, 1]};
assert.equal(edgeInRelease(released, releaseFiles, "2024-04-01"), false);
assert.equal(edgeInRelease(released, releaseFiles, "2024-05-01"), true);
assert.equal(edgeInRelease(released, releaseFiles, "2024-07-01"), true);
assert.equal(edgeInRelease(released, releaseFiles, "2025-01-01"), false);
assert.equal(compareTableValues("100", "9"), 91);
assert.ok(compareTableValues(null, 9, true) > 0);
assert.ok(compareTableValues("alpha", "Beta") < 0);
assert.ok(compareTableValues("alpha", "Beta", true) > 0);
assert.equal(csvRows([['a,"b', '=1+1', null, -2]]), '\"a,\"\"b\",\"\'=1+1\",\"\",\"-2\"\r\n');
assert.equal(timelineDateKey("1/2/2001"), "2001-01-02");
assert.equal(timelineDateKey("2024-01-01"), "2024-01-01");
// Gathered rings: centre untouched by construction, no two dots (or the centre) touch, deterministic.
{
  const centre = {x: 10, y: -5, radius: 30}, around = Array.from({length: 40}, (_, i) => ({id: "n" + i, radius: 6 + (i % 5) * 4}));
  const placed = ringPositions(centre, around, 20), again = ringPositions(centre, around, 20);
  assert.equal(placed.length, 40); assert.deepEqual(placed, again);
  const all = placed.map(p => ({...p, radius: around.find(a => a.id === p.id).radius}));
  for (const a of all) assert.ok(Math.hypot(a.x - centre.x, a.y - centre.y) >= centre.radius + a.radius + 20 - 1e-6);
  for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++)
    assert.ok(Math.hypot(all[i].x - all[j].x, all[i].y - all[j].y) >= all[i].radius + all[j].radius + 20 - 1e-6, `${all[i].id} touches ${all[j].id}`);
  assert.deepEqual(ringPositions(centre, []), []);
  assert.equal(ringPositions(centre, [{id: "a", radius: 5}]).length, 1);
}
// Node export: heading, caution, a connection with its source URL; Markdown characters in names stay literal.
{
  const md = nodeMarkdown({name: "Care *Plus* [LLC] #1", kind: "hospice", date: "2026-11-10", dataDate: "2026-09-29",
    notes: ["Pseudonymized."], facts: [{label: "Status", value: "active", url: files[2].api}],
    timeline: [{date: "2024-01-01", label: "First", url: "http://insecure.example/x"}],
    connections: [{name: "Zed_Person", role: "Officer", first: "2024-01-01", last: "2024-01-01", rows: [{label: "2024-01-21", url: files[1].api + "?filter%5BENROLLMENT%20ID%5D=O1 x>"}]},
      {name: "Beta | Home\nHealth", agency: true, status: "revoked 2025-01-01", role: "Owner", pct: "15", first: "2023-01-01", last: "2025-01-01", src: "x"}]});
  const lines = md.split("\n");
  assert.equal(lines[0], "# Care \\*Plus\\* \\[LLC\\] #1");
  assert.ok(lines[2].startsWith("hospice · exported 2026-11-10 from CareGraph (public CMS records, data as of 2026-09-29)."));
  assert.ok(md.includes("Links are listings in CMS records, not evidence of a current relationship, common control or wrongdoing. Check each source row."));
  assert.ok(md.includes("## Connections (2)"));
  const bullets = lines.filter(l => l.startsWith("- ") && l.includes(" — "));
  assert.equal(bullets.length, 2);
  assert.ok(bullets[0].startsWith("- Beta \\| Home Health (revoked 2025-01-01) — Owner — 15% — 2023-01-01 – 2025-01-01"), bullets[0]);   // agencies first
  assert.ok(bullets[1].includes("Zed\\_Person — Officer — 2024-01-01 — rows: 2024-01-21 <https://data.cms.gov/data-api/v1/dataset/owners/data?filter%5BENROLLMENT%20ID%5D=O1%20x%3E>"), bullets[1]);
  assert.ok(!md.includes("insecure.example"));   // only https links are written
}
console.log("test_logic: passed (sources, paths, release gaps, sorting, CSV)");
