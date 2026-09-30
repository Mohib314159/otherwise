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
const drawCoachTitle = document.getElementById("draw-coach-title");
const drawCoachHint = document.getElementById("draw-coach-hint");
const drawLive = document.getElementById("draw-live");
const drawLiveValue = document.getElementById("draw-live-value");
const drawLiveState = document.getElementById("draw-live-state");
const drawUndo = document.getElementById("draw-undo");
const drawAdd = document.getElementById("draw-add");
const drawDone = document.getElementById("draw-done");
const mobileCrosshair = document.getElementById("mobile-map-crosshair");
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
  cancelDrawingMode();
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
    const firstCase = caseRail.querySelector(".sc-card");
    if (firstCase) {
      firstCase.focus({ preventScroll: true });
      firstCase.animate([{ transform: "translateY(0)" }, { transform: "translateY(-5px)" }, { transform: "translateY(0)" }], { duration: 460, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }
});
caseClose?.addEventListener("click", () => document.body.classList.remove("show-cases"));
map.on("click", () => document.body.classList.remove("show-cases"));

if (location.hash === "#new") {
  requestAnimationFrame(() => openWorkbench());
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (document.body.classList.contains("is-drawing")) {
    cancelDrawingMode();
    return;
  }
  if (document.body.classList.contains("show-cases")) {
    document.body.classList.remove("show-cases");
    return;
  }
  if (document.body.classList.contains("is-workbench")) closeWorkbench();
});

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
  entries.forEach((entry, index) => {
    const card = document.createElement("a");
    card.className = "sc-card";
    card.href = `/v/${entry.id}`;

    const [place, eventTitle] = splitExampleLabel(entry.label);
    card.setAttribute("aria-label", `Open evidence for ${entry.label}`);

    const beforeSrc = `/api/runs/${entry.id}/before.png`;
    const afterSrc = entry.thumb || `/api/runs/${entry.id}/after.png`;
    const loading = index < 3 ? "eager" : "lazy";
    const verdictLabel = VERDICT_LABEL[entry.status] || entry.status;
    const changeLabel = CHANGE_TYPE_LABEL[entry.change_type] || entry.change_type;

    card.innerHTML = `
      <div class="sc-visual" aria-hidden="true">
        <img class="sc-thumb sc-before" src="${escapeHtml(beforeSrc)}" alt="" loading="${loading}" decoding="async">
        <img class="sc-thumb sc-after" src="${escapeHtml(afterSrc)}" alt="" loading="${loading}" decoding="async">
        <span class="sc-seam"></span>
        <span class="sc-image-label sc-before-label">Before</span>
        <span class="sc-image-label sc-after-label">After</span>
      </div>
      <div class="sc-body">
        <div class="sc-verdict"><span class="dot dot-${entry.status}"></span><span class="v-${entry.status}">${escapeHtml(verdictLabel)}</span></div>
        <div class="sc-place">${escapeHtml(place)}</div>
        <div class="sc-label">${escapeHtml(eventTitle)}</div>
        <div class="sc-blurb">${escapeHtml(entry.blurb || `${changeLabel} · ${fmtDate(entry.event_date)}`)}</div>
        <div class="sc-foot">
          <span class="sc-effect" data-effect>${escapeHtml(fmtDate(entry.event_date))} · ${escapeHtml(fmtHa(entry.area.ha))}</span>
          <span class="sc-open">Open evidence <span aria-hidden="true">↗</span></span>
        </div>
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
    if (mosaicTile) {
      const titleEl = mosaicTile.querySelector("[data-mosaic-title]");
      if (titleEl) titleEl.textContent = `${place} · ${eventTitle}`;
      mosaicTile.setAttribute("aria-label", `Open evidence for ${entry.label}`);
    }
    const activate = () => {
      layer.setStyle({ color: "var(--counter)", weight: 2.5 });
      mosaicTile?.classList.add("is-active");
      card.classList.add("is-linked-active");
    };
    const deactivate = () => {
      layer.setStyle({ color: "var(--ink)", weight: 1.5 });
      mosaicTile?.classList.remove("is-active");
      card.classList.remove("is-linked-active");
    };
    [card, mosaicTile].filter(Boolean).forEach((el) => {
      el.addEventListener("mouseenter", activate);
      el.addEventListener("mouseleave", deactivate);
      el.addEventListener("focus", activate);
      el.addEventListener("blur", deactivate);
    });

    listEl.appendChild(card);
    loadEffectSize(entry.id, card.querySelector("[data-effect]"));
  });
  if (bounds.isValid()) {
    // Phones: frame the sites in the strip above the bottom hero panel.
    const phone = window.matchMedia("(max-width: 640px)").matches;
    const panel = document.getElementById("hero-panel");
    const panelH = phone && panel ? Math.ceil(panel.offsetHeight + 12) : 0;
    map.fitBounds(bounds, panelH
      ? { paddingTopLeft: [40, 70], paddingBottomRight: [40, panelH + 24] }
      : { padding: [40, 40] });
  }
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

function splitExampleLabel(label) {
  const raw = String(label || "Example check");
  const i = raw.indexOf(":");
  if (i < 0) return [raw, "Open the completed check"];
  return [raw.slice(0, i).trim(), raw.slice(i + 1).trim()];
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

loadShowcase();

// ---- signal family tabs / air-policy lab -----------------------------------

const domainLandBtn = document.getElementById("domain-land");
const domainAirBtn = document.getElementById("domain-air");
const landPanel = document.getElementById("land-analysis-panel");
const airPanel = document.getElementById("air-analysis-panel");
const domainIntro = document.getElementById("domain-intro");

function setDomain(domain) {
  const air = domain === "air";
  document.body.dataset.domain = domain;
  domainLandBtn.classList.toggle("active", !air);
  domainAirBtn.classList.toggle("active", air);
  domainLandBtn.setAttribute("aria-selected", String(!air));
  domainAirBtn.setAttribute("aria-selected", String(air));
  landPanel.style.display = air ? "none" : "block";
  airPanel.style.display = air ? "block" : "none";
  if (!air && airBoundaryLayer) { map.removeLayer(airBoundaryLayer); airBoundaryLayer = null; }
  if (air) renderAirCase();
  domainIntro.hidden = !air;
  domainIntro.textContent = air
    ? "Choose a policy. Otherwise weather-normalises ground NO₂, builds a same-type no-policy counterfactual from monitors in other UK cities, and reruns symmetric placebo tests before comparing with published research."
    : "Draw an area, name the event and its date. Sentinel-1 and Sentinel-2 are compared against matched control areas that did not get the event.";
  // Air does not need a hand-drawn polygon; keeping the map visible preserves
  // the showcase and makes the switch reversible without losing map state.
}

domainLandBtn.addEventListener("click", () => setDomain("land"));
domainAirBtn.addEventListener("click", () => setDomain("air"));

const airForm = document.getElementById("air-run-form");
const airCaseSelect = document.getElementById("air-case");
const airCaseDescription = document.getElementById("air-case-description");
const airPostMonths = document.getElementById("air-post-months");
const airLabel = document.getElementById("air-label");
const airSubmit = document.getElementById("air-submit-btn");
const airError = document.getElementById("air-run-error");
const airProgress = document.getElementById("air-progress-block");
const airProgressFill = document.getElementById("air-progress-fill");
const airProgressStage = document.getElementById("air-progress-stage");
const airProgressLink = document.getElementById("air-progress-link");
let airCases = [];
let airPollTimer = null;
let airBoundaryLayer = null;

function airCaseById(id) { return airCases.find((c) => c.id === id); }

async function renderAirCase() {
  const c = airCaseById(airCaseSelect.value);
  if (!c) return;
  const notes = (c.notes || []).join(" ");
  const exploratory = c.force_cant_tell ? " Exploratory only: this registered case cannot return a decisive headline." : "";
  airCaseDescription.textContent = `${c.label} · ${fmtDate(c.event_date)}. ${c.description || ""}${exploratory}${notes ? " " + notes : ""}`;
  if (c.default_post_months && !airPostMonths.dataset.touched) {
    airPostMonths.value = String(c.default_post_months);
  }
  // Loading the case catalogue must not move the land map or place a London
  // boundary over a user's drawn area. Only the active air tab owns this layer.
  if (domainAirBtn.getAttribute("aria-selected") !== "true") return;
  if (airBoundaryLayer) { map.removeLayer(airBoundaryLayer); airBoundaryLayer = null; }
  map.setView([51.5074, -0.1278], c.id === "ulez-central-2019" ? 11 : 9);
  try {
    const boundary = await apiGet(`/api/air/cases/${encodeURIComponent(c.id)}/boundary`);
    if (domainAirBtn.getAttribute("aria-selected") !== "true" || airCaseSelect.value !== c.id) return;
    const feats = boundary && boundary.type === "FeatureCollection" ? boundary.features : (boundary && boundary.geometry ? [boundary] : []);
    if (feats.length) {
      airBoundaryLayer = L.geoJSON(boundary, { style: { color:"#161616", weight:2.2, fillColor:"#161616", fillOpacity:.05 } }).addTo(map);
      airBoundaryLayer.bindTooltip(c.label, { sticky:true, className:"area-label" });
      map.fitBounds(airBoundaryLayer.getBounds(), { padding:[32,32] });
    }
  } catch (_) {
    // Boundary display is a convenience only; inability to render it must not
    // prevent the actual server-side run from using the official geometry.
  }
}

airPostMonths.addEventListener("change", () => { airPostMonths.dataset.touched = "1"; });
airCaseSelect.addEventListener("change", renderAirCase);

async function loadAirCases() {
  try {
    const payload = await apiGet("/api/air/cases");
    airCases = Array.isArray(payload) ? payload : (payload.cases || []);
    airCaseSelect.innerHTML = airCases
      .filter((c) => c.supported !== false)
      .map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.label)}</option>`)
      .join("");
    renderAirCase();
    // The tab only appears when the server has air enabled (APP_AIR_ENABLED=1);
    // otherwise /api/air/cases is a 404 and the page stays land-only.
    if (airCases.length) document.getElementById("domain-picker").style.display = "";
  } catch (err) {
    airCaseSelect.innerHTML = '<option value="">Air cases unavailable</option>';
    airSubmit.disabled = true;
    airCaseDescription.textContent = "Could not load the pre-registered air-policy cases.";
  }
}

