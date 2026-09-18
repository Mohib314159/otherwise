// Otherwise — verdict page: one calm story in four acts.
//
// Data: GET /api/runs/<id>. Fields used here:
//   id, label, change_type, event_date, post_months, created, window
//   area: { ha, landcover, elevation_m, lat, lon, geojson }
//   imagery: { before: {url, date, clear}, after: {...} }        (optional)
//   verdict: { status: REAL|NOT_REAL|CANT_TELL, headline, statement, reasons[], lead_signal }
//   signals: { <sig>: { point, lo, hi, min_effect, n_pre, n_post, n_donors,
//                       placebo_n, placebo_p, sensor: S1|S2, ... } }
//   charts:  { <sig>: { dates[], treated[], counterfactual[], effect[], n_obs[],
//                       placebo_band: [lo[], hi[]], placebo_effects[], time_placebos[] } }
//   donors:  { <sig>: { grid_index[], weights[], counts, notes[] }, cells[] }
//   receipts[], data_summary, method, timing
//   evidence: { agreement, optical, radar, p_combined, sentence }  (optional, later)
//   pixels:   { fraction_changed, placebo_p, map: url }            (optional, later)
import {
  apiGet, fmtDate, fmtSignalValue, VERDICT_LABEL, VERDICT_VAR, CHANGE_TYPE_LABEL,
  SIGNAL_LABEL, REASON_LABEL, wireCopyLink, initHowItWorksDrawer, renderFooter,
} from "./common.js";
import { drawTrajectoryChart, drawGapChart, stripPlotSVG } from "./chart.js";

const LIGHT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const LIGHT_ATTR = "&copy; OpenStreetMap contributors";
const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

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
  if (/^[-+]0(\.0+)?( dB)?$/.test(s)) return s.slice(1); // rounds to zero: no sign
  return value < 0 ? s.replace("-", "−") : s;
}

/** Number only (no unit) for the big figure; unit rendered separately. */
function fmtBare(signal, value) {
  return fmtSigned(signal, value).replace(/\s*dB$/, "");
}

function unitFor(signal) {
  return ["VV", "VH", "RATIO"].includes(signal) ? "dB" : signal;
}

