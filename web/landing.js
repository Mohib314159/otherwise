// Otherwise — landing page: map, showcase, draw-and-run form.
import {
  apiGet, apiPost, fmtDate, fmtHa, fmtSignalValue, todayISO, initHowItWorksDrawer,
  VERDICT_LABEL, CHANGE_TYPE_LABEL, SIGNAL_LABEL,
} from "./common.js";

const LIGHT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const LIGHT_ATTR = "&copy; OpenStreetMap contributors";
const SAT_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const SAT_ATTR = "Esri, Maxar, Earthstar Geographics";

// Area limits and the WGS84 / UTM constants behind them. These mirror
// src/app/geometry.py: the server reprojects the drawn polygon to its local UTM
// zone, takes the planar area and raises PolygonError outside these bounds, so
// the client has to measure the same way or the two numbers disagree.
const MIN_HA = 0.5;
const MAX_HA = 500;
const WGS84_A = 6378137.0;                     // semi-major axis, m
const WGS84_F = 1 / 298.257223563;             // flattening
const WGS84_E2 = WGS84_F * (2 - WGS84_F);      // first eccentricity squared
const WGS84_EP2 = WGS84_E2 / (1 - WGS84_E2);   // second eccentricity squared
const UTM_K0 = 0.9996;                         // UTM central-meridian scale
const DEG = Math.PI / 180;
const COORD_PRECISION = 1e6;                   // 6 dp, as Leaflet's toGeoJSON writes

initHowItWorksDrawer();

// ---- map -------------------------------------------------------------------

const map = L.map("map", { zoomControl: true, attributionControl: true }).setView([20, 0], 2);
window.__DEBUG_MAP = map;
const lightLayer = L.tileLayer(LIGHT_TILES, { attribution: LIGHT_ATTR, maxZoom: 19, subdomains: "abcd" });
const satLayer = L.tileLayer(SAT_TILES, { attribution: SAT_ATTR, maxZoom: 19 }).addTo(map);

const satToggle = document.getElementById("sat-toggle");
const mapStyleLabel = document.getElementById("map-style-label");
const desktopMosaic = window.matchMedia("(min-width: 641px)");
let satOn = true;
let heroMapView = false;
satToggle.classList.add("active");

function syncMapToggleLabel() {
  if (!mapStyleLabel) return;
  if (desktopMosaic.matches && !document.body.classList.contains("is-workbench")) {
    mapStyleLabel.textContent = heroMapView ? "Mosaic" : "Map";
    return;
  }
  mapStyleLabel.textContent = satOn ? "Satellite" : "Street map";
}

function setHeroMapView(on) {
  heroMapView = Boolean(on);
  document.body.classList.toggle("hero-map-view", heroMapView);
  syncMapToggleLabel();
  if (heroMapView) setTimeout(() => map.invalidateSize({ pan: false }), 80);
}

satToggle.addEventListener("click", () => {
  if (desktopMosaic.matches && !document.body.classList.contains("is-workbench")) {
    setHeroMapView(!heroMapView);
    return;
  }
  satOn = !satOn;
  if (satOn) { map.removeLayer(lightLayer); map.addLayer(satLayer); }
  else { map.removeLayer(satLayer); map.addLayer(lightLayer); }
  satToggle.classList.toggle("active", satOn);
  satToggle.setAttribute("aria-pressed", String(satOn));
  syncMapToggleLabel();
});
desktopMosaic.addEventListener?.("change", () => {
  if (!desktopMosaic.matches) setHeroMapView(false);
  else syncMapToggleLabel();
});
syncMapToggleLabel();

const drawnItems = new L.FeatureGroup().addTo(map);

// ---- product shell ---------------------------------------------------------

const heroStart = document.getElementById("hero-start");
const heroCases = document.getElementById("hero-cases");
const workbench = document.getElementById("side-panel");
const workbenchClose = document.getElementById("workbench-close");
const stepPlace = document.getElementById("step-place");
const stepCount = document.getElementById("step-count");
const drawCoach = document.getElementById("draw-coach");
const drawCoachCancel = document.getElementById("draw-coach-cancel");
const caseRail = document.getElementById("case-rail");
const caseClose = document.getElementById("case-close");

