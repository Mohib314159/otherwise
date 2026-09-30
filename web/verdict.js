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
  apiGet, apiPost, fmtDate, fmtSignalValue, VERDICT_LABEL, VERDICT_VAR,
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
      ${px.overlay_url ? `<div class="compare-layer compare-map"><img src="${escapeHtml(px.overlay_url)}" alt="Pixels that changed more than comparable land, over the after image" decoding="async"></div>` : ""}
      <div class="compare-layer compare-before" id="compare-before"><img src="${escapeHtml(im.before.url)}" alt="Before the event, ${fmtDate(im.before.date)}" decoding="async"></div>
      <div class="compare-divider" id="compare-divider"><div class="compare-handle">${HANDLE_SVG}</div></div>
      <span class="compare-tag before">Before · ${fmtDate(im.before.date)}</span>
      <span class="compare-tag after">After · ${fmtDate(im.after.date)}</span>
      <div class="compare-coach" id="compare-coach" aria-hidden="true"><span>↔</span> Drag to compare</div>
    </div>`;
}

function changeWord(px, dir) {
  const name = { NDVI: "greenness", NBR: "burn ratio", NDWI: "surface water" }[px.signal] || "the index";
  return dir === "dec" ? `${name} fell;` : `${name} rose.`;
}

/** Facts about the drawn area only. What was claimed lives in claimSentence. */
function claimLine(d) {
  const parts = [`${d.area.ha} ha`];
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
      <div class="label">Satellite evidence</div>
      <div class="act1-grid">
        <div class="act1-media">
          ${renderCompare(d)}
          ${hasPair ? `<div class="compare-presets" role="group" aria-label="Comparison view">
            <button type="button" class="compare-preset" data-compare-preset="100">Before</button>
            <button type="button" class="compare-preset active" data-compare-preset="50">Split</button>
            <button type="button" class="compare-preset" data-compare-preset="0">After</button>
            ${px.overlay_url ? `<button type="button" class="compare-preset" data-compare-preset="0" data-compare-map="on">Changes</button>` : ""}
          </div>
          ${px.overlay_url ? `<p class="change-legend" id="change-legend" hidden><span class="sw dec"></span>${escapeHtml(changeWord(px, "dec"))} <span class="sw inc"></span>${escapeHtml(changeWord(px, "inc"))} Coloured pixels moved further than 95% of comparable land nearby, so about 1 in 20 would be coloured by chance.</p>` : ""}` : ""}
          <div id="lapse-mount"></div>
        </div>
        <aside class="act1-aside">
          ${renderNumber(d)}
          ${pixelLine}
          <p class="act1-lede muted">${hasPair ? "Same place, two dates. Drag the divider or tap Before / Split / After. " : ""}The white outline is the area you drew${px.overlay_url ? ". Tap Changes to colour the pixels that moved more than their surroundings" : ""}.</p>
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
    const mapOn = el.classList.contains("map-on");
    document.querySelectorAll("[data-compare-preset]").forEach((btn) => {
      const target = Number(btn.dataset.comparePreset);
      const on = Math.abs(target - pct) < 1 && (btn.dataset.compareMap === "on") === mapOn;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  set(50);

  let dragging = false;
  const fromEvent = (e) => {
    const r = el.getBoundingClientRect();
    return ((e.clientX - r.left) / r.width) * 100;
  };
  const hideCoach = () => document.getElementById("compare-coach")?.classList.add("hidden");
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest && e.target.closest(".compare-toggle")) return;
    hideCoach();
    if (el.classList.contains("map-on")) { el.classList.remove("map-on"); if (document.getElementById("change-legend")) document.getElementById("change-legend").hidden = true; }
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
    hideCoach();
    if (e.key === "ArrowLeft") { set(pct - step, { animate: true }); e.preventDefault(); }
    else if (e.key === "ArrowRight") { set(pct + step, { animate: true }); e.preventDefault(); }
    else if (e.key === "Home") { set(0, { animate: true }); e.preventDefault(); }
    else if (e.key === "End") { set(100, { animate: true }); e.preventDefault(); }
  });

  const legend = document.getElementById("change-legend");
  const setMap = (on) => {
    el.classList.toggle("map-on", on);
    if (legend) legend.hidden = !on;
  };
  document.querySelectorAll("[data-compare-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      hideCoach();
      setMap(btn.dataset.compareMap === "on");
      set(Number(btn.dataset.comparePreset), { animate: true });
    });
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
        ${eventInRange ? `<span class="lapse-event" style="left:${pos(d.event_date).toFixed(2)}%" title="event · ${fmtDate(d.event_date)}"><span class="lapse-event-lbl">Event · ${fmtDate(d.event_date)}</span></span>` : ""}
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

// The claim and the finding are kept apart on purpose. The change type is
// whatever the user picked in the dropdown; the method tests whether an index
// moved further than matched control areas did, and cannot tell a burn from a
// harvest or a flood from irrigation. So the dropdown word only ever appears in
// the reported-claim line, never in the sentence about what the data show.

const CLAIM_PHRASE = {
  clearing: "clearing",
  regrowth: "regrowth",
  flood: "a flood",
  burn: "a burn",
  construction: "construction",
  other: "a change",
};

/** What the user told us, stated as a claim and nothing more. */
function claimSentence(d) {
  const what = CLAIM_PHRASE[d.change_type] || "a change";
  if (d.showcase) {
    const nothing = d.showcase.expected === "NOT_REAL" || d.showcase.expected === "no_change";
    return `Claim tested: ${what} on ${fmtDate(d.event_date)}${nothing ? " (false-alarm check: nothing documented here)" : ""}`;
  }
  return `You reported ${what} here on ${fmtDate(d.event_date)}`;
}

/** Banner for an old showcase run that a newer run of the same case replaced. */
function supersededHtml(d) {
  if (!d.superseded_by) return "";
  return `<p class="superseded-note" id="superseded-note">Superseded: this is an older run of this case. Current version: <a href="/v/${encodeURIComponent(d.superseded_by)}">/v/${escapeHtml(d.superseded_by)}</a></p>`;
}

/** Known-answer sites are candidates until someone independent confirms them. */
function candidateBadgeHtml(d) {
  if (!d.showcase || d.showcase.confirmed) return "";
  return `<p class="candidate-badge" id="candidate-badge">candidate — not yet independently confirmed</p>`;
}

/** Magnitude only, unsigned, with the unit: "0.47", "0.9 dB". */
function fmtMagnitude(signal, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return fmtSignalValue(signal, Math.abs(value));
}

function indexName(signal) {
  const n = SIGNAL_LABEL[signal] || signal;
  return n.charAt(0).toUpperCase() + n.slice(1);
}

/**
 * What the data show: a gap between this area and the trajectory the matched
 * control areas imply. No mechanism, because the method cannot see one.
 */
function findingSentence(d) {
  const lead = d.verdict.lead_signal;
  const sig = (d.signals && d.signals[lead]) || {};
  const st = d.verdict.status;
  const when = fmtDate(d.event_date);
  const months = d.post_months;
  const name = indexName(lead);
  const size = fmtMagnitude(lead, sig.point);
  const dir = (sig.point || 0) < 0 ? "fell" : "rose";
  if (st === "REAL") {
    return `${name} ${dir} ${size} further here than the matched control areas did, over the ${months} months after ${when}.`;
  }
  if (st === "NOT_REAL") {
    if (/opposite/i.test((d.verdict.reasons || []).join(" "))) {
      return `${name} moved the opposite way to the reported change over the ${months} months after ${when}.`;
    }
    return `${name} moved ${size} against the matched control areas over the ${months} months after ${when} — smaller than the smallest change this test calls meaningful.`;
  }
  return plainReason(d.verdict.reasons);
}

// ---- quick-check (live) runs --------------------------------------------------
//
// A live run reads the drawn area at 10 m but its control cells at 40 m from a
// separate catalogue search, so treated and control pixels no longer come from
// the same scenes. Runs made before the profile field existed were all full
// mode, so a missing profile means full.

function isQuickCheck(d) {
  const p = d.profile || (d.method && d.method.profile);
  return p === "live";
}

const QUICK_CHECK_NOTE =
  "This ran as a quick check: the drawn area was read at 10 m but its control " +
  "areas at 40 m, from a separate catalogue search, so the area and its controls " +
  "are not read from the same scenes — weaker evidence than a full run, which " +
  "reads everything at 10 m from one search and is done offline.";

/** One line from the lead signal's own fields: in-space placebo count, then fake-date count. */
function heroSureLine(d) {
  const sig = d.signals[d.verdict.lead_signal] || {};
  const parts = [];
  const n = sig.placebo_n;
  const k = Number.isFinite(n) && n > 0 ? placeboCount(sig.placebo_p_effect, n) : null;
  if (k !== null) parts.push(`${k} of ${n} comparable untouched places moved this much`);
  const flags = Array.isArray(sig.time_placebo_flags) ? sig.time_placebo_flags : [];
  parts.push(flags.length
    ? `${flags.filter(Boolean).length} of ${flags.length} fake earlier dates fired`
    : "no fake-date test was possible");
  return parts.join(" · ");
}

function renderVerdictTop(d) {
  const st = d.verdict.status;
  const quick = isQuickCheck(d);
  return `
    <section class="verdict-top reveal in" id="verdict-top">
      ${supersededHtml(d)}
      <p class="verdict-kicker muted">${escapeHtml(claimSentence(d))}</p>
      <div class="verdict-word v-${st}">${escapeHtml(headlineFor(d))}</div>
      <p class="hero-sure tnum muted" id="hero-sure">${escapeHtml(heroSureLine(d))}</p>
      ${candidateBadgeHtml(d)}
      ${quick ? `<p class="quick-mark" id="quick-mark">Quick check</p>` : ""}
      <p class="verdict-plain">${escapeHtml(findingSentence(d))}</p>
      ${quick ? `<p class="quick-note muted" id="quick-note">${escapeHtml(QUICK_CHECK_NOTE)}</p>` : ""}
      <p class="verdict-claim tnum muted">${escapeHtml(d.label || "Drawn area")} · ${claimLine(d)}</p>
    </section>`;
}

// ---- the big number ------------------------------------------------------------
//
// The hero figure is the estimated gap. For an index (NDVI / NDWI / NBR) it is
// also shown as a percentage of the level the control trajectory predicted over
// the post-event window -- the definition is printed under it, and its interval
// is the 90% interval put through the same divisor, so the two cannot drift
// apart. When that divisor is near zero the percentage means nothing, so the
// absolute figure is shown instead of a huge or infinite percent.

const DIVISOR_FLOOR = 0.05;   // index levels below this make a percentage meaningless

/** Mean absolute counterfactual level over the post-event bins, or null. */
function counterfactualLevel(chart) {
  if (!chart || !Array.isArray(chart.counterfactual) || !Array.isArray(chart.pre)) return null;
  const post = chart.counterfactual.filter((_, i) => !chart.pre[i]).filter(Number.isFinite).map(Math.abs);
  if (!post.length) return null;
  const mean = post.reduce((a, b) => a + b, 0) / post.length;
  return Number.isFinite(mean) ? mean : null;
}

function fmtPct(v) {
  if (!Number.isFinite(v)) return "—";
  const n = Math.round(v);
  if (n === 0) return "0%";
  return `${n > 0 ? "+" : "−"}${Math.abs(n)}%`;
}

function relativeChange(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const chart = d.charts[lead];
  const isDb = /^(VV|VH|RATIO)$/.test(lead);
  const months = d.post_months;
  const name = SIGNAL_LABEL[lead] || lead;
  const hasInterval = Number.isFinite(sig.lo) && Number.isFinite(sig.hi);
  // Always available: the effect in the units the method estimates in.
  const absolute = {
    text: fmtBare(lead, sig.point),
    unit: unitFor(lead),
    sub: `${name} relative to the control trajectory, ${months} months after the event`,
    interval: hasInterval ? `90% interval ${fmtSigned(lead, sig.lo)} to ${fmtSigned(lead, sig.hi)}` : "",
    pct: "",
    unitFirst: !isDb,
    detail: "",
  };
  if (isDb || !Number.isFinite(sig.point)) return absolute;
  const base = counterfactualLevel(chart);
  if (!(base > DIVISOR_FLOOR)) {
    // near-zero divisor: no percentage, and say why the absolute number is here
    return {
      ...absolute,
      detail: base === null
        ? ""
        : `Shown in ${lead} units, not as a percentage: the control trajectory averaged ${fmtSignalValue(lead, base)} over this window, too close to zero for a percentage of it to mean anything.`,
    };
  }
  const pct = (sig.point / base) * 100;
  // Lead with the index units the method estimates in; the percentage is secondary.
  return {
    ...absolute,
    text: fmtBare(lead, sig.point),
    unit: lead,
    unitFirst: true,
    pct: `${fmtPct(pct)} of the control level`
      + (hasInterval ? ` (90% ${fmtPct((sig.lo / base) * 100)} to ${fmtPct((sig.hi / base) * 100)})` : ""),
    detail: `The gap between this area and the control trajectory is ${fmtSigned(lead, sig.point)} ${lead}. `
      + `The percentage is that gap divided by ${fmtSignalValue(lead, base)} — the average level the control trajectory predicted over the ${months} months after the event; `
      + `the interval is the same division applied to both ends of the 90% interval. `
      + `${lead} is an index, not a physical quantity, so read the percentage as a comparison with the control level rather than as a percentage of anything measurable.`,
  };
}

function renderNumber(d) {
  const st = d.verdict.status;
  const rc = relativeChange(d);
  return `
    <div class="big-number v-${st}" id="big-number">${rc.unitFirst ? `<span class="unit unit-lead">${escapeHtml(rc.unit)}</span>` : ""}<span class="value">${escapeHtml(rc.text)}</span>${rc.unit && !rc.unitFirst ? `<span class="unit">${escapeHtml(rc.unit)}</span>` : ""}</div>
    <div class="big-sub">${escapeHtml(rc.sub)}</div>
    ${rc.interval ? `<div class="big-sub tnum muted" id="big-interval">${escapeHtml(rc.interval)}</div>` : ""}
    ${rc.pct ? `<div class="big-sub big-pct tnum muted" id="big-pct">${escapeHtml(rc.pct)}</div>` : ""}
    ${rc.detail ? `<details class="what-num" id="what-num"><summary>What this number means</summary><p>${escapeHtml(rc.detail)}</p></details>` : ""}`;
}

// ---- act 1c: the drawn area next to its matched control areas ---------------

/** Say plainly when the controls that carry the prediction could not be pictured. */
function controlsNote(ci, shown) {
  const missing = ((ci && ci.skipped) || []).filter((s) => s.weight > 0);
  const nShownW = shown.filter((c) => c.role === "weighted").length;
  const parts = [];
  if (missing.length) {
    const share = Math.round(missing.reduce((a, s) => a + s.weight, 0) * 100);
    parts.push(`${missing.length === 1 ? "The control" : `${missing.length} controls`} carrying ${share}% of the no-event prediction had no clear view within 30 days of these dates, so ${missing.length === 1 ? "it is" : "they are"} not shown.`);
  }
  if (shown.some((c) => c.role === "pool")) {
    parts.push(`${nShownW ? "The other columns are" : "The columns shown are"} the closest pre-event matches from the same control pool, which the prediction did not weight.`);
  }
  return parts.length ? `<p class="cmp-note muted">${parts.join(" ")}</p>` : "";
}

function fmtKm(m) {
  if (!Number.isFinite(m)) return "";
  return m >= 10000 ? `${Math.round(m / 1000)} km away` : `${(m / 1000).toFixed(1)} km away`;
}

/**
 * The comparison the verdict rests on, as pictures: the drawn area and up to
 * three control areas, each on the same two dates. Controls that carry weight in
 * the no-event prediction are labelled with their share; any others are the
 * closest pre-event matches in the same pool and are labelled as not weighted.
 */
function renderControlsImagery(d) {
  const im = d.imagery || {};
  const ctl = (d.control_imagery && d.control_imagery.controls) || [];
  if (!im.before || !im.after || !ctl.length) return "";
  const cell = (label, sub, before, after) => `
    <figure class="cmp-col">
      <figcaption><strong>${escapeHtml(label)}</strong>${sub ? `<span>${escapeHtml(sub)}</span>` : ""}</figcaption>
      <div class="cmp-pair">
        <div class="cmp-shot"><img src="${escapeHtml(before.url)}" alt="${escapeHtml(label)} before, ${fmtDate(before.date)}" loading="lazy" decoding="async"><span class="cmp-date">${fmtDate(before.date)}</span></div>
        <div class="cmp-shot"><img src="${escapeHtml(after.url)}" alt="${escapeHtml(label)} after, ${fmtDate(after.date)}" loading="lazy" decoding="async"><span class="cmp-date">${fmtDate(after.date)}</span></div>
      </div>
    </figure>`;
  const cols = [cell("Your area", "the white outline", im.before, im.after)].concat(ctl.map((c, i) => {
    const share = c.role === "weighted"
      ? `${Math.round(c.weight * 100)}% of the no-event prediction`
      : "matched, not weighted";
    return cell(`Control ${i + 1}`, [share, fmtKm(c.distance_m)].filter(Boolean).join(" · "), c.before, c.after);
  }));
  const sameDates = ctl.every((c) => c.before.date === im.before.date && c.after.date === im.after.date);
  return `
    <section class="act reveal" id="act-controls">
      <div class="label">Compared with matched places</div>
      <p class="cmp-lede muted">Top row before the event, bottom row after${sameDates ? ", every column on the same two dates" : ""}. The control areas behaved like yours before the event and did not get it. If yours changed and they did not, that points to something local to your area rather than the season, the weather or a regional trend; the charts below test it.</p>
      <div class="cmp-grid" style="--cols:${cols.length}">${cols.join("")}</div>
      ${controlsNote(d.control_imagery, ctl)}
    </section>`;
}

// ---- act 1 (imagery + number) is renderAct1 above; charts below -------------

function renderCharts(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  return `
    <section class="act reveal" id="act-2">
      <div class="label">Observed vs counterfactual</div>
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