function headlineFor(d) {
  return d.verdict.headline || VERDICT_LABEL[d.verdict.status] || d.verdict.status;
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

// ---- act 1: what we saw ------------------------------------------------------

const HANDLE_SVG = `<svg width="14" height="10" viewBox="0 0 14 10" fill="none" stroke="rgba(255,255,255,0.95)" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 1 1 5l3 4M10 1l3 4-3 4"/></svg>`;

function renderCompare(d) {
  const im = d.imagery || {};
  const px = d.pixels || {};
  if (!im.before && !im.after) {
    return `<div class="compare-empty">No clear Sentinel-2 scene within 120 days on either side of the event</div>`;
  }
  if (!im.before || !im.after) {
    const one = im.before || im.after;
    const which = im.before ? "Before" : "After";
    return `
      <div class="compare-single">
        <img src="${escapeHtml(one.url)}" alt="${which} the event" decoding="async">
        <span class="compare-tag before">${which} · ${fmtDate(one.date)}</span>
      </div>`;
  }
  return `
    <div class="compare" id="compare" tabindex="0" role="slider" aria-label="Before and after comparison; drag or use arrow keys"
         aria-valuemin="0" aria-valuemax="100" aria-valuenow="50" aria-valuetext="Showing half before, half after">
      <div class="compare-layer compare-after"><img src="${escapeHtml(im.after.url)}" alt="After the event, ${fmtDate(im.after.date)}" decoding="async"></div>
      ${px.map ? `<div class="compare-layer compare-map"><img src="${escapeHtml(px.map)}" alt="Change map over the after image" decoding="async"></div>` : ""}
      <div class="compare-layer compare-before" id="compare-before"><img src="${escapeHtml(im.before.url)}" alt="Before the event, ${fmtDate(im.before.date)}" decoding="async"></div>
      <div class="compare-divider" id="compare-divider"><div class="compare-handle">${HANDLE_SVG}</div></div>
      <span class="compare-tag before">Before · ${fmtDate(im.before.date)}</span>
      <span class="compare-tag after">After · ${fmtDate(im.after.date)}</span>
      ${px.map ? `<button type="button" class="compare-toggle" id="compare-map-toggle" aria-pressed="false">Change map</button>` : ""}
    </div>`;
}

function claimLine(d) {
  const parts = [CHANGE_TYPE_LABEL[d.change_type] || d.change_type, fmtDate(d.event_date), `${d.area.ha} ha`];
  if (d.area.landcover) parts.push(d.area.landcover);
  return parts.map(escapeHtml).join(" · ");
}

function renderAct1(d) {
  const px = d.pixels || {};
  const pixelLine = (Number.isFinite(px.fraction_changed) && Number.isFinite(px.placebo_p))
    ? `<div class="act1-hint tnum">Pixel by pixel: ${(px.fraction_changed * 100).toFixed(0)}% of the area changed more than its own history would predict (placebo p = ${px.placebo_p.toFixed(3)}).</div>`
    : "";
  return `
    <section class="act reveal" id="act-1">
      <div class="label"><span class="act-n">1</span>What we saw</div>
      ${renderCompare(d)}
      <div id="lapse-mount"></div>
      <p class="act1-title">${escapeHtml(d.label || "Drawn area")}</p>
      <p class="act1-claim tnum">${claimLine(d)}</p>
      <div class="act1-hint">The white outline is the drawn area.${(d.imagery && d.imagery.before && d.imagery.after) ? " Drag the divider to compare." : ""}</div>
      ${pixelLine}
    </section>`;
}

function initCompare() {
  const el = document.getElementById("compare");
  if (!el) return;
  const before = document.getElementById("compare-before");
  const divider = document.getElementById("compare-divider");
  let pct = 50;

  function set(p, { animate = false } = {}) {
    pct = Math.max(0, Math.min(100, p));
    const t = animate && !REDUCED ? "clip-path 0.2s ease-out" : "none";
    before.style.transition = t;
    divider.style.transition = animate && !REDUCED ? "left 0.2s ease-out" : "none";
    before.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
    divider.style.left = `${pct}%`;
    el.setAttribute("aria-valuenow", Math.round(pct));
    el.setAttribute("aria-valuetext", `${Math.round(pct)}% before, ${Math.round(100 - pct)}% after`);
  }
  set(50);

  let dragging = false;
  const fromEvent = (e) => {
    const r = el.getBoundingClientRect();
    return ((e.clientX - r.left) / r.width) * 100;
  };
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest && e.target.closest(".compare-toggle")) return;
    dragging = true;
    el.setPointerCapture(e.pointerId);
    set(fromEvent(e));
    e.preventDefault();
  });
  el.addEventListener("pointermove", (e) => { if (dragging) set(fromEvent(e)); });
  const stop = () => { dragging = false; };
  el.addEventListener("pointerup", stop);
  el.addEventListener("pointercancel", stop);
  el.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 10 : 2;
    if (e.key === "ArrowLeft") { set(pct - step, { animate: true }); e.preventDefault(); }
    else if (e.key === "ArrowRight") { set(pct + step, { animate: true }); e.preventDefault(); }
    else if (e.key === "Home") { set(0, { animate: true }); e.preventDefault(); }
    else if (e.key === "End") { set(100, { animate: true }); e.preventDefault(); }
  });

  el.querySelectorAll("img").forEach((img) => {
    const mark = () => img.classList.add("loaded");
    if (img.complete && img.naturalWidth) mark(); else img.addEventListener("load", mark);
    img.addEventListener("error", mark);
  });

  const toggle = document.getElementById("compare-map-toggle");
  if (toggle) {
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const on = toggle.getAttribute("aria-pressed") !== "true";
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
      el.classList.toggle("map-on", on);
    });
  }
  // expose for tests
  el.__setCompare = set;
}

// ---- act 1b: time-lapse scrubber (only if /api/runs/<id>/frames answers) -------

/**
 * A row of dates under the slider. Clicking or dragging along it swaps the
 * right-hand (after) image for that frame, so any scene can be compared with
 * the fixed "before" scene on the left. Quietly does nothing when the
 * endpoint 404s or returns fewer than two frames.
 */
