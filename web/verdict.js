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
    ? `<div class="act1-hint tnum">${(px.fraction_changed * 100).toFixed(0)}% of the area's pixels changed more than the surrounding land did.</div>`
    : "";
  const hasPair = !!(d.imagery && d.imagery.before && d.imagery.after);
  return `
    <section class="act reveal" id="act-1">
      <div class="label">What we saw</div>
      <div class="act1-grid">
        <div class="act1-media">
          ${renderCompare(d)}
          <div id="lapse-mount"></div>
        </div>
        <aside class="act1-aside">
          ${renderNumber(d)}
          ${pixelLine}
          <p class="act1-lede muted">The white outline is the drawn area${hasPair ? ". Drag the divider to compare" : ""}${(d.pixels && d.pixels.map) ? "; the change map marks pixels that changed more than their surroundings" : ""}.</p>
        </aside>
      </div>
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
      <div class="lapse-head"><span class="label" style="margin:0">Time-lapse</span><span class="lapse-hint muted">${frames.length} clear scenes · drag along the timeline</span></div>
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

// ---- plain-English verdict --------------------------------------------------

const PLAIN_REASONS = [
  [/observation period\(?s?\)? after/i, "There are too few clear satellite images after the event."],
  [/observation periods? before/i, "There are too few clear satellite images before the event."],
  [/does not track the area well enough before/i, "No nearby areas track this one closely enough before the event."],
  [/control cells themselves shifted/i, "The whole region changed at the same time, so there is nothing untouched to compare with."],
  [/usable control cells/i, "Too few comparable areas nearby."],
  [/too wide/i, "The signal is too noisy to be sure either way."],
  [/found divergences this large in untouched cells too often/i, "Areas that did not have the event moved just as much."],
  [/no effect size was compatible/i, "The change does not look like a single step, so its size cannot be pinned down."],
  [/too few to confirm, too large to dismiss/i, "The few images after the event show a large change, but there are too few of them to be sure."],
];

function plainReason(reasons) {
  for (const r of reasons || []) {
    for (const [re, text] of PLAIN_REASONS) if (re.test(r)) return text;
  }
  return "The data do not support a confident answer.";
}

function plainWhat(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead] || {};
  const down = (sig.point || 0) < 0;
  switch (d.change_type) {
    case "clearing": return "This area lost its vegetation";
    case "burn": return "This area burned";
    case "flood": return "This area flooded";
    case "construction": return "This area was built over";
    case "regrowth": return "This area grew back";
    default: return down ? "This area lost greenness" : "This area gained greenness";
  }
}

function plainVerdict(d) {
  const when = fmtDate(d.event_date);
  const st = d.verdict.status;
  if (st === "REAL") return `${plainWhat(d)} after ${when}. Similar areas nearby did not.`;
  if (st === "NOT_REAL") {
    if (/opposite/i.test((d.verdict.reasons || []).join(" "))) return `This area moved the opposite way to a ${CHANGE_TYPE_LABEL[d.change_type] || d.change_type} after ${when}.`;
    return `Nothing here changed more than similar areas nearby did after ${when}.`;
  }
  return plainReason(d.verdict.reasons);
}

function renderVerdictTop(d) {
  const st = d.verdict.status;
  return `
    <section class="verdict-top reveal in" id="verdict-top">
      <div class="verdict-word v-${st}">${escapeHtml(headlineFor(d))}</div>
      <p class="verdict-plain">${escapeHtml(plainVerdict(d))}</p>
      <p class="verdict-claim tnum muted">${escapeHtml(d.label || "Drawn area")} · ${claimLine(d)}</p>
    </section>`;
}

// ---- the big number: relative change in plain words ----------------------------

const PLAIN_SIGNAL = { NDVI: "greenness", NDWI: "surface-water signal", NBR: "burn signal", VV: "radar brightness", VH: "radar brightness", RATIO: "radar ratio" };

function relativeChange(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const chart = d.charts[lead];
  const isDb = /^(VV|VH|RATIO)$/.test(lead);
  if (isDb) return { text: fmtSigned(lead, sig.point), sub: `${PLAIN_SIGNAL[lead]} compared with what was expected` };
  let base = null;
  if (chart && chart.counterfactual && chart.pre) {
    const post = chart.counterfactual.filter((_, i) => !chart.pre[i]).map(Math.abs);
    if (post.length) base = post.reduce((a, b) => a + b, 0) / post.length;
  }
  if (base && base > 0.05) {
    const pct = Math.round((sig.point / base) * 100);
    return { text: `${pct > 0 ? "+" : "−"}${Math.abs(pct)}%`, sub: `${PLAIN_SIGNAL[lead]} compared with what was expected` };
  }
  return { text: fmtSigned(lead, sig.point), sub: `${PLAIN_SIGNAL[lead]} (${lead} units) compared with what was expected` };
}

function renderNumber(d) {
  const st = d.verdict.status;
  const rc = relativeChange(d);
  return `
    <div class="big-number v-${st}" id="big-number"><span class="value">${escapeHtml(rc.text)}</span></div>
    <div class="big-sub">${escapeHtml(rc.sub)}</div>`;
}

// ---- act 1 (imagery + number) is renderAct1 above; charts below -------------

function renderCharts(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  return `
    <section class="act reveal" id="act-2">
      <div class="label">What it did, and what it would have done anyway</div>
      <div class="chart-wrap" id="main-chart"></div>
      <div class="chart-legend">
        <span><span class="swatch" style="border-color:var(--treated)"></span>This area</span>
        <span><span class="swatch dashed" style="border-color:var(--counter)"></span>What it would have done anyway</span>
        <span><span class="swatch band"></span>Where similar areas ended up</span>
      </div>
      <div class="gap-block">
        <div class="chart-wrap" id="gap-chart"></div>
        <div class="chart-caption">The gap between the two lines. Zero means no difference.</div>
      </div>
    </section>`;
}

function renderSure(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const k = Math.max(0, Math.round(sig.placebo_p * (sig.placebo_n + 1)) - 1);
  const st = d.verdict.status;
  const tail = st === "REAL" ? " That is why we call it real." : (st === "NOT_REAL" ? " That is why we call it not real." : "");
  return `
    <section class="act reveal" id="act-3">
      <div class="label">How sure</div>
      <div class="sure-row">
        <div class="strip-wrap" id="placebo-strip"></div>
        <p class="sure-line">${k} of ${sig.placebo_n} similar areas nearby showed a change this big.${tail}</p>
      </div>
    </section>`;
}

// ---- details: the numbers -------------------------------------------------------

function renderNumbers(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const chart = d.charts[lead];
  const rows = [
    ["Signal", `${SIGNAL_LABEL[lead] || lead} (${sig.sensor})`],
    ["Effect", `${fmtSigned(lead, sig.point)}${unitFor(lead)} relative to the no-event trajectory, ${d.post_months} months after the event`],
    ["90% interval", `${fmtSigned(lead, sig.lo)} to ${fmtSigned(lead, sig.hi)}`],
    ["Smallest meaningful change", fmtSignalValue(lead, sig.min_effect)],
    ["Placebo (space)", `${sig.placebo_p.toFixed(3)} over ${sig.placebo_n} control cells`],
    ["p for no effect", Number.isFinite(sig.p_zero) ? sig.p_zero.toFixed(3) : "n/a"],
    ["Pre-event fit error", `${fmtSignalValue(lead, sig.pre_rmse)} (typical for controls ${fmtSignalValue(lead, sig.placebo_pre_rmse_median)})`],
    ["Observation periods", `${sig.n_pre} before, ${sig.n_post} after; bins of ${d.method.bin_days} days`],
    ["Control cells", `${sig.n_donors}${d.controls && d.controls.mode === "wide" ? ` matched ${Math.round(d.controls.inner_m / 1000)}-${Math.round(d.controls.outer_m / 1000)} km away` : " within 1-12 km"}`],
  ];
  const others = otherSignals(d).filter(([, rv]) => rv && rv.n_post >= 1 && !(rv.point === 0 && rv.lo === 0 && rv.hi === 0));
  others.forEach(([rk, rv]) => rows.push([SIGNAL_LABEL[rk] || rk, `${fmtSigned(rk, rv.point)}${unitFor(rk)}, interval ${fmtSigned(rk, rv.lo)} to ${fmtSigned(rk, rv.hi)}, placebo p ${rv.placebo_p.toFixed(3)}, ${rv.n_post} periods after`]));
  const tps = (chart && chart.time_placebos) || [];
  const fake = tps.length ? `<div class="label" style="margin-top:18px">Fake event dates</div><ul class="fake-list tnum">${tps.map((tp) => `<li><span>${fmtDate(tp.date)} · gap ${fmtSigned(lead, tp.effect)}, interval ${fmtSigned(lead, tp.lo)} to ${fmtSigned(lead, tp.hi)}</span><span class="${tp.flagged ? "false-alarm" : "muted"}">${tp.flagged ? "false alarm" : "no effect found"}</span></li>`).join("")}</ul>` : "";
  const reasons = (d.verdict.reasons || []);
  const why = reasons.length ? `<div class="label" style="margin-top:18px">Why the verdict is what it is</div><ul class="why-list">${reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>${fixesFor(reasons).length ? `<p class="fix-line"><strong>What would fix it:</strong> ${escapeHtml(fixesFor(reasons).join("; "))}.</p>` : ""}` : "";
  const ev = d.evidence && d.evidence.sentence ? `<p class="statement" style="margin-top:14px">${escapeHtml(d.evidence.sentence)}</p>` : "";
  return `
    <table class="numbers tnum">${rows.map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(v)}</td></tr>`).join("")}</table>
    <p class="statement" style="margin-top:14px">${escapeHtml(d.verdict.statement)}</p>
    ${ev}${fake}${why}`;
}

