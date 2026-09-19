# DECISIONS

One or two lines per significant decision, newest at the bottom. Written so the
project can be explained and defended in an interview.

## 2026-09-18 — repo setup and first survey

- **Flattened the repo.** The upload landed everything under a nested
  `carbon-twin/carbon-twin/`. Moved it all to the root so `make test`, imports
  and a recruiter's first click work without a detour.
- **`grunt` subagent lives at `.claude/agents/grunt.md`** (moved from the root).
  It runs on Sonnet and is restricted to well-specified UI, boilerplate, tests-to-spec
  and deploy config. Statistical code in `scm.py`, `inference.py`, `audit.py` stays
  with the lead.
- **Added a `.gitignore`** (caches, venvs, `.env`, validation CSV, `DONOTREAD/`).
  `DONOTREAD/` was not in the upload; the rule to never read or commit it stands.
- **Baseline test run: 40 passed, 3 skipped** on Python 3.11 with numpy 2.4,
  scipy 1.17, pandas 3.0. The 3 skips are tests that need `xarray`, which is not
  in `requirements.txt`. Nothing is broken.

### What the sandbox can and cannot reach (re-tested 2026-09-18 with network policy = Full)

The first survey ran under a restricted network policy and found every catalogue
blocked. With the policy set to Full, every host was re-probed at the byte level
(STAC search, then a real windowed COG read with rasterio), not just an HTTP 200.

| Source | Catalogue | Pixel reads | Notes |
|---|---|---|---|
| Microsoft Planetary Computer STAC | **yes** | **yes** (S2 L2A and S1 RTC, SAS-signed, ~2.6 MB/s) | S1 RTC is global, 2014-10 to present. S2 items carry `s2:processing_baseline`; DNs are raw, so the +1000 offset must be removed by us. |
| Earth Search (Element84) | **yes** | **yes** (S2 L2A COGs on `sentinel-cogs`, no auth, ~6 MB/s) | S1 is GRD only (no RTC). |
| Copernicus Data Space STAC | **yes** | **no** without an account | Assets are `s3://eodata/...` behind CDSE credentials. |
| Source Cooperative (AlphaEarth, `tge-labs/aef`) | **yes** (S3 listing, index files) | **yes** (~5 MB/s) | Tiles are 8192x8192x64 int8 with 1024x1024 blocks, so one window read pulls ~64 MB; a 32x32 read took 56 s. Bottom-up GeoTIFFs; the raw `.tiff` opens fine in rasterio, the `.vrt` does not. |
| OpenStreetMap tiles, unpkg, jsDelivr, PyPI | yes | n/a | Map UI dependencies are available. |

- **Decision: Planetary Computer is the primary data source for both sensors.**
  It is the only free source with Sentinel-1 RTC (terrain-corrected gamma0, the
  product SPEC.md wanted), and its S2 L2A includes the SCL cloud mask. Earth
  Search stays as a second S2 provider behind the same interface, because it is
  faster and needs no signing. Copernicus Data Space is dropped: pixel access
  needs an account, which is one of the things Mohib has to create personally.
- **Baseline-04.00 offset is keyed on `s2:processing_baseline`, not on the
  acquisition date.** Planetary Computer reprocesses old scenes (a 2023 scene we
  fetched was generated in 2024 under baseline 05.10), so the date-based cutover
  in `spectral.py` would be wrong on this source. The new loader subtracts 1000 DN
  when the baseline is >= 04.00.
- **AlphaEarth is deferred (Mohib, 2026-09-18: timebox, ship tonight).** Each
  window read costs a 64 MB block (56 s for 32x32 px through the proxy), too
  slow for a live run. v1 shortlists donors with ESA WorldCover land cover,
  Copernicus DEM terrain and pre-event optical similarity. AlphaEarth stays a
  later upgrade, precomputed offline per showcase site, not read live.
- **Reachability is not the same as speed.** Throughput through the sandbox proxy
  is 2.6-6 MB/s. A live run must read only the window it needs, read SCL (20 m)
  before deciding whether to read the 10 m bands, and parallelise scene reads.
  The live-run budget is measured in milestone 1 and recorded here.

### Method direction, from the hackathon post-mortem (Mohib, 2026-09-18)

- **Why CarbonTwin said INCONCLUSIVE so often:** ~20-donor pools (p floors at
  1/21 = 0.048), 24 monthly steps, and a binary RMSPE-rank test. The app is
  designed against all three.
- **Large donor pools.** Candidate controls are a grid of cells the size of the
  drawn area in a ring around it (hundreds, not twenty), filtered for land cover
  and pre-event similarity. The permutation p-value floor then drops to well under
  0.01, and the pool is big enough for augmented SCM to be well-behaved.
- **Dense series.** Per-observation Sentinel-2 (5-day revisit) and Sentinel-1
  (6-12 day) series, not monthly composites. Three pre-event years give ~200 S2
  and ~100-180 S1 observations before any binning.
- **Effect sizes with intervals, not a binary rank.** Primary estimator is
  augmented SCM (Ben-Michael, Feller & Rothstein 2021: ridge-corrected convex
  weights, which fixes the bias when the convex fit is imperfect). Uncertainty
  comes from conformal inference (Chernozhukov, Wuthrich & Zhu 2021: permute
  post-event residuals under a null effect, moving-block variant) and gives a
  confidence interval for the average post-event effect. The Abadie in-space
  placebo is kept as the displayed placebo check, alongside in-time placebos
  (fake event dates in the pre period).
- **Detection power is measured, not assumed.** On the known-answer sites plus
  synthetic effects injected into untouched real cells, we record the hit rate
  per effect size and the false-alarm rate, and publish the table here and on
  the track-record page. If power is low for a change type, the app says so.

### What the existing engine does well, and what the app must change

- **Keep as-is:** convex-weight synthetic control (`scm.py`), Abadie placebo
  permutation with the conservative +1 p-value (`inference.py`), Benjamini-Hochberg
  for batches, the equal-weight fallback when SLSQP fails, and the "interpolated
  months are not evidence" coverage gate.