function airStageSentence(job) {
  const stage = job.stage || "";
  if (job.status === "queued") return `Waiting for a free slot (${job.queue_position || 0} ahead)`;
  if (stage.includes("boundary")) return "Reading the official ULEZ boundary";
  if (stage.includes("London monitor metadata")) return "Finding London NO₂ monitors";
  if (stage.includes("national control metadata")) return "Finding same-type control monitors outside London";
  if (stage.includes("London NO2")) return `Weather-normalising London monitors: ${job.done || 0} of ${job.total || 0}`;
  if (stage.includes("control NO2")) return `Weather-normalising control monitors: ${job.done || 0} of ${job.total || 0}`;
  if (stage.includes("counterfactual")) return `Fitting ${stage.includes("traffic") ? "traffic" : "background"} counterfactual + symmetric placebos`;
  if (stage === "done") return "Done";
  return "Building the independent NO₂ counterfactual…";
}

function airStageProgress(job) {
  const stage = job.stage || "";
  if (job.status === "queued") return 0.03;
  if (stage.includes("boundary")) return 0.08;
  if (stage.includes("London monitor metadata")) return 0.14;
  if (stage.includes("national control metadata")) return 0.20;
  if (stage.includes("London NO2")) {
    const f = job.total ? Math.min((job.done || 0) / job.total, 1) : 0;
    return 0.22 + 0.23 * f;
  }
  if (stage.includes("control NO2")) {
    const f = job.total ? Math.min((job.done || 0) / job.total, 1) : 0;
    return 0.45 + 0.33 * f;
  }
  if (stage.includes("counterfactual")) return stage.includes("background") ? 0.91 : 0.82;
  if (stage === "done") return 1;
  return 0.5;
}