function renderDetails(d) {
  const lead = d.verdict.lead_signal;
  const donors = d.donors[lead] || {};
  const hasCells = donors.grid_index && donors.grid_index.length && d.donors.cells && d.donors.cells.length;
  const notes = (donors.notes || []).join("; ");
  return `
    <section class="details-stack" id="details">
      <details class="dtl" id="dtl-numbers"><summary>The numbers</summary><div class="dtl-body">${renderNumbers(d)}</div></details>
      <details class="dtl" id="dtl-controls"><summary>Control areas</summary><div class="dtl-body">
        ${hasCells ? `<div id="control-map" aria-label="Map of the control cells around the area"></div>` : ""}
        <div class="map-caption">${escapeHtml(notes)}${donors.counts ? `. ${donors.counts.kept} of ${donors.counts.grid} cells used; darker cells carry more weight.` : ""}</div>
      </div></details>
      <details class="dtl" id="dtl-receipts"><summary>Receipts: what was thrown out and why</summary><div class="dtl-body">${renderReceiptsSection(d)}</div></details>
      <details class="dtl" id="dtl-method"><summary>Method</summary><div class="dtl-body">${renderMethodSection(d)}</div></details>
    </section>`;
}

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
  reasons.forEach((r) => { for (const [re, fix] of FIXES) if (re.test(r) && !out.includes(fix)) out.push(fix); });
  return out;
}

function otherSignals(d) {
  return Object.entries(d.signals).filter(([k]) => k !== d.verdict.lead_signal);
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
    const target = document.getElementById("verdict-top");
    if (target) target.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
  });

  const act1 = document.getElementById("verdict-top");
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
    renderVerdictTop(d) +
    renderAct1(d) +
    renderCharts(d) +
    renderSure(d) +
    renderDetails(d);

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
  });
  const dc = document.getElementById("dtl-controls");
  if (dc) dc.addEventListener("toggle", () => { if (dc.open && !mapDone) { mapDone = true; setTimeout(() => initControlMap(d), 120); } });
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