// ---- act 3: how sure ---------------------------------------------------------
//
// Two placebo figures come out of the run, and they are not the same thing:
//
//   placebo_p        the rank of this area's post/pre fit-error ratio among the
//                    control cells' own ratios -- how unusual it is that the
//                    no-event prediction broke down here after the event date,
//                    judged against how well it fitted before. This is the
//                    formal test.
//   placebo_p_effect the share of control cells whose signed post-event gap was
//                    at least as large in the same direction -- a count by
//                    effect size, ignoring pre-event fit.
//
// Both are (k + 1) / (n + 1) by construction (Abadie's "+1"), so the underlying
// count k comes back exactly. The page used to describe the second and compute
// the first; each now says what it is, on its own line.

function placeboCount(p, n) {
  if (!Number.isFinite(p) || !Number.isFinite(n)) return null;
  return Math.max(0, Math.round(p * (n + 1)) - 1);
}

function renderSure(d) {
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead];
  const n = sig.placebo_n;
  const kFit = placeboCount(sig.placebo_p, n);
  const kGap = placeboCount(sig.placebo_p_effect, n);
  const fitLine = kFit === null
    ? `<p class="sure-line">No in-space placebo test ran for this signal.</p>`
    : `<p class="sure-line"><span class="sure-tag">Placebo test</span>The same test was run on ${n} untouched control cells nearby. In ${kFit} of them, the no-event prediction missed by as much after the event date — relative to how closely it matched before — as it did here (placebo p ${sig.placebo_p.toFixed(2)}).</p>`;
  const gapLine = kGap === null
    ? ""
    : `<p class="sure-line second"><span class="sure-tag">Counted by gap size instead</span>${kGap} of those ${n} cells moved at least as far as this area did, in the same direction (${sig.placebo_p_effect.toFixed(2)}).</p>`;
  // Runs made before the CRITIQUE #4 fix carry no placebo_symmetric flag: their
  // placebo cells reused this area's control selection, which flatters the p-value.
  const asymLine = (kFit === null || sig.placebo_symmetric === true)
    ? ""
    : `<p class="sure-caveat"><span class="sure-tag">Older placebo procedure</span>This run predates a fix to the placebo test: its control cells were scored against controls chosen for this area rather than for themselves, which makes the p-value look stronger than it should. It has not been re-run yet.</p>`;
  return `
    <section class="act reveal" id="act-3">
      <div class="label">Placebo test</div>
      <div class="sure-row">
        <div class="strip-wrap" id="placebo-strip"></div>
        <div class="sure-lines">${fitLine}${gapLine}${asymLine}</div>
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
    ["Placebo p (fit ratio)", `${sig.placebo_p.toFixed(3)} — share of ${sig.placebo_n} control cells whose post-event fit error grew, against their own pre-event fit, at least as much as this area's did`],
    ["Placebo p (gap size)", Number.isFinite(sig.placebo_p_effect)
      ? `${sig.placebo_p_effect.toFixed(3)} — share of the same cells whose post-event gap was at least as large in the same direction`
      : "n/a"],
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