function setStep(n) {
  if (stepCount) stepCount.textContent = `${n} / 3`;
  document.querySelectorAll("[data-step-dot]").forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.stepDot) <= n);
  });
}

function openWorkbench() {
  document.body.classList.remove("show-cases", "hero-map-view");
  heroMapView = false;
  document.body.classList.add("is-workbench");
  if (workbench) workbench.setAttribute("aria-hidden", "false");
  setStep(currentGeoJSON ? 2 : 1);
  syncMapToggleLabel();
  setTimeout(() => map.invalidateSize({ pan: false }), 360);
}

function closeWorkbench() {
  document.body.classList.remove("is-workbench", "is-drawing", "hero-map-view");
  heroMapView = false;
  if (drawHandler) drawHandler.disable();
  if (workbench) workbench.setAttribute("aria-hidden", "true");
  syncMapToggleLabel();
  setTimeout(() => map.invalidateSize({ pan: false }), 360);
}

heroStart?.addEventListener("click", openWorkbench);
workbenchClose?.addEventListener("click", closeWorkbench);
heroCases?.addEventListener("click", () => {
  if (matchMedia("(max-width: 640px)").matches) {
    document.body.classList.toggle("show-cases");
    document.body.classList.remove("is-workbench");
  } else if (caseRail) {
    caseRail.animate([{ transform: "translateY(0)" }, { transform: "translateY(-8px)" }, { transform: "translateY(0)" }], { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
});
caseClose?.addEventListener("click", () => document.body.classList.remove("show-cases"));
map.on("click", () => document.body.classList.remove("show-cases"));

if (location.hash === "#new") {
  requestAnimationFrame(() => openWorkbench());
}

// ---- showcase ----------------------------------------------------------------

async function loadShowcase() {
  const listEl = document.getElementById("showcase-list");
  const emptyEl = document.getElementById("showcase-empty");
  let entries = [];
  try {
    entries = await apiGet("/api/showcase");
  } catch (_) {
    entries = [];
  }
  if (!entries.length) {
    emptyEl.style.display = "block";
    return;
  }

  const bounds = L.latLngBounds([]);
  entries.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "sc-card";

    const thumb = entry.thumb
      ? `<img class="sc-thumb" src="${escapeHtml(entry.thumb)}" alt="" loading="lazy">`
      : `<div class="sc-thumb placeholder"></div>`;
    const verdictLabel = VERDICT_LABEL[entry.status] || entry.status;
    const changeLabel = CHANGE_TYPE_LABEL[entry.change_type] || entry.change_type;

    card.innerHTML = `
      ${thumb}
      <div class="sc-body">
        <div class="sc-label">${escapeHtml(entry.label)}</div>
        <div class="sc-meta">${escapeHtml(changeLabel)} &middot; ${fmtDate(entry.event_date)} &middot; ${fmtHa(entry.area.ha)}</div>
        <div class="sc-verdict"><span class="dot dot-${entry.status}"></span><span class="v-${entry.status}">${escapeHtml(verdictLabel)}</span></div>
        <div class="sc-effect" data-effect></div>
      </div>`;

    const layer = L.geoJSON(entry.area.geojson, {
      style: { color: "var(--ink)", weight: 1.5, fill: false },
    }).addTo(map);
    layer.bindTooltip(entry.label, { permanent: false, direction: "top", className: "area-label" });
    bounds.extend(layer.getBounds());
    // a small dot so each showcase site is visible at world zoom; hover for the name, click to open
    const c = layer.getBounds().getCenter();
    const dot = L.circleMarker(c, { radius: 5, color: "#f6f4ee", weight: 1.5, fillColor: "#161616", fillOpacity: 0.9 }).addTo(map);
    dot.bindTooltip(entry.label, { permanent: false, direction: "top", className: "area-label" });
    dot.on("click", () => { location.href = `/v/${entry.id}`; });

    const mosaicTile = [...document.querySelectorAll(".mosaic-tile")].find((el) => el.dataset.runId === entry.id);
    card.addEventListener("mouseenter", () => {
      layer.setStyle({ color: "var(--counter)", weight: 2.5 });
      mosaicTile?.classList.add("is-active");
    });
    card.addEventListener("mouseleave", () => {
      layer.setStyle({ color: "var(--ink)", weight: 1.5 });
      mosaicTile?.classList.remove("is-active");
    });
    card.addEventListener("click", () => { location.href = `/v/${entry.id}`; });

    listEl.appendChild(card);
    loadEffectSize(entry.id, card.querySelector("[data-effect]"));
  });
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40] });
}

