// Otherwise — batch page: submit a FeatureCollection, poll status, link reports.
import {
  apiGet, apiPost, fmtSignalValue, VERDICT_LABEL, renderFooter,
} from "./common.js";

const POLL_MS = 3000;

const form = document.getElementById("batch-form");
const fileInput = document.getElementById("f-file");
const pasteInput = document.getElementById("f-paste");
const changeTypeInput = document.getElementById("f-change-type");
const eventDateInput = document.getElementById("f-event-date");
const postMonthsInput = document.getElementById("f-post-months");
const submitBtn = document.getElementById("submit-btn");
const errorEl = document.getElementById("batch-error");
const resultEl = document.getElementById("batch-result");
const tbody = document.getElementById("batch-tbody");
const dlBatchReport = document.getElementById("dl-batch-report");

let pollTimer = null;
const runCache = new Map(); // run_id -> run json (fetched once done)

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function readFeatures() {
  let text = (pasteInput.value || "").trim();
  if (!text && fileInput.files && fileInput.files[0]) {
    text = await fileInput.files[0].text();
  }
  if (!text) throw new Error("Choose a file or paste a FeatureCollection.");
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    throw new Error("That is not valid JSON.");
  }
  const features = parsed.type === "FeatureCollection" ? parsed.features
    : Array.isArray(parsed) ? parsed
    : parsed.type === "Feature" ? [parsed]
    : null;
  if (!Array.isArray(features) || features.length === 0) {
    throw new Error("No features found. Expected a GeoJSON FeatureCollection.");
  }
  return features;
}

function statusLabel(item) {
  if (item.error) return "error";
  if (item.status === "done" || item.done) return "done";
  if (item.status === "running") return item.stage ? `running — ${item.stage}` : "running";
  if (item.status === "queued") return "queued";
  return item.status || "pending";
}

function linksCell(item) {
  if (!item.run_id) return '<span class="muted">—</span>';
  const rid = encodeURIComponent(item.run_id);
  const parts = [`<a href="/v/${rid}">verdict</a>`];
  if (item.status === "done" || item.done) {
    parts.push(`<a href="/api/runs/${rid}/report.md">report.md</a>`);
    parts.push(`<a href="/api/runs/${rid}/run.json">run.json</a>`);
  }
  return parts.join("");
}

async function verdictCells(item) {
  if (item.error) return { verdictHtml: `<span class="v-NOT_REAL">error</span>`, effect: "—" };
  if (item.status !== "done" && !item.done) return { verdictHtml: '<span class="muted">—</span>', effect: "—" };
  if (!item.run_id) return { verdictHtml: '<span class="muted">—</span>', effect: "—" };
  let run = runCache.get(item.run_id);
  if (!run) {
    try {
      run = await apiGet(`/api/runs/${encodeURIComponent(item.run_id)}`);
      runCache.set(item.run_id, run);
    } catch (e) {
      return { verdictHtml: '<span class="muted">—</span>', effect: "—" };
    }
  }
  const v = run.verdict || {};
  const label = VERDICT_LABEL[v.status] || v.status || "—";
  const verdictHtml = `<span class="v-${v.status}">${escapeHtml(label)}</span>`;
  const lead = v.lead_signal;
  const sig = lead && run.signals ? run.signals[lead] : null;
  const effect = sig
    ? `${fmtSignalValue(lead, sig.point, { sign: true })} (${fmtSignalValue(lead, sig.lo, { sign: true })} to ${fmtSignalValue(lead, sig.hi, { sign: true })})`
    : "—";
  return { verdictHtml, effect };
}

async function renderRows(items) {
  const rows = await Promise.all(items.map(async (item) => {
    const { verdictHtml, effect } = await verdictCells(item);
    const stageClass = item.error ? " stage-error" : "";
    return `
      <tr>
        <td>${escapeHtml(item.label || `Feature ${item.index}`)}</td>
        <td class="status-cell${stageClass}">${escapeHtml(item.error || statusLabel(item))}</td>
        <td>${verdictHtml}</td>
        <td class="tnum">${effect}</td>
        <td class="links-cell">${linksCell(item)}</td>
      </tr>`;
  }));
  tbody.innerHTML = rows.join("");
}

function allSettled(items) {
  return items.every((it) => it.error || it.status === "done" || it.done);
}

async function poll(batchId) {
  let data;
  try {
    data = await apiGet(`/api/batch/${encodeURIComponent(batchId)}`);
  } catch (e) {
    return;
  }
  await renderRows(data.items);
  if (allSettled(data.items)) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.textContent = "";
  submitBtn.disabled = true;
  try {
    const features = await readFeatures();
    const body = {
      features,
      default_change_type: changeTypeInput.value,
      default_post_months: Number(postMonthsInput.value),
    };
    if (eventDateInput.value) body.default_event_date = eventDateInput.value;
    const data = await apiPost("/api/batch", body);
    runCache.clear();
    resultEl.style.display = "";
    dlBatchReport.href = `/api/batch/${encodeURIComponent(data.batch_id)}/report.md`;
    await renderRows(data.items);
    if (pollTimer) clearInterval(pollTimer);
    if (!allSettled(data.items)) {
      pollTimer = setInterval(() => poll(data.batch_id), POLL_MS);
    }
  } catch (err) {
    errorEl.textContent = err.message || "Could not run the batch.";
  } finally {
    submitBtn.disabled = false;
  }
});

renderFooter(document.getElementById("site-footer"), { withHowItWorks: false });