// ---- air-policy verdict -------------------------------------------------------

function airSignalRows(d) {
  return ["NO2_TRAFFIC", "NO2_BACKGROUND"]
    .filter((k) => d.signals && d.signals[k])
    .map((k) => [k, d.signals[k]]);
}

function airStationTypeLabel(signal) {
  return signal === "NO2_TRAFFIC" ? "Roadside / traffic monitors" : "Urban-background monitors";
}

function fmtAirPct(v) {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) < 0.05) return "0.0%";
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
}

function renderAirTop(d) {
  const st = d.verdict.status;
  const lead = d.verdict.lead_signal;
  const sig = d.signals[lead] || {};
  const effect = Number.isFinite(sig.relative_pct) ? fmtAirPct(sig.relative_pct) : fmtSigned(lead, sig.point);
  return `
    <section class="verdict-top reveal in" id="verdict-top">
      <p class="verdict-kicker muted">Independent policy check · ${escapeHtml(d.case?.label || d.label || "Air pollution")}</p>
      <div class="verdict-word v-${st}">${escapeHtml(headlineFor(d))}</div>
      <p class="verdict-plain">${escapeHtml(st === "CANT_TELL" ? "The available data cannot reliably determine whether this policy caused an additional NO₂ reduction. See the estimates and checks for each monitor type below." : (d.verdict.statement || ""))}</p>
      <p class="verdict-claim tnum muted">Policy start ${fmtDate(d.event_date)} · ${d.post_months} month window · NO₂ · ground monitors + ERA5</p>
      <div class="air-hero-number v-${st}"><span>${escapeHtml(effect)}</span></div>
      <div class="big-sub">${escapeHtml(SIGNAL_LABEL[lead] || lead)} against the matched no-policy trajectory</div>
      ${Number.isFinite(sig.point) ? `<div class="big-sub tnum muted">${fmtSigned(lead, sig.point)} absolute gap · 90% interval ${fmtSigned(lead, sig.lo)} to ${fmtSigned(lead, sig.hi)}</div>` : ""}
    </section>
    <details class="dtl air-verdict-reasons"><summary>Why this verdict?</summary><div class="dtl-body"><p>${escapeHtml(d.verdict.statement || "")}</p></div></details>`;
}