/** Signal value with sign, using a proper Unicode minus (U+2212) for negatives. */
function fmtSigned(signal, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const s = fmtSignalValue(signal, value, { sign: true });
  return value < 0 ? s.replace("-", "−") : s;
}

/** Lazily fills in a card's effect-size line from its run JSON. Fails quietly. */
async function loadEffectSize(id, el) {
  let run;
  try {
    run = await apiGet(`/api/runs/${id}`);
  } catch (_) {
    return;
  }
  const lead = run.verdict && run.verdict.lead_signal;
  const sig = lead && run.signals && run.signals[lead];
  if (!sig) return;
  const point = fmtSigned(lead, sig.point);
  if (point === null) return;
  const label = SIGNAL_LABEL[lead] || lead;
  el.textContent = `${point} ${label} vs matched places`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

loadShowcase();

// ---- place search ----------------------------------------------------------

const NOMINATIM_URL = "https://nominatim.openstreetmap.org/search";
const placeInput = document.getElementById("place-search-input");
const placeBtn = document.getElementById("place-search-btn");
const placeError = document.getElementById("place-search-error");
let lastPlaceSearchAt = 0;

async function searchPlace() {
  const q = placeInput.value.trim();
  if (!q) return;
  const now = Date.now();
  if (now - lastPlaceSearchAt < 1000) return; // at most one request per second
  lastPlaceSearchAt = now;
  placeError.style.display = "none";
  placeError.textContent = "";
  try {
    const url = `${NOMINATIM_URL}?format=json&limit=1&q=${encodeURIComponent(q)}`;
    const res = await fetch(url, { headers: { "Accept-Language": "en" } });
    const results = res.ok ? await res.json() : [];
    if (!results.length) {
      placeError.textContent = "No place found";
      placeError.style.display = "block";
      return;
    }
    const r = results[0];
    if (Array.isArray(r.boundingbox) && r.boundingbox.length === 4) {
      const [south, north, west, east] = r.boundingbox.map(Number);
      map.fitBounds([[south, west], [north, east]], { padding: [40, 40] });
    } else {
      map.setView([Number(r.lat), Number(r.lon)], 14);
    }
  } catch (_) {
    placeError.textContent = "No place found";
    placeError.style.display = "block";
  }
}

window.__DEBUG_SEARCH = searchPlace;
placeBtn.addEventListener("click", searchPlace);
placeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); searchPlace(); }
});

// ---- draw an area --------------------------------------------------------------

const drawBtn = document.getElementById("draw-btn");
const runForm = document.getElementById("run-form");
const areaHaLine = document.getElementById("area-ha-line");
let drawHandler = null;
let currentGeoJSON = null;
let currentHa = null;

drawBtn.addEventListener("click", () => {
  if (drawHandler) drawHandler.disable();
  document.body.classList.add("is-drawing");
  document.body.classList.remove("show-cases");
  drawHandler = new L.Draw.Polygon(map, {
    shapeOptions: { color: "#d9ff71", weight: 2, fillOpacity: 0.10, fillColor: "#d9ff71" },
    showArea: false,
    allowIntersection: false,
  });
  drawHandler.enable();
});

drawCoachCancel?.addEventListener("click", () => {
  if (drawHandler) drawHandler.disable();
  document.body.classList.remove("is-drawing");
});

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  onPolygonReady(e.layer);
});

/** Longitude into [-180, 180). Leaflet pans across world copies, so a drawn
 *  ring can carry lng 358.5 for a point that is really at -1.5. */
function wrapLng(lng) {
  return lng - Math.floor((lng + 180) / 360) * 360;
}

/** Leaflet's toGeoJSON rounds to 6 dp; measure exactly what we will send. */
function round6(x) {
  return Math.round(x * COORD_PRECISION) / COORD_PRECISION;
}

