// Otherwise — landing page: map, showcase, draw-and-run form.
import { apiGet, apiPost, fmtDate, todayISO, initHowItWorksDrawer } from "./common.js";

const LIGHT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const LIGHT_ATTR = "&copy; OpenStreetMap contributors";
const SAT_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const SAT_ATTR = "Esri, Maxar, Earthstar Geographics";
const EARTH_R = 6371008.8; // mean earth radius, m

initHowItWorksDrawer();

// ---- map -------------------------------------------------------------------

const map = L.map("map", { zoomControl: true, attributionControl: true }).setView([20, 0], 2);
const lightLayer = L.tileLayer(LIGHT_TILES, { attribution: LIGHT_ATTR, maxZoom: 19, subdomains: "abcd" }).addTo(map);
const satLayer = L.tileLayer(SAT_TILES, { attribution: SAT_ATTR, maxZoom: 19 });

const satToggle = document.getElementById("sat-toggle");
let satOn = false;
satToggle.addEventListener("click", () => {
  satOn = !satOn;
  if (satOn) { map.removeLayer(lightLayer); map.addLayer(satLayer); }
  else { map.removeLayer(satLayer); map.addLayer(lightLayer); }
  satToggle.classList.toggle("active", satOn);
});

const drawnItems = new L.FeatureGroup().addTo(map);

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
    const row = document.createElement("div");
    row.className = "showcase-row";
    row.innerHTML = `
      <span class="dot dot-${entry.status}"></span>
      <div>
        <div class="sc-label">${escapeHtml(entry.label)}</div>
        <div class="sc-meta">${escapeHtml(entry.change_type)} &middot; ${fmtDate(entry.event_date)} &middot; ${entry.area.ha} ha</div>
      </div>`;

    const layer = L.geoJSON(entry.area.geojson, {
      style: { color: "var(--ink)", weight: 1.5, fill: false },
    }).addTo(map);
    layer.bindTooltip(entry.label, { permanent: true, direction: "center", className: "area-label" });
    bounds.extend(layer.getBounds());

    row.addEventListener("mouseenter", () => layer.setStyle({ color: "var(--counter)", weight: 2.5 }));
    row.addEventListener("mouseleave", () => layer.setStyle({ color: "var(--ink)", weight: 1.5 }));
    row.addEventListener("click", () => { location.href = `/v/${entry.id}`; });

    listEl.appendChild(row);
  });
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40] });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

loadShowcase();

// ---- draw an area --------------------------------------------------------------

const drawBtn = document.getElementById("draw-btn");
const runForm = document.getElementById("run-form");
const areaHaLine = document.getElementById("area-ha-line");
let drawHandler = null;
let currentGeoJSON = null;
let currentHa = null;

drawBtn.addEventListener("click", () => {
  if (drawHandler) drawHandler.disable();
  drawHandler = new L.Draw.Polygon(map, {
    shapeOptions: { color: "var(--ink)", weight: 1.5, fillOpacity: 0.06, fillColor: "var(--ink)" },
    showArea: false,
    allowIntersection: false,
  });
  drawHandler.enable();
});

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  onPolygonReady(e.layer);
});

function polygonAreaHa(latlngs) {
  // Local equirectangular projection about the ring's mean latitude, then shoelace.
  const lat0 = (latlngs.reduce((s, p) => s + p.lat, 0) / latlngs.length) * (Math.PI / 180);
  const pts = latlngs.map((p) => ({
    x: (p.lng * Math.PI / 180) * EARTH_R * Math.cos(lat0),
    y: (p.lat * Math.PI / 180) * EARTH_R,
  }));
  let area2 = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    area2 += a.x * b.y - b.x * a.y;
  }
  return Math.abs(area2 / 2) / 10000; // m^2 -> ha
}

function onPolygonReady(layer) {
  const latlngs = layer.getLatLngs()[0];
  currentHa = polygonAreaHa(latlngs);
  currentGeoJSON = layer.toGeoJSON().geometry;
  renderHa();
  runForm.style.display = "block";
  drawBtn.textContent = "Redraw area";
  document.getElementById("run-error").style.display = "none";
}

function renderHa() {
  const ok = currentHa >= 0.5 && currentHa <= 500;
  areaHaLine.classList.toggle("bad", !ok);
  const haStr = currentHa.toFixed(currentHa < 10 ? 2 : 1);
  areaHaLine.textContent = ok
    ? `${haStr} ha`
    : `${haStr} ha — must be between 0.5 and 500 hectares`;
  submitBtn.disabled = !ok;
}

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
  if (stage === "sentinel-2") return `Reading Sentinel-2 scene ${job.done} of ${job.total}`;
  if (stage === "sentinel-1") return `Reading Sentinel-1 scene ${job.done} of ${job.total}`;
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
}

function resetToForm() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  progressBlock.style.display = "none";
  runForm.style.display = "block";
  submitBtn.disabled = false;
  submitBtn.textContent = "Check it";
}

runForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentGeoJSON || !(currentHa >= 0.5 && currentHa <= 500)) return;
  runErrorEl.style.display = "none";
  submitBtn.disabled = true;
  submitBtn.textContent = "Checking…";

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
    pollJob(resp.job_id, resp.run_id);
  } catch (err) {
    submitBtn.disabled = false;
    submitBtn.textContent = "Check it";
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

function rebuildProgressBlock() {
  progressBlock.innerHTML = `
    <div class="progress-wrap">
      <div class="progress-bar-track"><div class="progress-bar-fill" id="progress-fill"></div></div>
    </div>
    <div class="progress-stage" id="progress-stage">Starting&hellip;</div>
    <div class="progress-note">Live runs read every Sentinel scene over the area for the last three years and usually take three to eight minutes.</div>`;
  progressFill = document.getElementById("progress-fill");
  progressStage = document.getElementById("progress-stage");
}