async function initLapse(d) {
  const mount = document.getElementById("lapse-mount");
  const compare = document.getElementById("compare");
  if (!mount || !compare) return;
  let frames;
  try {
    const res = await apiGet(`/api/runs/${encodeURIComponent(d.id)}/frames`);
    frames = Array.isArray(res) ? res : (res && Array.isArray(res.frames) ? res.frames : []);
  } catch (_) {
    return; // no frames for this run
  }
  frames = frames.filter((f) => f && f.url && f.date).sort((a, b) => (a.date < b.date ? -1 : 1));
  if (frames.length < 2) return;

  const afterLayer = compare.querySelector(".compare-after");
  const afterTag = compare.querySelector(".compare-tag.after");
  const afterDate = d.imagery && d.imagery.after ? d.imagery.after.date : null;
  const afterUrl = d.imagery && d.imagery.after ? d.imagery.after.url : null;
  const t0 = Date.parse(frames[0].date), t1 = Date.parse(frames[frames.length - 1].date);
  const span = Math.max(t1 - t0, 1);
  const pos = (iso) => Math.max(0, Math.min(100, ((Date.parse(iso) - t0) / span) * 100));
  const eventT = Date.parse(d.event_date);
  const eventInRange = eventT >= t0 && eventT <= t1;

  mount.innerHTML = `
    <div class="lapse">
      <div class="lapse-head"><span class="label" style="margin:0">Time-lapse</span><span class="lapse-hint muted">${frames.length} clear scenes. Click a date to show it on the right.</span></div>
      <div class="lapse-track" id="lapse-track" tabindex="0" role="slider" aria-label="Time-lapse scene"
           aria-valuemin="0" aria-valuemax="${frames.length - 1}" aria-valuenow="0">
        ${eventInRange ? `<span class="lapse-event" style="left:${pos(d.event_date).toFixed(2)}%" title="event · ${fmtDate(d.event_date)}"></span>` : ""}
        ${frames.map((f, i) => `<span class="lapse-frame${i === 0 ? " first" : i === frames.length - 1 ? " last" : ""}" data-i="${i}" style="left:${pos(f.date).toFixed(2)}%"><span class="lbl">${fmtDate(f.date)}</span></span>`).join("")}
      </div>
    </div>`;
  const track = document.getElementById("lapse-track");
  const ticks = Array.from(track.querySelectorAll(".lapse-frame"));
  let current = -1;

  function showFrame(i) {
    if (i === current) return;
    current = i;
    const f = frames[i];
    ticks.forEach((t, j) => t.classList.toggle("on", j === i));
    track.setAttribute("aria-valuenow", i);
    track.setAttribute("aria-valuetext", fmtDate(f.date));
    // double-buffer: fade the new scene in over the old one, then drop the old one
    const old = afterLayer.querySelector("img");
    const img = document.createElement("img");
    img.alt = `Scene from ${fmtDate(f.date)}`;
    img.decoding = "async";
    img.addEventListener("load", () => {
      img.classList.add("loaded");
      setTimeout(() => { if (old && old.parentNode === afterLayer && old !== img) old.remove(); }, REDUCED ? 0 : 320);
    });
    img.addEventListener("error", () => img.remove());
    img.src = f.url;
    afterLayer.appendChild(img);
    if (afterTag) {
      const isAfter = afterUrl && (f.url === afterUrl || f.date === afterDate);
      afterTag.textContent = isAfter ? `After · ${fmtDate(f.date)}` : `Scene · ${fmtDate(f.date)}`;
    }
  }
  // start on the frame that is already showing, when it is one of the frames
  const start = frames.findIndex((f) => f.url === afterUrl || f.date === afterDate);
  current = start; // already on screen; only mark it
  if (start >= 0) { ticks[start].classList.add("on"); track.setAttribute("aria-valuenow", start); }

  const nearest = (clientX) => {
    const r = track.getBoundingClientRect();
    const p = ((clientX - r.left) / r.width) * 100;
    let best = 0, dist = Infinity;
    frames.forEach((f, i) => { const dd = Math.abs(pos(f.date) - p); if (dd < dist) { dist = dd; best = i; } });
    return best;
  };
  let dragging = false;
  track.addEventListener("pointerdown", (e) => {
    dragging = true;
    track.setPointerCapture(e.pointerId);
    showFrame(nearest(e.clientX));
    e.preventDefault();
  });
  track.addEventListener("pointermove", (e) => { if (dragging) showFrame(nearest(e.clientX)); });
  const stop = () => { dragging = false; };
  track.addEventListener("pointerup", stop);
  track.addEventListener("pointercancel", stop);
  track.addEventListener("keydown", (e) => {
    const c = Math.max(current, 0);
    if (e.key === "ArrowLeft") { showFrame(Math.max(0, c - 1)); e.preventDefault(); }
    else if (e.key === "ArrowRight") { showFrame(Math.min(frames.length - 1, c + 1)); e.preventDefault(); }
    else if (e.key === "Home") { showFrame(0); e.preventDefault(); }
    else if (e.key === "End") { showFrame(frames.length - 1); e.preventDefault(); }
  });
  // warm the cache so scrubbing is instant
  frames.forEach((f) => { const im = new Image(); im.src = f.url; });
  track.__showFrame = showFrame; // for tests
}

