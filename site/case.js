// Case tray: agencies the visitor collects, with local marks and notes. Everything stays in this browser
// (localStorage); nothing is sent anywhere and none of it goes into shared links. People appear only as their
// pseudonymous codes, as everywhere on the site.
const CASE_KEY = "caregraph-case", NOTES_KEY = "caregraph-notes";
const caseLoad = (key, empty) => { try { return JSON.parse(localStorage.getItem(key)) || empty; } catch { return empty; } };
let caseItems = caseLoad(CASE_KEY, []), caseNotes = caseLoad(NOTES_KEY, {});
const caseSave = () => { localStorage.setItem(CASE_KEY, JSON.stringify(caseItems)); localStorage.setItem(NOTES_KEY, JSON.stringify(caseNotes)); };
function caseHas(id) { return caseItems.includes(id); }
function caseToggle(id) {
  caseItems = caseHas(id) ? caseItems.filter(x => x !== id) : [...caseItems, id];
  caseSave(); caseRefresh();
}
const MARKS = {"": "No mark", follow: "Follow up", referred: "Referred", reviewed: "Reviewed"};

async function caseRows() {
  const rows = await tableData("agencies"), byId = new Map(rows.map(r => [r.id, r]));
  return caseItems.map(id => byId.get(id) || {id, name: id});
}
function caseRefresh() {
  document.querySelectorAll("[data-case-toggle]").forEach(b => { b.textContent = caseHas(b.dataset.caseToggle) ? "In case · Remove" : "Add to case"; });
  const btn = $("casebtn");
  if (btn) { btn.textContent = `Case (${caseItems.length})`; btn.hidden = !caseItems.length && !$("casetray").open; }
  if ($("casetray")?.open) caseDraw();
}
window.caseRefresh = caseRefresh;

async function caseDraw() {
  const box = $("casebody");
  if (!caseItems.length) { box.innerHTML = '<p class="note">No agencies yet. Use "Add to case" in the Agencies table or an agency panel.</p>'; return; }
  box.innerHTML = '<small role="status">Loading…</small>';
  let rows;
  try { rows = await caseRows(); } catch { box.innerHTML = 'Could not load agencies. <button id="caseretry">Retry</button>'; $("caseretry").onclick = caseDraw; return; }
  box.innerHTML = rows.map(r => {
    const note = caseNotes[r.id] || {};
    return `<div class="caseitem" data-case-item="${esc(r.id)}"><b>${esc(nice(r.dba || r.name))}</b> <small>${esc([r.city, r.state, r.ccn && "CCN " + r.ccn].filter(Boolean).join(" · "))}</small>
      <br><select data-case-mark aria-label="Mark">${Object.entries(MARKS).map(([k, v]) => `<option value="${k}"${note.mark === k ? " selected" : ""}>${v}</option>`).join("")}</select>
      <button data-case-toggle="${esc(r.id)}">Remove</button><button data-case-open="${esc(agencyHash(r))}">Open</button>
      <textarea data-case-note rows="2" placeholder="Note (stays in this browser)">${esc(note.note || "")}</textarea></div>`;
  }).join("");
}

// One record per agency, gathered from the published data: agency fields, dated links, timeline, metrics, indicators.
async function caseRecord(r) {
  await loadIndex();
  const metrics = await loadMetrics().catch(() => null), rec = metrics?.[r.ccn];
  const out = {agency: r, links: [], timeline: [], metrics: [], indicators: [], notAssessed: [], note: caseNotes[r.id] || {}};
  if (r.group && !String(r.group).startsWith("solo-")) {
    const d = await loadGroup(r.group);
    if (!d.recordsLoaded) { const keep = current; current = r.group; try { await loadRecords(r.group); } finally { current = keep; } }
    const n = d.byId[r.id];
    if (n) {
      const es = d.edges.filter(e => e.from === n.id || e.to === n.id);
      out.links = es.map(e => { const o = d.byId[e.from === n.id ? e.to : e.from];
        return {other: o?.dba || o?.name || o?.id, kind: o?.kind, roles: roles(e), pct: e.pct, first: e.first, last: e.last}; });
      out.timeline = timelineEvents(n, es, d.byId);
    }
  }
  if (rec) {
    const meta = tableMeta?.metrics || {};
    out.metrics = Object.entries(rec.m || {}).map(([k, [v, p]]) => ({label: meta[k]?.label || k, value: v, pct: p}));
    if (r.kind === "hospice") {
      out.indicators = (rec.ind || []).map(k => ({label: indLabel(k), means: indMeans(k, rec)}));
      out.notAssessed = (rec.ind_na || []).map(indLabel);
    }
  }
  return out;
}
const CASE_DISCLAIMER = "Public CMS records. A link, a metric or an indicator is not evidence of wrongdoing. " + IND_SENTENCE +
  " People are shown as pseudonymous codes. Revocations are CMS administrative actions; they can be appealed and are not findings against any person listed.";

