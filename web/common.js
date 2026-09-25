// Otherwise — shared helpers: fetch, formatting, verdict colours, drawer, footer.

export const VERDICT_LABEL = { REAL: "Real change", NOT_REAL: "Not real", CANT_TELL: "Can't tell" };
export const VERDICT_VAR = { REAL: "--real", NOT_REAL: "--notreal", CANT_TELL: "--canttell" };

export const CHANGE_TYPE_LABEL = {
  clearing: "Clearing",
  regrowth: "Regrowth",
  flood: "Flood",
  burn: "Burn",
  construction: "Construction",
  other: "Other",
};

export const SIGNAL_LABEL = {
  NDVI: "greenness (NDVI)",
  NDWI: "surface water (NDWI)",
  NBR: "burn ratio (NBR)",
  VV: "radar VV backscatter (dB)",
  VH: "radar VH backscatter (dB)",
  RATIO: "radar VH/VV (dB)",
};

export const RADAR_SIGNALS = new Set(["VV", "VH", "RATIO"]);

export const REASON_LABEL = {
  cloud: "Cloud or shadow over the area",
  haze: "Haze the classifier missed",
  duplicate: "Duplicate acquisition (tile overlap, merged)",
  orbit: "Different radar orbit (look angle)",
  edge: "Radar swath edge",
  "read-error": "Could not read scene",
};

// ---- fetch helpers ---------------------------------------------------------

export async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch (_) { /* not json */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let json = null;
  try { json = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const err = new Error((json && json.detail) || res.statusText);
    err.status = res.status;
    err.detail = json && json.detail;
    throw err;
  }
  return json;
}

// ---- formatting -------------------------------------------------------------

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2020-02-14" (or "2020-02-14T10:03:00Z") -> "14 Feb 2020" */
export function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** value formatted per-signal: indices to 2dp, radar (dB) to 1dp with suffix. */
export function fmtSignalValue(signal, value, { sign = false } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = sign && value > 0 ? "+" : "";
  if (RADAR_SIGNALS.has(signal)) return `${s}${value.toFixed(1)} dB`;
  return `${s}${value.toFixed(2)}`;
}

export function fmtHa(ha) {
  if (ha === null || ha === undefined) return "—";
  const n = Number(ha);
  return (Number.isInteger(n) ? n.toString() : n.toFixed(n < 10 ? 2 : 1)) + " ha";
}

// ---- copy link ---------------------------------------------------------------

export function wireCopyLink(button) {
  if (!button) return;
  const original = button.textContent;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href);
    } catch (_) {
      // clipboard API unavailable — fall back to a selection-based copy
      const ta = document.createElement("textarea");
      ta.value = location.href;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (_) { /* give up quietly */ }
      document.body.removeChild(ta);
    }
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = original; }, 1500);
  });
}

// ---- "how this works" drawer --------------------------------------------------

const HOW_IT_WORKS_HTML = `
<button class="drawer-close" data-drawer-close aria-label="Close">&times;</button>
<div class="method-intro">
  <div class="label">Method</div>
  <h2>The idea in 20 seconds.</h2>
  <p>Seeing a change is easy. The useful question is whether this place changed <em>more than comparable places would have anyway</em>.</p>
</div>
<div class="method-flow">
  <div class="method-step">
    <span class="method-num">01</span>
    <div><strong>Find its twins.</strong><p>Nearby places that moved like this one before the event become the comparison.</p></div>
  </div>
  <div class="method-step">
    <span class="method-num">02</span>
    <div><strong>Hold that match fixed.</strong><p>We use the pre-event relationship to estimate what this place would have looked like without the event.</p></div>
  </div>
  <div class="method-step">
    <span class="method-num">03</span>
    <div><strong>Watch for the break.</strong><p>After the event, we measure how far the observed satellite signal pulls away from its counterfactual.</p></div>
  </div>
  <div class="method-step">
    <span class="method-num">04</span>
    <div><strong>Try to fool it.</strong><p>We repeat the test on control places and fake dates. If the method fires too easily, Otherwise does not call the change real.</p></div>
  </div>
</div>
<div class="verdict-key" aria-label="Verdict meanings">
  <div><span class="method-dot real"></span><strong>Real change</strong><small>Evidence clears the checks.</small></div>
  <div><span class="method-dot no"></span><strong>Not real</strong><small>A meaningful change is ruled out.</small></div>
  <div><span class="method-dot unsure"></span><strong>Can't tell</strong><small>The evidence is not strong enough.</small></div>
</div>
<details class="method-detail">
  <summary>Technical detail</summary>
  <div class="method-detail-body">
    <p>Sentinel-2 optical and Sentinel-1 radar observations are filtered for quality. Candidate controls are screened by land cover and terrain, then ranked by pre-event similarity.</p>
    <p>The counterfactual uses augmented synthetic control. Uncertainty is estimated with conformal inference, with spatial and pre-event placebo checks used as stress tests. Every excluded observation and intermediate diagnostic is kept in the run receipt.</p>
    <p class="method-cites">Methods: Ben-Michael, Feller &amp; Rothstein (2021); Chernozhukov, W&uuml;thrich &amp; Zhu (2021). Data via Microsoft Planetary Computer.</p>
  </div>
</details>
<div class="method-links">
  <a href="/track-record">Track record <span aria-hidden="true">↗</span></a>
  <a href="https://github.com/Mohib314159/carbon-twin" target="_blank" rel="noopener">Source <span aria-hidden="true">↗</span></a>
</div>`

/** Mounts the drawer + backdrop once, wires every [data-drawer-trigger] to open it. */
export function initHowItWorksDrawer() {
  if (document.getElementById("how-it-works-drawer")) return;
  const backdrop = document.createElement("div");
  backdrop.className = "drawer-backdrop";
  backdrop.id = "how-it-works-backdrop";
  const drawer = document.createElement("aside");
  drawer.className = "drawer";
  drawer.id = "how-it-works-drawer";
  drawer.innerHTML = HOW_IT_WORKS_HTML;
  document.body.appendChild(backdrop);
  document.body.appendChild(drawer);

  const open = () => { drawer.classList.add("open"); backdrop.classList.add("open"); };
  const close = () => { drawer.classList.remove("open"); backdrop.classList.remove("open"); };

  document.querySelectorAll("[data-drawer-trigger]").forEach((t) => {
    t.addEventListener("click", (e) => { e.preventDefault(); open(); });
  });
  drawer.querySelector("[data-drawer-close]").addEventListener("click", close);
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

// ---- footer --------------------------------------------------------------------

export const DATA_ATTRIBUTION =
  "Contains modified Copernicus Sentinel data. Land cover © ESA WorldCover. " +
  "Terrain © Copernicus DEM. Data via Microsoft Planetary Computer.";

export function renderFooter(el, { withHowItWorks = false } = {}) {
  if (!el) return;
  el.innerHTML = `
    <span>${DATA_ATTRIBUTION}</span>
    <span>
      ${withHowItWorks ? '<a href="#" data-drawer-trigger>How this works</a> · ' : ""}
      <a href="/track-record">Track record</a> ·
      <a href="https://github.com/Mohib314159/carbon-twin" target="_blank" rel="noopener">Source</a>
    </span>
  `;
}
