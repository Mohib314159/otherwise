// Otherwise — track record page.
import {
  apiGet, fmtSignalValue, VERDICT_LABEL, SIGNAL_LABEL, CHANGE_TYPE_LABEL, initHowItWorksDrawer, renderFooter,
} from "./common.js";

const contentEl = document.getElementById("content");

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function summaryLine(summary) {
  const parts = [];
  if (summary.n !== undefined) parts.push(`${summary.n} sites`);
  if (summary.hits !== undefined) parts.push(`${summary.hits} correct`);
  if (summary.false_alarms !== undefined) parts.push(`${summary.false_alarms} false alarms`);
  if (summary.cant_tell !== undefined) parts.push(`${summary.cant_tell} can't tell`);
  return parts.join(" · ");
}

function renderRow(r) {
  const statusLabel = VERDICT_LABEL[r.status] || r.status || "—";
  const effect = (r.effect !== undefined && r.effect !== null && r.signal)
    ? `${fmtSignalValue(r.signal, r.effect, { sign: true })}${r.lo !== undefined && r.hi !== undefined ? ` (${fmtSignalValue(r.signal, r.lo, { sign: true })} to ${fmtSignalValue(r.signal, r.hi, { sign: true })})` : ""}`
    : "—";
  return `
    <tr>
      <td><a href="/v/${encodeURIComponent(r.id)}">${escapeHtml(r.label || r.id)}</a></td>
      <td>${escapeHtml(CHANGE_TYPE_LABEL[r.type] || r.type || "—")}</td>
      <td>${escapeHtml(r.expected || "—")}</td>
      <td class="verdict-cell v-${r.status}">${statusLabel}</td>
      <td class="tnum">${effect}</td>
      <td>${escapeHtml(r.signal ? (SIGNAL_LABEL[r.signal] || r.signal) : "—")}</td>
      <td>${r.source ? `<a href="${escapeHtml(r.source)}" target="_blank" rel="noopener">source</a>` : "—"}</td>
    </tr>`;
}

async function boot() {
  let data;
  try {
    data = await apiGet("/api/track-record");
  } catch (err) {
    contentEl.innerHTML = `<div class="error-state"><p class="muted">Could not load the track record.</p></div>`;
    return;
  }

  if (!data.summary) {
    contentEl.innerHTML = `
      <section class="page-head">
        <h1>Track record</h1>
        <p>No validation runs yet.</p>
      </section>`;
  } else {
    const rows = (data.runs || []).map(renderRow).join("");
    contentEl.innerHTML = `
      <section class="page-head">
        <h1>Track record</h1>
        <p>Every known-answer site the tool has been run on, misses included. Expected answers come from the documented sources linked in each row.</p>
        <div class="summary-line tnum">${summaryLine(data.summary)}</div>
      </section>
      <div class="table-wrap">
        <table class="track-table">
          <thead>
            <tr><th>Site</th><th>Type</th><th>Expected</th><th>Verdict</th><th>Effect</th><th>Signal</th><th>Source</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  initHowItWorksDrawer();
  renderFooter(document.getElementById("site-footer"), { withHowItWorks: true });
}

boot();