- **p-value floor is 1/(donors+1).** With fewer than 19 donors the method cannot
  reach p<0.05, so the app must guarantee a donor pool of at least ~20 or report
  "can't tell". This is a feature: thin pools cannot produce a confident verdict.
- **The verdict logic is one-directional and agriculture-specific.** `audit.py`
  only treats a *positive* NDVI uplift as an effect and scores an off-season
  window (Oct–Dec, Mar–Apr). Clearing, burn and flooding are *negative* optical
  effects with no off-season. The app needs a direction-aware effect over the
  full post-event window. This is new code beside `audit.py`, not an edit to it.
- **Treatment date is year-granular.** `pipeline.run_audit` splits pre/post by
  calendar year and defaults to 2021. The app needs a real event date.
- **Carbon estimation is wired into `run_audit`.** `estimate_carbon` is called on
  every audit. The app path will not call it; `carbon.py`, `actuary.py`,
  `portfolio.py` stay in the repo and off the product as SPEC.md says.
- **Hardcoded 2021 in `plots.py` and `dashboard.py`.** The app gets its own
  verdict-page rendering; the old dashboard stays for the CarbonTwin demo.
- **`radar.py` is simulated Sentinel-1**, as SPEC.md warns. Nothing in it is
  reusable for a real radar path beyond the idea that backscatter drops on
  clearing and on standing water.
- **The Baseline-04.00 fix in `spectral.py` is for raw L2A digital numbers.**
  The `sentinel-cogs` bucket stores L2A with the same offset convention on and
  after 2022-01-25, so the same correction applies there.

### Open, not yet decided

- ~~Final choice between AWS `sentinel-cogs` only versus Planetary Computer.~~
  Settled above: Planetary Computer primary, Earth Search as second S2 provider.
- Hosting. Candidates are a static frontend plus a small Python backend on a
  free tier. Nothing chosen until the compute cost of a live run is measured.
- Known-answer validation sites. To be proposed with sources, then confirmed
  by Mohib before they are treated as ground truth.

## 2026-09-18 — milestone 1: data in and cleaned for one area (`src/app/`)

- **New package `src/app/`, old modules untouched.** `geometry` (validation, UTM,
  donor grid), `providers` (STAC), `extract` (windowed zonal stats), `s2`, `s1`,
  `series` (cache format), `fetch` (orchestrator). CLI: `python -m scripts.fetch_area`.
- **One read per band per scene for every polygon.** The drawn area and all donor
  cells are rasterised to one label image and reduced with `bincount`, so a run
  costs about five range requests per usable Sentinel-2 scene, not hundreds.
- **SCL first, bands only if clear.** The 20 m scene classification is read first;
  bands are read only when >= 80% of the drawn area is clear (classes 4, 5, 6:
  vegetation, bare, water). Unclassified (7) is treated as unusable, because it
  often marks cloud edges and a missed thin cloud looks exactly like clearing.
- **Area limits 0.5-500 ha.** Below 0.5 ha there are fewer than ~50 pixels and
  speckle/edge effects dominate; above 500 ha the donor cells (same footprint)
  make the read window impractically large.
- **Donor cells match the treated footprint** (side = sqrt(area)), in a ring
  1-12 km out, thinned evenly to at most 400. Same footprint means comparable
  noise; the inner exclusion is the spillover buffer; the ring keeps the climate
  and phenology shared.
- **Scenes are filtered by footprint before any read**, and Planetary Computer's
  multiple processing versions of one acquisition are collapsed to the newest
  baseline. Tile overlaps (same minute, two MGRS tiles) are merged zone by zone
  so donor cells on a tile boundary keep their coverage.
- **Radar: one relative orbit, chosen before reading.** The relative orbit with
  the most passes over the area is kept; other orbits are logged as receipts.
  Means are taken in linear power and converted to dB afterwards.
- **A second cloud filter on the series.** SCL misses haze; an NDVI value far
  below its temporal neighbours (within 40 days, more than max(0.12, 3 MAD))
  is dropped with a "haze" receipt. It is one-sided and local, so a real,
  persistent drop is not flagged.
- **Every dropped observation gets a receipt** with a reason (cloud, haze,
  duplicate, orbit, edge, read-error) and a human sentence; scene-footprint
  misses are counted but not shown.
- **Timing, small Midlands field, 30 cells, 6 months:** 63 s end to end
  (S2 40 s over 51 covering scenes, S1 20 s over 15 scenes) with 16 threads
  through the sandbox proxy. **Three years, 100 cells, same field: 191 s** (S2 66 s over 286 covering scenes, 57 clear observations; S1 114 s over 117 scenes on one orbit, 117 observations). Median donor coverage of the treated area's clear dates is 0.74, so the donor coverage threshold is set at 0.70.

## 2026-09-18 — milestone 2: method (`src/app/estimator.py`, `prep.py`, `donors.py`, `verdict.py`, `run.py`)

- **Product name: "Otherwise".** As in "more than it would have changed
  otherwise". Short, says what the counterfactual is, and does not sound like a
  dashboard. SPEC.md allowed a rename.
- **Bins of 10 days anchored on the event date**, median within a bin. The
  treated column is never interpolated: a bin without a real observation is
  dropped, so every point on the chart is evidence. Donor gaps are interpolated
  and donors under 70% coverage are dropped.
- **Donor pool: filter, then rank.** Coverage, then same WorldCover class
  (2020 map for events before 2022, else 2021, so the map is pre-event), then
  elevation within 150 m, each relaxed in turn if fewer than 30 cells remain,
  then the 80 cells with the lowest pre-event RMSE to the area. Reasons and
  counts are returned so the page can show why a cell was used.
- **Estimator: augmented SCM.** Convex weights from the existing `scm.py`,
  plus a ridge correction (Ben-Michael, Feller & Rothstein 2021) for whatever
  the convex fit could not match. The ridge penalty is chosen by holding out
  the last quarter of the pre-period. `lam=0` recovers plain SCM, so the old
  method is still available for comparison.