async function caseCSV() {
  const recs = await Promise.all((await caseRows()).map(caseRecord));
  const lines = [["Enrollment ID", "Name", "DBA", "Type", "City", "State", "CCN", "Status", "2024 Medicare paid", "2024 patients", "Network",
    "Linked (role, first-last release)", "Metrics (value, national percentile)", "Indicators", "Indicators not assessed", "Mark", "Note", "Caveat"]];
  for (const c of recs) {
    const a = c.agency;
    lines.push([a.id, a.name, a.dba, a.kind, a.city, a.state, a.ccn, agencyStatus(a), a.paid, a.benes_2024, a.group,
      c.links.map(l => `${l.other} (${l.roles}${l.pct ? " " + l.pct + "%" : ""}, ${l.first}-${l.last})`).join("; "),
      c.metrics.map(m => `${m.label}: ${m.value} (p${m.pct})`).join("; "),
      c.indicators.map(i => i.label).join("; "), c.notAssessed.join("; "), MARKS[c.note.mark || ""], c.note.note || "", CASE_DISCLAIMER]);
  }
  downloadFile("\ufeff" + csvRows(lines), "text/csv;charset=utf-8", "caregraph-case.csv");
}
async function casePrint() {
  const recs = await Promise.all((await caseRows()).map(caseRecord));
  const body = recs.map(c => { const a = c.agency;
    return `<section><h2>${esc(nice(a.dba || a.name))}</h2><p>${esc(a.name)} · ${esc(a.kind === "hha" ? "home health agency" : "hospice")} · ${esc([a.city, a.state].filter(Boolean).join(", "))}
      · Enrollment ${esc(a.id)} · CCN ${esc(a.ccn || "—")} · ${esc(agencyStatus(a))}${a.rev_date ? " " + esc(a.rev_date) : ""} · 2024 paid ${esc(fmt$(a.paid))}${a.group ? " · network #" + esc(a.group) : ""}</p>
      ${c.note.mark || c.note.note ? `<p><b>Your mark:</b> ${esc(MARKS[c.note.mark || ""])} ${esc(c.note.note || "")}</p>` : ""}
      ${c.indicators.length || c.notAssessed.length ? `<h3>Indicators</h3><p><i>${esc(IND_SENTENCE)}</i></p><ul>${c.indicators.map(i => `<li><b>${esc(i.label)}</b>: ${esc(i.means)}</li>`).join("")}</ul>${c.notAssessed.length ? `<p>Not assessed: ${esc(c.notAssessed.join("; "))}</p>` : ""}` : ""}
      ${c.metrics.length ? `<h3>Metrics</h3><table>${c.metrics.map(m => `<tr><td>${esc(m.label)}</td><td>${esc(m.value)}</td><td>${esc(ordinal(m.pct))} percentile</td></tr>`).join("")}</table>` : ""}
      ${c.links.length ? `<h3>Links</h3><ul>${c.links.map(l => `<li>${esc(nice(l.other))} — ${esc(l.roles)}${l.pct ? " " + esc(l.pct) + "%" : ""} · ${esc(l.first)} – ${esc(l.last)}</li>`).join("")}</ul>` : ""}
      ${c.timeline.length ? `<h3>Timeline</h3><p><small>Dates are the first/last CMS release seen unless labelled as an event date.</small></p><ol>${c.timeline.map(e => `<li>${esc(e.date)} · ${esc(e.label)}${e.url ? ` <small>${esc(e.url)}</small>` : ""}</li>`).join("")}</ol>` : ""}
    </section>`; }).join("");
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CareGraph case</title><style>body{font:12px/1.4 system-ui,sans-serif;margin:20px}section{break-inside:avoid-page;border-top:1px solid #999;margin-top:12px}small{color:#555;word-break:break-all}td{padding:1px 8px 1px 0}</style></head><body>
    <h1>CareGraph case</h1><p>Printed ${esc(new Date().toISOString().slice(0, 10))} from caregraph.lasu.dev. Data: CMS enrollment and owner files to ${esc(LATEST || "")}, CMS payments 2024, Care Compare 2023-24.</p>
    <p><b>${esc(CASE_DISCLAIMER)}</b></p>${body}</body></html>`;
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;width:0;height:0;border:0;right:0;bottom:0";
  document.body.append(frame);
  frame.contentDocument.open(); frame.contentDocument.write(html); frame.contentDocument.close();
  frame.contentWindow.focus(); frame.contentWindow.print();
  setTimeout(() => frame.remove(), 60000);
}
function caseExportNotes() {
  downloadFile(JSON.stringify({case: caseItems, notes: caseNotes}, null, 1), "application/json", "caregraph-notes.json");
}
function caseImportNotes(file) {
  file.text().then(t => {
    const d = JSON.parse(t);
    if (!d || typeof d !== "object" || (d.case && !Array.isArray(d.case))) throw new Error("format");
    caseItems = [...new Set([...caseItems, ...(d.case || []).map(String)])];
    for (const [id, v] of Object.entries(d.notes || {})) if (v && typeof v === "object")
      caseNotes[id] = {mark: MARKS[v.mark] != null ? v.mark : "", note: String(v.note || "")};
    caseSave(); caseRefresh();
  }).catch(() => { $("casestatus").textContent = "That file is not a CareGraph notes file."; });
}
const caseRun = fn => () => { $("casestatus").textContent = "Preparing…";
  fn().then(() => $("casestatus").textContent = "").catch(() => $("casestatus").textContent = "Could not load the data. Try again."); };

addEventListener("DOMContentLoaded", () => {
  document.body.insertAdjacentHTML("beforeend", `<button id="casebtn" hidden></button>
    <details id="casetray"><summary>Case</summary><p class="note">Stays in this browser only; not in shared links. People appear as codes.</p>
    <div id="casebody"></div><div class="caseactions"><button id="casecsv">Export CSV</button> <button id="caseprint">Print / PDF</button>
    <button id="casenotesout">Export notes</button> <label class="filebtn">Import notes <input id="casenotesin" type="file" accept="application/json,.json" hidden></label></div>
    <div id="casestatus" class="note" role="status"></div></details>`);
  $("casebtn").onclick = () => { $("casetray").open = true; caseRefresh(); };
  $("casetray").addEventListener("toggle", caseRefresh);
  $("casecsv").onclick = caseRun(caseCSV); $("caseprint").onclick = caseRun(casePrint);
  $("casenotesout").onclick = caseExportNotes;
  $("casenotesin").onchange = ev => { if (ev.target.files[0]) caseImportNotes(ev.target.files[0]); ev.target.value = ""; };
  document.addEventListener("click", ev => {
    const t = ev.target.closest("[data-case-toggle]");
    if (t) { ev.preventDefault(); caseToggle(t.dataset.caseToggle); return; }
    const o = ev.target.closest("[data-case-open]");
    if (o) location.hash = o.dataset.caseOpen;
  });
  $("casebody").addEventListener("input", ev => {
    const item = ev.target.closest("[data-case-item]");
    if (!item) return;
    const id = item.dataset.caseItem, note = caseNotes[id] ||= {};
    if (ev.target.matches("[data-case-mark]")) note.mark = ev.target.value;
    if (ev.target.matches("[data-case-note]")) note.note = ev.target.value;
    caseSave();
  });
  caseRefresh();
});