/** UTM zone for a longitude, clamped as src/app/geometry.py::utm_epsg does. */
function utmZone(lon) {
  return Math.min(Math.max(Math.floor((lon + 180) / 6) + 1, 1), 60);
}

/** WGS84 lon/lat to UTM easting/northing (Snyder's series; mm-accurate in zone). */
function toUTM(lon, lat, zone) {
  const lon0 = (zone - 1) * 6 - 180 + 3;
  const phi = lat * DEG;
  const sp = Math.sin(phi), cp = Math.cos(phi), tp = Math.tan(phi);
  const n = WGS84_A / Math.sqrt(1 - WGS84_E2 * sp * sp);
  const t = tp * tp;
  const c = WGS84_EP2 * cp * cp;
  const a = ((lon - lon0) * DEG) * cp;
  const a2 = a * a;
  const e2 = WGS84_E2, e4 = e2 * e2, e6 = e4 * e2;
  const m = WGS84_A * (
    (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
    - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
    + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi)
    - (35 * e6 / 3072) * Math.sin(6 * phi));
  const x = UTM_K0 * n * (a
    + (1 - t + c) * a2 * a / 6
    + (5 - 18 * t + t * t + 72 * c - 58 * WGS84_EP2) * a2 * a2 * a / 120) + 500000;
  const y = UTM_K0 * (m + n * tp * (a2 / 2
    + (5 - t + 9 * c + 4 * c * c) * a2 * a2 / 24
    + (61 - 58 * t + t * t + 600 * c - 330 * WGS84_EP2) * a2 * a2 * a2 / 720));
  return [x, y];
}

/** Planar centroid of a [lon, lat] ring — the same point shapely picks the zone from. */
function ringCentroid(ring) {
  let a2 = 0, cx = 0, cy = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x0, y0] = ring[i], [x1, y1] = ring[(i + 1) % ring.length];
    const cross = x0 * y1 - x1 * y0;
    a2 += cross; cx += (x0 + x1) * cross; cy += (y0 + y1) * cross;
  }
  if (a2 === 0) {
    const n = ring.length;
    return [ring.reduce((s, p) => s + p[0], 0) / n, ring.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (3 * a2), cy / (3 * a2)];
}

/** Hectares, measured as the server does: local UTM, then shoelace. */
function polygonAreaHa(ring) {
  const zone = utmZone(ringCentroid(ring)[0]);
  const pts = ring.map(([lon, lat]) => toUTM(lon, lat, zone));
  let area2 = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    area2 += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(area2 / 2) / 10000; // m^2 -> ha
}

/** Drawn layer to an open [lon, lat] ring: longitudes unwrapped to one world
 *  copy, coordinates rounded to what will actually be posted. */
function ringFromLayer(layer) {
  const latlngs = layer.getLatLngs()[0];
  // Shift every vertex by the same multiple of 360 so the ring stays contiguous.
  const shift = wrapLng(latlngs[0].lng) - latlngs[0].lng;
  return latlngs.map((p) => [round6(p.lng + shift), round6(p.lat)]);
}

function areaOk() {
  return currentHa !== null && currentHa >= MIN_HA && currentHa <= MAX_HA;
}

function onPolygonReady(layer) {
  const ring = ringFromLayer(layer);
  currentHa = polygonAreaHa(ring);
  currentGeoJSON = { type: "Polygon", coordinates: [ring.concat([ring[0]])] };
  document.body.classList.remove("is-drawing");
  document.body.classList.add("is-workbench");
  renderHa();
  if (stepPlace) stepPlace.style.display = "none";
  runForm.style.display = "block";
  runErrorEl.style.display = "none";
  setStep(2);
  const head = workbench?.querySelector(".workbench-head h2");
  if (head) head.textContent = "Describe the event.";
  // Keep the next action inside the visible panel on short screens.
  submitBtn.scrollIntoView({ block: "nearest" });
}

function renderHa() {
  const ok = areaOk();
  areaHaLine.classList.toggle("bad", !ok);
  const haStr = currentHa.toFixed(currentHa < 10 ? 2 : 1);
  areaHaLine.textContent = ok
    ? `${haStr} ha`
    : `${haStr} ha — must be between ${MIN_HA} and ${MAX_HA} hectares`;
  submitBtn.disabled = !ok;
}