- **Uncertainty: conformal inference**, moving-block permutations
  (Chernozhukov, Wuthrich & Zhu 2021), 90% interval by test inversion over a
  41-point grid. On synthetic data with 60 donors and 100 steps it recovered a
  planted -0.20 effect as -0.19 [-0.24, -0.16] and gave p = 0.66 on the null.
- **Two placebo checks, both shown.** In-space: every donor is treated as if
  it were the area (Abadie RMSPE-rank p, plus the share of donors whose gap is
  at least as large in the same direction). In-time: three fake event dates in
  the pre-period, each with its own conformal interval; a "significant" fake
  effect is reported as a false alarm on the verdict page.
- **Verdict rules are explicit** (`verdict.py`): REAL needs the 90% interval
  to exclude zero in the claimed direction, an effect of at least 0.05 index
  units (1 dB for radar), and in-space placebo p <= 0.10. NOT REAL needs the
  interval to rule out a 0.05 change. Anything else, or fewer than 20 donors,
  20 pre-event bins, 3 post-event bins, or a pre-event fit worse than 1.5x the
  placebo median, is CAN'T TELL with the reason attached. The 0.05 / 1 dB
  minimum is a design threshold, not a measurement, and is labelled as such.
- **Radar corroborates, and leads only when optical cannot.** The optical
  index for the change type is the lead signal; a radar polarisation is
  analysed the same way and shown beside it. Radar becomes the lead only when
  optical has fewer than three clear post-event bins.
- **Known-answer sites are proposed in `SITES.md`** with sources and are
  labelled "candidate" until Mohib confirms them.
- **Convex weights solved by NNLS, not SLSQP.** The first live verdict spent
  11 CPU-minutes in the placebo stage because `scm.solve_weights` (SLSQP, 80
  variables) takes 1.4-2.2 s per solve and a verdict needs several hundred
  solves. The same problem as non-negative least squares with a weighted
  sum-to-one row returns the same loss (0.00802 vs 0.00802 on real data) in
  about 1 ms. `scm.py` is left unchanged for the old demo; the app uses
  `estimator.solve_weights`.

### Detection power, measured (`scripts/power.py`)

Real, untouched donor cells around the Midlands test area (400 cells, 2020-2024,
the cloudiest case we have: 79 clear optical observations in four years). Each
of 20 randomly chosen cells was treated as "the area", a step effect was added
after a fake event date at 70% of the window, and the full estimator + verdict
rules were applied (90% conformal interval, min effect 0.05, placebo p <= 0.10).

| Signal | Injected effect | Called REAL | False alarms |
|---|---|---|---|
| NDVI | 0.00 | 0 / 20 | 0 / 20 |
| NDVI | -0.05 | 6 / 20 (30%) | |
| NDVI | -0.10 | 17 / 20 (85%) | |
| NDVI | -0.20 | 19 / 20 (95%) | |
| VH (radar, dB) | 0.0 | 0 / 20 | 0 / 20 |
| VH | -0.5 | 0 / 20 | |
| VH | -1.0 | 7 / 20 (35%) | |
| VH | -2.0 | 20 / 20 (100%) | |

- Reading: a clearing, burn or flood moves NDVI/NBR/NDWI by 0.2 or more, so
  those are detected almost always even under UK cloud; a 0.05 change is
  below the method's power there and will usually come back CAN'T TELL or
  NOT REAL, which is the honest answer. Sunnier sites have 2-3x the clear
  observations and should do better; this will be re-measured on the
  known-answer sites.
- The cells in this test were not land-cover filtered (the power script uses
  the 60 best pre-fit donors), so it slightly understates the app's power.

## 2026-09-18 — milestone 3: the web app (`web/`, `src/app/server.py`)

- **No framework, no build step.** Plain HTML/CSS/ES modules with Leaflet and
  a hand-written SVG chart. It loads in under a second, deploys as static files
  next to the API, and every pixel of the verdict page is under our control.
- **One FastAPI process serves both the API and the pages.** Live runs are
  background threads behind a semaphore (one at a time by default), results
  are JSON files, and `/v/<id>` is the permalink. Showcase results live in
  `showcase/` in the repo so the landing page never waits on a satellite read.
- **Basemap is OpenStreetMap's standard tiles.** CARTO's free basemap now
  returns "API key required" tiles; OSM tiles work with attribution and the
  traffic here is tiny. A satellite toggle uses Esri World Imagery.
- **No sample or placeholder data ships.** The frontend was first built
  against an invented development sample; it was deleted before commit so
  nothing on the site can be mistaken for a result.
- **The first big-burn case exposed a real limit, and the verdict says so.**
  Rhodes 2023 burnt ~17,600 ha, larger than the 12 km control ring, so the
  control cells burnt too and the tool returned CAN'T TELL. The verdict now
  states when the control cells shifted with the area at the event date. A
  smaller burn (Saddleworth Moor 2018, ~800 ha) was added to test the burn
  path where an untouched ring exists.
- **Verdict statements are recomputable from stored numbers**
  (`scripts/refresh_verdicts.py`), so a wording or threshold change never
  requires refetching satellite data.
- **Pre-fit gate relaxed when the effect dwarfs the fit error.** The corrected
  Grünheide polygon gave NDVI -0.61 (interval -0.57 to -0.45, placebo p 0.03)
  but was blocked because its pre-event error (0.043) was just over 1.5x the
  placebo median (0.028). The interval and the placebo ratio already scale
  with that error, so the gate now applies only when |effect| < 4x pre-RMSE.
- **The conformal interval is for a constant post-event shift.** When the
  effect varies over time (a clearing that starts to regrow), the mean gap can
  sit outside the accepted set, as it does for Grünheide (-0.61 vs -0.57 to
  -0.45). Both numbers are shown; neither is adjusted to look tidier.

## 2026-09-18 — milestone 4: known-answer results (candidate sites, `showcase/`)

