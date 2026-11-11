"use strict";
// CMS row URLs; absent metadata in older exports simply produces no link.
function apiUrl(file, filters) {
  if (!file?.api) return null;
  return file.api + "?" + Object.entries(filters).map(([key, value]) =>
    encodeURIComponent("filter[" + key + "]") + "=" + encodeURIComponent(value)).join("&");
}
function enrollmentUrl(files, i, id) {
  return apiUrl(files?.[i], {"ENROLLMENT ID": id});
}
// Person links are never filtered by owner ID or name: the link opens the agency's own rows in that release.
function recordUrl(files, i, edge) {
  return enrollmentUrl(files, i, edge.to);
}
// Per-network graph, record and address files are bucketed by this hash of their name (FNV-1a, 256 buckets, as
// scripts/site_tables.py shard_key); a bucket file holds {name: value}.
function shardKey(stem) {
  let n = 2166136261;
  for (const c of String(stem)) n = Math.imul(n ^ c.charCodeAt(0), 16777619) >>> 0;
  return (n % 256).toString(16).padStart(2, "0");
}
function shardPath(folder, stem) { return folder + "/" + shardKey(stem); }
function revocationUrl(files, ext, id) {
  return apiUrl(files?.[ext?.rev], {ENRLMT_ID: id});
}
function paymentsUrl(files, ext, node) {
  return node.ccn ? apiUrl(files?.[ext?.["pac_" + node.kind]], {PRVDR_ID: node.ccn, SMRY_CTGRY: "PROVIDER"}) : null;
}
function careCompareUrl(node) {
  const kind = {hospice: "hospice", hha: "home-health"}[node.kind];
  return node.ccn && kind ? "https://www.medicare.gov/care-compare/details/" + kind + "/" + encodeURIComponent(node.ccn) : null;
}
function nppesUrl(node) {
  return node.npi ? "https://npiregistry.cms.hhs.gov/provider-view/" + encodeURIComponent(node.npi) : null;
}
function datasetUrl(files, i) { return files?.[i]?.page || null; }
function latestFile(files, indexes = []) {
  return indexes.filter(i => files?.[i]).reduce((best, i) =>
    best == null || (files[i].rel || "") > (files[best].rel || "") ? i : best, null);
}
function latestRecord(files, edge) {
  let latest = null;
  for (const record of edge.recs || []) {
    const i = latestFile(files, record.f);
    if (i != null && (!latest || (files[i].rel || "") > (files[latest.i].rel || ""))) latest = {record, i};
  }
  return latest;
}

// Undirected adjacency; all node lists share one compact edge-index buffer.
function buildAdjacency(paths, strongOnly = false) {
  const counts = new Uint32Array(paths.names.length), edges = paths.edges;
  const keep = i => !strongOnly || (paths.weak[i] !== "1" && "oca".includes(paths.cat[i]));
  for (let i = 0; i < edges.length / 4; i++) if (keep(i)) {
    counts[edges[i * 4]]++; counts[edges[i * 4 + 1]]++;
  }
  const buffer = new Uint32Array(counts.reduce((sum, n) => sum + n, 0));
  let offset = 0;
  const adj = Array.from(counts, n => { const list = buffer.subarray(offset, offset + n); offset += n; return list; });
  counts.fill(0);
  for (let i = 0; i < edges.length / 4; i++) if (keep(i)) {
    const a = edges[i * 4], b = edges[i * 4 + 1];
    adj[a][counts[a]++] = i; adj[b][counts[b]++] = i;
  }
  return adj;
}
function shortestPath(adj, paths, from, to) {
  if (!Number.isInteger(from) || !Number.isInteger(to) || !adj[from] || !adj[to]) return null;
  if (from === to) return [];
  const prev = new Int32Array(adj.length).fill(-1), queue = new Uint32Array(adj.length);
  let head = 0, tail = 1;
  queue[0] = from; prev[from] = -2;
  while (head < tail) {
    const node = queue[head++];
    for (const i of adj[node]) {
      const a = paths.edges[i * 4], b = paths.edges[i * 4 + 1], next = a === node ? b : a;
      if (prev[next] !== -1) continue;
      prev[next] = i;
      if (next === to) {
        const result = [];
        for (let n = to; n !== from;) {
          const e = prev[n], a = paths.edges[e * 4], b = paths.edges[e * 4 + 1];
          result.push(e); n = a === n ? b : a;
        }
        return result.reverse();
      }
      queue[tail++] = next;
    }
  }
  return null;
}
function matchNames(paths, query, limit = 12) {
  const q = query.trim().toUpperCase(), matches = [[], [], []];
  if (q.length < 3 || limit <= 0) return [];
  for (let i = 0; i < paths.names.length; i++) {
    const name = paths.names[i].toUpperCase();
    const rank = name === q ? 0 : name.startsWith(q) ? 1 : paths.search[i].includes(q) ? 2 : -1;
    if (rank >= 0 && matches[rank].length < limit) matches[rank].push(i);
  }
  return matches.flat().slice(0, limit);
}

