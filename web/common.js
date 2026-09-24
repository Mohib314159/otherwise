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
  NO2_TRAFFIC: "roadside / traffic NO₂",
  NO2_BACKGROUND: "urban-background NO₂",
};

export const RADAR_SIGNALS = new Set(["VV", "VH", "RATIO"]);
export const AIR_SIGNALS = new Set(["NO2_TRAFFIC", "NO2_BACKGROUND"]);

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
  if (AIR_SIGNALS.has(signal)) return `${s}${value.toFixed(1)} µg/m³`;
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
<h2 style="font-size:20px;font-weight:600;margin:4px 0 4px;">How this works</h2>
<p>Most tools tell you something changed. Otherwise asks whether it changed more than it would have anyway.</p>
<h3>1. Data</h3>
<p>The data depend on the question. Land uses Sentinel-2 optical and Sentinel-1 radar. Air pollution uses hourly ground NO₂ monitors from LAQN and DEFRA AURN plus ERA5 meteorology. Every observation thrown out is listed in the receipts.</p>
<h3>2. Controls</h3>
<p>Controls are matched to the unit being tested. Land uses nearby cells with similar land cover, terrain and pre-event history. Air uses same-type monitors in other UK cities, excluding a London spillover buffer, then ranks them by pre-policy NO₂ trajectory and baseline level.</p>
<h3>3. Counterfactual</h3>
<p>An augmented synthetic control (Ben-Michael, Feller &amp; Rothstein, 2021) builds the no-event trajectory as a weighted average of control cells, with a ridge correction for what the weights could not match. The gap after the event is the estimated effect.</p>
<h3>4. Uncertainty</h3>
<p>A conformal interval (Chernozhukov, W&uuml;thrich &amp; Zhu, 2021) is formed by refitting under hypothetical effect sizes and comparing post-event residuals with block permutations of the whole residual sequence. No distribution is assumed.</p>
<h3>5. Placebo checks</h3>
<p>The same test is run on untouched comparison units as if they were treated, and at fake event dates before the real one. Air placebos reselect their own controls and ridge penalty and use fake cohorts the same size as the treated cohort. If the method finds effects where there are none, the verdict says so.</p>
<h3>6. Verdict</h3>
<p>Real change: the interval excludes zero in the claimed direction, the effect exceeds a minimum meaningful size, and the placebo rate is low. Not real: the interval rules out a meaningful change. Can't tell: too few clear observations, a poor pre-event fit, or an interval too wide to decide.</p>
<h3>Prior art</h3>
<ul class="prior-art">
  <li><a href="https://github.com/oballinger/PWTT" target="_blank" rel="noopener">PWTT (Ballinger)</a> — pixel-wise t-test against each pixel's own history, no matched controls.</li>
  <li><a href="https://github.com/quantifyearth/tmf-implementation" target="_blank" rel="noopener">Cambridge 4C PACT / tmf-implementation</a> — pixel-matched counterfactuals for tropical forest carbon, command line, on a forest-cover map.</li>
  <li><a href="https://github.com/epingchris/placebo_evaluation" target="_blank" rel="noopener">Placebo evaluation of counterfactual methods (4C, 2025)</a> — the idea behind the placebo check.</li>
  <li>Global Forest Watch, Pachama dynamic baselines, CTrees LUCA, Earth Blox.</li>
</ul>
`;

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