| Site | Type | Expected | Verdict | Lead signal | Effect (90% interval) | Placebo p |
|---|---|---|---|---|---|---|
| Grünheide 2020 (Tesla site) | clearing | REAL | **REAL** | NDVI | -0.61 (-0.57 to -0.45) | 0.03 |
| Saddleworth Moor 2018 | burn | REAL | CAN'T TELL | VH (NBR had 2 post bins) | NBR -0.40 on 2 observations | 0.03 |
| Rhodes 2023 | burn | REAL | CAN'T TELL | NBR | controls burnt too | 0.61 |
| Sindh 2022 | flood | REAL | CAN'T TELL | NDWI | controls flooded too | 0.51 |
| Richmond Park (null) | none | NOT REAL | CAN'T TELL | NDVI | -0.01 (-0.10 to +0.10) | 0.93 |
| Jaú NP (null) | none | NOT REAL | CAN'T TELL | NDVI | -0.01 (-0.07 to +0.06) | 0.64 |

- **Zero false alarms**, one clean hit, four honest "can't tell"s, each with
  the reason on the page. Nothing is claimed that the data do not support.
- **Two lessons already changed the product.** (1) Events larger than the
  12 km control ring (Rhodes, Sindh) cannot be tested this way; the verdict
  now says so. (2) A radar NOT REAL must not override an optical series that
  shows a large effect on too few observations (Saddleworth: NBR -0.40 on two
  post-event bins because Planetary Computer's Sentinel-2 archive is thin over
  the UK before 2018); `verdict.combine` returns CAN'T TELL there.
- **Null sites came back CAN'T TELL rather than NOT REAL** because their
  intervals are too wide to rule out a 0.05 change (Jaú: saturated, cloudy
  forest; Richmond: few comparable cells in London). That is the right
  answer for a method that refuses to over-claim, but it means the track
  record's "correct" count will stay low until sites with denser data are
  added. A wider ring for small areas and a 2020-2024 window (denser archive)
  are the obvious next improvements.
- **Sites remain candidates until Mohib confirms them.**

## 2026-09-18 (evening) — decisive where honest: method changes, each re-tested on the null

- **Conformal statistic is the absolute mean of post-event residuals, not their
  RMS.** With RMS, a time-varying effect (construction that keeps changing,
  clearing that regrows) rejects every constant shift and the interval
  collapsed to a point; Austin (NDVI -0.19, placebo p 0.016) came back CAN'T
  TELL for that reason alone. The absolute mean tests exactly the average
  effect we report. Null power test after the change: NDVI false alarms 0/20;
  detection 7/20 at -0.05, 19/20 at -0.10, 19/20 at -0.20 (was 6, 17, 19).
- **Interval widening is capped** at ±1.0 index units (±10 dB), beyond which
  an interval carries no information; fake-date placebos no longer print ±6.
- **Wide-area matched controls (`mode="wide"`).** For events larger than the
  ring: candidate cells are sampled uniformly over an annulus (e.g. 20-150 km),
  filtered by WorldCover class, elevation and slope from coarse reads, then
  read in compact groups at 40 m from the COG overviews. Each group has its own
  date axis; series are joined on event-anchored 10-day bins. `mode="auto"`
  runs the ring first and escalates to wide when the ring's placebo cells
  shifted with the area.
- **Evidence across sensors (`evidence.py`).** One p-value per sensor (indices
  within a sensor are correlated), Bonferroni across sensors, agreement
  reported in one sentence. It never loosens the single-signal verdict rules.
- **Time-lapse frames** (`imagery.make_timelapse`): up to eight clear
  true-colour frames across the window for the scrubber.

## 2026-09-18 (late) — state at the spend limit, and what is where

The monthly spend limit stopped the parallel agents mid-flight. Everything on
`main` runs and passes its tests; this entry records what landed, what is
parked, and what the evidence says.

**Landed and merged**
- Method: NNLS convex weights, ridge augmentation, conformal interval on the
  absolute-mean statistic, in-space and in-time placebos, explicit verdict
  rules, cross-sensor evidence sentence, radar-over-optical guard, wide-area
  matched controls (`mode="wide"`, auto-escalation when ring controls shift).
- Data: Planetary Computer S2 L2A + S1 RTC, SCL-first reads, receipts, cache,
  covariates (WorldCover, DEM), before/after thumbnails, 8-frame time-lapses.
- Product: map landing page with showcase cards and place search, story-first
  verdict page, track-record page, batch upload (`/batch`) with Markdown and
  JSON report export, permalinks, Docker/Render/Hugging Face deploy config.
- Validation: null power test (0/20 false alarms on NDVI and VH; 19/20
  detection at -0.10 NDVI, 20/20 at -2 dB VH), ten known-answer runs in
  `showcase/` with sources in SITES.md, `scripts/validate_app.py`,
  `docs/METHOD.md`, pixel-level change test (`src/app/pixels.py`),
  calibration and red-team scripts (`scripts/calibration.py`,
  `scripts/redteam.py`; their write-ups were not finished).

**Parked, not lost**
- Design pass (before/after slider, four-act story): the slider works; Acts
  2-4 were not finished when the agent stopped. The diff is saved as
  `docs/design-pass-slider.patch`; apply it and finish `web/verdict.js`
  render of acts 2-4 before shipping. The committed page is the story-first
  version, which is complete.
- Break-date search (`src/app/breakdate.py`): implemented with a
  search-aware placebo, one accuracy test marked xfail; not wired into the
  product.
- Blind validation (`scripts/blind_sample.py`, `scripts/blind_validation.py`):
  the Hansen-loss sampler and harness exist; no results were produced before
  the stop. Run per docs/BLIND_VALIDATION.md when credit allows.
- Wide-area reruns of Rhodes and Sindh were in progress at the stop; their
  results, when present, are in `showcase/` under the site keys.

**What the evidence says today**
- Sharp, well-bounded changes are called REAL with tight intervals and near-
  zero placebo rates (Grünheide: NDVI -0.61, placebo p 0.03).
- No false alarm has been produced on any null site or null cell.
- CAN'T TELL still dominates on (a) events larger than the control ring
  (now addressed by wide mode, unproven at the stop), (b) thin optical
  archives before 2018, and (c) gradual changes (addressed by the absolute-
  mean statistic; Austin should be re-run). Each CAN'T TELL states its reason.

## HANDOFF (2026-09-18, end of session)