function airPlaceboP(sig, key) {
  return sig.placebo_n > 0 && Number.isFinite(sig[key]) ? sig[key].toFixed(3) : "—";
}

function airSensitivityStatus(check) {
  if (!check || !check.applicable) return "not applicable";
  if (check.reason?.includes("not estimable")) return "not estimable";
  return check.robust ? "robust" : "not robust";
}

function renderAirCharts(d) {
  return airSignalRows(d).map(([signal, sig], i) => {
    const chart = d.charts[signal];
    if (!chart) return "";
    return `
      <section class="act reveal air-signal" id="air-signal-${signal}">
        <div class="label">${escapeHtml(airStationTypeLabel(signal))}</div>
        <div class="air-result-grid">
          <div><div class="air-effect tnum">${fmtAirPct(sig.relative_pct)}</div><div class="muted small">relative NO₂ effect</div></div>
          <div><div class="air-effect tnum">${fmtSigned(signal, sig.point)}</div><div class="muted small">absolute gap</div></div>
          <div><div class="air-effect tnum">${airPlaceboP(sig, "placebo_p")}</div><div class="muted small">placebo fit-ratio p-value</div></div>
          <div><div class="air-effect tnum">${airPlaceboP(sig, "placebo_p_effect")}</div><div class="muted small">placebo effect-size p-value</div></div>
          <div><div class="air-interval tnum">${fmtSigned(signal, sig.lo)} to ${fmtSigned(signal, sig.hi)}</div><div class="muted small">90% confidence interval</div></div>
          <div><div class="air-effect tnum">${sig.treated_station_count ?? "—"} / ${sig.n_donors ?? "—"}</div><div class="muted small">London / control monitors</div></div>
        </div>
        <div class="chart-wrap air-main-chart" id="air-main-chart-${signal}"></div>
        <div class="chart-legend">
          <span><span class="swatch" style="border-color:var(--treated)"></span>London monitors</span>
          <span><span class="swatch dashed" style="border-color:var(--counter)"></span>Matched no-policy trajectory</span>
          ${chart.placebo_band?.[0]?.some((v, j) => Number.isFinite(v) && Number.isFinite(chart.placebo_band?.[1]?.[j])) ? '<span><span class="swatch band"></span>Placebo range</span>' : '<span>Placebo range unavailable</span>'}
        </div>
        <div class="gap-block"><div class="chart-wrap" id="air-gap-chart-${signal}"></div><div class="chart-caption">Weather-normalised London NO₂ minus the matched no-policy trajectory. Zero means no additional effect.</div></div>
        <div class="strip-wrap air-placebo-strip" id="air-placebo-${signal}"></div>
        <p class="sure-line"><span class="sure-tag">Design</span>${sig.treated_station_count} of ${sig.treated_station_requested} requested London ${sig.site_type} monitors survived fixed-cohort coverage rules; ${sig.n_donors} same-type controls were selected. ${sig.placebo_n > 0 ? `${sig.placebo_n} exact-size placebo cohorts reran control selection and ridge tuning from scratch.` : "No exact-size placebo cohort could be formed, so this stratum has no placebo test and no placebo p-value."}</p>
        <p class="sure-line second"><span class="sure-tag">Stress checks</span>Pre-trend: ${sig.pretrend == null || sig.pretrend.applicable === false ? "not run" : (sig.pretrend.flagged ? "flagged" : "clear")} · leave-one-London-monitor-out: ${airSensitivityStatus(sig.treated_jackknife)} · influential-control removal: ${airSensitivityStatus(sig.donor_sensitivity)} · interval search: ${!Number.isFinite(sig.lo) || !Number.isFinite(sig.hi) ? "not available" : (sig.conformal_boundary_hit || sig.conformal_empty ? "unresolved" : "resolved")}.</p>
      </section>`;
  }).join("");
}