const redrawBtn = document.getElementById("redraw-btn");
redrawBtn?.addEventListener("click", () => drawBtn.click());

// Exposed for the browser regression test, alongside __DEBUG_MAP above.
window.__DEBUG_AREA = { polygonAreaHa, ringFromLayer, wrapLng, areaOk: () => areaOk() };

// ---- form ------------------------------------------------------------------

const dateInput = document.getElementById("f-date");
dateInput.max = todayISO();

const changeTypeSelect = document.getElementById("f-change-type");
const postMonthsSelect = document.getElementById("f-post-months");
const labelInput = document.getElementById("f-label");
const submitBtn = document.getElementById("submit-btn");
const runErrorEl = document.getElementById("run-error");

let postMonthsTouched = false;
postMonthsSelect.addEventListener("change", () => { postMonthsTouched = true; });
changeTypeSelect.addEventListener("change", () => {
  if (changeTypeSelect.value === "flood" && !postMonthsTouched) postMonthsSelect.value = "3";
});

const progressBlock = document.getElementById("progress-block");
let progressFill = document.getElementById("progress-fill");
let progressStage = document.getElementById("progress-stage");
let pollTimer = null;

function stageSentence(job) {
  if (job.status === "queued") {
    const n = job.queue_position || 0;
    return `Waiting for a free slot (${n} ahead)`;
  }
  const stage = job.stage || "";
  if (stage === "search" || stage === "fetch" || stage === "cache" || stage === "starting") {
    return "Searching the catalogues";
  }
  // Stage names carry a suffix in the two-pass fetch: "sentinel-2" for the drawn
  // area, "sentinel-2 controls" for the control cells, plus " group i/n" when the
  // controls are read in several windows. Match on the prefix so every pass gets
  // a real sentence instead of falling through to "Working...".
  const sat = stage.startsWith("sentinel-2") ? "Sentinel-2" : stage.startsWith("sentinel-1") ? "Sentinel-1" : null;
  if (sat) {
    const what = stage.includes("controls") || stage.includes("group") ? "control areas" : "your area";
    const m = stage.match(/group (\d+)\/(\d+)/);
    const grp = m ? ` (window ${m[1]} of ${m[2]})` : "";
    return `Reading ${sat} over ${what}${grp}: scene ${job.done} of ${job.total}`;
  }
  if (stage === "covariates") return "Reading land cover and terrain";
  if (stage.endsWith(": fitting")) return `Fitting the control trajectory (${stage.split(":")[0]})`;
  if (stage.endsWith(": placebo")) return `Running placebo checks (${stage.split(":")[0]})`;
  if (stage === "imagery") return "Fetching before/after imagery";
  if (stage === "done") return "Done";
  return "Working…";
}

function stageProgressFraction(job) {
  const order = ["queued", "starting", "fetch", "search", "cache", "sentinel-2", "sentinel-1", "covariates"];
  if (job.status === "queued") return 0.03;
  const stage = job.stage || "";
  // Within a read stage, advance by scenes done rather than sitting still: the
  // control pass is the longest part of a run and used to look frozen.
  if (stage.startsWith("sentinel-")) {
    const base = stage.includes("controls") || stage.includes("group") ? 0.35 : 0.12;
    const span = stage.includes("controls") || stage.includes("group") ? 0.35 : 0.23;
    const frac = job.total > 0 ? Math.min(job.done / job.total, 1) : 0;
    return base + span * frac;
  }
  const idx = order.indexOf(job.stage);
  if (job.stage && (job.stage.endsWith(": fitting") || job.stage.endsWith(": placebo"))) return 0.75;
  if (job.stage === "imagery") return 0.92;
  if (job.stage === "done") return 1;
  if (idx >= 0) return 0.08 + (idx / order.length) * 0.55;
  return 0.5;
}

function showRunError(msg) {
  runErrorEl.textContent = msg;
  runErrorEl.style.display = "block";
  runErrorEl.scrollIntoView({ block: "nearest" });
}