### Done and on `main`
- **Method**: NNLS convex weights + ridge augmentation; conformal 90% interval
  on the absolute-mean statistic (capped widening); in-space and in-time
  placebos; explicit verdict rules (`src/app/verdict.py`, incl. `combine`);
  cross-sensor evidence sentence (`evidence.py`); **wide-area matched
  controls** (`fetch.py::_fetch_wide`, `run.py mode="wide"/"auto"`), proven
  on Rhodes: NBR -0.47 (-0.49 to -0.31), placebo p 0.02, 42 controls 20-150 km
  away, REAL.
- **Known-answer track record** (`showcase/track_record.json`, page
  `/track-record`): 9 counted, 4 REAL hits (Grünheide, Rhodes, Table
  Mountain, Austin), 0 misses, 0 false alarms, 5 can't tell (Saddleworth:
  radar interval too wide; Lützerath, Richmond, Jaú: pre-event fit worse than
  1.5x the placebo median; Sindh: ring result, wide rerun unfinished).
- **Null power** (`scripts/power.py`, cached Midlands 2020-24): NDVI 0/20
  false alarms, 7/20 at -0.05, 19/20 at -0.10, 19/20 at -0.20; VH 0/20, then
  0, 7, 20 of 20 at -0.5, -1, -2 dB.
- **Product**: landing map with showcase cards, place search and satellite
  toggle; story-first verdict page; track record; batch upload `/batch` with
  Markdown/JSON reports; permalinks; time-lapse frames (`*_frames.json`,
  served as `/api/runs/<id>/t<i>.png` only once a route is added, see below);
  pixel change test module (`pixels.py`, not yet wired into `run.py`).
- **Docs**: `docs/METHOD.md`, `docs/REDTEAM.md` (adversarial review with
  numbers), `SITES.md`, `DEPLOY.md`, `PLAN.md`.
- **Tests**: `python -m pytest -q` is green (xfails are deliberate:
  `tests/test_redteam.py` encodes 7 known weaknesses with strict xfail so a fix
  flips them; `tests/test_app_breakdate.py` has one xfail).

### Unfinished, and where it lives
1. **Sindh wide rerun** (`python -m scripts.run_sites sindh`, mode wide,
   150-400 km) was still running at the stop; if `showcase/` has no updated
   Sindh JSON with `"mode": "wide"`, rerun it (about an hour).
2. **Design pass**: branch `wip-design` (commit 239b46e) holds the four-act
   verdict story with the before/after slider; `docs/design-pass-slider.patch`
   is the first attempt. Direction: Act 1 "What we saw" = slider (drag divider,
   Before/After labels, optional change-map overlay, time-lapse scrubber from
   `_frames.json`); Act 2 "What would have happened anyway" = trajectory
   chart with the actual line drawing in on scroll; Act 3 "The difference" =
   gap chart + the effect number counting up; Act 4 "How sure" = placebo strip,
   fake dates, evidence sentence, then the verdict word and, for CAN'T TELL,
   "Why not decisive" + "What would fix it"; sticky verdict pill; scroll
   reveal; Inter, paper/ink, hairline rules, no dashboard chrome. The critic
   agent's baseline critique was not written; run one (screenshots at 1280 and
   390, judge against Linear/Stripe/Planet Explorer) before merging.
3. **Blind validation**: `scripts/blind_sample.py` (seeded Hansen loss-year
   sampler, 663 lines) and `scripts/blind_validation.py` (parallel runner,
   writes `showcase/blind/results.jsonl`, `summary.json`,
   `docs/BLIND_VALIDATION.md`) exist with tests; `showcase/blind/sample.json`
   holds a partial draw. No verdict results yet. Resume with
   `python -m scripts.blind_sample --seed 20260918 ...` then
   `python -m scripts.blind_validation --sample showcase/blind/sample.json --parallel 3`.
4. **Red-team fixes** (ranked in `docs/REDTEAM.md`, not yet applied):
   (a) a flagged in-time placebo must return CAN'T TELL and disable the 4x
   pre-fit bypass (pre-trends were confirmed as events 9-14/15);
   (b) the haze despike deletes short floods: make it NDWI-aware in
   `s2.despike` and its three call sites; (c) `evidence.status_of` must apply
   the donor/pre-bin/pre-fit/controls-shifted gates. Then the edge-to-edge
   donor buffer in `geometry.donor_grid` and a nearest-cells "controls
   shifted" test. Re-run `scripts/power.py` after each.
5. **Wiring left**: `pixels.compute_pixel_change` into `run.py` (change map
   on the page); `/api/runs/<id>/t<i>.png` and `/frames` routes in
   `server.py`; `breakdate.py` ("when did it change?") behind a UI toggle;
   share-preview images, progressive results, rate limiting and health
   checks were specified but not started.
6. **Deployment** needs Mohib's Hugging Face or Render account (DEPLOY.md).

### Exact next steps, in order
1. `git checkout main && python -m pytest -q` (expect green with xfails).
2. Apply red-team fixes (a)-(c); re-run `python -m scripts.power` and
   `python -m scripts.validate_app`; commit with the numbers.
3. Finish Sindh wide; refresh with `python -m scripts.refresh_verdicts &&
   python -m scripts.track_record`; commit `showcase/`.
4. Merge `wip-design` after finishing acts 2-4 and a screenshot pass.
5. Run blind validation (target 100+), publish `summary.json` on the track
   record page (add a "Blind validation" section reading it), log failures here.
6. Deploy (DEPLOY.md), then send links.

### Design pass, merged (2026-09-18, final)
- The verdict page is now: one plain-English verdict line (serif display type,
  centred), the before/after slider with change-map toggle and time-lapse
  scrubber, one big plain number (percent of expected greenness for NDVI;
  value on the -1 to 1 scale for burn/water signals; dB for radar), the two
  charts with a one-line caption, one "how sure" sentence with the placebo
  strip, and everything else (numbers, control areas, receipts, method) behind
  details toggles. Judged on Grünheide and Rhodes desktop screenshots against
  incident.io's hero as the reference. Mobile only checked for nothing broken.