function showAirPermalink(runId) {
  if (!runId) return;
  const href = `/v/${encodeURIComponent(runId)}`;
  airProgressLink.innerHTML = `Permanent result: <a href="${escapeHtml(href)}">${escapeHtml(location.origin + href)}</a>`;
}

function pollAirJob(jobId, fallbackRunId) {
  const poll = async () => {
    let job;
    try { job = await apiGet(`/api/jobs/${jobId}`); } catch (_) { return; }
    if (job.status === "error") {
      clearInterval(airPollTimer); airPollTimer = null;
      airProgress.style.display = "none";
      airForm.style.display = "block";
      airSubmit.disabled = false;
      airSubmit.textContent = "Test the policy";
      airError.textContent = job.error || "The air-policy run failed.";
      airError.style.display = "block";
      return;
    }
    if (job.status === "done") {
      clearInterval(airPollTimer); airPollTimer = null;
      location.href = `/v/${job.run_id || fallbackRunId}`;
      return;
    }
    airProgressStage.textContent = airStageSentence(job);
    airProgressFill.style.width = `${Math.round(airStageProgress(job) * 100)}%`;
  };
  poll();
  airPollTimer = setInterval(poll, 1500);
}

airForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const c = airCaseById(airCaseSelect.value);
  if (!c) return;
  airError.style.display = "none";
  airSubmit.disabled = true;
  airSubmit.textContent = "Testing…";
  try {
    const resp = await apiPost("/api/run", {
      domain: "air",
      case_id: c.id,
      post_months: Number(airPostMonths.value),
      label: airLabel.value.trim(),
    });
    if (resp.done) { location.href = `/v/${resp.run_id}`; return; }
    airForm.style.display = "none";
    airProgress.style.display = "block";
    airProgressFill.style.width = "3%";
    showAirPermalink(resp.run_id);
    pollAirJob(resp.job_id, resp.run_id);
  } catch (err) {
    airSubmit.disabled = false;
    airSubmit.textContent = "Test the policy";
    airError.textContent = err.detail || err.message || "Something went wrong.";
    airError.style.display = "block";
  }
});