function renderAirResearch(d) {
  const rows = d.research_comparison || [];
  if (!rows.length) return "";
  return `
    <section class="act reveal" id="air-research">
      <div class="label">Now reveal the published answer</div>
      <p class="muted">These papers are answer keys only. Their estimates are attached after Otherwise has finished fitting the counterfactual.</p>
      <div class="air-research-list">${rows.map((r) => {
        const ours = Number.isFinite(r.otherwise_pct)
          ? `${fmtAirPct(r.otherwise_pct)} (90% ${fmtAirPct(r.otherwise_pct_interval?.[0])} to ${fmtAirPct(r.otherwise_pct_interval?.[1])})`
          : "No matching Otherwise stratum in this run";
        const pub = Number.isFinite(r.point_pct) ? fmtAirPct(r.point_pct) : r.finding;
        return `<article class="air-research-card">
          <div class="small muted">${escapeHtml(r.stratum ? airStationTypeLabel(r.stratum === "traffic" ? "NO2_TRAFFIC" : "NO2_BACKGROUND") : "Published study")}</div>
          <div><strong>Otherwise:</strong> <span class="tnum">${escapeHtml(ours)}</span></div>
          <div><strong>Published:</strong> <span class="tnum">${escapeHtml(pub)}</span></div>
          ${Number.isFinite(r.point_pct) && r.finding ? `<p class="small">${escapeHtml(r.finding)}</p>` : ""}
          ${r.comparison ? `<p class="small muted">${escapeHtml(r.comparison)}</p>` : ""}
          <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.citation)}</a>
        </article>`;
      }).join("")}</div>
    </section>`;
}

