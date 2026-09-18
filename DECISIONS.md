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