loadAirCases();

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
let mobileDrawPoints = [];
let mobileDrawLayer = null;
let mobilePreviewEdge = null;
let mobileVertexLayer = null;
let mobilePreviewFrame = null;
let lastDesktopPreviewLatLng = null;

function isPhoneViewport() {
  return matchMedia("(max-width: 640px)").matches;
}

function formatDrawHa(ha) {
  if (ha === null || !Number.isFinite(ha)) return null;
  if (ha < 1) return `${ha.toFixed(2)} ha`;
  if (ha < 10) return `${ha.toFixed(1)} ha`;
  return `${Math.round(ha)} ha`;
}

function classifyArea(ha, pointCount) {
  if (pointCount < 3 || ha === null || !Number.isFinite(ha)) {
    return { state: "waiting", valid: false, message: pointCount ? "Add another point" : `Target: ${MIN_HA}–${MAX_HA} ha` };
  }
  if (ha > MAX_HA) return { state: "large", valid: false, message: "Too large — move inward or undo" };
  if (ha < MIN_HA) return { state: "small", valid: false, message: "Too small — make the outline wider" };
  if (ha > MAX_HA * 0.8) return { state: "near", valid: true, message: "Within limit — getting close to 500 ha" };
  return { state: "ok", valid: true, message: "Within the 0.5–500 ha limit" };
}

function setDrawFeedback({ ha = null, pointCount = 0, preview = false } = {}) {
  const info = classifyArea(ha, pointCount);
  if (drawLive) drawLive.dataset.state = info.state;
  if (drawLiveValue) {
    const size = formatDrawHa(ha);
    drawLiveValue.textContent = size ? `${size}${preview ? " preview" : ""}` : `${pointCount} point${pointCount === 1 ? "" : "s"}`;
  }
  if (drawLiveState) drawLiveState.textContent = info.message;
  if (drawDone) drawDone.disabled = !info.valid || preview;
  if (drawUndo) drawUndo.disabled = pointCount === 0;
  document.body.classList.toggle("draw-area-invalid", info.state === "large" || info.state === "small");
  document.body.classList.toggle("draw-area-too-large", info.state === "large");
  return info;
}

function latLngsToRing(latlngs) {
  if (!latlngs.length) return [];
  const shift = wrapLng(latlngs[0].lng) - latlngs[0].lng;
  return latlngs.map((p) => [round6(p.lng + shift), round6(p.lat)]);
}

function areaFromLatLngs(latlngs) {
  if (latlngs.length < 3) return null;
  return polygonAreaHa(latLngsToRing(latlngs));
}