// ---- act 2: what would have happened anyway ---------------------------------

function renderAct2(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  return `
    <section class="act reveal" id="act-2">
      <div class="label"><span class="act-n">2</span>What would have happened anyway</div>
      <p class="act-lede">The dashed line is the area's no-event trajectory, built from ${sig.n_donors} matched control cells.</p>
      <div class="chart-wrap" id="main-chart"></div>
      <div class="chart-legend">
        <span><span class="swatch" style="border-color:var(--treated)"></span>Area, ${escapeHtml(SIGNAL_LABEL[lead] || lead)}</span>
        <span><span class="swatch dashed" style="border-color:var(--counter)"></span>No-event trajectory</span>
        <span><span class="swatch band"></span>Where 90% of placebo cells fell</span>
      </div>
      <div class="chart-caption tnum">${sig.n_pre} clear observation periods before the event, ${sig.n_post} after; bins of ${d.method.bin_days} days.</div>
    </section>`;
}

// ---- act 3: the difference --------------------------------------------------

function renderAct3(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const status = d.verdict.status;
  return `
    <section class="act reveal" id="act-3">
      <div class="label"><span class="act-n">3</span>The difference</div>
      <div class="diff-grid">
        <div>
          <p class="act-lede">The gap between the area and its no-event trajectory. Zero means no difference from the controls.</p>
          <div class="chart-wrap" id="gap-chart"></div>
        </div>
        <div class="diff-side">
          <div class="big-number tnum v-${status}" id="big-number" data-final="${sig.point}" data-signal="${escapeHtml(lead)}">
            <span class="value">${fmtBare(lead, 0)}</span><span class="unit">${escapeHtml(unitFor(lead))}</span>
          </div>
          <div class="big-sub muted">${escapeHtml(SIGNAL_LABEL[lead] || lead)} relative to the no-event trajectory, ${d.post_months} months after the event</div>
          <div class="big-sub tnum">90% interval ${fmtSigned(lead, sig.lo)} to ${fmtSigned(lead, sig.hi)}</div>
          <div class="big-sub muted tnum">Smallest change we call meaningful: ${fmtSignalValue(lead, sig.min_effect)}</div>
        </div>
      </div>
    </section>`;
}

function countUp(el) {
  const lead = el.dataset.signal;
  const final = Number(el.dataset.final);
  const out = el.querySelector(".value");
  if (!Number.isFinite(final) || !out) return;
  if (REDUCED) { out.textContent = fmtBare(lead, final); return; }
  const dur = 600;
  const t0 = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - t0) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    out.textContent = fmtBare(lead, final * eased);
    if (t < 1) requestAnimationFrame(tick); else out.textContent = fmtBare(lead, final);
  };
  requestAnimationFrame(tick);
}

// ---- act 4: how sure --------------------------------------------------------

const FIXES = [
  [/observation period\(?s?\)? after/i, "wait for more clear scenes or extend the window"],
  [/observation periods? before/i, "extend the window"],
  [/does not track the area well enough before/i, "draw the area more tightly around one land-cover type"],
  [/control cells themselves shifted/i, "the event is larger than the control ring; use a wider control search"],
  [/usable control cells/i, "draw a larger or more typical area"],
  [/too wide/i, "more observations are needed; try a longer window"],
];

function fixesFor(reasons) {
  const out = [];
  reasons.forEach((r) => {
    for (const [re, advice] of FIXES) {
      if (re.test(r) && !out.includes(advice)) { out.push(advice); break; }
    }
  });
  return out;
}

function otherSignals(d) {
  return Object.entries(d.signals).filter(([k]) => k !== d.verdict.lead_signal);
}

