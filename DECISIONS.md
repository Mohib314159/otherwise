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