function polygonSelfIntersects(latlngs) {
  if (latlngs.length < 4) return false;
  const pts = latlngs.map((p) => [p.lng, p.lat]);
  const orient = (a, b, c) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
  const intersects = (a, b, c, d) => {
    const o1 = orient(a, b, c), o2 = orient(a, b, d), o3 = orient(c, d, a), o4 = orient(c, d, b);
    return o1 !== 0 && o2 !== 0 && o3 !== 0 && o4 !== 0 && o1 !== o2 && o3 !== o4;
  };
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const a = pts[i], b = pts[(i + 1) % n];
    for (let j = i + 1; j < n; j++) {
      // Adjacent edges share a vertex and are allowed; first/last are adjacent too.
      if (j === i || j === i + 1 || (i === 0 && j === n - 1)) continue;
      const c = pts[j], d = pts[(j + 1) % n];
      if (intersects(a, b, c, d)) return true;
    }
  }
  return false;
}

function desktopMarkers() {
  return drawHandler?._markers?.map((m) => m.getLatLng()) || [];
}

function updateDesktopDrawFeedback(previewLatLng = null) {
  if (!drawHandler || isPhoneViewport()) return;
  const fixed = desktopMarkers();
  const fixedHa = areaFromLatLngs(fixed);
  const fixedInfo = classifyArea(fixedHa, fixed.length);
  const hasPreview = Boolean(previewLatLng && fixed.length >= 2);
  const points = hasPreview ? [...fixed, previewLatLng] : fixed;
  const ha = areaFromLatLngs(points);
  const info = setDrawFeedback({ ha, pointCount: fixed.length, preview: hasPreview });
  // A moving preview can be out of bounds while the already-placed polygon is
  // finishable. Keep Done tied to the fixed vertices, not the cursor.
  if (drawDone) drawDone.disabled = !fixedInfo.valid;
  if (drawHandler._poly) {
    const color = info.state === "large" ? "#ff8f86" : info.state === "small" ? "#ffd771" : "#d9ff71";
    drawHandler._poly.setStyle({ color, fillColor: color, fillOpacity: info.state === "large" ? 0.16 : 0.10 });
  }
}

function finishDesktopPolygon() {
  if (!drawHandler || isPhoneViewport()) return;
  const fixed = desktopMarkers();
  const ha = areaFromLatLngs(fixed);
  const info = setDrawFeedback({ ha, pointCount: fixed.length });
  if (!info.valid) {
    drawCoach?.animate(
      [{ transform: "translate(-50%,0)" }, { transform: "translate(-50%,-2px) scale(1.012)" }, { transform: "translate(-50%,0)" }],
      { duration: 280, easing: "ease-out" }
    );
    return;
  }
  drawHandler._finishShape();
}

function beginDesktopDrawing() {
  drawHandler = new L.Draw.Polygon(map, {
    shapeOptions: { color: "#d9ff71", weight: 2, fillOpacity: 0.10, fillColor: "#d9ff71" },
    showArea: false,
    allowIntersection: false,
  });
  const nativeFinish = drawHandler._finishShape.bind(drawHandler);
  drawHandler._finishShape = function guardedFinish() {
    const fixed = desktopMarkers();
    const ha = areaFromLatLngs(fixed);
    const info = setDrawFeedback({ ha, pointCount: fixed.length });
    if (!info.valid) return;
    nativeFinish();
  };
  drawHandler.enable();
  setDrawFeedback({ pointCount: 0 });
}

function clearMobileDrawLayers() {
  [mobileDrawLayer, mobilePreviewEdge, mobileVertexLayer].forEach((layer) => {
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
  });
  mobileDrawLayer = null;
  mobilePreviewEdge = null;
  mobileVertexLayer = null;
}

function mobileCrosshairLatLng() {
  const el = map.getContainer();
  const point = L.point(el.clientWidth / 2, el.clientHeight * 0.43);
  return map.containerPointToLatLng(point);
}

function mobilePreviewPoints() {
  return mobileDrawPoints.length >= 2 ? [...mobileDrawPoints, mobileCrosshairLatLng()] : mobileDrawPoints;
}

function scheduleMobileDrawPreview() {
  if (mobilePreviewFrame !== null) return;
  mobilePreviewFrame = requestAnimationFrame(() => {
    mobilePreviewFrame = null;
    updateMobileDrawPreview();
  });
}