function renderAirReceipts(d) {
  const counts = (d.data_summary && d.data_summary.receipts) || {};
  const countRows = Object.entries(counts).sort((a,b) => b[1]-a[1]);
  const examples = (d.receipts || []).slice(0, 80);
  return `
    <p class="receipts-summary tnum">${d.data_summary?.treated_stations ?? 0} usable London monitors · ${d.data_summary?.control_stations ?? 0} usable UK control monitors · hourly → daily (≥19 h; >75%) → weekly (≥4 d).</p>
    ${countRows.length ? `<p class="small muted">Dropped / flagged: ${countRows.map(([k,v]) => `${escapeHtml(k)} ${v}`).join(" · ")}</p>` : ""}
    ${examples.length ? `<table class="receipts-table"><thead><tr><th>Date</th><th>Sensor</th><th>Reason</th><th>Detail</th></tr></thead><tbody>${examples.map((r) => `<tr><td class="tnum">${escapeHtml(r.date || "")}</td><td>${escapeHtml(r.sensor || "")}</td><td>${escapeHtml(r.reason || "")}</td><td>${escapeHtml(r.detail || "")}</td></tr>`).join("")}</tbody></table>` : '<p class="small muted">No dropped-observation receipts in this run.</p>'}`;
}

function renderAirDetails(d) {
  const limits = (d.limits || []).filter(Boolean);
  const signals = airSignalRows(d);
  return `
    <section class="details-stack" id="details">
      <details class="dtl" id="dtl-numbers"><summary>The numbers</summary><div class="dtl-body">
        <table class="numbers tnum"><thead><tr><th>Monitor type</th><th>Effect</th><th>90% interval</th><th>Relative</th><th>p fit</th><th>p effect</th><th>Pre / post weeks</th></tr></thead><tbody>
        ${signals.map(([k,s]) => `<tr><td>${escapeHtml(airStationTypeLabel(k))}</td><td>${fmtSigned(k,s.point)}</td><td>${fmtSigned(k,s.lo)} to ${fmtSigned(k,s.hi)}</td><td>${fmtAirPct(s.relative_pct)}</td><td>${airPlaceboP(s, "placebo_p")}</td><td>${airPlaceboP(s, "placebo_p_effect")}</td><td>${s.n_pre} / ${s.n_post}</td></tr>`).join("")}
        </tbody></table>
        <p class="statement" style="margin-top:14px">${escapeHtml(d.verdict.statement || "")}</p>
      </div></details>
      <details class="dtl" id="dtl-controls"><summary>London and control monitors</summary><div class="dtl-body"><div id="control-map" aria-label="Map of London and matched UK air quality monitors"></div><div class="map-caption">Black points are London monitors in the registered treated geography. Control monitors are same-type DEFRA AURN sites at least ${d.controls?.spillover_exclusion_km ?? 60} km from central London; matching uses pre-policy data only. ${(d.controls?.policy_exclusions || []).length} candidate monitors were screened out because a known local CAZ/LEZ/ZEZ launched inside this analysis window.</div></div></details>
      <details class="dtl" id="dtl-receipts"><summary>Receipts: what was thrown out and why</summary><div class="dtl-body">${renderAirReceipts(d)}</div></details>
      <details class="dtl" id="dtl-method"><summary>Method and failure modes</summary><div class="dtl-body">
        <p><strong>${escapeHtml(d.method?.estimator || "Augmented synthetic control")}</strong></p>
        <p><strong>Estimand:</strong> ${escapeHtml(signals[0]?.[1]?.estimand || "Incremental post-policy change against a matched no-policy trajectory.")}</p>
        <p>Registered baseline begins ${escapeHtml(d.method?.registered_analysis_start || d.window?.[0] || "—")}. NO₂ is weather-normalised with ERA5 using a ridge model trained only before the policy and season-matched pre-policy reference weather. Traffic/roadside and urban-background monitors are never pooled.</p>
        <p>${escapeHtml(d.method?.placebo || "")}</p>
        <p>${escapeHtml(d.method?.interval || "")}</p>
        ${signals.map(([k, sig]) => [ ["Leave-one-London-monitor-out", sig.treated_jackknife], ["Influential-control removal", sig.donor_sensitivity] ].filter(([, check]) => check?.reason).map(([name, check]) => `<p><strong>${escapeHtml(airStationTypeLabel(k))} · ${name}:</strong> ${escapeHtml(check.reason)}</p>`).join("")).join("")}
        <p><strong>Answer-key rule:</strong> ${escapeHtml(d.method?.answer_key_leakage || "Published findings are attached only after estimation.")}</p>
        ${limits.length ? `<div class="label" style="margin-top:18px">Known limits</div><ul class="why-list">${limits.map((x)=>`<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
      </div></details>
    </section>`;
}

function initAirControlMap(d) {
  const el = document.getElementById("control-map");
  if (!el || !window.L) return;
  const map = L.map(el, { scrollWheelZoom: false }).setView([54.2, -2.5], 5);
  L.tileLayer(LIGHT_TILES, { attribution: LIGHT_ATTR, maxZoom: 19 }).addTo(map);
  const bounds = L.latLngBounds([]);
  if (d.area && d.area.geojson) {
    const zone = L.geoJSON(d.area.geojson, { style: { color: "#161616", weight: 2, fillOpacity: 0.03 } }).addTo(map);
    bounds.extend(zone.getBounds());
  }
  (d.stations?.treated || []).forEach((s) => {
    if (!Number.isFinite(s.lat) || !Number.isFinite(s.lon)) return;
    const m = L.circleMarker([s.lat,s.lon], { radius:5, color:"#161616", weight:1.5, fillColor:"#f6f4ee", fillOpacity:1 }).addTo(map);
    m.bindTooltip(`${s.name || s.code} · London ${s.site_type || "monitor"}`);
    bounds.extend([s.lat,s.lon]);
  });
  const seen = new Set();
  Object.entries(d.donors || {}).forEach(([signal, info]) => {
    (info.stations || []).forEach((s) => {
      const key = s.code || `${s.lat}:${s.lon}`;
      if (seen.has(key) || !Number.isFinite(s.lat) || !Number.isFinite(s.lon)) return;
      seen.add(key);
      const m = L.circleMarker([s.lat,s.lon], { radius:4, color:"#777", weight:1, fillColor:"#777", fillOpacity:0.45 }).addTo(map);
      m.bindTooltip(`${s.name || s.code} · control ${s.site_type || "monitor"}`);
      bounds.extend([s.lat,s.lon]);
    });
  });
  if (bounds.isValid()) map.fitBounds(bounds, { padding:[25,25], maxZoom:10 });
  setTimeout(() => map.invalidateSize({ animate:false }), 100);
}

function renderAir(d) {
  document.body.classList.add("air-evidence");
  document.title = (d.label ? `${d.label} — ` : "") + "Otherwise";
  document.getElementById("copy-link-btn").style.display = "inline-block";
  contentEl.innerHTML = renderAirTop(d) + renderAirCharts(d) + renderAirResearch(d) + renderAirDetails(d);

  const chartObjs = [];
  airSignalRows(d).forEach(([signal, sig]) => {
    const chart = d.charts[signal];
    if (!chart) return;
    const obj = drawTrajectoryChart(document.getElementById(`air-main-chart-${signal}`), chart, { eventDate:d.event_date, signal, animate:true });
    chartObjs.push(obj);
    drawGapChart(document.getElementById(`air-gap-chart-${signal}`), chart, { eventDate:d.event_date, signal });
    const strip = document.getElementById(`air-placebo-${signal}`);
    if (strip) strip.innerHTML = stripPlotSVG(strip.clientWidth || 520, chart.placebo_effects || [], sig.point, VERDICT_VAR[d.verdict.status], signal);
  });
  initReveal(() => {});
  chartObjs.forEach((x) => x.reveal());
  let mapDone = false;
  const dc = document.getElementById("dtl-controls");
  if (dc) dc.addEventListener("toggle", () => { if (dc.open && !mapDone) { mapDone=true; setTimeout(() => initAirControlMap(d), 120); } });
  initPill(d);
  initAnalystLayer(d);
  wireCopyLink(document.getElementById("copy-link-btn"));
  initHowItWorksDrawer();
  const footer = document.getElementById("site-footer");
  if (footer) footer.innerHTML = `<span>NO₂: London Air Quality Network + DEFRA AURN. Weather: ERA5 reanalysis. Policy boundary: TfL / Greater London Authority.</span><span><a href="/track-record">Track record</a> · <a href="https://github.com/Mohib314159/carbon-twin" target="_blank" rel="noopener">Source</a></span>`;
}

function render(d) {
  if (d.domain === "air") return renderAir(d);
  document.title = (d.label ? `${d.label} — ` : "") + "Otherwise";
  document.getElementById("copy-link-btn").style.display = "inline-block";

  contentEl.innerHTML =
    renderVerdictTop(d) +
    renderAct1(d) +
    renderControlsImagery(d) +
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
  initAnalystLayer(d);
  wireCopyLink(document.getElementById("copy-link-btn"));
  initHowItWorksDrawer();
  renderFooter(document.getElementById("site-footer"), { withHowItWorks: false });
}

// ---- analyst layer -----------------------------------------------------------
//
// A human annotation attached to this run: the reviewer's call, a status, a
// note and evidence links. It sits below the verdict and below everything the
// tool computed, in a box labelled "Human annotation", and it never changes
// the verdict: nothing in here is read by the pipeline, and the API that
// stores it is separate from the one that serves the run. Persisted through
// the review router (src/app/review.py); if that router is not mounted, the
// section is simply not shown.

const ANALYST_STYLE = `
.analyst { margin: 40px 0 72px; border-top: 1px solid var(--rule); padding-top: 18px; }
.analyst .analyst-kicker { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 500; }
.analyst h2 { font-size: 19px; font-weight: 600; margin-top: 6px; }
.analyst .analyst-sub { color: var(--muted); font-size: 13px; max-width: 620px; margin-top: 6px; }
.analyst .ann { border: 1px solid var(--rule); background: var(--panel); padding: 12px; margin-top: 12px; }
.analyst .ann-head { display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline; font-size: 13px; }
.analyst .ann-call { font-weight: 600; }
.analyst .ann-status { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; border: 1px solid var(--rule); padding: 1px 6px; }
.analyst .ann-note { margin-top: 8px; white-space: pre-wrap; }
.analyst .ann-links { margin-top: 8px; font-size: 13px; word-break: break-all; }
.analyst form { margin-top: 14px; display: grid; gap: 10px; max-width: 620px; }
.analyst select, .analyst input, .analyst textarea { font: inherit; padding: 7px 9px; border: 1px solid var(--rule); background: var(--panel); color: var(--ink); border-radius: 2px; }
.analyst .analyst-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.analyst .analyst-msg { font-size: 13px; color: var(--muted); }
`;

const CALL_WORDS = { changed: "Analyst: changed", not_changed: "Analyst: not changed", unsure: "Analyst: unsure" };

/** The analyst token from ?analyst=..., or "" for everyone else. */
function analystToken() {
  try { return new URLSearchParams(location.search).get("analyst") || ""; } catch (_) { return ""; }
}

function annotationHtml(a) {
  const links = (a.links || [])
    .map((u) => `<a href="${escapeHtml(u)}" target="_blank" rel="noopener">${escapeHtml(u)}</a>`)
    .join(" · ");
  return `
    <div class="ann">
      <div class="ann-head">
        ${a.call ? `<span class="ann-call">${escapeHtml(CALL_WORDS[a.call] || a.call)}</span>` : ""}
        ${a.status ? `<span class="ann-status">${escapeHtml(String(a.status).replace("_", " "))}</span>` : ""}
        <span class="muted">${escapeHtml(a.author || "anonymous")} · ${escapeHtml((a.created || "").slice(0, 10))}</span>
      </div>
      ${a.note ? `<div class="ann-note">${escapeHtml(a.note)}</div>` : ""}
      ${links ? `<div class="ann-links">${links}</div>` : ""}
    </div>`;
}

async function initAnalystLayer(d) {
  let data;
  try {
    data = await apiGet(`/api/review/annotations/${encodeURIComponent(d.id)}`);
  } catch (err) {
    return;                       // review router not mounted: no analyst layer
  }
  if (!document.getElementById("analyst-style")) {
    const st = document.createElement("style");
    st.id = "analyst-style";
    st.textContent = ANALYST_STYLE;
    document.head.appendChild(st);
  }
  const section = document.createElement("section");
  section.className = "analyst";
  section.id = "analyst-layer";
  contentEl.appendChild(section);

  let annotations = data.annotations || [];
  const token = analystToken();

  function draw() {
    section.innerHTML = `
      <div class="analyst-kicker">Human annotation</div>
      <h2>Analyst review</h2>
      <p class="analyst-sub">The verdict above is the tool's output: a statistical test of this area against matched control areas. Everything in this box was typed by a person, is kept beside that verdict as evidence, and does not change it.</p>
      ${annotations.length
        ? annotations.map(annotationHtml).join("")
        : `<p class="analyst-sub" style="margin-top:12px">No analyst has annotated this run yet.</p>`}
      ${token ? `<form id="ann-form">
        <div class="analyst-row">
          <label>Call
            <select name="call">
              <option value="">no call</option>
              <option value="changed">changed</option>
              <option value="not_changed">not changed</option>
              <option value="unsure">unsure</option>
            </select>
          </label>
          <label>Status
            <select name="status">
              <option value="in_review">in review</option>
              <option value="confirmed">confirmed</option>
              <option value="disputed">disputed</option>
            </select>
          </label>
          <input name="author" type="text" placeholder="Your name (optional)" aria-label="Author">
        </div>
        <textarea name="note" rows="3" placeholder="What did you check, and what did you see?" aria-label="Note"></textarea>
        <input name="links" type="text" placeholder="Evidence links, space separated (https://…)" aria-label="Evidence links">
        <div class="analyst-row">
          <button class="btn" type="submit">Attach annotation</button>
          <span class="analyst-msg" id="ann-msg"></span>
        </div>
      </form>` : ""}`;
    const form = section.querySelector("#ann-form");
    const msg = section.querySelector("#ann-msg");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(form);
      msg.textContent = "Saving…";
      try {
        const res = await apiPost("/api/review/annotations", {
          run_id: d.id,
          call: (f.get("call") || "").toString(),
          status: (f.get("status") || "").toString(),
          note: (f.get("note") || "").toString().slice(0, 4000),
          links: (f.get("links") || "").toString().split(/\s+/).filter(Boolean),
          author: (f.get("author") || "").toString().slice(0, 80),
        }, { "X-Review-Token": token });
        annotations = [res.annotation].concat(annotations);
        draw();
      } catch (err) {
        msg.textContent = `Could not save: ${err.message}`;
      }
    });
  }
  draw();
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
