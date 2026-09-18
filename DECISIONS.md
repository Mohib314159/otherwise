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

### What the sandbox can and cannot reach (this drives the data design)

The remote sandbox's network policy blocks the two data sources SPEC.md names.
Tested by direct HTTPS probe:

| Host | Reachable from sandbox |
|---|---|
| Microsoft Planetary Computer STAC | **no** (403 from egress proxy) |
| Copernicus Data Space STAC | **no** |
| Earth Search STAC (Element84) | **no** |
| `sentinel-cogs` S3 bucket (Sentinel-2 L2A COGs, AWS open data) | **yes**, and bucket listing works |
| `sentinel-s1-rtc-indigo` S3 bucket (Sentinel-1 RTC, CONUS, 2016–2021) | **yes** |
| `gcp-public-data-sentinel-2` (Google public Sentinel-2) | **yes** |
| ESA WorldCover S3, Copernicus DEM 30 m S3 | **yes** |
| Source Cooperative (AlphaEarth embeddings) | **no** |
| OpenStreetMap tiles, unpkg, jsDelivr | **no** |

- **Decision: the data layer gets a provider interface, not a hard-wired STAC
  client.** Sandbox development and validation will use the `sentinel-cogs` bucket
  directly (predictable key layout, no catalogue needed). The Planetary Computer
  path for Sentinel-1 RTC will be written and unit-tested against fixtures here,
  but can only be verified live from Mohib's machine or the deployed backend.
  This will be stated plainly in the README until it has been verified.
- **AlphaEarth embeddings cannot be evaluated from the sandbox.** Control
  selection will start from what is reachable (land cover, terrain, distance,
  pre-event optical similarity) and AlphaEarth is a candidate to test later from
  a machine that can reach Source Cooperative.

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

- Final choice between AWS `sentinel-cogs` only versus Planetary Computer for
  the deployed backend (Sentinel-1 RTC availability is the deciding factor).
- Hosting. Candidates are a static frontend plus a small Python backend on a
  free tier. Nothing chosen until the compute cost of a live run is measured.
- Known-answer validation sites. To be proposed with sources, then confirmed
  by Mohib before they are treated as ground truth.