- After-images start 10 days after the event (smoke, standing water) and
  accept a 60% clear share, because burnt ground is classed "dark" by the scene
  classifier; Rhodes now shows the scar on 17 Aug 2023.
- Landing: serif wordmark, showcase cards with thumbnails and effect sizes,
  hover labels with dot markers on the map. Branches `design` and `wip-design`
  are merged/superseded; `main` is the state to deploy.

## 2026-09-19 — memory-bounded live runs, the hectare bug, mobile, and a CRITIQUE triage

Five tracks ran in parallel this session (three as subagents, plus an
independent read-only reviewer). What follows is what was decided and why, then
the triage of `CRITIQUE.md`.

### Why live runs died, measured rather than guessed

The read window was set by the **control ring, not by the drawn area**. For the
27 ha Grünheide polygon, `donor_grid` puts 400 same-size cells in a 1–12 km ring,
so `Zones.build` snapped a 24.5 × 24.5 km window and every scene was read over
**6.02 Mpx at 10 m** — while the treated polygon alone is **0.0028 Mpx**, about
2000× smaller. Per scene that window costs roughly 420 MB of arrays (int32 label
image 24 MB, four float32 bands 96 MB, three index rasters 72 MB, plus float64
upcasts inside the zonal reduction), and `APP_FETCH_WORKERS` was 8 on Render.

Two GDAL settings compounded it and are easy to miss: `VSI_CACHE_SIZE` was 50 MB
**per open file handle** (8 threads × 5 band handles ≈ up to 2 GB of cache
alone), and `GDAL_CACHEMAX` defaults to a share of *host* RAM, which a
container's cgroup limit does not constrain.

Scene counts for the same area, measured against Planetary Computer: 1594 found
for the ring bbox, **389 covering the drawn area**, all distinct acquisition
minutes; 231 at cloud < 60, 163 at cloud < 40.

### Decision: a `profile` argument, not a rewrite

`run_verdict(..., profile=...)` → `fetch_area(..., profile=...)`:

- **`full`** (default, offline): unchanged. Showcase, validation and
  track-record numbers must not move because of a deployment fix.