function renderAct4(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const chart = d.charts[lead];
  const status = d.verdict.status;
  const k = Math.max(0, Math.round(sig.placebo_p * (sig.placebo_n + 1)) - 1);
  const timePlacebos = (chart && chart.time_placebos) || [];

  const placeboLine = `The same test was run on ${sig.placebo_n} untouched control cells as if each were the area. ${k} of ${sig.placebo_n} produced a gap at least this large (placebo p = ${sig.placebo_p.toFixed(3)}).`;
  const lines = [];
  otherSignals(d).forEach(([rk, rv]) => {
    const kind = rv.sensor === "S1" ? "Radar" : "Optical";
    const label = (SIGNAL_LABEL[rk] || rk).replace(/^radar /, "").replace(/ \(dB\)$/, "");
    lines.push(`${kind}, ${label}: ${fmtSigned(rk, rv.point)}, interval ${fmtSigned(rk, rv.lo)} to ${fmtSigned(rk, rv.hi)}, ${rv.n_post} observation period${rv.n_post === 1 ? "" : "s"} after the event.`);
  });
  if (d.evidence && d.evidence.sentence) lines.push(d.evidence.sentence);

  const fakeDates = timePlacebos.length ? `
    <div class="fake-dates">
      <div class="label">Fake event dates</div>
      <ul class="tnum">${timePlacebos.map((tp) => `<li><span>${fmtDate(tp.date)} · gap ${fmtSigned(lead, tp.effect)}, interval ${fmtSigned(lead, tp.lo)} to ${fmtSigned(lead, tp.hi)}</span><span class="${tp.flagged ? "false-alarm" : "muted"}">${tp.flagged ? "false alarm" : "no effect found"}</span></li>`).join("")}</ul>
    </div>` : "";

  const reasons = (d.verdict.reasons || []);
  let reasonsHtml = "";
  if (status === "CANT_TELL" && reasons.length) {
    const fixes = fixesFor(reasons);
    reasonsHtml = `
      <div class="reasons-why">
        <div class="label">Why not decisive</div>
        <ul>${reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
      </div>
      ${fixes.length ? `<p class="fix-line"><strong>What would fix it:</strong> ${escapeHtml(fixes.join("; "))}.</p>` : ""}`;
  }

  return `
    <section class="act reveal" id="act-4">
      <div class="label"><span class="act-n">4</span>How sure</div>
      <div class="sure-grid">
        <div>
          <div class="strip-wrap" id="placebo-strip"></div>
          <p class="sure-line tnum">${escapeHtml(placeboLine)}</p>
          ${fakeDates}
          ${lines.length ? `<div class="sure-lines tnum">${lines.map((l) => `<div>${escapeHtml(l)}</div>`).join("")}</div>` : ""}
        </div>
        <div class="verdict-block">
          <div class="label">Verdict</div>
          <div class="verdict-word v-${status}">${escapeHtml(headlineFor(d))}</div>
          <p class="statement">${escapeHtml(d.verdict.statement)}</p>
          ${reasonsHtml}
        </div>
      </div>
    </section>`;
}