function updateMobileDrawPreview() {
  if (!document.body.classList.contains("mobile-draw-mode")) return;
  clearMobileDrawLayers();
  const previewPoints = mobilePreviewPoints();
  const previewHa = areaFromLatLngs(previewPoints);
  const previewCrosses = polygonSelfIntersects(previewPoints);
  const previewInfo = previewCrosses
    ? { state: "cross", valid: false, message: "Edges would cross — move the point" }
    : classifyArea(previewHa, previewPoints.length);
  const fixedHa = areaFromLatLngs(mobileDrawPoints);
  const fixedInfo = classifyArea(fixedHa, mobileDrawPoints.length);
  const color = (previewInfo.state === "large" || previewInfo.state === "cross") ? "#ff8f86" : previewInfo.state === "small" ? "#ffd771" : "#d9ff71";

  if (previewPoints.length >= 3) {
    mobileDrawLayer = L.polygon(previewPoints, { color, weight: 2.4, fillColor: color, fillOpacity: previewInfo.state === "large" ? .16 : .10, interactive: false }).addTo(map);
  } else if (previewPoints.length >= 2) {
    mobilePreviewEdge = L.polyline(previewPoints, { color, weight: 2.2, dashArray: "5 6", opacity: .9, interactive: false }).addTo(map);
  }
  if (mobileDrawPoints.length) {
    mobileVertexLayer = L.layerGroup(mobileDrawPoints.map((p, i) => L.circleMarker(p, {
      radius: i === 0 ? 5 : 4,
      color: "#0e120d",
      weight: 2,
      fillColor: "#d9ff71",
      fillOpacity: 1,
      interactive: false,
    }))).addTo(map);
  }

  // The live readout describes the fixed polygon when it can be finished;
  // otherwise it previews what would happen if the user adds the crosshair.
  if (mobileDrawPoints.length >= 3) {
    setDrawFeedback({ ha: fixedHa, pointCount: mobileDrawPoints.length });
    if (drawCoachHint) drawCoachHint.textContent = fixedInfo.valid
      ? previewInfo.state === "large"
        ? "Current outline is valid. Move the crosshair inward before adding another point, or tap Done."
        : "Area is valid. Add more corners for precision, or tap Done."
      : fixedInfo.state === "large"
        ? "That outline is over 500 ha. Undo a point to bring it back inside the limit."
        : "Keep adding a wider corner until the area reaches 0.5 ha.";
  } else {
    setDrawFeedback({ ha: previewHa, pointCount: previewPoints.length, preview: previewPoints.length >= 3 });
    if (drawUndo) drawUndo.disabled = mobileDrawPoints.length === 0;
    if (drawCoachHint) drawCoachHint.textContent = previewInfo.state === "cross"
      ? "That next corner would cross the outline. Pan to a different corner."
      : previewInfo.state === "large"
        ? "That next corner would push the area over 500 ha. Pan inward before adding it."
        : mobileDrawPoints.length === 0
        ? "Pan the map until the crosshair sits on a corner, then add a point."
        : "Pan to the next corner and add another point.";
  }

  if (drawAdd) {
    const wouldExceed = previewPoints.length >= 3 && previewInfo.state === "large";
    const wouldCross = previewInfo.state === "cross";
    drawAdd.dataset.previewState = previewInfo.state;
    drawAdd.disabled = wouldExceed || wouldCross;
    drawAdd.textContent = wouldCross
      ? "Avoid crossing"
      : wouldExceed
        ? "Move inward"
        : mobileDrawPoints.length === 0 ? "Add first point" : "Add point";
  }
  if (mobileCrosshair) mobileCrosshair.dataset.state = previewInfo.state;
}

function beginMobileDrawing() {
  document.body.classList.add("mobile-draw-mode");
  mobileDrawPoints = [];
  clearMobileDrawLayers();
  if (drawCoachTitle) drawCoachTitle.textContent = "Outline with the crosshair";
  if (drawCoachHint) drawCoachHint.textContent = "Pan the map until the crosshair sits on a corner, then add a point.";
  setDrawFeedback({ pointCount: 0 });
  map.on("move", scheduleMobileDrawPreview);
  map.on("zoom", scheduleMobileDrawPreview);
  updateMobileDrawPreview();
}