// Push overlapping circles {x, y, radius} apart in place; returns whether any moved.
function separateDots(points, gap = 12, maxPasses = 24) {
  const cell = Math.max(1, ...points.map(p => p.radius * 2 + gap + 1));
  let moved = false;
  for (let pass = 0; pass < maxPasses; pass++) {
    const grid = new Map();
    points.forEach((p, i) => {
      const key = `${Math.floor(p.x / cell)},${Math.floor(p.y / cell)}`;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(i);
    });
    let collisions = 0;
    points.forEach((a, i) => {
      const cx = Math.floor(a.x / cell), cy = Math.floor(a.y / cell);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (const j of grid.get(`${cx + dx},${cy + dy}`) || []) {
        if (j <= i) continue;
        const b = points[j], minimum = a.radius + b.radius + gap;
        let vx = b.x - a.x, vy = b.y - a.y, distance = Math.hypot(vx, vy);
        if (distance >= minimum) continue;
        if (distance < 1e-9) { const angle = (i * 31 + j * 17) * 2.399963229728653; vx = Math.cos(angle); vy = Math.sin(angle); distance = 1; }
        const shift = (minimum - Math.hypot(b.x - a.x, b.y - a.y)) / 2 + 0.01;
        const mx = vx / distance * shift, my = vy / distance * shift;
        a.x -= mx; a.y -= my; b.x += mx; b.y += my;
        collisions++; moved = true;
      }
    });
    if (!collisions) break;
  }
  return moved;
}

