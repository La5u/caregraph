"use strict";
// Tables are independent of the network index. Only the first page is needed on an ordinary visit.
let tableBack = null, tableMeta, tableFirst, tablePage = 0, tableFiltered = [], tableRows = {}, tablePromises = {};
let tableKind = "agencies", tableVersion = 0, tableTimer;
const TABLE_SIZE = 100;
const IND_SENTENCE = "A prompt to look closer, not a finding. These were tested against later CMS revocations; most agencies with an indicator have done nothing wrong.";
const TABLE_CAVEAT = 'Public CMS records, as of Oct 2026. A link is not evidence of wrongdoing. Past means missing from the latest enrollment file; it does not establish closure. A CMS revocation can be appealed and later reversed; it is not a criminal finding or a finding against a listed person.';
// Metrics and indicators are one lazy file keyed by CCN (not part of the first page); labels come from tables.json.
let metricsPromise, METRICS_DATA;
function loadMetrics() {
  if (!metricsPromise) metricsPromise = Promise.all([dataFile("metrics"), tableMeta || dataFile("tables")])
    .then(([m, meta]) => { tableMeta ||= meta; METRICS_DATA = m; return m; })
    .catch(e => { metricsPromise = null; throw e; });
  return metricsPromise;
}
const indLabel = k => tableMeta?.indicators?.[k]?.label || k;
// Indicators exist for hospices only; a home health agency never has them.
const agencyInd = n => n.kind === "hospice" ? METRICS_DATA?.[n.ccn]?.ind || [] : [];
function indMeans(k, rec) {
  const means = tableMeta?.indicators?.[k]?.means || "";
  return k === "busy_building" && rec?.bldg_n ? `${rec.bldg_n} hospices and home health agencies are listed in this building. It may be an ordinary office building.` : means;
}
function chipsHTML(n) {
  return agencyInd(n).map(k => `<span class="chip" title="${esc(indMeans(k, METRICS_DATA[n.ccn]))}">${esc(indLabel(k))}</span>`).join(" ");
}
const ordinal = p => p + ((p % 100 >= 11 && p % 100 <= 13) ? "th" : ["th", "st", "nd", "rd"][p % 10] || "th");
const metricValue = (meta, v) => v == null ? "" : meta?.money ? fmt$(v) : Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
function metricsHTML(n, rec) {
  const meta = tableMeta?.metrics || {}, hha = n.kind === "hha";
  if (!rec) return `<h3>Metrics</h3><p class="note">No metrics are published for this agency (no CCN, or no matching CMS rows).</p>`;
  const rows = Object.entries(rec.m || {}).map(([k, [v, p]]) =>
    `<tr><td>${esc(meta[k]?.label || k)}</td><td>${esc(metricValue(meta[k], v))}</td><td>${esc(ordinal(p))} percentile</td></tr>`).join("");
  const na = (rec.na || []).map(k => esc(meta[k]?.label || k)).join("; ");
  const years = Object.entries(rec.y || {}).map(([y, [patients, paid, days]]) =>
    `<tr><td>${esc(y)}</td><td>${esc(metricValue(null, patients))}</td><td>${esc(paid == null ? "" : fmt$(paid))}</td><td>${esc(metricValue(null, days))}</td></tr>`).join("");
  return `<h3>Metrics</h3><table class="metrics"><thead><tr><th>Metric</th><th>Value</th><th>National percentile</th></tr></thead><tbody>${rows}</tbody></table>` +
    (na ? `<p class="note">Not assessed: ${na}</p>` : "") +
    (years ? `<table class="metrics"><thead><tr><th>Year</th><th>Patients</th><th>Paid</th><th>Days</th></tr></thead><tbody>${years}</tbody></table>` : "") +
    `<p class="note">Percentiles compare each ${hha ? "home health agency with other home health agencies" : "hospice with other hospices"} nationally. Source: CMS Medicare Post-Acute Care Utilization by Provider, 2024 (yearly rows 2021-2024)${hha ? "" : "; Care Compare hospice measures 2023-24"}. A missing value is not assessed, not zero.</p>`;
}
function indicatorsHTML(n, rec) {
  if (n.kind !== "hospice" || !rec) return "";
  const flagged = (rec.ind || []).map(k => `<li><b>${esc(indLabel(k))}</b>: ${esc(indMeans(k, rec))}</li>`).join("");
  const na = (rec.ind_na || []).map(k => `<li>${esc(indLabel(k))}</li>`).join("");
  return `<h3>Indicators</h3><p class="note">${esc(IND_SENTENCE)} <a href="about.html#indicators">How these were tested</a></p>` +
    (flagged ? `<ul>${flagged}</ul>` : "<p>No indicators apply to this hospice.</p>") +
    (na ? `<p class="note">Not assessed (not the same as no indicator):</p><ul>${na}</ul>` : "");
}
// Fills the agency panel's Metrics and Indicators once metrics.json arrives; the rest of the panel does not wait.
function fillAgencyExtra(n, version) {
  const box = $("agency-extra");
  if (!box) return;
  const draw = () => { if (version === panelVersion && $("agency-extra")) $("agency-extra").innerHTML = metricsHTML(n, METRICS_DATA[n.ccn]) + indicatorsHTML(n, METRICS_DATA[n.ccn]); };
  if (METRICS_DATA) { draw(); return; }
  loadMetrics().then(draw).catch(() => {
    if (version !== panelVersion || !$("agency-extra")) return;
    $("agency-extra").innerHTML = '<small>Could not load metrics. <button id="metrics-retry">Retry</button></small>';
    $("metrics-retry").onclick = () => { $("agency-extra").innerHTML = '<small role="status">Loading metrics…</small>'; fillAgencyExtra(n, version); };
  });
}
function showIndicators() {
  if (METRICS_DATA) return;
  loadMetrics().then(() => { if (document.body.dataset.section === "agencies" && tableKind === "agencies") renderTable(); }).catch(() => {
    $("table-statusline").innerHTML = 'Could not load indicators. <button id="ind-retry">Retry</button>'; $("ind-retry").onclick = showIndicators; });
}
const TABLE_COLS = {
  agencies: [["name", "Name / DBA"], ["kind", "Type"], ["city", "City"], ["state", "State"], ["ccn", "CCN"],
    ["status", "Status"], ["paid", "2024 Medicare paid"], ["benes_2024", "2024 patients"], ["first_seen", "First seen"], ["group", "Network"]],
  addresses: [["address", "Address / building"], ["ever", "Agencies ever listed"], ["current", "Currently listed"],
    ["revoked", "Revoked count"], ["paid", "Total 2024 paid"], ["flags", "Published labels"]],
  changes: [["release", "Release pair / observation"], ["name", "Agency"], ["state", "State"], ["event", "Event"], ["detail", "CMS listing change"]]
};
const agencyStatus = n => n.status === "active" ? "Active" : n.status === "revoked" ? "Revoked" : "Past";
function tableData(kind) {
  if (!tablePromises[kind]) tablePromises[kind] = dataFile(kind).then(d => tableRows[kind] = d)
    .catch(e => { delete tablePromises[kind]; throw e; });
  return tablePromises[kind];
}
function tableParams() { return new URLSearchParams(location.hash.split("?")[1] || ""); }
function tableSort(kind, params) {
  const fallback = kind === "addresses" ? "current" : kind === "changes" ? "release" : "name";
  const key = TABLE_COLS[kind].some(([k]) => k === params.get("sort")) ? params.get("sort") : fallback;
  return {key, desc: params.has("dir") ? params.get("dir") === "desc" : kind !== "agencies"};
}
function updateTableURL(params) {
  const query = params.toString();
  history.replaceState(null, "", "#/" + tableKind + (query ? "?" + query : ""));
}
function tableFilterChange() {
  clearTimeout(tableTimer);
  tableTimer = setTimeout(() => {
    const params = tableParams();
    for (const field of ["q", "state", "type", "status", "release", "event"]) {
      const input = document.getElementById("table-" + field);
      if (!input) continue;
      if (input.value) params.set(field, input.value); else params.delete(field);
    }
    const inds = [...document.querySelectorAll("[data-ind]:checked")].map(i => i.dataset.ind);
    if (inds.length) params.set("ind", inds.join(",")); else params.delete("ind");
    params.delete("page"); updateTableURL(params); renderTable();
  }, 150);
}
function tableOption(value, label = value) { return `<option value="${esc(value)}">${esc(label)}</option>`; }
function tableShell(kind, params) {
  const title = {agencies: "Agencies", addresses: "Addresses", changes: "Changes"}[kind];
  const search = kind !== "changes" ? '<label>Search <input id="table-q" type="search" placeholder="Name, city, CCN or enrollment ID"></label>' : "";
  const states = kind !== "addresses" ? `<label>State <select id="table-state">${tableOption("", "All states")}${tableMeta.states.map(s => tableOption(s)).join("")}</select></label>` : "";
  const filters = kind === "agencies" ? `<label>Type <select id="table-type">${tableOption("", "All types")}${tableOption("hospice", "Hospice")}${tableOption("hha", "Home health")}</select></label><label>Status <select id="table-status">${["", "Active", "Past", "Revoked"].map(s => tableOption(s, s || "All statuses")).join("")}</select></label>`
    : kind === "changes" ? `<label>Release <select id="table-release">${tableOption("", "All release pairs")}${tableMeta.pairs.map(([before, after]) => tableOption(before + "|" + after, before ? before + " → " + after : after + " (extract observation)")).join("")}</select></label><label>Event <select id="table-event">${tableOption("", "All events")}${tableMeta.events.map(s => tableOption(s)).join("")}</select></label>` : "";
  const caveat = TABLE_CAVEAT;
  const indFilter = kind === "agencies" ? `<details id="table-advanced"><summary>Advanced filters</summary><fieldset><legend>Indicators (hospices only; every ticked indicator must apply)</legend>${Object.entries(tableMeta.indicators || {}).map(([k, x]) => `<label><input type="checkbox" data-ind="${esc(k)}"> ${esc(x.label)} (${Number(tableMeta.indicator_counts?.[k] || 0).toLocaleString()})</label>`).join("<br>")}</fieldset><p class="note">${esc(IND_SENTENCE)} <a href="about.html#indicators">About indicators</a></p></details>` : "";
  $("tableview").innerHTML = `<h1>${title}</h1>${kind === "changes" ? '<p>A change between files may be a filing correction.</p><p class="tablecaveat">Comparisons use consecutive available files of the same dataset. Revocations show the effective date and the extract observation date, rather than an inferred quarterly filing change.</p>' : ""}<p class="tablecaveat">${caveat}</p>
    ${kind === "agencies" ? '<p class="note">One row per enrollment, including agencies outside multi-agency networks. Dates are first CMS release seen. “Active” means listed in the latest enrollment file with no revocation row found. No 2024 claims found is not a zero payment.</p>' : ""}
    ${kind === "addresses" ? '<p class="note">Addresses and buildings with two or more agencies across all enrollment files. “Currently listed” uses each agency type’s latest enrollment file. Dates are first/last CMS release seen, not event dates. Payments sum enrollment rows and may repeat for enrollments sharing a CCN; address and building rows can overlap.</p>' : ""}
    <div class="tablefilters">${search}${states}${filters}<button id="table-csv">Export filtered CSV</button>${indFilter}</div><div id="table-statusline" role="status"></div><div id="table-results"></div>`;
  for (const field of ["q", "state", "type", "status", "release", "event"]) {
    const input = document.getElementById("table-" + field);
    if (!input) continue;
    input.value = params.get(field) || "";
    input.addEventListener(input.tagName === "INPUT" ? "input" : "change", tableFilterChange);
  }
  $("table-csv").onclick = exportTable;
  const advanced = $("table-advanced");
  if (advanced) {
    const chosen = (params.get("ind") || "").split(",");
    advanced.querySelectorAll("[data-ind]").forEach(box => { box.checked = chosen.includes(box.dataset.ind); box.addEventListener("change", tableFilterChange); });
    advanced.open = chosen.some(Boolean);
    advanced.addEventListener("toggle", () => { if (advanced.open) showIndicators(); });
  }
}
async function tableRoute() {
  const match = /^#\/(agencies|addresses|changes)(?:\?|$)/.exec(location.hash);
  if (location.hash && !match) { tableVersion++; return false; }
  const version = ++tableVersion, kind = match?.[1] || "agencies";
  document.body.dataset.section = kind;
  document.querySelectorAll("#topnav a").forEach(a => a.setAttribute("aria-current", a.hash === "#/" + kind ? "page" : "false"));
  network?.stopLayout(); current = null; G = null; panelVersion++;
  $("tableview").innerHTML = '<p role="status">Loading table…</p>';
  try {
    tableMeta ||= await dataFile("tables");
    if (version !== tableVersion) return true;
    tableKind = kind;
    tableShell(kind, tableParams());
    await renderTable();
  } catch {
    if (version === tableVersion) { $("tableview").innerHTML = '<p>Could not load table. <button id="table-retry">Retry</button></p>'; $("table-retry").onclick = route; }
  }
  return true;
}
async function filteredTable(kind, params) {
  const rows = await tableData(kind);
  let agencies;
  if (kind === "changes") agencies = Object.fromEntries((await tableData("agencies")).map(n => [n.id, n]));
  const q = (params.get("q") || "").trim().toUpperCase();
  const wanted = kind === "agencies" ? (params.get("ind") || "").split(",").filter(k => tableMeta.indicators?.[k]) : [];
  if (wanted.length) await loadMetrics();
  const filtered = rows.filter(row => {
    const n = kind === "changes" ? agencies[row.id] : row;
    return (!params.get("state") || n.state === params.get("state")) &&
      (!params.get("type") || n.kind === params.get("type")) &&
      (!params.get("status") || agencyStatus(n) === params.get("status")) &&
      (!params.get("release") || row.before + "|" + row.release === params.get("release")) &&
      (!params.get("event") || row.event === params.get("event")) &&
      (!wanted.length || wanted.every(k => agencyInd(n).includes(k))) &&
      (!q || [row.address, ...(row.flags || []), n.name, n.dba, n.city, n.state, n.ccn, n.id].filter(Boolean).join(" ").toUpperCase().includes(q));
  }).map(n => kind === "changes" ? {...n, name: agencies[n.id].name, state: agencies[n.id].state, group: agencies[n.id].group} : n);
  const {key, desc} = tableSort(kind, params);
  filtered.sort((a, b) => compareTableValues(key === "status" ? agencyStatus(a) : a[key], key === "status" ? agencyStatus(b) : b[key], desc) || String(a.id).localeCompare(String(b.id)));
  return filtered;
}
let renderTableVersion = 0;
async function renderTable() {
  const version = ++renderTableVersion, view = tableVersion, kind = tableKind, params = tableParams();
  $("table-statusline").textContent = "Loading table…";
  try {
    // The build's first page has the exact same ordering as a full name-ascending sort.
    const firstOnly = kind === "agencies" && ![...params].some(([k, v]) => v && !(k === "page" && v === "0"));
    let total;
    if (firstOnly && !tableRows.agencies) {
      tableFirst ||= await dataFile("agencies-first");
      tableFiltered = tableFirst; total = tableMeta.count;
    } else { tableFiltered = await filteredTable(kind, params); total = tableFiltered.length; }
    if (version !== renderTableVersion || view !== tableVersion) return;
    tablePage = Math.max(0, Math.min(Number.parseInt(params.get("page")) || 0, Math.max(0, Math.ceil(total / TABLE_SIZE) - 1)));
    const rows = tableFiltered.slice(tablePage * TABLE_SIZE, (tablePage + 1) * TABLE_SIZE);
    const {key, desc} = tableSort(kind, params);
    $("table-statusline").textContent = `${total.toLocaleString()} rows · ${tablePage * TABLE_SIZE + (total ? 1 : 0)}–${Math.min((tablePage + 1) * TABLE_SIZE, total)}`;
    $("table-results").innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr>${TABLE_COLS[kind].map(([k, label]) => `<th scope="col" aria-sort="${k === key ? desc ? "descending" : "ascending" : "none"}"><button data-sort="${k}">${esc(label)}${k === key ? desc ? " ↓" : " ↑" : ""}</button></th>`).join("")}${kind === "agencies" ? `<th scope="col">${METRICS_DATA ? "Indicators" : '<button data-load-indicators>Show indicators</button>'}</th><th scope="col">Case</th>` : ""}</tr></thead><tbody>${rows.map(row => tableRowHTML(kind, row)).join("")}</tbody></table></div><div class="pager"><button data-page="${tablePage - 1}" ${tablePage ? "" : "disabled"}>Previous</button><span>Page ${tablePage + 1} of ${Math.max(1, Math.ceil(total / TABLE_SIZE))}</span><button data-page="${tablePage + 1}" ${(tablePage + 1) * TABLE_SIZE >= total ? "disabled" : ""}>Next</button></div>`;
  } catch {
    if (version === renderTableVersion && view === tableVersion) { $("table-statusline").innerHTML = 'Could not load table. <button id="rows-retry">Retry</button>'; $("rows-retry").onclick = renderTable; }
  }
}
function agencyHash(row) { return row.group ? "#" + row.group + "/" + encodeURIComponent(row.id) : "#/agency/" + encodeURIComponent(row.id); }
function tableRowHTML(kind, row) {
  const cells = TABLE_COLS[kind].map(([key]) => {
    const value = row[key];
    if ((kind === "agencies" && key === "name") || (kind === "changes" && key === "name")) return `<td><a data-open-agency href="${esc(agencyHash(row))}">${esc(nice(value || row.dba || row.id))}</a>${row.dba ? `<small>DBA ${esc(nice(row.dba))}</small>` : ""}</td>`;
    if (kind === "addresses" && key === "address") return `<td><button data-address="${esc(row.id)}" aria-expanded="false">Expand</button> ${esc(nice(value))}${row.building ? '<small>Whole building · suites may be separate tenants</small>' : ""}</td>`;
    if (key === "paid") return `<td>${esc(fmt$(value))}</td>`;
    if (key === "benes_2024") return `<td>${esc(value ?? "—")}</td>`;
    if (key === "kind") return `<td>${value === "hha" ? "Home health" : "Hospice"}</td>`;
    if (key === "status") return `<td>${agencyStatus(row)}</td>`;
    if (key === "group") return `<td>${value ? "#" + esc(value) : "No multi-agency network"}</td>`;
    if (key === "release") return `<td>${esc(row.before ? row.before + " → " + value : value + " (extract observation)")}</td>`;
    if (key === "flags") return `<td>${(value || []).map(v => `<strong class="badge past">${esc(v)}</strong>`).join(" ") || "—"}</td>`;
    return `<td>${esc(value ?? "—")}</td>`;
  }).join("");
  return `<tr ${kind !== "addresses" ? `data-agency="${esc(agencyHash(row))}"` : ""}>${cells}${kind === "agencies" ? `<td class="chips">${chipsHTML(row)}</td><td><button data-case-toggle="${esc(row.id)}">${caseHas(row.id) ? "In case · Remove" : "Add to case"}</button></td>` : ""}</tr>`;
}
async function expandAddress(button) {
  const row = button.closest("tr"), id = button.dataset.address;
  if (row.nextElementSibling?.dataset.addressDetail === id) { row.nextElementSibling.remove(); button.setAttribute("aria-expanded", "false"); button.textContent = "Expand"; return; }
  const detail = document.createElement("tr"); detail.dataset.addressDetail = id;
  detail.innerHTML = '<td colspan="6" role="status">Loading agency listings and source rows…</td>';
  row.after(detail); button.setAttribute("aria-expanded", "true"); button.textContent = "Collapse";
  const draw = async () => {
    try {
      const [listings, agencyRows] = await Promise.all([shardItem("a", id), tableData("agencies"), loadIndex()]);
      const agencies = Object.fromEntries(agencyRows.map(n => [n.id, n]));
      detail.innerHTML = `<td colspan="6"><table class="data-table"><thead><tr><th>Agency</th><th>Address and suite as CMS wrote it</th><th>First / last release seen</th><th>Sources</th></tr></thead><tbody>${listings.map(l => `<tr><td><a data-open-agency href="${esc(agencyHash(agencies[l.id]))}">${esc(nice(agencies[l.id].name))}</a></td><td>${esc(l.address)}</td><td>${esc(l.first)} – ${esc(l.last)}</td><td>${releaseLinks(l.files, i => enrollmentUrl(INDEX.files, i, l.id))}</td></tr>`).join("")}</tbody></table></td>`;
    } catch { detail.innerHTML = '<td colspan="6">Could not load listings. <button>Retry</button></td>'; detail.querySelector("button").onclick = draw; }
  };
  await draw();
}
async function exportTable() {
  const button = $("table-csv"), kind = tableKind, params = tableParams();
  button.disabled = true; button.textContent = "Preparing CSV…";
  try {
    const rows = await filteredTable(kind, params);
    const base = kind === "agencies" ? [["id", "Enrollment ID"], ["name", "Name"], ["dba", "DBA"], ...TABLE_COLS[kind].slice(1)]
      : kind === "changes" ? [["id", "Enrollment ID"], ...TABLE_COLS[kind]] : TABLE_COLS[kind];
    const columns = base.map(([key, label]) => [label, n => key === "status" ? agencyStatus(n) : key === "release" ? (n.before ? n.before + " → " : "Extract observation ") + n.release : Array.isArray(n[key]) ? n[key].join("; ") : n[key]]);
    if (kind === "agencies") {
      await loadMetrics();
      const meta = tableMeta.metrics || {};
      columns.push(["Indicators (a prompt to look closer, not a finding)", n => agencyInd(n).map(indLabel).join("; ")],
        ["Indicators not assessed", n => n.kind === "hospice" ? (METRICS_DATA[n.ccn]?.ind_na || []).map(indLabel).join("; ") : ""]);
      for (const [k, m] of Object.entries(meta)) columns.push([m.label, n => METRICS_DATA[n.ccn]?.m?.[k]?.[0]], [m.label + " (national percentile)", n => METRICS_DATA[n.ccn]?.m?.[k]?.[1]]);
    }
    const text = csvRows([columns.map(([label]) => label), ...rows.map(n => columns.map(([, get]) => get(n)))]);
    downloadFile("\ufeff" + text, "text/csv;charset=utf-8", "caregraph-" + kind + ".csv");
    button.textContent = "Export filtered CSV";
  } catch { button.textContent = "Could not export · Retry CSV"; }
  finally { button.disabled = false; }
}
function agencyTimeline(n, edges) {
  return '<ol>' + timelineEvents(n, edges, G.byId).map(e => `<li><time>${esc(e.date)}</time> · ${esc(e.label)}${sourceLink(e.url)}</li>`).join("") + '</ol>';
}
function timelineEvents(n, edges, byId) {
  const events = [], add = (date, label, url) => { if (date && date !== "None") events.push({date, label, url}); };
  const fs = (n.ef || []).sort((a, b) => INDEX.files[a].rel.localeCompare(INDEX.files[b].rel));
  if (fs.length) {
    add(INDEX.files[fs[0]].rel, "First enrollment-file release seen", enrollmentUrl(INDEX.files, fs[0], n.id));
    add(INDEX.files[fs.at(-1)].rel, "Last enrollment-file release seen", enrollmentUrl(INDEX.files, fs.at(-1), n.id));
  }
  add(n.certified, "CMS certification date (event date)", careCompareUrl(n));
  for (const e of edges) for (const r of e.recs || []) {
    const indexes = [...r.f].sort((a, b) => INDEX.files[a].rel.localeCompare(INDEX.files[b].rel));
    if (!indexes.length) continue;
    const other = byId[e.from === n.id ? e.to : e.from], label = `${r.role || roles(e)} · ${r.addr || other?.name || other?.id}`;
    add(INDEX.files[indexes[0]].rel, "First release seen: " + label, recordUrl(INDEX.files, indexes[0], e, r));
    add(INDEX.files[indexes.at(-1)].rel, "Last release seen: " + label, recordUrl(INDEX.files, indexes.at(-1), e, r));
  }
  add(n.rev_date, "CMS revocation effective date (event date)" + (n.rev_bar ? " · Re-enrollment bar: " + n.rev_bar : ""), revocationUrl(INDEX.files, INDEX.ext, n.id));
  events.sort((a, b) => timelineDateKey(a.date).localeCompare(timelineDateKey(b.date)));
  return events;
}
// Delegated events keep table rerenders small and keyboard access native (links and buttons).
addEventListener("DOMContentLoaded", () => {
  $("tableview").onclick = ev => {
    const sort = ev.target.closest("[data-sort]"), page = ev.target.closest("[data-page]"), address = ev.target.closest("[data-address]");
    if (sort || page) {
      const p = tableParams();
      if (sort) { const old = tableSort(tableKind, p); p.set("sort", sort.dataset.sort); p.set("dir", old.key === sort.dataset.sort && !old.desc ? "desc" : "asc"); p.delete("page"); }
      else p.set("page", page.dataset.page);
      updateTableURL(p); renderTable(); return;
    }
    if (address) { expandAddress(address); return; }
    if (ev.target.closest("[data-load-indicators]")) { showIndicators(); return; }
    if (ev.target.closest("[data-case-toggle]")) return;   // handled by case.js; must not open the agency
    const link = ev.target.closest("[data-open-agency]"), row = ev.target.closest("[data-agency]");
    if ((link || row) && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey && !ev.altKey) {
      tableBack = location.hash || "#/agencies";
      if (!link) location.hash = row.dataset.agency;
    }
  };
});