// ---- receipts / method (as before) ------------------------------------------

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
    <section class="block reveal" id="receipts">
      <div class="label">Receipts: observations thrown out</div>
      <p class="receipts-summary tnum">${summaryLine}</p>
      ${groupsHtml || '<p class="muted small">No observations were thrown out.</p>'}
    </section>`;
}

function renderMethodSection(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const donors = d.donors && d.donors[lead];
  const notes = donors ? (donors.notes || []).join("; ") : "";
  const hasCells = donors && d.donors.cells && d.donors.cells.length;
  return `
    <section class="block reveal" id="method">
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
      ${hasCells ? `
      <div id="control-map" aria-label="Map of the control cells around the area"></div>
      <div class="map-caption">Control cells: ${escapeHtml(notes)}. ${donors.counts.kept} of ${donors.counts.grid} cells used; darker cells carry more weight.</div>` : ""}
      <div class="run-stats tnum">Run ${escapeHtml(d.id)} · computed ${fmtDate(d.created)} · ${d.timing.run_s} s</div>
    </section>`;
}

// ---- control cells map ------------------------------------------------------

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
  L.tileLayer(LIGHT_TILES, { attribution: LIGHT_ATTR, maxZoom: 19 }).addTo(map);

  const bounds = L.latLngBounds([]);
  cells.forEach((geom, idx) => {
    const used = usedWeight.has(idx);
    const layer = L.geoJSON(geom, {
      style: used
        ? { color: "#2b5fa8", weight: 1, opacity: 0.5, fillColor: "#2b5fa8", fillOpacity: Math.min(0.7, Math.max(0.08, 0.08 + 0.62 * (usedWeight.get(idx) / (maxW || 1)))) }
        : { color: "#dcd8ce", weight: 1, fillOpacity: 0 },
    }).addTo(map);
    bounds.extend(layer.getBounds());
  });

  const areaLayer = L.geoJSON(d.area.geojson, { style: { color: "#161616", weight: 2, fillOpacity: 0 } }).addTo(map);
  bounds.extend(areaLayer.getBounds());
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [12, 12], animate: false });
  setTimeout(() => map.invalidateSize({ animate: false }), 350);
}

// ---- sticky verdict pill ----------------------------------------------------

function initPill(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const status = d.verdict.status;
  const pill = document.createElement("button");
  pill.type = "button";
  pill.className = "verdict-pill tnum";
  pill.id = "verdict-pill";
  pill.setAttribute("aria-label", "Jump to the verdict");
  pill.innerHTML = `<span class="dot dot-${status}"></span><span class="v-${status}">${escapeHtml(headlineFor(d))}</span><span class="sep">·</span><span>${fmtSigned(lead, sig.point)}</span>`;
  document.body.appendChild(pill);
  pill.addEventListener("click", () => {
    const target = document.getElementById("act-4");
    if (target) target.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
  });

  const act1 = document.getElementById("act-1");
  if (!act1 || !("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      const past = !en.isIntersecting && en.boundingClientRect.bottom < 0;
      pill.classList.toggle("show", past);
    });
  }, { threshold: 0 });
  io.observe(act1);
}

// ---- scroll reveal ----------------------------------------------------------

function initReveal(onEnter) {
  const items = Array.from(document.querySelectorAll(".reveal"));
  if (!("IntersectionObserver" in window)) {
    items.forEach((el) => { el.classList.add("in"); onEnter(el); });
    return;
  }
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      en.target.classList.add("in");
      onEnter(en.target);
      io.unobserve(en.target);
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  items.forEach((el) => io.observe(el));
}

// ---- top-level render -------------------------------------------------------

function render(d) {
  document.title = (d.label ? `${d.label} — ` : "") + "Otherwise";
  document.getElementById("copy-link-btn").style.display = "inline-block";

  contentEl.innerHTML =
    renderAct1(d) +
    renderAct2(d) +
    renderAct3(d) +
    renderAct4(d) +
    renderReceiptsSection(d) +
    renderMethodSection(d);

  const lead = d.verdict.lead_signal;
  const chart = d.charts[lead];
  const sig = d.signals[lead];

  let mainChart = null;
  let mainRevealed = false;
  function drawCharts(animate) {
    mainChart = drawTrajectoryChart(document.getElementById("main-chart"), chart, { eventDate: d.event_date, signal: lead, animate });
    if (mainRevealed) mainChart.reveal();
    drawGapChart(document.getElementById("gap-chart"), chart, { eventDate: d.event_date, signal: lead });
    const stripWrap = document.getElementById("placebo-strip");
    if (stripWrap) {
      stripWrap.innerHTML = stripPlotSVG(stripWrap.clientWidth || 360, chart.placebo_effects || [], sig.point, VERDICT_VAR[d.verdict.status], lead);
    }
  }
  drawCharts(true);
  let resizeTimer;
  let lastW = window.innerWidth;
  window.addEventListener("resize", () => {
    if (window.innerWidth === lastW) return; // mobile URL-bar height changes
    lastW = window.innerWidth;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => drawCharts(false), 150);
  });

  initCompare();
  initLapse(d);
  let counted = false;
  let mapDone = false;
  initReveal((el) => {
    if (el.id === "act-2" && mainChart) { mainRevealed = true; mainChart.reveal(); }
    if (el.id === "act-3" && !counted) { counted = true; countUp(document.getElementById("big-number")); }
    // the map is built once its section is visible, so Leaflet measures a laid-out container
    if (el.id === "method" && !mapDone) { mapDone = true; setTimeout(() => initControlMap(d), 320); }
  });
  initPill(d);
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
