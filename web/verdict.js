// Otherwise — verdict page.
import {
  apiGet, fmtDate, fmtSignalValue, VERDICT_LABEL, VERDICT_VAR, CHANGE_TYPE_LABEL,
  SIGNAL_LABEL, REASON_LABEL, wireCopyLink, initHowItWorksDrawer, renderFooter,
} from "./common.js";
import { drawTrajectoryChart, drawGapChart } from "./chart.js";

const LIGHT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const LIGHT_ATTR = "&copy; OpenStreetMap contributors";

const contentEl = document.getElementById("content");

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/** Signal value with sign, using a proper Unicode minus (U+2212) for negatives. */
function fmtSigned(signal, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = fmtSignalValue(signal, value, { sign: true });
  return value < 0 ? s.replace("-", "−") : s;
}

function getRunId() {
  const parts = location.pathname.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

function showLoading() {
  contentEl.innerHTML = '<div class="loading-state">Loading verdict&hellip;</div>';
}

function show404() {
  contentEl.innerHTML = `
    <div class="error-state">
      <div class="verdict-word">No verdict with that id.</div>
      <p class="muted"><a href="/">Back to the map</a></p>
    </div>`;
}

function showGenericError(msg) {
  contentEl.innerHTML = `
    <div class="error-state">
      <div class="verdict-word">Could not load this verdict.</div>
      <p class="muted">${escapeHtml(msg || "")}</p>
    </div>`;
}

// ---- section builders ------------------------------------------------------

function renderStoryImagery(d) {
  const im = d.imagery || {};
  if (!im.before && !im.after) {
    return `<div class="story-imagery-empty">No clear Sentinel-2 scene within 120 days on either side of the event</div>`;
  }
  return `
    <div class="imagery-grid">
      ${im.before ? `<figure><img src="${im.before.url}" alt="Before the event" loading="lazy"><figcaption>Before · ${fmtDate(im.before.date)}</figcaption></figure>` : ""}
      ${im.after ? `<figure><img src="${im.after.url}" alt="After the event" loading="lazy"><figcaption>After · ${fmtDate(im.after.date)}</figcaption></figure>` : ""}
    </div>
    <div class="chart-caption">The white outline in the image is the drawn area.</div>`;
}

function renderWhatChanged(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const status = d.verdict.status;
  return `
    <div class="story-section">
      <div class="label">What changed</div>
      <div class="story-number tnum v-${status}">${fmtSigned(lead, sig.point)}</div>
      <div class="story-number-sub muted">${escapeHtml(SIGNAL_LABEL[lead] || lead)} relative to the no-event trajectory, ${d.post_months} months after the event</div>
      <div class="story-number-sub muted tnum">90% interval ${fmtSigned(lead, sig.lo)} to ${fmtSigned(lead, sig.hi)}</div>
    </div>`;
}

function renderHowSure(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const chart = d.charts[lead];
  const k = Math.max(0, Math.round(sig.placebo_p * (sig.placebo_n + 1)) - 1);
  const timePlacebos = (chart && chart.time_placebos) || [];
  const nFlagged = timePlacebos.filter((tp) => tp.flagged).length;
  const lines = [`Placebo: ${k} of ${sig.placebo_n} untouched cells showed a gap this large (p = ${sig.placebo_p.toFixed(3)})`];
  if (timePlacebos.length) {
    lines.push(`Fake dates before the event: ${nFlagged} of ${timePlacebos.length} false alarms`);
  }
  lines.push(`${sig.n_pre} clear observation periods before, ${sig.n_post} after; ${sig.n_donors} control cells`);
  radarSignals(d).forEach(([rk, rv]) => {
    lines.push(`Radar (${rk}): ${fmtSigned(rk, rv.point)}, interval ${fmtSigned(rk, rv.lo)} to ${fmtSigned(rk, rv.hi)}`);
  });
  return `
    <div class="story-section">
      <div class="label">How sure</div>
      <div class="story-lines tnum">${lines.map((l) => `<div>${escapeHtml(l)}</div>`).join("")}</div>
    </div>`;
}

function renderStoryVerdict(d) {
  const status = d.verdict.status;
  const statusLabel = VERDICT_LABEL[status] || status;
  let reasonsHtml = "";
  if (status === "CANT_TELL" && d.verdict.reasons && d.verdict.reasons.length) {
    reasonsHtml = `
      <div class="reasons-why">
        <div class="label">Why not decisive</div>
        <ul>${d.verdict.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
      </div>`;
  }
  return `
    <div class="story-section">
      <div class="label">Verdict</div>
      <div class="story-verdict-word v-${status}">${statusLabel}</div>
      <p class="statement">${escapeHtml(d.verdict.statement)}</p>
      ${reasonsHtml}
    </div>`;
}

function renderStoryHero(d) {
  const parts = [CHANGE_TYPE_LABEL[d.change_type] || d.change_type, fmtDate(d.event_date), `${d.area.ha} ha`];
  if (d.area.landcover) parts.push(d.area.landcover);
  return `
    <section class="story-hero">
      <div class="label">${parts.map(escapeHtml).join(" · ")}</div>
      <div class="story-title">${escapeHtml(d.label || "Drawn area")}</div>
      <div class="story-grid">
        <div class="story-imagery">${renderStoryImagery(d)}</div>
        <div class="story-summary">
          ${renderWhatChanged(d)}
          ${renderHowSure(d)}
          ${renderStoryVerdict(d)}
        </div>
      </div>
      <div class="story-caption muted">The images show what a person would see; the number is how much more the area changed than its matched controls; the verdict is whether that difference survives the placebo checks.</div>
    </section>`;
}

function renderChartsSection(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  return `
    <section class="block">
      <div class="label">Actual vs. no-event trajectory</div>
      <div class="chart-block" style="margin-top:14px;">
        <div class="chart-wrap" id="main-chart"></div>
        <div class="chart-legend">
          <span><span class="swatch" style="border-color:var(--treated)"></span>Area</span>
          <span><span class="swatch dashed" style="border-color:var(--counter)"></span>What it would have done anyway (counterfactual)</span>
          <span><span class="swatch band"></span>Range of 90% of placebo cells</span>
        </div>
        <div class="chart-caption tnum">${sig.n_pre} observation periods before the event, ${sig.n_post} after; ${sig.n_donors} control cells; bins of ${d.method.bin_days} days.</div>
      </div>
      <div class="chart-block">
        <h3>Gap between actual and counterfactual</h3>
        <div class="chart-wrap" id="gap-chart"></div>
      </div>
    </section>`;
}

function tickSVG(cx, cy, color, label) {
  let s = `<line x1="${cx}" y1="${cy - 6}" x2="${cx}" y2="${cy + 6}" stroke="${color}" stroke-width="1"/>`;
  if (label !== undefined) s += `<text x="${cx}" y="${cy + 19}" text-anchor="middle" font-size="10" fill="${color}">${label}</text>`;
  return s;
}

function numberLineSVG(width, { lo, hi, point, minEffect, status }) {
  const height = 56;
  const mx = 14;
  const vals = [lo, hi, point, -minEffect, minEffect, 0];
  let dMin = Math.min(...vals), dMax = Math.max(...vals);
  const pad = (dMax - dMin) * 0.15 || 0.1;
  dMin -= pad; dMax += pad;
  const x = (v) => mx + ((v - dMin) / (dMax - dMin)) * (width - 2 * mx);
  const axisY = height / 2 - 4;
  const color = `var(${VERDICT_VAR[status]})`;
  let s = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
  s += `<line x1="${mx}" y1="${axisY}" x2="${width - mx}" y2="${axisY}" stroke="var(--rule)" stroke-width="1"/>`;
  s += tickSVG(x(0), axisY, "var(--muted)", "0");
  s += tickSVG(x(-minEffect), axisY, "var(--muted)");
  s += tickSVG(x(minEffect), axisY, "var(--muted)");
  s += `<line x1="${x(lo)}" y1="${axisY}" x2="${x(hi)}" y2="${axisY}" stroke="${color}" stroke-width="4" stroke-linecap="round"/>`;
  s += `<circle cx="${x(point)}" cy="${axisY}" r="5" fill="${color}"/>`;
  s += "</svg>";
  return s;
}

function stripPlotSVG(width, effects, point, status) {
  const height = 44;
  const mx = 12;
  const all = [...effects, point, 0];
  let dMin = Math.min(...all), dMax = Math.max(...all);
  const pad = (dMax - dMin) * 0.12 || 0.1;
  dMin -= pad; dMax += pad;
  const x = (v) => mx + ((v - dMin) / (dMax - dMin)) * (width - 2 * mx);
  const y = height / 2;
  let s = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`;
  s += `<line x1="${mx}" y1="${y}" x2="${width - mx}" y2="${y}" stroke="var(--rule)" stroke-width="1"/>`;
  s += `<line x1="${x(0)}" y1="${y - 11}" x2="${x(0)}" y2="${y + 11}" stroke="var(--muted)" stroke-width="1"/>`;
  effects.forEach((v) => {
    s += `<line x1="${x(v)}" y1="${y - 5}" x2="${x(v)}" y2="${y + 5}" stroke="var(--muted)" stroke-width="1.2" opacity="0.55"/>`;
  });
  s += `<circle cx="${x(point)}" cy="${y}" r="5.5" fill="var(${VERDICT_VAR[status]})" stroke="var(--panel)" stroke-width="1"/>`;
  s += "</svg>";
  return s;
}

function renderEffectBlock(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const status = d.verdict.status;
  return `
    <div class="evidence-block rule-top">
      <div class="label">Effect</div>
      <div class="effect-number tnum v-${status}">${fmtSignalValue(lead, sig.point, { sign: true })}</div>
      <div class="effect-sub tnum">90% interval ${fmtSignalValue(lead, sig.lo, { sign: true })} to ${fmtSignalValue(lead, sig.hi, { sign: true })}</div>
      <div class="effect-sub tnum">smallest change we call meaningful: ${fmtSignalValue(lead, sig.min_effect)}</div>
      <div class="numberline-wrap" id="effect-numberline"></div>
    </div>`;
}

function renderPlaceboBlock(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const chart = d.charts[lead];
  const k = Math.max(0, Math.round(sig.placebo_p * (sig.placebo_n + 1)) - 1);
  const timePlacebos = chart.time_placebos || [];
  return `
    <div class="evidence-block rule-top">
      <div class="label">Placebo check</div>
      <p class="placebo-sentence">The same test was run on ${sig.placebo_n} untouched control cells as if each were the area. ${k} produced a gap at least this large (placebo p = ${sig.placebo_p.toFixed(3)}).</p>
      <div id="placebo-strip"></div>
      ${timePlacebos.length ? `
      <div class="fake-dates">
        <div class="label">Fake event dates</div>
        <ul>${timePlacebos.map((tp) => `<li>${fmtDate(tp.date)}: gap ${fmtSignalValue(lead, tp.effect, { sign: true })} (interval ${fmtSignalValue(lead, tp.lo, { sign: true })} to ${fmtSignalValue(lead, tp.hi, { sign: true })}) — <span class="${tp.flagged ? "false-alarm" : ""}">${tp.flagged ? "false alarm" : "no effect found"}</span></li>`).join("")}</ul>
      </div>` : ""}
    </div>`;
}

function radarSignals(d) {
  return Object.entries(d.signals).filter(([, v]) => v.sensor === "S1");
}

function renderRadarBlock(d) {
  const rs = radarSignals(d);
  if (!rs.length) return "";
  const rows = rs.map(([k, v]) => `
    <div class="radar-row">
      <div class="rlabel">${SIGNAL_LABEL[k] || k}</div>
      <div class="tnum muted">${fmtSignalValue(k, v.point, { sign: true })} · interval ${fmtSignalValue(k, v.lo, { sign: true })} to ${fmtSignalValue(k, v.hi, { sign: true })} · n=${v.n_post}</div>
    </div>`).join("");
  return `
    <div class="evidence-block rule-top">
      <div class="label">Radar corroboration</div>
      ${rows}
      <p class="muted small" style="margin-top:8px;">Radar sees structure and moisture, not colour, and is not blocked by cloud.</p>
    </div>`;
}

function renderControlCellsBlock(d) {
  const lead = d.verdict.lead_signal;
  const donors = d.donors[lead];
  const notes = (donors.notes || []).join("; ");
  return `
    <div class="evidence-block rule-top">
      <div class="label">Control cells</div>
      <div id="control-map"></div>
      <div class="map-caption">${escapeHtml(notes)}. ${donors.counts.kept} of ${donors.counts.grid} cells used.</div>
    </div>`;
}

function renderEvidenceSection(d) {
  const radar = renderRadarBlock(d);
  return `
    <section class="block">
      <div class="grid-2">
        <div>${renderEffectBlock(d)}</div>
        <div>${renderPlaceboBlock(d)}</div>
        ${radar ? `<div>${radar}</div>` : ""}
        <div>${renderControlCellsBlock(d)}</div>
      </div>
    </section>`;
}

function renderReceiptsSection(d) {
  const ds = d.data_summary || {};
  const summaryLine = `${ds.s2_observations ?? 0} clear Sentinel-2 observations kept out of ${ds.s2_scenes_covering ?? 0} scenes; ${ds.s1_observations ?? 0} Sentinel-1 passes on orbit ${ds.s1_orbit ?? "—"}.`;
  const groups = {};
  (d.receipts || []).forEach((r) => { (groups[r.reason] = groups[r.reason] || []).push(r); });
  const order = ["cloud", "haze", "duplicate", "orbit", "edge", "read-error"];
  const groupsHtml = order.filter((k) => groups[k] && groups[k].length).map((k) => {
    const all = groups[k];
    const rows = all.slice(0, 200);
    const more = all.length > 200 ? `<div class="receipt-more">…and ${all.length - 200} more</div>` : "";
    return `
      <details class="receipt-group">
        <summary>${REASON_LABEL[k] || k} (${all.length})</summary>
        <table class="receipts-table">
          <thead><tr><th>Date</th><th>Sensor</th><th>Reason</th><th>Detail</th></tr></thead>
          <tbody>${rows.map((r) => `<tr><td class="tnum">${fmtDate(r.date)}</td><td>${escapeHtml(r.sensor)}</td><td>${REASON_LABEL[r.reason] || r.reason}</td><td>${escapeHtml(r.detail || "")}</td></tr>`).join("")}</tbody>
        </table>
        ${more}
      </details>`;
  }).join("");
  return `
    <section class="block">
      <div class="label">Receipts: observations thrown out</div>
      <p class="receipts-summary tnum">${summaryLine}</p>
      ${groupsHtml || '<p class="muted small">No observations were thrown out.</p>'}
    </section>`;
}

function renderMethodSection(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  return `
    <section class="block">
      <div class="label">Method</div>
      <div class="method-lines">
        <div>${escapeHtml(d.method.estimator)}</div>
        <div>${escapeHtml(d.method.interval)}</div>
        <p>Counterfactual: augmented synthetic control on ${sig.n_donors} control cells chosen by land cover, terrain and pre-event similarity. Uncertainty: conformal inference (block permutations of the post-event residuals).</p>
      </div>
      <div class="method-links">
        <a href="#" data-drawer-trigger>How this works</a>
        <a href="https://github.com/oballinger/PWTT" target="_blank" rel="noopener">PWTT</a>
        <a href="https://github.com/quantifyearth/tmf-implementation" target="_blank" rel="noopener">4C PACT</a>
        <a href="https://github.com/epingchris/placebo_evaluation" target="_blank" rel="noopener">Placebo evaluation</a>
      </div>
      <div class="run-stats tnum">Run ${escapeHtml(d.id)} · computed ${fmtDate(d.created)} · ${d.timing.run_s} s</div>
    </section>`;
}

// ---- control cells map -------------------------------------------------------

function initControlMap(d) {
  const el = document.getElementById("control-map");
  if (!el || typeof L === "undefined") return;
  const lead = d.verdict.lead_signal;
  const donors = d.donors[lead];
  const cells = d.donors.cells || [];
  const usedWeight = new Map();
  (donors.grid_index || []).forEach((idx, i) => usedWeight.set(idx, donors.weights[i]));
  const maxW = Math.max(...(donors.weights && donors.weights.length ? donors.weights : [1]));

  const map = L.map(el, { zoomControl: false, attributionControl: true, scrollWheelZoom: false, dragging: !L.Browser.mobile });
  L.tileLayer(LIGHT_TILES, { attribution: LIGHT_ATTR, subdomains: "abcd", maxZoom: 19 }).addTo(map);

  const bounds = L.latLngBounds([]);
  cells.forEach((geom, idx) => {
    const used = usedWeight.has(idx);
    const layer = L.geoJSON(geom, {
      style: used
        ? { color: "var(--counter)", weight: 1, opacity: 0.5, fillColor: "var(--counter)", fillOpacity: Math.min(0.7, Math.max(0.08, 0.08 + 0.62 * (usedWeight.get(idx) / (maxW || 1)))) }
        : { color: "var(--rule)", weight: 1, fillOpacity: 0 },
    }).addTo(map);
    bounds.extend(layer.getBounds());
  });

  const areaLayer = L.geoJSON(d.area.geojson, { style: { color: "var(--ink)", weight: 2, fillOpacity: 0 } }).addTo(map);
  bounds.extend(areaLayer.getBounds());
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [12, 12] });
}

// ---- top-level render -------------------------------------------------------

function render(d) {
  document.title = (d.label ? `${d.label} — ` : "") + "Otherwise";
  document.getElementById("copy-link-btn").style.display = "inline-block";

  contentEl.innerHTML =
    renderStoryHero(d) +
    renderChartsSection(d) +
    renderEvidenceSection(d) +
    renderReceiptsSection(d) +
    renderMethodSection(d);

  const lead = d.verdict.lead_signal;
  const chart = d.charts[lead];
  const sig = d.signals[lead];

  function drawCharts() {
    drawTrajectoryChart(document.getElementById("main-chart"), chart, { eventDate: d.event_date, signal: lead });
    drawGapChart(document.getElementById("gap-chart"), chart, { eventDate: d.event_date, signal: lead });
  }
  drawCharts();
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawCharts, 150);
  });

  const nlWrap = document.getElementById("effect-numberline");
  if (nlWrap) {
    nlWrap.innerHTML = numberLineSVG(nlWrap.clientWidth || 360, {
      lo: sig.lo, hi: sig.hi, point: sig.point, minEffect: sig.min_effect, status: d.verdict.status,
    });
  }
  const stripWrap = document.getElementById("placebo-strip");
  if (stripWrap) {
    stripWrap.innerHTML = stripPlotSVG(stripWrap.clientWidth || 360, chart.placebo_effects || [], sig.point, d.verdict.status);
  }

  initControlMap(d);
  wireCopyLink(document.getElementById("copy-link-btn"));
  initHowItWorksDrawer();
  renderFooter(document.getElementById("site-footer"), { withHowItWorks: false });
}

// ---- boot --------------------------------------------------------------------

async function boot() {
  showLoading();
  const id = getRunId();
  try {
    const data = await apiGet(`/api/runs/${id}`);
    render(data);
  } catch (err) {
    if (err.status === 404) show404();
    else showGenericError(err.message);
  }
}

boot();