// Sort missing values last in either direction; CMS counts can arrive as numeric strings.
function compareTableValues(a, b, descending = false) {
  const empty = v => v == null || v === "";
  if (empty(a) || empty(b)) return empty(a) - empty(b);
  const numeric = v => typeof v === "number" || /^-?\d+(?:\.\d+)?$/.test(String(v));
  let result;
  if (numeric(a) && numeric(b)) result = Number(a) - Number(b);
  else { const x = String(a).toUpperCase(), y = String(b).toUpperCase(); result = x < y ? -1 : x > y ? 1 : 0; }
  return descending ? -result : result;
}
function csvRows(rows) {
  return rows.map(row => row.map(value => {
    let text = String(value ?? "");
    // Treat public text as text in spreadsheets, including names beginning with a formula character.
    if (typeof value === "string" && /^[\s]*[=+\-@]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }).join(",")).join("\r\n") + "\r\n";
}
function timelineDateKey(value) {
  const text = String(value ?? ""), us = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(text);
  return us ? `${us[3]}-${us[1].padStart(2, "0")}-${us[2].padStart(2, "0")}` : text;
}
function edgeInRelease(edge, files, release) {
  if (!edge.first) return true;
  const fs = edge.fs || (edge.recs || []).flatMap(r => r.f);
  const datasets = new Set(fs.map(i => files[i].ds));
  return files.some(f => f.rel === release && datasets.has(f.ds)) ? fs.some(i => files[i].rel === release)
    : edge.first <= release && release <= edge.last;
}

// Positions for neighbours gathered around a centre in non-touching rings (ported from the sibling viewer).
// centre {x, y, radius}; neighbours [{id, radius}] -> [{id, x, y}]; ring spacing keeps `gap` between dot edges.
function ringPositions(center, neighbors, gap = 20) {
  if (!neighbors.length) return [];
  const largest = Math.max(...neighbors.map(n => n.radius)), pitch = 2 * largest + gap;
  let ring = center.radius + largest + gap, index = 0;
  const out = [];
  while (index < neighbors.length) {
    // Chord spacing keeps neighbouring dots on one ring from touching.
    const capacity = Math.max(1, Math.floor(Math.PI / Math.asin(Math.min(1, pitch / (2 * ring)))));
    const count = Math.min(capacity, neighbors.length - index);
    for (let slot = 0; slot < count; slot++) {
      const angle = -Math.PI / 2 + slot * 2 * Math.PI / count;
      out.push({id: neighbors[index++].id, x: center.x + ring * Math.cos(angle), y: center.y + ring * Math.sin(angle)});
    }
    ring += pitch;
  }
  return out;
}

// Markdown text for one node. Pure: index.html passes what the panel already shows.
// d: {name, kind, date, dataDate, notes[], facts[{label, value, url}], timeline[{date, label, url}],
//     connections[{name, agency, status, role, pct, first, last, rows[{label, url}], src}]}
const mdText = v => String(v ?? "").replace(/\s+/g, " ").trim().replace(/[\\`*_\[\]<>|~]/g, "\\$&");
const mdUrl = u => typeof u === "string" && u.startsWith("https://") ? " <" + u.replace(/[<>\s]/g, encodeURIComponent) + ">" : "";
function nodeMarkdown(d) {
  const out = ["# " + mdText(d.name), "",
    `${mdText(d.kind)} · exported ${d.date} from CareGraph (public CMS records, data as of ${mdText(d.dataDate)}).`, "",
    "Links are listings in CMS records, not evidence of a current relationship, common control or wrongdoing. Check each source row.", ""];
  for (const note of d.notes || []) out.push(mdText(note), "");
  if ((d.facts || []).length) out.push("## Summary", "", ...d.facts.map(f => `- ${mdText(f.label)}: ${mdText(f.value)}${mdUrl(f.url)}`), "");
  if ((d.timeline || []).length) out.push("## Timeline", "", ...d.timeline.map(t => `- ${mdText(t.date)} · ${mdText(t.label)}${mdUrl(t.url)}`), "");
  const links = [...d.connections || []].sort((a, b) => !!b.agency - !!a.agency || String(a.name).localeCompare(String(b.name)));
  out.push(`## Connections (${links.length})`, "");
  for (const c of links) {
    const dates = c.first ? (c.first === c.last ? c.first : c.first + " – " + (c.last || "?")) : "";
    const parts = [mdText(c.role), c.pct ? mdText(c.pct) + "%" : "", mdText(dates),
      c.rows?.length ? "rows: " + c.rows.map(r => mdText(r.label) + mdUrl(r.url)).join("; ") : c.src ? mdText(c.src) : ""].filter(Boolean);
    out.push(`- ${mdText(c.name)}${c.status ? " (" + mdText(c.status) + ")" : ""}${parts.length ? " — " + parts.join(" — ") : ""}`);
  }
  return out.join("\n") + "\n";
}

if (typeof module !== "undefined") {
  module.exports = {shardKey, shardPath, apiUrl, enrollmentUrl, recordUrl, revocationUrl, paymentsUrl, careCompareUrl, nppesUrl,
    datasetUrl, latestFile, latestRecord, separateDots, buildAdjacency, shortestPath, matchNames, compareTableValues, csvRows, edgeInRelease, timelineDateKey, ringPositions, nodeMarkdown};
}