function addMobilePoint() {
  if (!document.body.classList.contains("mobile-draw-mode")) return;
  const point = mobileCrosshairLatLng();
  const candidate = [...mobileDrawPoints, point];
  const ha = areaFromLatLngs(candidate);
  const info = classifyArea(ha, candidate.length);
  const crosses = polygonSelfIntersects(candidate);
  // Preview validation normally catches these before the tap. Keep this guard
  // too, so a stale animation frame can never commit a bad next vertex.
  if (crosses || info.state === "large") {
    updateMobileDrawPreview();
    navigator.vibrate?.(18);
    drawCoach?.animate(
      [{ transform: "translateY(0)" }, { transform: "translateY(-3px) scale(1.01)" }, { transform: "translateY(0)" }],
      { duration: 260, easing: "ease-out" }
    );
    return;
  }
  mobileDrawPoints.push(L.latLng(point.lat, point.lng));
  updateMobileDrawPreview();
}

function undoMobilePoint() {
  if (!mobileDrawPoints.length) return;
  mobileDrawPoints.pop();
  updateMobileDrawPreview();
}

function finishMobilePolygon() {
  const ha = areaFromLatLngs(mobileDrawPoints);
  const info = setDrawFeedback({ ha, pointCount: mobileDrawPoints.length });
  if (!info.valid) return;
  const layer = L.polygon(mobileDrawPoints, { color: "#d9ff71", weight: 2, fillOpacity: .10, fillColor: "#d9ff71" });
  clearMobileDrawLayers();
  drawnItems.clearLayers();
  drawnItems.addLayer(layer);
  document.body.classList.remove("mobile-draw-mode");
  map.off("move", scheduleMobileDrawPreview);
  map.off("zoom", scheduleMobileDrawPreview);
  onPolygonReady(layer);
}

function cancelDrawingMode() {
  drawHandler?.disable();
  drawHandler = null;
  lastDesktopPreviewLatLng = null;
  map.off("move", scheduleMobileDrawPreview);
  map.off("zoom", scheduleMobileDrawPreview);
  clearMobileDrawLayers();
  mobileDrawPoints = [];
  if (mobilePreviewFrame !== null) { cancelAnimationFrame(mobilePreviewFrame); mobilePreviewFrame = null; }
  document.body.classList.remove("is-drawing", "mobile-draw-mode", "draw-area-invalid", "draw-area-too-large");
  if (drawCoachTitle) drawCoachTitle.textContent = "Outline the area";
  if (drawCoachHint) drawCoachHint.textContent = "Click around its boundary. We’ll tell you the size before you finish.";
  if (drawAdd) { drawAdd.disabled = false; drawAdd.textContent = "Add point"; drawAdd.dataset.previewState = "waiting"; }
  if (mobileCrosshair) mobileCrosshair.dataset.state = "waiting";
  setDrawFeedback({ pointCount: 0 });
}

drawBtn.addEventListener("click", () => {
  cancelDrawingMode();
  document.body.classList.add("is-drawing");
  document.body.classList.remove("show-cases");
  if (isPhoneViewport()) beginMobileDrawing();
  else beginDesktopDrawing();
});

drawCoachCancel?.addEventListener("click", cancelDrawingMode);
drawAdd?.addEventListener("click", addMobilePoint);
drawUndo?.addEventListener("click", () => {
  if (isPhoneViewport()) undoMobilePoint();
  else {
    drawHandler?.deleteLastVertex?.();
    updateDesktopDrawFeedback(lastDesktopPreviewLatLng);
  }
});
drawDone?.addEventListener("click", () => {
  if (isPhoneViewport()) finishMobilePolygon();
  else finishDesktopPolygon();
});

map.on(L.Draw.Event.DRAWVERTEX, () => updateDesktopDrawFeedback(lastDesktopPreviewLatLng));
map.on("mousemove", (e) => {
  if (!document.body.classList.contains("is-drawing") || isPhoneViewport()) return;
  lastDesktopPreviewLatLng = e.latlng;
  updateDesktopDrawFeedback(e.latlng);
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
  return latLngsToRing(layer.getLatLngs()[0]);
}

function areaOk() {
  return currentHa !== null && currentHa >= MIN_HA && currentHa <= MAX_HA;
}

function onPolygonReady(layer) {
  const ring = ringFromLayer(layer);
  currentHa = polygonAreaHa(ring);
  currentGeoJSON = { type: "Polygon", coordinates: [ring.concat([ring[0]])] };
  cancelDrawingMode();
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
window.__DEBUG_AREA = { polygonAreaHa, ringFromLayer, wrapLng, areaOk: () => areaOk(), classifyArea };

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