- **`live`** (the server's default for user-drawn runs): the treated area is
  read **alone at 10 m** in its own tight window; control cells are read
  **separately at 40 m** from the COG overviews and joined on event-anchored
  bins by `prep.binned_groups` — the same two-pass structure wide mode already
  used, so this reuses a proven path rather than inventing one. Scenes are cut
  *before any pixel is read*: `eo:cloud_cover < 60` at search time, one tile per
  acquisition minute, and at most 2 scenes per 10-day analysis bin, least cloudy
  first. 120 control cells (was 400), 40 donors (was 80), 3 reader threads
  (was 8).

One tile per acquisition minute is the cheapest of these and was pure waste
before: adjacent MGRS tiles overlap by ~10 km, so a single acquisition appeared
up to four times and **all copies were read at full cost and then averaged** by
`merge_duplicates`. Capping per bin follows from the estimator already taking a
median within each 10-day bin — a fifth cloudy scene in a bin costs a full read
and changes almost nothing.

`choose_donor_res` walks 40 / 60 / 80 m and raises `MemoryBudgetError` *before
any read* if even the coarsest does not fit, so an impossible area fails fast
with an explanation instead of being OOM-killed. The server surfaces that, and a
real `MemoryError`, as explained job errors.

Independent of profile: `VSI_CACHE_SIZE` 50 MB → 4 MB, `GDAL_CACHEMAX` pinned to
48 MB, `GDAL_NUM_THREADS=1`; `s2.process_scene` reads, reduces and releases one
band at a time, keeping only B08 across steps; `extract.zone_means` reduces in
512-row blocks; new `extract.zone_counts` avoids allocating a full-size float32
of zeros purely to count pixels.

**Honest limitation of this fix, and it matters methodologically.** Live mode now
measures the treated area at 10 m and its controls at 40 m, from separate STAC
searches with their own dates. That is exactly the weakness `CRITIQUE.md` issue 6
raises against wide mode: it gives up co-observation (treated and control read
from the same pixels of the same scene, which cancels most atmosphere, sun-angle
and BRDF effects) and mixes two supports with no intercept term. The live-vs-full
comparison exists to measure what that costs. Until it has, **live verdicts must
not be presented as equivalent to full-mode verdicts.**

### Not deployed yet, deliberately

`main` auto-deploys to Render, so the memory work is staged on
`claude/elegant-franklin-en2noi` and **not merged to `main`** until a live run is
shown to produce correct results under a real memory limit, not merely to fit.
A run that fits because every read failed is not a fix.

### Test-environment note, so the next session does not repeat it

Docker is available here but the sandbox's egress proxy does not serve container
traffic to Planetary Computer: GDAL's `/vsicurl` reads fail TLS verification
(`self-signed certificate in certificate chain`) and, once the CA is added to
certifi, the STAC search returns 403. Container runs therefore reported
**0 observations** and a misleadingly low peak RSS — the memory looked fine only
because nothing was read. `RLIMIT_AS` is also not a usable substitute: it counts
reserved address space, which numpy/scipy/GDAL over-reserve, so a 512 MB cap
fails at import or on thread creation rather than on the workload. What does
work: a real **cgroup v1** memory limit
(`/sys/fs/cgroup/memory/<name>/memory.limit_in_bytes`), verified to kill a
deliberate 900 MB allocation at ~500 MB. Note this host is cgroup **v1**; a
directory made under `/sys/fs/cgroup/` is not a cgroup and its `memory.max` is
an inert file that enforces nothing.

### Two pre-existing failures fixed so the suite runs at all

- `requirements.txt` was missing `fastapi` and `httpx`, so `pytest` aborted at
  collection on `tests/test_app_server.py` and `tests/test_app_batch.py`. This is
  why CI cannot have been green (`CRITIQUE.md` issue 15).
- `tests/test_known_answer.py` asserted Rhodes must not be REAL, but Rhodes was
  deliberately re-run in **wide** mode, where REAL is the intended answer. The
  test now asserts on the mode that produced the run, which is the distinction it
  was actually trying to make: a *ring* run of an event larger than the ring must
  not be REAL.

### The hectare bug was not what I assumed

My hypothesis was a leaflet-draw 1.0.4 / Leaflet 1.9.4 incompatibility. **That
was wrong**, and was disproven in a real browser: Leaflet 1.9.4 still ships the
deprecated `_flat` aliases leaflet-draw needs, `showArea: false` already avoids
the one `readableArea` path that breaks, drawing completes and `draw:created`
fires with zero console errors. Recorded because the wrong hypothesis was
plausible and cost a detour.

The actual bug was **two client/server disagreements**:

1. The client measured area with a local equirectangular projection while the
   server reprojects to the polygon's UTM zone. Over a 576-case grid the two
   differ by −0.75% to +0.53%, so near the 0.5 / 500 ha limits the client
   enabled "Check it" for polygons the server then rejected with a 400 — and the
   landing page's hectare figure never matched the verdict page's, which shows
   the server's value. Fixed by computing the area the way the server does
   (WGS84 → UTM, planar ring centroid to pick the zone, shoelace in UTM),
   validated against pyproj/shapely over 576 rings spanning lat −75…75 and
   0.5–500 ha: worst relative difference **1.96e-07**.
2. `layer.toGeoJSON()` was posted with **unwrapped longitudes**. Leaflet pans
   across world copies, and at the landing page's own default view a
   1400 px window already spans lng −246…+246, so a polygon drawn after panning
   east carried lng ≈ 358.5 for a point really at −1.5. Area is
   translation-invariant, so the hectare line looked perfectly normal and submit
   was enabled; the server then rejected it — with a message naming *latitude*
   when the problem was longitude (`geometry.py:69-70` tests both in one
   branch). Fixed by wrapping every vertex by the same multiple of 360 (so a ring
   straddling the antimeridian stays contiguous) and posting the same ring that
   was measured.

Also found: at 1366×768 the run form opened entirely below the fold of the
scrolling side panel, so the user drew an area and saw no "Check it" at all.

### Mobile: sheet in mobile-only CSS, desktop proven unchanged

Google-Maps-style bottom sheet on the landing page: three snap points (peek
≈120 px, half 55vh, full 92vh), velocity-aware release, and the Google Maps
drag-vs-scroll rule (content scrolls unless the sheet is at full *and* already
scrolled to the top *and* the drag is downward). It attaches to the existing DOM
from a separate `web/mobile.js` and never touches `landing.js`; `web/mobile.css`
is mechanically verified (brace-depth walk) to contain nothing outside a single
`@media (max-width: 640px)` block.

Desktop is **byte-identical** — 0 differing pixels on `/`, `/v/<id>`,
`/track-record` and `/batch` at both 1280×800 and 1920×1080. That claim is only
worth anything because the harness was first validated against itself: two
independent captures of the *unmodified* base branch, also 0 px. An earlier
~150–200 px verdict-page diff turned out to be `chart.js`'s ~1.1 s draw-in
animation racing the screenshot; the harness now forces
`prefers-reduced-motion: reduce`, which `chart.js` already respects. A
"looks like jitter" explanation was not accepted without that control.

One real cascade bug caught on the way: `mobile.css` linked *before* each page's
unconditional inline `<style>` block lost cascade ties at equal specificity, so
desktop rules clobbered mobile ones. The link now comes after.

### CRITIQUE.md triage — judged, not obeyed

An independent read-only reviewer produced `CRITIQUE.md` (23 issues) against
commit `6d8776d`. I verified the claims I acted on rather than taking them on
trust; where I disagree with the framing I say so. **No statistical method was
changed on the strength of the critique** — the method items are logged below
with the reasoning and left for a deliberate decision, because changing an
estimator in response to a reviewer, without a held-out set, is the same mistake
issue 1 is about.

Verdict key: **valid** / **partly valid** (the finding is real but the framing or
severity overstates it) / **wrong**.

| # | Sev | Verdict | One-line reason | Action |
|---|---|---|---|---|
| 1 | BLOCKER | valid | Verified: `verdict.py:68` does bypass the pre-fit gate at `4×`, and the two commits that add the rescuing rules are titled for the behaviour they rescue; Rhodes/Sindh control radii are hand-set in `run_sites.py:23,31` and unreachable from the UI. | No method change. Blind validation (track D) is the only real answer; 34 event runs exist, 0 control runs. Open. |
| 2 | BLOCKER | partly valid | The unapplied red-team fixes are a logged HANDOFF item, not a hidden flaw — but it is true that `docs/METHOD.md` §9 "Known limits" omits the two failures the repo's own red team calls "breaks", and `README.md` never links `docs/REDTEAM.md`. That gap is the credibility problem, not the backlog. | **Doing now:** publish both breaks in METHOD.md §9 and link REDTEAM.md from README. |
| 3 | BLOCKER | valid | Independently measured before reading the critique; same root cause. | **Fixed** this session (live profile). Its second half — live runs are threads *inside* the web process, so an OOM kills the showcase too — is valid and **not** fixed. Open: run jobs in a subprocess. |
| 4 | MAJOR | valid, and the sharpest finding here | Donors are ranked by pre-event fit **to the treated unit** and truncated to the best K (`donors.py:63-67`), then the in-space placebo is computed over that same treated-optimised pool. That breaks the exchangeability Abadie's placebo test rests on, in the treated unit's favour, so the reported p is anti-conservative on every published run. | No change yet, deliberately. Correct fix is to re-select donors for each placebo unit (each placebo unit gets its own best-K pool), or to drop truncation for the placebo distribution. Highest-priority method question. Open. |
| 5 | MAJOR | partly valid | Spatial clustering inflating effective n is real and matters (Rhodes' 42 cells sit in 6 compact buckets by construction). But "p = 1/43 is exactly its own floor" describes *resolution*, not bias: with 42 donors 0.023 is the smallest attainable p, and reaching it means no donor beat the treated unit — the strongest available evidence. The defect is presenting it as 42 independent draws. | Open: report effective n / cluster-aware p, or state the resolution limit on the page. |
| 6 | MAJOR | valid, and it now applies to my own live profile | Wide mode reads the treated area at 10 m and each donor group from its own STAC search at 40 m, giving up co-observation and mixing supports with no intercept. The live profile I added this session does the same thing by design. | Open, and this is precisely what the live-vs-full comparison must quantify. Logged above under the memory fix. |
| 7 | MAJOR | valid | Verified: the sentence says "*k* of *n* untouched cells showed a divergence this large" (an effect-size count) but computes *k* from `placebo_p`, the RMSPE-**ratio** p. `placebo_p_effect` is computed and stored and never shown. | Quick, but it changes a reported statistic on the verdict page — **awaiting Mohib's go-ahead** on whether to fix the sentence or switch to `p_effect`. |
| 8 | MAJOR | partly valid | The buckets are defensible (a REAL on a no-change site *does* count as a false alarm, a NOT REAL on a real event *does* count as a miss), so "unfalsifiable" overstates it. What is fair: every *failure to detect* lands in "can't tell", so "0 misses, 0 false alarms" beside "misses included" reads as stronger than it is, with 5 of 9 can't-tell unheadlined. | Open: headline the can't-tell rate next to the record. Blind validation is the substantive fix. |
| 9 | MAJOR | valid | Verified: `power.py:55` gates on interval + min effect + placebo p only; it omits the pre-fit gate, the controls-shifted gate and the in-time placebo flags that `verdict.decide` applies. The published table therefore characterises a decision rule the product does not use. | Open: either drive `verdict.decide` from `power.py` and re-run, or relabel the table. Re-running changes a published number, so it is not a silent edit. |
| 10 | MAJOR | valid | `docs/METHOD.md` §9-10, `showcase/track_record.json` and `showcase/validation.md` disagree on Rhodes and on Grünheide's interval. | Open: regenerate all three from the committed runs, or mark the stale ones stale. Cheap and worth doing next. |
| 11 | MAJOR | valid | Verified: `select_donors` returns indices into the **coverage-filtered** columns, and `run.py:84` mapped them through an index over **all** cells, so the control-areas map drew the wrong cells whenever any cell was dropped for coverage — most runs. Display only; estimation uses the matrix columns directly and is unaffected. | **Fixed** this session: `DonorSelection.cell_index`, plus a regression test. |
| 12 | MAJOR | valid | `pollJob` returns silently on every error, forever, so a dead job leaves the UI spinning. | Quick — but it is UI. **Awaiting go-ahead.** |
| 13 | MAJOR | partly valid | "This area burned" is taken from the user's dropdown and stated as a finding, which is a real wording fault. But the method never claims to identify the mechanism and the page's frame is "you told us what happened, we test whether it moved more than expected", so this is a copy problem, not the causal over-claim the title implies. | UI copy. **Awaiting go-ahead.** |
| 14 | MAJOR | valid | The largest number on the page is `point / mean(|counterfactual|)` as a percentage, with no interval and no definition anywhere in the UI. | UI. **Awaiting go-ahead.** |
| 15 | MAJOR | valid | Reproduced: collection aborted on missing `httpx`; with those files skipped, `test_known_answer.py` failed on committed data. | **Fixed** this session. Suite is now 233 passed, 3 skipped, 8 xfailed, 0 failed. |
| 16 | MINOR | valid | `donor_grid:109` measures `inner_m` centroid-to-polygon, so at ≥200 ha the nearest kept control can share an edge with the treated area — contradicting METHOD.md §3. Costs power rather than causing false alarms. | Open: switch to edge-to-edge distance. Changes donor eligibility and therefore published numbers, so not a silent edit. |
| 17 | MINOR | valid | Both halves true. | **Fixed for live runs** (cloud < 60; controls at 40 m). SCL is still upsampled to 10 m on the treated pass, but that window is now ~3 kpx, so the cost is immaterial. Docs should stop claiming 20 m. |
| 18 | MINOR | valid | No rate limit, no job timeout, in-memory job state on a tier that spins down. The job timeout is the dangerous one: `_worker` holds the semaphore of 1 for the life of a run, so one wedged job blocks every future live run until restart. | Open. The job timeout is cheap and I recommend doing it before any public link goes out. |
| 19 | MINOR | valid | `conformal_interval:167` infers whether it is in index units or dB from the magnitude of the pre-RMSE (`1.0 if scale < 0.3 else 10.0`). Fragile by construction. | Open: pass the signal's units explicitly. Method-adjacent, so logged rather than done. |
| 20 | MINOR | valid | Nothing pinned beyond `numpy<3`, and `validate_app.py` reads from a gitignored `data/cache/`, so `showcase/validation.md` cannot be reproduced by anyone else. | Partly addressed (added the missing test deps). Open: pin versions, and drive validation from committed inputs. |
| 21 | MINOR | valid | Correct on all counts for the old inline sheet. | **Fixed** this session (track/mobile). The `100vh`-vs-`dvh` point stands: the new sheet uses `vh`, so the URL bar still shifts it. Open, small. |
| 22 | MINOR | valid, and under-rated by its own severity | No `og:`/`twitter:` tags and one shared `<title>`, while `SPEC.md`'s entire distribution plan is "send them a permalink". The `*_after.png` thumbnails already exist to use. | **Awaiting go-ahead** (touches page metadata). Recommend doing it — highest value per minute on this list. |
| 23 | NIT | valid | All three. | Dead `_box` import **fixed** incidentally by the `_fetch_group` rewrite. `prep.bin_days` patching and the `HF_TOKEN`-in-URL habit: open. |

**Summary: 18 valid, 5 partly valid, 0 wrong.** Fixed this session: 3, 11, 15,
17 (live path), 21, 23. Doing now: 2. Awaiting go-ahead because they change
user-facing copy, numbers or metadata: 7, 12, 13, 14, 22. Left open with
reasoning, not silently changed: 1, 4, 5, 6, 8, 9, 10, 16, 18, 19, 20.

The reviewer's bottom line — that the published evidence does not describe the
shipped product — is fair, and issue 4 is the one I would most want settled
before showing this to anyone who does this professionally.
