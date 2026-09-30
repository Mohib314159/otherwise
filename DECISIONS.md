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
| 9 | MAJOR | valid | Verified: `power.py:55` gates on interval + min effect + placebo p only; it omits the pre-fit gate, the controls-shifted gate and the in-time placebo flags that `verdict.decide` applies. The published table therefore characterises a decision rule the product does not use. | **Code fixed 2026-09-30, table not yet re-run**: `power.py` now builds each unit's `SignalResult` with `run.signal_result` (shared with `_analyse`) and counts `verdict.combine`'s status. See the 2026-09-30 entry. The published `showcase/power.json` still describes the old gate until it is re-run. |
| 10 | MAJOR | valid | `docs/METHOD.md` §9-10, `showcase/track_record.json` and `showcase/validation.md` disagree on Rhodes and on Grünheide's interval. | Open: regenerate all three from the committed runs, or mark the stale ones stale. Cheap and worth doing next. |
| 11 | MAJOR | valid | Verified: `select_donors` returns indices into the **coverage-filtered** columns, and `run.py:84` mapped them through an index over **all** cells, so the control-areas map drew the wrong cells whenever any cell was dropped for coverage — most runs. Display only; estimation uses the matrix columns directly and is unaffected. | **Fixed** this session: `DonorSelection.cell_index`, plus a regression test. |
| 12 | MAJOR | valid | `pollJob` returns silently on every error, forever, so a dead job leaves the UI spinning. | Quick — but it is UI. **Awaiting go-ahead.** |
| 13 | MAJOR | partly valid | "This area burned" is taken from the user's dropdown and stated as a finding, which is a real wording fault. But the method never claims to identify the mechanism and the page's frame is "you told us what happened, we test whether it moved more than expected", so this is a copy problem, not the causal over-claim the title implies. | UI copy. **Awaiting go-ahead.** |
| 14 | MAJOR | valid | The largest number on the page is `point / mean(|counterfactual|)` as a percentage, with no interval and no definition anywhere in the UI. | UI. **Awaiting go-ahead.** |
| 15 | MAJOR | valid | Reproduced: collection aborted on missing `httpx`; with those files skipped, `test_known_answer.py` failed on committed data. | **Fixed** this session. Suite is now 233 passed, 3 skipped, 8 xfailed, 0 failed. |
| 16 | MINOR | valid | `donor_grid:109` measures `inner_m` centroid-to-polygon, so at ≥200 ha the nearest kept control can share an edge with the treated area — contradicting METHOD.md §3. Costs power rather than causing false alarms. | **Fixed in code** (2026-09-30, see entry below): inner gap is edge-to-edge in `donor_grid` and `wide_candidates`. Published showcase numbers predate it and need a re-run. |
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

## HANDOFF (2026-09-19)

Branch to work from: **`claude/elegant-franklin-en2noi`**. `main` is untouched
this session and still auto-deploys to Render, so nothing here is live yet.

`python -m pytest -q`: **254 passed, 3 skipped, 8 xfailed, 0 failed.** The 8
xfails are deliberate (`tests/test_redteam.py` encodes 7 known weaknesses so a
fix flips them; `tests/test_app_breakdate.py` has one).

### Track A — memory fix for live runs: DONE, verified, not deployed

Live runs fit. A cold Grünheide live run produced **REAL** (agreeing with full
mode) from **113 S2 and 208 S1 observations**, at **339 MB peak RSS** against a
400 MB target. A second cold run under an **enforced 512 MiB cgroup** peaked at
**467 MB of cgroup-accounted memory with no OOM kill**.

Read those two numbers as different things: 339 MB is resident set; 467 MB is
cgroup accounting, which includes reclaimable page cache from the COG reads. The
RSS figure is the one to compare against the 400 MB target; the cgroup figure is
what a container limit actually counts, and 467/512 is tighter than I would like.
**Recommended margin, not yet applied:** `APP_LIVE_FETCH_WORKERS=2` (from 3) and
`APP_GDAL_CACHEMAX_MB=32` (from 48). Not applied mid-comparison because it would
invalidate the timings in flight.

**The real remaining constraint is CPU, not memory.** That 25-minute wall clock
was on a box with about two usable cores (43 min CPU). Render's free tier is
0.1 CPU. A live run there could take hours, and the tier spins down after 15
idle minutes. Deciding what to do about that — a longer `APP_JOB_TIMEOUT_S`, a
paid instance, precomputed-only public runs, or a queue with email-on-done — is
the next real decision, and it is a product decision, not a code one.

Where it lives: `src/app/fetch.py` (`PROFILES`, `_fetch_live_ring`,
`best_tile_per_minute`, `cap_per_bin`, `choose_donor_res`, `MemoryBudgetError`),
`src/app/s2.py` (one band at a time), `src/app/extract.py` (GDAL caps,
`zone_counts`, chunked `zone_means`), `src/app/run.py` (`profile`, `LIVE_DONOR_K`),
`src/app/server.py` (`LIVE_PROFILE`, `JOB_TIMEOUT_S`), `scripts/memtest.py`,
`tests/test_app_live_profile.py`.

**Next step:** apply the margin settings above, re-run `scripts/memtest.py` on a
second, larger area (a 300–500 ha polygon, not just 27 ha) to confirm the budget
holds at the size limit, then decide the CPU question before merging to `main`.

### Track A2 — live vs full comparison: RUNNING, incomplete

`scripts/compare_profiles.py`, resumable, checkpointing to
`showcase/profile_comparison.json` after every site. The full arm is read from
the committed `showcase/*.json` (they are full-mode runs); the live arm is run
now. It holds the control geometry constant and varies only the profile — an
earlier version used `mode="auto"` for the live arm, which would have measured
mode and profile together.

At handoff: **0 of 10 live runs recorded.** Each cold run is ~25 minutes, so the
full sweep is about four hours. Nothing is inferred from an unfinished sweep, and
the table prints "not run" rather than an estimate.

**Next step:** let it finish, or resume with
`python -m scripts.compare_profiles`; rebuild the table any time with
`--table`. Then decide the "quick check" labelling: live mode reads controls at
40 m from a separate catalogue search, giving up the co-observation full mode
relies on (this is `CRITIQUE.md` issue 6 applied to the live path), so unless the
comparison shows it costs nothing, live verdicts should be labelled and should
not be presented as equivalent to the published runs.

### Track B — hectare input: DONE, merged

Merged from `track/hectare` (`e85d787`). Root cause was **not** the
leaflet-draw/Leaflet version mismatch I assumed — that was disproven in a real
browser. It was two client/server disagreements: the client measured area
equirectangularly while the server uses UTM (−0.75%/+0.53%, so the client
enabled "Check it" on polygons the server rejected with a 400), and
`toGeoJSON()` posted unwrapped longitudes after the map panned across a world
copy. Client area now matches the server to 1.96e-07 over 576 validation rings.
`tests/test_area_input.py` (8 tests, Playwright-driven, skips cleanly without a
browser).

**Not applied, and needs a decision** (reported by the track, deliberately left
alone because it is a layout change): give the showcase list its own scroll
region in `web/index.html` so the run form is not pushed below the fold on short
laptop screens, and extend the draw hint to say how to close a polygon
("Click to add corners, then click the first one to close") — a user who clicks
two points and then the first one currently hits a dead end with no feedback.

### Track C — mobile redesign: DONE, merged

Merged from `track/mobile` (`f860e88`). Google-Maps-style bottom sheet, three
snap points, velocity-aware release, correct drag-vs-scroll. All mobile rules
live in `web/mobile.css` inside one `@media (max-width: 640px)` block, verified
mechanically. Desktop is **byte-identical**: 0 differing pixels on `/`,
`/v/<id>`, `/track-record` and `/batch` at 1280×800 and 1920×1080 — and the
harness (`scripts/desktop_screenshots.py`) was validated against itself first,
which is what makes the claim worth anything.

**Open, small:** the sheet uses `vh`, so a mobile URL bar still shifts it;
`dvh`/`svh` is the fix. Mobile screenshots in `docs/screenshots/mobile/` show a
blank map because this sandbox's proxy blocks the Leaflet CDN for the browser —
the sheet itself is faithfully captured, but nobody has seen it over real tiles.

### Track D — blind validation: HALF DONE, merged

Merged from `track/blind` (`ac3c5ca`), plus the `include_router` line in
`server.py` that the track could not add itself.

**Done:** seeded sampler (Hansen GFC-2023 v1.11 + MTBS), resumable parallel
runner, `/review` blind review page, three-way rate reporting, analyst
annotation layer, `docs/BLIND_VALIDATION.md`, 16 tests including two that assert
the blind payload leaks no ground truth.