function resetToForm() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  progressBlock.style.display = "none";
  runForm.style.display = "block";
  submitBtn.disabled = !areaOk();
  submitBtn.textContent = "Run comparison";
  setStep(2);
}

runForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentGeoJSON || !areaOk()) return;
  runErrorEl.style.display = "none";
  submitBtn.disabled = true;
  submitBtn.textContent = "Starting…";

  const payload = {
    geojson: currentGeoJSON,
    event_date: dateInput.value,
    change_type: changeTypeSelect.value,
    post_months: Number(postMonthsSelect.value),
    label: labelInput.value.trim(),
  };

  try {
    const resp = await apiPost("/api/run", payload);
    if (resp.done) {
      location.href = `/v/${resp.run_id}`;
      return;
    }
    runForm.style.display = "none";
    progressBlock.style.display = "block";
    setStep(3);
    const head = workbench?.querySelector(".workbench-head h2");
    if (head) head.textContent = "Building the comparison.";
    showProgressLink(resp.run_id);
    pollJob(resp.job_id, resp.run_id);
  } catch (err) {
    submitBtn.disabled = false;
    submitBtn.textContent = "Run comparison";
    if (err.status === 400 || err.status === 503) {
      showRunError(err.detail || err.message);
    } else {
      showRunError(err.message || "Something went wrong. Try again.");
    }
  }
});

function pollJob(jobId, fallbackRunId) {
  const poll = async () => {
    let job;
    try {
      job = await apiGet(`/api/jobs/${jobId}`);
    } catch (err) {
      return; // transient network hiccup; try again next tick
    }
    if (job.status === "error") {
      clearInterval(pollTimer); pollTimer = null;
      progressBlock.innerHTML = `
        <div style="color:var(--notreal);">${escapeHtml(job.error || "The run failed.")}</div>
        <a href="#" id="try-again-link" class="small" style="margin-top:8px;display:inline-block;">Try again</a>`;
      document.getElementById("try-again-link").addEventListener("click", (e) => {
        e.preventDefault();
        rebuildProgressBlock();
        resetToForm();
      });
      return;
    }
    if (job.status === "done") {
      clearInterval(pollTimer); pollTimer = null;
      location.href = `/v/${job.run_id || fallbackRunId}`;
      return;
    }
    progressStage.textContent = stageSentence(job);
    progressFill.style.width = `${Math.round(stageProgressFraction(job) * 100)}%`;
  };
  poll();
  pollTimer = setInterval(poll, 1500);
}

// Kept identical to the block in web/index.html. No minute count: the only live
// runs timed so far ran on other hardware, and this deployment has a fraction of
// a CPU, so a range would be invented rather than measured.
const PROGRESS_NOTE =
  "Live checks can take tens of minutes or longer because they read several years of satellite scenes. "
  + "You can close this tab; the run keeps going at the link below.";

function rebuildProgressBlock() {
  progressBlock.innerHTML = `
    <div class="progress-orbit" aria-hidden="true"><span></span><i></i></div>
    <div class="form-kicker">Running</div>
    <h3 id="progress-stage">Starting&hellip;</h3>
    <div class="progress-wrap" aria-hidden="true"><div class="progress-bar-track"><div class="progress-bar-fill" id="progress-fill"></div></div></div>
    <div class="progress-pipeline" aria-hidden="true"><span class="done">Area</span><span>Controls</span><span>Placebos</span><span>Evidence</span></div>
    <p class="progress-note">${escapeHtml(PROGRESS_NOTE)}</p>
    <div class="progress-link" id="progress-link"></div>
    <p class="quick-disclosure">Live checks use a faster control read than the published examples. The verdict page labels this clearly.</p>`;
  progressFill = document.getElementById("progress-fill");
  progressStage = document.getElementById("progress-stage");
}

/** The run's permalink, shown while it runs so closing the tab loses nothing. */
function showProgressLink(runId) {
  const el = document.getElementById("progress-link");
  if (!el || !runId) return;
  const href = `/v/${encodeURIComponent(runId)}`;
  el.innerHTML = `<span class="muted">Keep this link</span><br><a href="${escapeHtml(href)}">${escapeHtml(location.origin + href)}</a>`;
}