**The numbers, exactly:** 247 items drawn (130 events, 117 controls) at seed
20260918; **34 verdict runs completed, all of them events, zero controls.** So
there is a detection rate (18/34 REAL, 1/34 NOT REAL, 15/34 can't tell) and
**no false-alarm rate at all**. The detection figure must not be quoted on its
own, and the page and docs say so instead of rendering a placeholder. **No human
has reviewed anything**: 0 reviews, and `scripts/blind_review_prep.py` has never
been run, so the review pool is empty.

Runs were produced at commit `6d8776d`, i.e. **before** this session's live
profile. They are full-mode numbers.

**Next step:** `APP_CACHE_DIR=data/cache/blind python -m scripts.blind_validation
--sample showcase/blind/sample.json --parallel 3 --shuffle-seed 20260918 --out
showcase/blind/`. The shuffle makes the finished subset a random subsample, so
control runs — and therefore the false-alarm rate — start appearing immediately.
Then `python -m scripts.blind_review_prep --frames` to fill the review pool.
Paused during Track A2 so the two do not contend for CPU.

**Also missing:** no floods or water change in the sample (Copernicus EMS has no
programmatic index to sample mechanically; EFFIS timed out; JRC Global Surface
Water carries no event year in the change layer, though its yearly
classification product would). So nothing here speaks to the flood path, which
is also where the red team's E7 "break" lives.

### Track E — critique: TRIAGED

`CRITIQUE.md` is on the branch; the 23-item triage table is in the section above
(18 valid, 5 partly valid, 0 wrong). Fixed this session: 3, 10, 11, 15, 17
(live path), 18, 21, 23, and 2 (published the red team's two "breaks" in
METHOD.md §9 and linked REDTEAM.md from the README).

**Awaiting Mohib**, all user-facing: 7 (the "how sure" sentence reports the
RMSPE-ratio p while describing the effect-size count), 22 (no `og:` tags, one
shared `<title>`, though the whole distribution plan is permalinks), 12 (a dead
job spins the UI forever), 13 and 14 (the verdict copy states the user's
dropdown as a finding; the hero percentage has no interval or definition).

**Left open deliberately, method not changed on a reviewer's say-so:** 1, 4, 5,
6, 8, 9, 16, 19, 20. Of these, **4 is the one to settle first**: donors are
ranked by pre-event fit to the treated unit and truncated to the best K, then
that same treated-optimised pool is used as the placebo distribution, which
breaks the exchangeability the placebo test rests on and makes every published
p anti-conservative. The fix is to re-select donors for each placebo unit, or to
drop the truncation for the placebo distribution. It will move published
numbers, so it belongs with a re-run of `scripts/power.py` and the showcase.

## 2026-09-19 — CRITIQUE #4: making the placebo test symmetric (pre-registered)

**Written before implementing the change and before looking at any new numbers,
deliberately.** The finding this fixes is that verdict rules were adjusted after
seeing which sites they rescued (`CRITIQUE.md` issue 1). Deciding the fix first,
in writing, and then publishing whatever the re-runs produce, is the only way
this change does not repeat that mistake. Mohib's instruction: every placebo unit
must go through the identical donor-selection procedure as the treated unit, then
re-run `scripts/power.py` and all showcase sites and publish the result even if
verdicts weaken.

### The defect, stated precisely

`run._analyse` does this:

1. `b.matrix` holds the treated series in column 0 and **every** covered
   candidate cell in columns 1..n (n is 120 in live mode, up to 400 in full).
2. `select_donors` ranks those candidates by pre-event RMSE **to the treated
   series**, filters them by the **treated** area's land cover and elevation, and
   keeps the best `k` (80 full, 40 live).
3. The treated unit is fitted on that pool.
4. `space_placebo` then takes each donor **inside that pool** and fits it on the
   other K-1 members of the same pool, reusing the treated unit's tuned ridge
   penalty.

So the treated unit's counterfactual is built from an argmax over n candidates,
while a placebo unit's counterfactual is built from a pool selected for a
*different* unit. Three separate asymmetries, all pushing the same way:

- **Selection.** The treated pool is chosen by minimising pre-period fit error on
  the same pre-period the RMSPE ratio's denominator is computed from. That
  denominator is therefore optimistically small for the treated unit and honest
  for every placebo. Since the placebo p is `P(ratio_j >= ratio_treated)` and the
  ratio is `RMSE_post / RMSE_pre`, shrinking the treated denominator inflates the
  treated ratio and **shrinks p**. Anti-conservative, on every published run.
- **Covariates.** Candidates are filtered to match the treated area's land cover
  and elevation. A placebo unit in a different class is compared against a pool
  matched to the treated area, not to itself, so its counterfactual is poor for
  reasons that have nothing to do with an event — which again makes the treated
  unit look unusually good.
- **Ridge penalty.** `space_placebo` is passed `lam=f.lam`, the value
  `_choose_lambda` tuned on the treated unit's own holdout. Placebos inherit a
  hyperparameter fitted to someone else's data.

The RMSPE *ratio* statistic (Abadie's device) partly protects against
heterogeneous fit quality, which is presumably why this was not obvious. It does
not protect against in-sample optimisation of its own denominator.

### The fix, exactly

`space_placebo` takes the **full candidate pool** and a selection callable, and
for each placebo unit j:

1. re-runs `select_donors` with j in the treated slot, over all candidates except
   j, using **j's own** land cover and elevation, with the same `k` and the same
   relaxation rules;
2. fits j on **its own** selected pool;
3. chooses **its own** ridge penalty by the same holdout rule (`lam=None`),
   rather than inheriting the treated unit's.

One further change follows from the same principle and is part of this fix:
**placebo units are drawn from all candidates, not from the treated unit's
selected K.** The reference distribution should be over comparable units, not
over units pre-selected for resembling the treated area — otherwise the
comparison set is itself chosen by the thing being tested.

Two asymmetries remain and are accepted, with reasons:

- A placebo unit chooses from n-1 candidates while the treated unit chooses from
  n. Unavoidable, and negligible at n = 120.
- The treated unit is never offered as a donor to a placebo unit, because it may
  carry the event. That is deliberate, and matches the treated unit's own pool
  excluding itself.

### What I expect to happen, recorded before measuring

Placebo units will now get their own best-fitting pools, so their pre-fits
improve, their denominators shrink and their ratios rise. **Placebo p-values
should go up and verdicts should weaken.** If they do not move at all I should
suspect the change is not wired in. If a site's p moves from below 0.05 to above
it, that site was resting on the asymmetry, and the honest outcome is that it
stops being REAL. The four current REALs (Grünheide, Rhodes, Table Mountain,
Austin) are the ones at risk. The null sites should be unaffected or become more
clearly not-REAL, which is a check in the other direction: if a null site becomes
*more* significant, something is wrong with the implementation.

Cost is roughly 7 extra estimator fits per placebo unit (6 for the lambda
holdout, 1 for the fit) — about 420 NNLS solves per signal at 60 units, which the
fast NNLS path makes affordable.

### Deliberately NOT changed in the same step

The **in-time** placebo (`time_placebos`) has the same class of leakage: it
selects donors using the whole pre-period, including the window after its own
fake event date. Fixing it means re-selecting donors using only data before the
fake date. That is a real defect and it is logged here as the next thing to fix,
but it is **not** part of this change, so that the re-run measures exactly one
thing. Changing two placebo procedures at once would make it impossible to
attribute any movement in the published numbers to either.

### What the implementation showed, against the prediction above

**My pre-registered prediction was too simple, and I am recording that before
the re-runs rather than quietly adjusting it.** I predicted "placebo p-values
should go up". On synthetic panels p went *down* — 0.0909 to 0.0244 on all eight
seeds. That looked like the opposite of the intended effect. It is not:

- 0.0909 is exactly 1/11 and 0.0244 is exactly 1/41. **Both are the floor**,
  `1/(units + 1)`. In each case the treated unit beat every placebo, so p was
  pinned at the smallest value the rank statistic can express. What changed was
  not the evidence but the **resolution**, because the fix also draws placebo
  units from the whole candidate pool instead of the treated unit's selected k,
  taking the unit count from 10 to 40 on that panel.
- That is the same distinction I drew against `CRITIQUE.md` issue 5, where the
  reviewer called Rhodes' p "exactly its own floor" a defect. A floor is a
  resolution limit, not a bias, and it cuts both ways: more placebo units mean a
  finer p and the *ability* to express stronger evidence.

Isolating the bias with the **unit set held fixed**, which is the only way to
compare procedures rather than resolutions:

- A unit fitted on its own selected donors fits better than the same unit fitted
  on the treated unit's pool: **8 of 9 units**, median pre-event RMSE lower.
  This is the asymmetry, measured directly.
- With the unit set fixed, the **median placebo RMSPE ratio rises from 1.259 to
  1.373**. Placebos become harder to beat, so the test gets stricter. That is the
  conservative direction predicted, and it is what the fix was for.
- On null panels (no real effect) the symmetric procedure reached p <= 0.05 in
  **0 of 12** seeds, mean p 0.514. The sanity check in the other direction
  passes: nothing became spuriously significant.

So the mechanism is confirmed and the direction of the *procedural* change is
conservative, while the *resolution* change is a separate, benign effect that
moves p down. **On the real sites the two will combine**, and which dominates is
exactly what the re-runs will show. In full mode the unit count is unchanged
(`max_units=60`, and k was already 80), so the resolution effect should be
absent there and only the conservative effect should appear. In live mode units
go from 40 to 60, so a small resolution effect is expected on top.

The tests in `tests/test_placebo_symmetry.py` assert the mechanism and the null
rate rather than a p direction, for this reason, and say so.

## 2026-09-19 — where live runs should run, and two corrections

### The 2.8-hour figure, pinned down

An independent review of the hosting question could not find the "2.8 hour worst
case" I had been quoting, and was right to object: it was not written down
anywhere, and the committed Rhodes run records `timing.total_s = 3226.0`, i.e.
**53.8 minutes**. Both numbers are real and they measure different things:

| Run | Profile | Mode | Wall | Where it is recorded |
|---|---|---|---|---|
| Rhodes, original | full | wide | 3226 s (53.8 min) | `showcase/0c2af4baa8c24486.json` |
| Rhodes, this session | live | wide | 10123 s (2.81 h) | `showcase/profile_comparison.json` |
| Grünheide, this session | live | ring | 1565 s (26 min) | same |
| Table Mountain, this session | live | ring | 1867 s (31 min) | same |

All of this session's figures are post-donor-window-fix, on this machine (about
two usable cores).

**The uncomfortable implication: live mode is not faster than full mode for wide
runs — on this evidence it is about twice as slow** (10123 s against 3226 s),
while using far less memory. Different machines and network conditions, n = 1
each, so this is weak evidence. But it does mean the live profile's justification
is *memory*, not speed, and nothing in the copy or docs should imply otherwise.
The likely cause is that wide mode makes a separate catalogue search and read per
control group, and the per-bin and cloud pre-filters save less when the groups
are small.

### Decision: do not run live jobs on GitHub Actions

`docs/LIVE_RUNS_DESIGN.md` works the question through. The blocking objection is
not technical — a 25-minute run fits comfortably inside the documented 6-hour
per-job limit — it is GitHub's Additional Product Terms, which prohibit using
Actions "as part of a serverless application" or for "any other activity
unrelated to the production, testing, deployment, or publication of the software
project", with account suspension as the stated penalty. A visitor-triggered
analysis service is exactly the shape that clause exists to stop, and the thing
at risk is the account the whole portfolio lives on, not a bill.

So: **Actions stays for owner-triggered batch work**, which is squarely within
the terms and would immediately unblock the parked Sindh wide rerun, the blind
validation runs and the `compare_profiles` sweep. Live-on-demand runs come off
the public critical path instead, and the permalink becomes the waiting room.
If live runs later earn their place, the per-second options (Modal and similar)
or a paid Render instance are the honest choices, with Render free kept as a thin
request relay so no token ever reaches the browser. Not built, not decided beyond
ruling Actions out — this needs Mohib, because it is the first thing here that
costs money.

Worth weighing against all of it, from SPEC.md: the primary audience clicks a
link from a cold email and needs the verdict in about 15 seconds. Live runs may
be a feature that sounds essential and is not.

### Correction: DEPLOY.md Route A was not free

`DEPLOY.md` recommended a Hugging Face Docker Space as the free route. Hugging
Face's own documentation now says otherwise
(https://huggingface.co/docs/hub/spaces-overview, read 2026-09-19):

> Static Spaces are free for everyone. Gradio and Docker Spaces run on compute
> and require a paid plan to create: PRO for personal accounts, Team or
> Enterprise for organizations.

PRO is listed at "$9 /month" (https://huggingface.co/pricing, read 2026-09-19).
`DEPLOY.md` is corrected, Render is relabelled as the free route and the one
actually deployed, and the measured live-run timings are stated there rather than
left to be discovered. The `hf-sync` workflow itself is unchanged and still
correct.

One genuine argument for paying it: CPU Basic is 2 vCPU and **16 GB RAM**, which
is enough to run the `full` profile, and that would dissolve the co-observation
caveat live verdicts must currently carry. The same argument applies to any
off-Render compute, so it is not specific to Hugging Face.

## HANDOFF (2026-09-19, end of session 2)

### What is live

**`main` is at `2717b38`**, which Render auto-deploys. It carries four finished,
tested pieces: the live-run memory fix, the hectare input fix, the mobile layout
(including a scroll bug that locked every non-landing page to one screen on a
phone), and the honest verdict copy plus server-rendered share previews. Suite on
that tree: **272 passed, 3 skipped, 8 xfailed, 0 failed**, smoke-tested against a
live server.

**`main` deliberately does NOT have** the CRITIQUE #4 placebo-symmetry fix, the
blind-validation surfaces, or the comparison results. All three are on
`claude/elegant-franklin-en2noi` (`ec9b310` at the time of writing). The deploy
commit message lists exactly what was held back and why.

**So main still computes an anti-conservative placebo p-value.** That is recorded
in `CRITIQUE.md`, in the triage in this file, and now in every downloaded report,
which prints a note whenever `placebo_symmetric` is false. It is the most
important thing outstanding.

### First thing to check on the live site

Whether Render's 0.1 CPU can finish a live run at all. Memory is solved; CPU is
not. Measured on a two-core machine: 26 min for a 27 ha ring run, 2.81 h for a
wide-control run. `APP_JOB_TIMEOUT_S` is 2400 s, so a run slower than 40 minutes
is now cancelled with a message rather than blocking the queue for ever — on 0.1
CPU that may cancel everything. If it does, the honest fix is
`APP_LIVE_RUNS=0` plus the "request an area" route in `docs/LIVE_RUNS_DESIGN.md`,
not a longer timeout.

### Unfinished, where it lives, and how to resume

**1. CRITIQUE #4 — placebo symmetry.** Branch `claude/elegant-franklin-en2noi`.
Pre-registered, implemented, 7 tests. Every placebo unit now re-runs the treated
unit's donor selection on itself, with its own covariates and its own ridge
penalty, and placebo units are drawn from the whole candidate pool. Verified
mechanism: own-pool fits beat inherited-pool fits for 8 of 9 units, median placebo
RMSPE ratio rises 1.259 → 1.373, 0 of 12 null panels reach p ≤ 0.05.

*Resume:* re-run `python -m scripts.power data/cache/<dir> NDVI` (it now runs both
procedures on the same cache, so the fix is measured rather than confounded with a
change of test area), then re-run every showcase site and publish the result even
if verdicts weaken, then `python -m scripts.method_tables` and
`python -m scripts.track_record`. **Be honest about the cost:** full-mode showcase
re-runs read ~6 Mpx windows per scene and those caches are gitignored and gone, so
this is hours per site, not minutes. Do not substitute live-mode numbers for
full-mode ones to save time; they are not the same measurement.

*Not done in the same step, on purpose:* the in-time placebo (`time_placebos`)
selects donors using the whole pre-period including the window after its own fake
event date. Same class of leakage. Fix it separately so each change's effect on
the published numbers stays attributable.

**2. Live-vs-full comparison.** `scripts/compare_profiles.py`, results in
`showcase/profile_comparison.json` on the branch. **4 of 10 sites**, and all four
REALs agree: effect sizes move by at most 0.016 (Rhodes, 3.4%).

*One thing I could not explain and did not paper over:* interval width goes both
ways — wider on Grünheide (×1.10) but narrower on Rhodes (×0.97), Table Mountain
(×0.60) and Austin (×0.72). I expected 40 m controls to widen intervals. Two
candidates, neither confirmed: coarser cells average more pixels and carry less
per-observation noise, or the per-bin scene cap changes how many observations
enter each bin. The remaining six sites, especially the two nulls and the marginal
Lützerath and Hasankeyf, should discriminate.

*Resume:* `python -m scripts.compare_profiles` (resumable, checkpoints per site);
`--table` rebuilds the table. **These results predate #4 on both arms**, so they
measure the profile difference under the old placebo and must be re-run after #4
lands.

**3. Blind validation.** Branch `claude/elegant-franklin-en2noi`. Harness, `/review`
blind review page, three-way rate reporting and the analyst layer are all built
and tested, including two tests proving the blind payload leaks no ground truth.
**247 items drawn, 34 verdict runs completed, all events, zero controls.** So
there is a detection rate and no false-alarm rate, which is not a blind test.
Nobody has reviewed anything; the review pool is empty.

*Resume:* `APP_CACHE_DIR=data/cache/blind python -m scripts.blind_validation
--sample showcase/blind/sample.json --parallel 3 --shuffle-seed 20260918 --out
showcase/blind/` — the shuffle makes the finished subset a random subsample, so
control runs and therefore the false-alarm rate start appearing immediately. Then
`python -m scripts.blind_review_prep --frames`. Note the runs on disk were
produced at `6d8776d`, i.e. before both the memory work and #4.

**4. Hosting.** `docs/LIVE_RUNS_DESIGN.md`. GitHub Actions is ruled out — not on
limits (a 25-minute run fits the 6-hour job cap easily) but on GitHub's Additional
Product Terms, which prohibit Actions as part of a serverless application, with
account suspension as the penalty. Actions stays for owner-triggered batch work,
which would unblock the Sindh wide rerun, blind validation and the sweep. The next
step costs money and needs Mohib.

**5. SPEC-v2.md is on `main` and has not been started.** It was uploaded during
this session and asks for the engine to be generalised so a "signal" is a plugin,
then air pollution, UK open data, urban heat and night lights — each with its own
known-answer tests and null power test before it is shown to users, and with land
required to keep working exactly as it does now. Nothing in this session addressed
it. Worth noting that its rule 1 ("run the existing test suite and land power test
after every merge") is the discipline the #4 re-runs above are already owed.

### Open items from CRITIQUE.md, unchanged

Fixed: 2, 3, 7, 10, 11, 12, 13, 14, 15, 17, 18, 21, 22, 23. Left open with
reasoning in the triage table above: 1, 4 (fixed on the branch, unpublished), 5,
6, 8, 9, 16, 19, 20. Issue 6 — wide mode giving up co-observation — now applies to
the live profile too, which is what the "quick check" label exists to admit.

### Live vs full: the completed sweep (10 of 10)

The sweep finished after the HANDOFF above was written. Correcting it: this is no
longer unfinished.

| Site | Expected | Full | Live | Agree | Full effect | Live effect | Full width | Live width | Full p | Live p |
|---|---|---|---|---|---|---|---|---|---|---|
| grunheide | REAL | REAL | REAL | yes | -0.606 | -0.601 | 0.156 | 0.172 | 0.029 | 0.024 |
| rhodes | REAL | REAL | REAL | yes | -0.468 | -0.452 | 0.178 | 0.172 | 0.023 | 0.036 |
| tablemountain | REAL | REAL | REAL | yes | -0.463 | -0.465 | 0.285 | 0.170 | 0.032 | 0.024 |
| austin | REAL | REAL | REAL | yes | -0.188 | -0.188 | 0.069 | 0.050 | 0.016 | 0.024 |
| saddleworth | REAL | CANT_TELL | **REAL** | **no** | -0.909 | -1.019 | 0.880 | 1.358 | 0.016 | 0.024 |
| lutzerath | REAL | CANT_TELL | CANT_TELL | yes | -0.074 | -0.083 | 0.109 | 0.116 | 0.623 | 0.854 |
| hasankeyf | REAL | CANT_TELL | CANT_TELL | yes | 0.101 | 0.759 | 2.050 | 1.600 | 0.951 | 0.268 |
| sindh | REAL | CANT_TELL | CANT_TELL | yes | -0.129 | -0.247 | 0.000 | 2.050 | 0.508 | 0.317 |
| richmond | NOT_REAL | CANT_TELL | CANT_TELL | yes | -0.013 | 0.004 | 0.091 | 0.075 | 0.933 | 0.854 |
| jau | NOT_REAL | CANT_TELL | CANT_TELL | yes | -0.011 | 0.020 | 0.054 | 0.119 | 0.639 | 0.854 |

**9 of 10 agree. Mean live/full interval width ratio 1.09, wider on 4 of 9.**

**The one disagreement matters and is not in live mode's favour.** Saddleworth
goes CAN'T TELL → REAL, and on the numbers that is live mode being *less*
cautious about a case the full run refused to call: its interval is wider
(1.358 against 0.880) on a radar signal that full mode already flagged as having
too few post-event bins, and its effect grew from -0.909 to -1.019 dB. A verdict
that flips toward REAL because the evidence got noisier is the wrong direction.
It does not become a hit for the track record; it is a reason not to present live
verdicts as equivalent, which is what the "quick check" label now does.

Two further things worth not glossing:

- **Hasankeyf's effect changes sign and magnitude wildly** (+0.101 → +0.759 NDWI)
  while staying CAN'T TELL. Both runs are uninformative there, so the verdict is
  right for the wrong-looking reason, but it shows how unstable that site is.
- **Sindh's degenerate interval (0.000) becomes 2.050.** The full run's
  zero-width interval was never precision — it was the conformal search failing
  to find an accepted set, which the generated METHOD.md table now labels as
  degenerate. Live mode's honest 2.050 is an improvement in presentation even
  though neither is a usable estimate.

On effect sizes the two profiles agree closely wherever the data support a verdict
at all: within 0.016 on all four REALs. The disagreements are concentrated exactly
where the full run already said it could not tell.

**These numbers describe the pre-#4 placebo procedure on both arms** and must be
re-run once the symmetric placebo is published.

## 2026-09-25 — placebo fix and blind validation merged to main

Mohib decided to merge `claude/elegant-franklin-en2noi` to `main` before the
showcase re-runs, reversing the earlier hold ("two procedures on one site").
What that means, stated plainly:

- **New runs** (live and batch) use the symmetric placebo procedure (CRITIQUE #4)
  and record `placebo_symmetric: true`.
- **Every committed showcase run predates the fix** and carries no flag. Missing
  is now read as "old procedure": the verdict page shows an "Older placebo
  procedure" caveat and the Markdown report prints the anti-conservative note.
  Before this change the report note only fired on an explicit `false`, so the
  showcase runs showed their flattering p-values with no warning.
- The known-answer table in `docs/METHOD.md`, `showcase/track_record.json` and the
  power table in METHOD.md §10 still describe the old procedure. They are not
  edited by hand; they change only when `scripts/power.py` and the showcase sites
  are re-run (hours per site; caches are gone). That re-run is still owed.
- Blind validation (`/review`, runner, 34 event runs, 0 control runs) is now on
  main. It still has **no false-alarm rate**; the page says so.

Merge conflicts: `scripts/power.py`, `src/app/server.py` and `DECISIONS.md`
took the branch side (main's side was the "fix not on this branch" stub);
`showcase/blind/sample.json` and `sample.log`, deliberately dropped from the
earlier deploy, come back with the blind-validation work.

## 2026-09-20 — air v1: ULEZ uses ground monitors first, with symmetric cohort placebos

`SPEC-v2.md` says ground NO₂ + ERA5 first, then Sentinel-5P. That ordering is now implemented rather than treating "air" as a satellite-only feature.

### Why ground first

The central 2019 ULEZ is smaller than a useful TROPOMI causal unit and its published effects differ sharply between roadside/traffic and urban-background monitors. LAQN is therefore the treated network, DEFRA AURN supplies non-London controls, and ERA5 supplies meteorology. Sentinel-5P remains an **independent cross-sensor validation layer**, not a way to inflate the evidence count by mixing kilometre-scale columns with street monitors.

### The estimator is not allowed to know the answer key

Published ULEZ findings live in `src/app/air/cases.py`. The inference layer (`air/analysis.py`) never imports that module. `run_air_verdict` attaches the research comparison only after the effect, interval, placebos and verdict exist. If the ULEZ estimate disagrees with Ma (2021) or Tong et al. (2025), the track-record table shows the disagreement; no threshold or donor pool is tuned to make the paper fall inside the interval.

### Monitor types stay separate

Traffic/roadside and urban-background monitors are separate strata all the way through the pipeline. A disagreement between strata forces the combined verdict to CAN'T TELL rather than averaging away a physically meaningful difference.

### Weather normalisation is pre-period-only

Each monitor's weather model is selected and fit only before the policy date. ERA5 actual-weather predictions are replaced by a representative pre-policy weather state, leaving the calendar component and residual post-policy shift. This does not remove concurrent local policy or behavioural changes, which are listed as a limit on every air verdict.

### Placebo design starts with the land symmetry lesson already learned

Air never implements the treated-pool placebo shortcut. Every fake treated cohort has the same size as the real London cohort, is removed from the candidate pool, re-selects its own controls from pre-policy data, and re-selects its own ASCM lambda. The symmetric procedure is deterministic from the case/date/stratum seed. This is stricter than the old `estimator.py` snapshot in this uploaded archive and should be the model for the eventual land code reconciliation.

### Validation surfaces

- `python -m scripts.air_power` — synthetic null/effect calibration; reports REAL / NOT_REAL / CAN'T TELL separately.
- `python -m scripts.air_known_answers` — runs pre-registered cases and writes `showcase/air_validation.json` **after** estimation.
- `/api/air/validation` + `/track-record` — show real generated rows if they exist and explicitly show "not run yet" otherwise.
- each run is ordinary `data/runs/<id>.json` and therefore gets `/v/<id>`, `report.md` and `run.json` like land.

Known incompleteness is deliberate and public: no Sentinel-5P yet, no OpenAQ global provider, and no population/road-density donor covariates in ground-v1. Those are next only after the ULEZ ground results are inspected rather than before.

## 2026-09-20 — air protocol v2.2: adversarial hardening before any live ULEZ claim

The first air implementation was red-teamed before accepting a live ULEZ result. One attack exposed a real false-positive mechanism: if a high-baseline London monitor disappeared at the policy date, the week-by-week treated average could fall even with **zero true intervention effect**. The estimator called that synthetic case REAL. That is now a regression test and the protocol changed rather than tuning the example away.

### Fixed treated composition

A treated station must pass ≥80% coverage separately before and after implementation. Eligible stations form a fixed cohort. Their series are baseline-aligned using pre-policy means, and a week is kept only when ≥80% of that fixed cohort is observed. The dropout attack no longer produces a positive verdict.

### Outcome missingness is no longer seasonally manufactured

Donor outcomes may interpolate at most one internal missing week. Any remaining gap on a week used by the treated cohort excludes the donor. The old idea of filling a long post-policy hole from a donor's historical week-of-year pattern was rejected: it can manufacture exactly the smooth counterfactual we are trying to test.

### Placebos are exact-size or they do not count

Every placebo cohort has exactly the real treated cohort size, is removed from the candidate pool, and then re-runs donor selection and lambda tuning. No placebo cohort may silently shrink. A positive verdict requires at least 19 valid cohorts, plus both an RMSPE-ratio p-value and a signed-effect p-value ≤0.10.

### New falsification/sensitivity gates

Air now runs a 13-week lead/pre-trend check, fake pre-policy event dates, leave-one-treated-monitor-out refits, and influential-donor removal. An applicable failure yields CAN'T TELL. A synthetic one-monitor-only improvement and a pre-existing decline are both now rejected as decisive evidence.

### NO₂-specific conformal search

The inherited land/radar numerical search could stop at ±10 units even when a plausible roadside NO₂ effect was larger. Air now uses a wider adaptive search that is forced to span zero. If the accepted set is empty or reaches the numerical boundary, the interval is marked unresolved and REAL is disallowed.

### Registered ULEZ windows/geographies corrected

- 2019 starts 2018-03-08 rather than fitting across the earlier T-Charge transition.
- 2021 is exploratory and forcibly CAN'T_TELL because the post-lockdown clean baseline is too short.
- 2023 starts 2021-07-19 and defines treatment as the official London-wide/LEZ footprint minus the already-treated 2021 ULEZ polygon. The estimand is therefore the incremental post-29-Aug-2023 change in newly covered outer London.

These choices were registered because they address known design contamination, not because they make an answer agree with a paper.

### Control-policy contamination screen

AURN candidates near known UK CAZ/LEZ/ZEZ launches are conservatively excluded when that launch falls inside the registered analysis window. The exclusions are written to the evidence JSON. This screen is intentionally incomplete rather than described as a universal policy database.

### Remaining identification failure stays visible

A synthetic London-only unmeasured shock beginning on exactly the policy date still looks like a policy effect. That is not patched with another threshold because it is a genuine observational identification limit. It is written into every air verdict's limitations and motivates richer covariates / independent sensors.

### Immutable evidence

Air run IDs now include `air-ground-no2-v2.2`. Results created by the old method cannot be silently served under the same permalink as results created by the hardened protocol.


## 2026-09-25 Codex air validation checkpoint

- Integrated the supplied air v2.2 archive and selected flagship UI styles; retained separate traffic/background estimation and land behavior.
- Fixed verified ingestion/coverage bugs: DEFRA hour-ending timestamps and adjacent status, NOx column confusion, GLA MapServer endpoint, LAQN exclusive EndDate and NO2 instrument dates, absent ERA5 rejection and explicit coverage receipts.
- Enforced the documented one-internal-week repair limit, excluded mixed policy weeks at analysis entry, and corrected positive-point/wide-interval abstention. Protocol is now air-ground-no2-v2.3.1 so prior evidence is not silently reinterpreted. These changes require method-owner review before any merge.
- Saved evidence is immutable; cohort budgets enter identity; missing chart values become JSON null. Added Windows date/UTF-8/path/monotonic-time compatibility fixes and regression tests.
- Latest full suite: 308 passed,20 skipped,8 xfailed. Live validation remains incomplete due LAQN annual timeouts; latest2019 has no estimate and latest2023 has inadequate placebo support. See docs/validation/air-ulez-2026-09-25.
- No estimator tuning to literature; no merge to main. Further method proposals in ULEZ-DESIGN.md are not implemented by this checkpoint.

## 2026-09-25 — Codex air changes: triage (architect review)

Reviewed by reading the current code in `src/app/air/` and `src/app/estimator.py`,
not the handoff's description of it. Git cannot separate what came from the v2.2
archive and what Codex changed (the whole air package arrived in one commit), so
this reviews the method **as it now stands**, including the inherited v2.2
decisions logged above under 2026-09-20, which nobody had triaged. Verdict key
as for CRITIQUE: **valid** / **partly valid** / **wrong**.

| # | Change | Verdict | Reason | Action |
|---|---|---|---|---|
| 1 | Shared `conformal_interval` gains `max_half`, `ensure_zero`, `boundary_hit`, `accepted_empty` | valid | Defaults reproduce the old land behaviour exactly: 120 random panels, identical lo/hi/p/grid against main's version (checked this session). Air uses the wider search and abstains when the accepted set touches the search edge or is empty. | Keep. CRITIQUE #19 (units inferred from scale) still open for land. |
| 2 | NOT REAL now needs the interval, not just the sign: a positive point with an interval that still admits a ≥1 µg/m³ drop is CAN'T TELL | valid | `_decide`: NOT REAL requires `lo > 0` (clearly worse) or `lo > -AIR_MIN_EFFECT` (interval rules out a meaningful drop). Calling NOT REAL while the interval contains the effect being tested was simply wrong. Makes NOT REAL harder, REAL unchanged. | Keep. Log it as a verdict-rule change: it is one. |
| 3 | Donor weekly repair: at most one internal one-week hole, both neighbours exactly 7 days away; otherwise no repair and the donor is dropped if a used week is missing | valid, conservative | Stricter than "one gap": a series with two holes gets no repair at all. Cannot manufacture a smooth counterfactual. One edge: for a Monday launch (8 Apr 2019 is a Monday) no week is dropped, so a donor hole in the first post week is interpolated from one pre and one post week. Donors are untreated, so this is not treatment leakage. | Keep. Note only. |
| 4 | Weeks straddling a mid-week launch dropped from the panel | valid | A mixed pre/post week is neither; excluding it is the standard answer. Tested. | Keep. |
| 5 | Weather: all four core ERA5 fields required; internal gaps ≤3 days interpolated separately before and after the policy date; longer gaps exclude the station; absent boundary-layer height recorded as unavailable | partly valid | The no-leakage part is right: repair never crosses the policy date, the model and reference weather use pre-policy data only (tested: post-policy values cannot change the fit). But the check is over every day in the station's window, including days with no NO₂, so a station can be dropped for weather gaps on days that contribute nothing. Conservative (costs stations, not false alarms), and ERA5 gaps should be rare. | Keep. Read the coverage receipts on the next live run to see whether it ever bites. |
| 6 | Zero placebo cohorts returned p = 1.0 and the CLI printed `p=1.000` | valid (Codex flagged it, did not fix it) | A sentinel, not a test. | **Fixed this session:** stored as null; CLI, report, share preview and verdict page say no placebo test could be run, including for older files carrying 1.0. No verdict changes (REAL already needs ≥19 cohorts). |
| 7 | Ingestion fixes: DEFRA hour-ending timestamps incl. 24:00 and year end; NO₂ status column read beside NO₂; NOx-as-NO₂ not mistaken for NO₂; LAQN `EndDate` exclusive; NO₂ instrument dates bound station activity; GLA MapServer endpoint | valid on the tests; live behaviour not independently re-verified | Each has a regression test on realistic fixtures (`tests/test_air_providers.py`). I did not re-download the endpoints this session. These are data-correctness fixes, not method changes. | Keep. Re-verify against live responses when LAQN acquisition is fixed. |
| 8 | Run identity includes the protocol string and cohort fetch budgets; saved results never recomputed or overwritten | partly valid | Right for evidence integrity. Data vintage and dependency versions are not in the ID, so a re-acquisition needs a fresh `APP_RUNS_DIR`; a proper retry/snapshot identity is a product decision, not yet made. | Open. |
| 9 | Pre-fit gate `pre_rmse > max(1.5 × placebo median, 5.0)` is bypassed when `|point| ≥ 3 × pre_rmse` | partly valid, **flag** | Same shape as land's 4× bypass, which CRITIQUE #1 flagged as a rule that rescues results. Here it arrived with v2.2 before any live ULEZ result existed, so the repo shows no post-hoc tuning, but it is unvalidated. The 5.0 µg/m³ floor is also unexplained. | Open: justify both with the air power test, or remove before any air claim. |
| 10 | Inherited v2.2: ground monitors first; answer keys never imported by the estimator; traffic and background never pooled; pre-policy-only weather; exact-size symmetric placebos, ≥19 cohorts, both p-values ≤0.10; 2021 forced CAN'T TELL; 2023 estimand = newly covered outer London | valid | Verified in code: `analysis.py` imports only the shared estimator, not `cases.py`. These match SPEC-v2 and `ULEZ-DESIGN.md` §1. The placebo design is stricter than land's was. | Keep. |
| 11 | Inherited v2.2: control-city policy screen | partly valid | Screens only the launches it lists; the code says so. Birmingham CAZ (Jun 2021) is the case that matters for 2023 and should be checked explicitly. | Open. |

### Not in this code, and needed before air is shown

These are gaps against `ULEZ-DESIGN.md`, not defects in what exists: no
roadside-minus-background differencing, no traffic-hours filter, no NOx series, a
step rather than a ramp, no announcement-date test, no minimum detectable effect
on the page. Adopting any of them changes the estimand, so they need a
pre-registered design decision and a fresh power test, not a patch. Until then:
air stays off (`APP_AIR_ENABLED=0`), and nothing public claims anything about
ULEZ. The bar for switching it on is Mohib's: its own known-answer set (a large
point source, the COVID relative-null, null cities and fake dates) and a
false-alarm rate from `scripts.air_power` on the current protocol.

### Also done in this merge

- Air hidden, not removed: `APP_AIR_ENABLED` defaults to off, and `render.yaml` pins it to `"0"`. The landing tab only
  appears when the server reports air cases; `/api/air/*` returns 404 and air
  runs are refused. Codex's desktop UI (`desktop.css`, `evidence.css`, favicon,
  null-safe charts) ships as is, per Mohib.
- README, SPEC-v2 status and AIR_METHOD header no longer present air as a live or
  validated signal. The live URL, https://otherwise-r1vd.onrender.com, is recorded in README
  and DEPLOY.

## 2026-09-25 — Hero V3 UI (branch `ui`) reconciled onto main, frontend only

Source: Codex's branch `ui` (one commit, "Import supplied Hero V3 archive for
selective UI review"; Mohib referred to it as `codex/ui-flagship-v3`, which does
not exist on the remote). The archive was built from an older snapshot, so a
straight merge would have reverted about 850 lines outside `web/`.

**Rejected, everything outside `web/` except the PWA routes:** reversions of
the symmetric placebo in `estimator.py`/`run.py`/`power.py`, blind validation,
the `/review` router, air routes and `APP_AIR_ENABLED`, the report's
placebo caveat and air p-value guard, monotonic job timeouts, 311 lines of
DECISIONS.md, README/DEPLOY/SPEC-v2 honesty text, `render.yaml`, requirements,
and tests. None of them was a new backend feature.

**Taken, one backend dependency (Mohib approved it):** the PWA needs
`/manifest.webmanifest` and `/sw.js` served from the root with
`Service-Worker-Allowed: /`. Both routes were added to main's `server.py`, with
`tests/test_pwa.py`. The service worker was **rewritten**: Codex's served
`/static/` JS/CSS cache-first under a cache name that never changed, so a
deploy's new HTML could run against old scripts on an installed phone, and it
cached error responses. Now every same-origin GET, both HTML and static, is
network-first (`cache: "no-cache"`); Cache Storage is only an offline fallback,
only successful responses are stored, and `/api/*` is never intercepted. A test
guards against a cache-first handler coming back.

**`web/`, reconciled per file rather than overwritten:**

- Taken from V3: the new landing shell (hero, mosaic, workbench, case rail, draw
  coach), CSS, the batch upload box, the track-record mobile cards, the
  Before/Split/After compare control, the "New check" topbar link, the new
  "How this works" drawer, and PWA install.
- Kept from main, because V3 predates them:
  - `chart.js` in full (null-safe lines and bands);
  - the air verdict renderer and the zero-placebo p-value guard;
  - the "Older placebo procedure" caveat;
  - the track record's air section (still 404-gated);
  - `NO2_*` signal labels;
  - the `.sure-caveat` and air styles in `app.css`;
  - `evidence.css` on the verdict, track and batch pages.
- Put back into the new shell:
  - the server-gated air tab and panel (hidden unless `APP_AIR_ENABLED=1`);
  - the Batch link;
  - the Copernicus / ESA WorldCover / DEM attribution, which V3's workbench had
    dropped;
  - the prior-art list in "How this works", which SPEC.md requires.
- `mobile.js` stays unloaded: V3 replaces the draggable sheet with its own
  workbench (its `mobile.css` drops the sheet rules and keeps the landing-only
  scroll lock).
- The hectare fix (UTM area and longitude wrapping in `landing.js`) is intact in V3.

**Copy changed for honesty (Mohib to confirm):**

- The hero said "See the change. **Test the cause.**" The method tests whether an
  area broke away from matched places after a date, not what caused it (CRITIQUE
  #13). It now says "Test whether it's real."
- The drawer said that if the method "fires too easily, Otherwise does not call the
  change real". That is true for the in-space placebo but not for fake dates: a
  flagged fake date only adds a caveat (REDTEAM E5). It now says exactly that.
- Landing cards no longer show a placebo p. That is V3's change, and it is kept:
  every committed showcase p comes from the pre-fix procedure.

**Fixed in V3's own CSS:** the active "Split" button was white text on white.
**Tests adapted to the new UX, not weakened:** the area-input harness matched
`/api/run` as a prefix, so the mosaic's `/api/runs/<id>/after.png` requests were
parsed as run submissions; the mouse-draw test now clicks "Check an area" before
drawing. Suite: 361 passed, 8 xfailed.

## 2026-09-26 — visual evidence on the verdict page, and an imagery audit

Mohib asked for the comparison to be visible without reading a chart.

**Matched controls as pictures.** The verdict page now shows the drawn area beside up to
three control areas, before and after (`imagery.make_control_thumbnails`).

- **Fairness rule: the same Sentinel-2 scene as the area's own thumbnail.** Distant
  wide-mode controls can fall on another tile. Then the clearest scene within ±5 days is
  used, its real date is shown, and the page drops its "same two dates" line.
- **Which controls.** Controls that carry weight in the no-event prediction come first,
  labelled with their share. Convex weights are often sparse (Grünheide puts 100 % on one
  cell), so any free slots go to the closest pre-event matches in the same selected pool,
  labelled "matched, not weighted". They are never presented as the counterfactual.
- **Clear sky.** A control that is not clear on those dates (the same 0.9 / 0.6 bar as the
  area's thumbnails) is skipped and recorded.

**The change map was not aligned.** The old "Change map" toggle laid `_change.png` over
the after image. That PNG is a greyscale view of a window at least 4 km across, while the
thumbnails are a square three times the area, so the overlay never lined up. It also existed
for only 2 of 10 showcase runs.

- `pixels.compute_pixel_change` now also writes `_changeoverlay.png`: transparent,
  cropped to the thumbnail's own square, coloured only where the per-pixel test is defined
  (the area and control pixels of its land-cover class).
- It is the same statistic as the "% of pixels changed" figure, not a new one.
- It sits behind a "Changes" preset with a legend that states the roughly 1-in-20 chance
  speckle.
- The wide greyscale map is no longer overlaid.

**Imagery audit (`scripts/showcase_imagery.py`, output `showcase/imagery_audit.json`).**
Every showcase run was checked: "before" dated before the event, "after" after it, clear
share at or above the bar, and a time-lapse spanning the event so it can be marked. It
found three real failures, now fixed:

- **Table Mountain:** no time-lapse. Regenerated.
- **Hasankeyf:** no time-lapse either, and its before thumbnail was 0.79 clear, below the
  thumbnailer's own 0.9 bar. Within 365 days, no scene reaches 0.9 over the area.
  - The scene classification scores the town's bright limestone and fresh fill as cloud
    or "unclassified" (10–18 % of area pixels) on scenes that are 4–9 % cloudy overall.
    Checked by eye: cloud-free.
  - Added a disclosed last resort, used only after the widened search: the nearest scene
    ≤ 5 % cloudy overall and ≥ 0.65 clear over the area. The basis is stored with the
    thumbnail and listed in the audit.
- **Sindh:** eight equal time-lapse slots over three years before and three months after
  all landed before the flood, so the event could not be marked. The time-lapse now adds
  the clearest frame on any empty side of the event.

After the fixes, 10 of 10 runs pass. The Saddleworth control on another tile is listed
as a note.

**Copy:** the panel says a difference "points to something local … the charts below test
it", not that pictures prove the cause.

## 2026-09-25 — fair placebo test published: showcase and power re-run (CRITIQUE #4)

All ten showcase sites were re-run in full mode under the symmetric placebo, and
`scripts/power.py` was run under both procedures. The numbers are published as they
came out; the generated tables are in `docs/METHOD.md` §10 (`showcase/power.json`,
`showcase/track_record.json`).

**Showcase: no verdict changed.** Effects and intervals are identical, because only
the placebo procedure changed. Placebo p moved as follows:

| Site | Placebo p, old | Placebo p, new |
|---|---|---|
| Grünheide | 0.029 | 0.016 |
| Table Mountain | 0.032 | 0.016 |
| Rhodes | 0.023 | 0.023 |
| Austin | 0.016 | 0.016 |
| Saddleworth | 0.016 | 0.016 |
| Lützerath | 0.623 | 0.820 |
| Hasankeyf | 0.951 | 0.279 |
| Richmond | 0.933 | 0.934 |
| Jaú | 0.639 | 0.672 |

Grünheide and Table Mountain went down because the unit count rose from 33 and 30 to
60. Their old p sat at the resolution floor, 1/(n+1); the new one sits at the floor too.
This is the resolution effect recorded on 19 Sep, not evidence getting stronger.

**Sindh changed for a different reason.** `run_sites.py` specifies wide mode (150–400
km), but the committed Sindh run was a ring run: the planned wide re-run had never
finished. This time it did. NDWI +0.58 (90% interval +0.19 to +0.77), so the direction
is right for a flood. Only 12 control cells were usable, against the 20 required, so the
verdict is CAN'T TELL. It is the same verdict as before, with a different reason.

**Power, both procedures on one rebuilt Midlands cache.** The old cache is gone and its
exact geometry was never recorded, so the area is not identical to the 18 Sep table.

| Signal | Injected effect | REAL, symmetric (fair) | REAL, asymmetric (old) |
|---|---|---|---|
| NDVI | none | 0/20 | 0/20 |
| NDVI | −0.05 | 3/20 | 3/20 |
| NDVI | −0.10 | 11/20 | 13/20 |
| NDVI | −0.20 | 16/20 | 18/20 |
| VH | none | 0/20 | 0/20 |
| VH | −0.5 dB | 0/20 | 0/20 |
| VH | −1 dB | 8/20 | 8/20 |
| VH | −2 dB | 19/20 | 19/20 |

The fair test costs some optical power and raises no false alarms, as predicted. The
VH run first used NDVI-sized effects by mistake; it was re-run in dB and only that run is
published. CRITIQUE #9 still stands: `power.py`'s gate omits the pre-fit,
controls-shifted and in-time checks.

**A display bug this exposed, now fixed.** Every run made before the CRITIQUE #11 fix
stored donor indices into the *coverage-filtered* column list. Yesterday's control
thumbnails mapped those indices onto all cells and so pictured the wrong neighbours.
This was display only; no estimate used the mapping. The re-runs store correct indices,
and all control thumbnails were regenerated from them.

- Where the correctly indexed controls were under cloud near the area's dates, the
  search now widens to ±30 days, never crossing the event.
- If the main controls still cannot be pictured, the page says so: "The control
  carrying 100% of the no-event prediction had no clear view … so it is not shown"
  (Grünheide; also Hasankeyf 89 %, Sindh 36 %).

**The older-placebo caveat.** No showcase page shows it any more, because every run
carries `placebo_symmetric: true`. The code stays until the blind-validation re-run
replaces the 34 old-procedure blind runs that the track record still summarises; it
is removed after that.

Visible consequence, recorded so nobody "fixes" it cosmetically: Grünheide's correctly
indexed controls are farmland and grassland, not pine forest, because ESA WorldCover
2020 classes the drawn area as grassland and the donor filter matches that class. They
match the area's pre-event greenness trajectory, which is what the method uses, but they
do not look like it. The earlier, wrongly indexed thumbnails showed forest. The land-cover
label of the Grünheide polygon is itself a finding worth checking before it is used in
outreach.

## 2026-09-25 — blind-validation runner timed items out before they ran

The first blind_v2 attempt recorded 246 of 247 items as "timeout after 3600 s"
within an hour. The runner submitted every item to a process pool at once and timed
each one from **submission**, so after one timeout period every item still waiting in
the queue was marked timed out without ever starting. The "timed-out" workers were also
never stopped, so they kept burning CPU (load about 10 on 4 cores), and if they
finished, their result was discarded.

The same runner produced the original 34 blind runs (25-minute timeout). Some or all
of their 6 error rows may be this bug rather than genuine timeouts, which is one more
reason the v1 numbers are superseded rather than merged.

**Fix (`scripts/blind_validation.run_bounded`, tested in `tests/test_blind_runner.py`):**
- At most `--parallel` items run at once, each in its own process.
- The timeout counts from the item's own start.
- An overrunning process is terminated and recorded as such.
- The timeout for this run is 90 minutes: one completed full-mode item took 33 minutes.
- Genuine timeouts are reported as errors, per stratum, not dropped.

The attempt's log is kept as `logs/blind_attempt1_submission_timeout_bug.log` in the
run worktree. Its one genuine result (a CAN'T TELL) is kept; the 246 bogus rows are
retried.

## 2026-09-25 — Codex UI pass V4 (branch `uiv4`) landed, reconciled

`uiv4` touches only `web/` (7 files) and is based on the Hero V3 merge (963b8be). It was
merged three-way into main and every hunk reviewed.

**Taken from V4:**
- the "1 Pick a place → 2 Name the event → 3 See if it broke away" hero flow;
- outcome labels on the demo chart;
- example cards as real links showing before/after thumbnails, the sourced blurb and
  "Open evidence";
- keyboard support: Escape closes drawing, the rail and the workbench, and cards take focus;
- the manifest description.

**Rejected: stale reverts in V4's snapshot:**
- the cache-first `sw.js` (main keeps network-first; a test guards it);
- "Test the cause" (main keeps "Test whether it's real");
- deletion of the hidden air tab, its panel and landing.js block (still gated by
  `APP_AIR_ENABLED=0`);
- the Batch link and the Copernicus/WorldCover/DEM attribution;
- the CSS cache-busting (now `v=ui5`);
- the invisible "Split" button colour;
- the attribution and air-tab styles.

**Changed:** the example rail's new heading said "Start with a place you already know
changed", but the rail includes the two no-change sites. It now reads "Start with a
documented case."

Suite 368 passed; screenshots in `docs/screenshots/2026-09-25-ui-v4/`.

## 2026-09-25 — Codex UI pass V5 (branch `uiv5`) landed, with one bug fixed

`uiv5` is V4 plus one commit touching 6 `web/` files. It was merged three-way (base = V4 tip),
so only the V4→V5 changes applied.

**Taken from V5:**
- **Live area feedback while drawing.** It uses the existing server-matched
  `polygonAreaHa` / `wrapLng` from the hectare fix, so the readout is the number the
  server will accept.
- **Explicit Undo / Done / Cancel controls.** Done is enabled only for a valid shape, and
  Leaflet's own finish is guarded the same way.
- **A crosshair "Add point" mode on phones.**
- **Mosaic tiles as links** to their verdict pages.

**Rejected:** V5's service-worker cache-name bump. main keeps its network-first worker.

**Fixed in V5's own CSS: desktop drawing was impossible.** To keep the hero clickable over
the new clickable mosaic, V5 set `pointer-events: auto` on `.landing-shell`. That element
is a full-screen fixed layer, so on desktop it swallowed every map click, and no polygon
could be drawn. The real mouse-drawing test caught it: the click landed on
`landing-shell`, not the map. Now only the shell's children (hero panel, workbench) take
pointer events. The drawing test passes (21.4 ha), with screenshots of both drawing modes.

**V6 was requested but does not exist on the remote.** Only `uiv4` and `uiv5` were pushed.

Suite 368 passed; screenshots in `docs/screenshots/2026-09-25-ui-v5/`.

## 2026-09-30 — red-team fixes E5 and E7 implemented (METHOD.md section 9)

- **E5: a flagged in-time placebo now forces CAN'T TELL.** `verdict.decide`
  returns CAN'T TELL with the reason "the same test finds a 'change' at a fake
  date before the event, so the shift began before the date given" instead of
  REAL with a caveat, and `SignalResult.pre_fit_ok` no longer applies the 4x
  bypass when any in-time placebo is flagged. The 24-bin skip in
  `estimator.time_placebos` (REDTEAM E5 item 3) is not changed here.
- **E7: the haze despike is NDWI-aware.** `s2.despike(..., ndwi=)` keeps an NDVI
  dip when that observation's NDWI rises above its neighbours' median by more
  than the same threshold the NDVI dip cleared, *and* is above 0. The absolute
  condition is what separates water from haze: haze raises NDWI towards but not
  above about 0. Without NDWI the rule is unchanged. All five despike call sites
  in `fetch.py` now pass NDWI.
- Published numbers (showcase, power table, red-team tables) predate both
  fixes and must be re-run before METHOD.md section 9 and REDTEAM.md are
  updated to say the fixes are applied.

## 2026-09-30 — spillover buffer measured edge to edge (CRITIQUE #16, REDTEAM E2)

- `geometry.donor_grid`: a cell is eligible only if `cell.distance(area.utm) >= inner_m`
  (nearest boundary to nearest boundary, local UTM). Previously the test was the cell
  *centroid* to the polygon, which let cells within half a cell-side of the area in,
  and at >= ~200 ha let cells sharing an edge in (kept or dropped by float rounding).
- Outer limit unchanged: cell centroid within `outer_m` of the polygon. That is a
  consistent ring (it can only include cells, never break the inner rule), so it
  was left alone. `distances_m` keeps its meaning (centroid to polygon) so the
  published `distance_m` fields and the thinning order are unchanged in kind.
- `geometry.wide_candidates` applies the same edge rule: a draw whose cell comes
  within `inner_m` of the polygon is rejected and redrawn from the same RNG stream,
  so a draw with no rejections is identical to before. The placement radius stays
  centroid to centroid, which is why the old code could put a cell edge inside
  `inner_m` (by up to half a cell diagonal plus the polygon's extent).
- Finding: the leak was not confined to >= 200 ha. Real drawn polygons are not
  squares aligned to the grid, so for the eight ring showcase sites the old rule's
  nearest kept cell edge was 607-939 m from the area at seven of them (Jaú, 1107 m,
  was the exception). Because `max_cells = 400` thinning is an even stride over
  the distance-sorted list, removing even a few inner cells changes which cells
  survive thinning across the whole ring: 71-305 of 400 candidate cells are shared
  old vs new at those seven sites (Jaú: all 400). Wide mode: 1 (Rhodes) and 2
  (Sindh) of 600 candidates replaced.
- Consequence: donor eligibility changed for every ring site, so the published
  showcase numbers (and track record / power tables built from them) are stale
  until `scripts/run_sites.py` is re-run. Not re-run here.


## 2026-09-30 — power.py judges units with the product's verdict (CRITIQUE #9)

- **What changed.** The block that built a `SignalResult` inside `run._analyse` is now
  `run.signal_result` (fit, conformal interval, 60-unit space placebo, three in-time
  placebos). `_analyse` calls it with no change in behaviour. `scripts/power.py` calls the same helper
  for each pseudo-treated unit, passes the result to `verdict.combine`, and counts
  REAL / NOT_REAL / CANT_TELL. `detected` means REAL. The pre-fit gate (with its 4x
  bypass), the donor, pre-bin and post-bin minima, the controls-shifted rule and the
  degenerate-interval rule now all apply.
- **Settings that moved to the product's values as a result.** The space placebo now uses 60 units, up from 30, so the p floor is 1/61. The
  conformal grid now has 41 points, up from 21. Each unit also gains three in-time placebos. Expected sign = sign of the injected
  effect, so the null row stays two-sided, as it was under the old gate.
- **In-time placebo flags do not change the status.** In `verdict.decide` a flagged fake
  date adds a caution to a REAL verdict but leaves it REAL. The power table reproduces that and reports the count separately
  (`real_with_time_placebo_flag`). It does not invent a stricter rule than the app's.
- **Kept for comparison:** `old_gate_detected`, the old three-condition count on the same units.
- **Still differs from production** (rest of #9): the donors are the 60 best pre-fit cells rather than
  `select_donors` with filters and a buffer, and the effect is a step.
- **Radar defaults.** When `VV`, `VH` or `RATIO` is run without `--effects`, the effects are
  (0, −0.5, −1, −2) dB. Before this, VH was run with the NDVI sizes.
- **Not re-run.** `showcase/power.json` and the METHOD.md table still show the old gate's
  numbers, and say so. Re-running is a separate publish step.

## 2026-09-30 — CRITIQUE #4 follow-up: leak-free in-time placebo

This is the defect logged under "Deliberately NOT changed in the same step" in
the 2026-09-19 CRITIQUE #4 entry, fixed on its own so any movement in the
published numbers can be attributed to it alone.

**The leak.** `time_placebos` fakes three event dates inside the real
pre-period (at 1/4, 1/2 and 3/4 of it) and asks whether the method "finds" an
effect there. It fitted every fake date on the treated unit's donors, which
`select_donors` had chosen by pre-event similarity over the *whole* real
pre-period, including the window after each fake date: the window the
fake-date test scores. It also inherited the ridge penalty tuned on the whole
pre-period. Donors picked partly for fitting the fake "post" window fit it well
by construction, so fake-date effects were shrunk towards zero and genuine
pre-event divergence was less likely to be flagged.

**The fix.** For each fake date, `run._time_selector` re-runs `select_donors`
for the treated unit (same land-cover and elevation filters, same k, same
relaxation) with the similarity ranking restricted to the bins before that fake
date, drawing from the full covered candidate pool; `fit_ascm` then re-chooses
lambda (`lam=None`) by the usual holdout inside that window. Same pattern as the
symmetric space placebo (`pool` + selector callable). Fake-date placement is
unchanged. The coverage filter is not re-run per fake date: it is a
data-availability rule, not an outcome comparison, and it defines the
candidate set that both placebos draw from. Air (`air/analysis.py`) already
re-selected per fake date; this brings land in line.

**Recorded.** `TimePlacebo.reselected`; `charts[sig].time_placebo_reselected`
and `signals[sig].time_placebo_reselected` in the run JSON. Missing/false means
the run predates this fix. (`SignalResult` in `verdict.py` was left untouched
because verdict.py was being changed concurrently; the flag is added to the
signal dict in `run_verdict` instead.)

**What it did on synthetic panels** (the `tests/test_redteam.py` panel shape,
60 candidates, k = 20, 3 fake dates each; measured, not asserted exactly):

| Panel | Fake-date tests | Flagged, old | Flagged, new |
|---|---|---|---|
| null, production `MIN_EFFECT` gate | 600 (200 seeds) | 0 | 1 |
| null, no effect gate (conformal only) | 600 (200 seeds) | 84 (14.0%) | 103 (17.2%) |
| pre-trend (-0.2 NDVI/yr from 1 yr before) | 120 (40 seeds) | 66 | 71 |

Decomposing the raw null rise on the same 600 tests: re-selection alone 91,
re-tuned lambda alone 83, both 103. So the leak was suppressing flags, as the
defect description predicted, and removing it raises the raw conformal flag
rate on nulls by about 3 points. The rate was already above the nominal 10%
under the old procedure too; that is a property of the short fake pre-windows,
not of this change, and is noted for later rather than tuned now. Behind the
production effect gate the null rate stays essentially zero, and pre-trends are
flagged more often. Fake-date point effects on the pre-trend panels grew in
magnitude (less flattered fits).

**Cost.** Per signal: 3 extra `select_donors` calls and 18 extra NNLS fits (6
per fake date for the lambda holdout). Timed at about +0.02–0.03 s per signal
at n = 120 / k = 40 and n = 400 / k = 80, i.e. negligible next to the space
placebo.

**Not changed:** `scripts/redteam.py` and `tests/test_redteam.py` build their
own pipeline and still call the old path (they already used the asymmetric
space placebo too). Committed showcase/validation runs carry the old in-time
placebo and no `time_placebo_reselected` field until re-run.

## 2026-09-30 — method v2: one batch, then one set of re-runs

The fixes found by CRITIQUE and REDTEAM land together as "method v2", so that
the public site never mixes verdicts from two procedures:

- E5: a flagged in-time placebo gives CAN'T TELL, and it switches off the 4x bypass.
- E7: the haze despike keeps NDVI dips that are water (NDWI rise and NDWI > 0).
- #16 / E2: the 1 km spillover gap is measured edge to edge (ring and wide mode).
- #4 follow-up: each fake date re-selects donors and re-tunes lambda on data
  before that date only.
- E9: the evidence sentence calls a signal supportive only if `decide` would
  give it REAL on its own; a clear but gated move is reported with its numbers.
- #1 disclosure: a REAL that passed the fit check only via the 4x rule says so,
  and the run JSON records `pre_fit_loose`.
- #9: `power.py` counts the product's verdict (shared `run.signal_result`).
- REDTEAM E5 item 3 (lower the 24-bin skip for in-time placebos to 20) is
  **not** taken. With 20 pre bins the fake pre-windows would be 5, 10 and 15
  bins, and the leak-free placebo already flags 17% of null fake dates without
  the effect gate at the current lengths; shorter windows would make the
  in-time test mostly noise, and under E5 a flag is decisive. Instead, a REAL
  with no in-time test at all now says so on the page.

Consequences:
- #16 changes which control cells are fetched at every ring site, so cached
  fetches cannot be reused: every showcase site and every blind item is re-run
  from a fresh fetch. (Storing pre-despike data in the cache, so future despike
  changes can be re-evaluated without refetching, was considered and deferred:
  it touches `fetch.py` while the fetch speed-up work is in flight, and #16
  forces a refetch now regardless.)
- Blind validation "v2" (100 of 247 items, method at 4c98145) is stopped and
  kept as a superseded partial record. The same sample and seed (20260918) are
  re-run in full under method v2 as `showcase/blind_v3/`. Same items, same
  order, same rules for what counts as correct; only the method changes.
- Order of CPU use on the 4-core box: showcase re-run, then the power table,
  then blind v3; each at nice 19, OPENBLAS_NUM_THREADS=1.
- `main` keeps method v1 until the showcase and power re-runs are published.
