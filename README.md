# Otherwise — did it really change?

**A public web app.** Draw an area on a map, say what supposedly happened there
and when ("forest cleared in February 2020", "this field flooded"), and get a
verdict: **real change / not real / can't tell**, with the evidence behind it.

**Live site:** https://otherwise-r1vd.onrender.com (Render free tier: the first
visit after 15 idle minutes takes about a minute to wake up).

Most tools tell you *something changed*. Otherwise tells you whether it changed
**more than it would have anyway**, by comparing the area with matched control
areas that did not get the event, and by running the same test on untouched
areas and fake dates to show how often the method finds effects that are not there.

### What is and isn't validated yet

- The known-answer sites are **candidates**, not yet confirmed: of 10, 4 correct
  REAL, 0 missed, 0 false alarms, **6 can't tell** ([`docs/METHOD.md`](docs/METHOD.md) §10).
- Every showcase run was re-run on 25 Sep 2026 under the fixed, symmetric placebo
  test (CRITIQUE #4 in `DECISIONS.md`). No verdict changed; the numbers are the
  generated tables in [`docs/METHOD.md`](docs/METHOD.md) §10.
- Blind validation has event runs only and **no false-alarm rate yet**.
- Live runs on the free tier are a "quick check" (coarser controls), not
  equivalent to the showcase runs. On 30 Sep 2026 a 29 ha live run finished
  on the free host in 18 minutes (40-minute limit), after the control scenes
  moved to server-side reads; earlier that day the same kind of run had read
  only 60 of 242 control scenes before hitting the limit.

### In development, not public: air pollution (ground NO₂ / London ULEZ)

`src/app/air/` holds a ground-monitor NO₂ pipeline for London's ULEZ (LAQN
treated monitors, DEFRA AURN controls, pre-policy-only ERA5 weather adjustment,
exact-size symmetric placebos; [`docs/AIR_METHOD.md`](docs/AIR_METHOD.md)). It is
**switched off** on the public site (`APP_AIR_ENABLED=0`) and makes no claims:
no ULEZ run has yet produced a usable estimate, and air has no known-answer set
or false-alarm test of its own. It will not be shown until both exist and pass.

## What it does, in one screen

- **Data:** every Sentinel-2 optical scene and Sentinel-1 radar pass over the
  area for three years before the event and up to 18 months after, from
  Microsoft Planetary Computer. Cloud, shadow, haze, tile overlaps and
  mismatched radar orbits are removed, and every dropped observation is listed
  as a receipt.
- **Controls:** a grid of same-sized cells 1–12 km away, filtered to the same
  land cover (ESA WorldCover) and similar elevation (Copernicus DEM), ranked by
  pre-event similarity.
- **Counterfactual:** augmented synthetic control (Ben-Michael, Feller &
  Rothstein 2021) on the existing CarbonTwin convex-weight engine.
- **Uncertainty:** conformal inference (Chernozhukov, Wüthrich & Zhu 2021), a
  90% interval for the post-event effect with no distributional assumptions.
- **Placebo checks on every verdict:** every control cell tested as if it were
  the area, plus fake event dates before the real one.
- **Verdict rules are explicit** (`src/app/verdict.py`) and every verdict page
  is a permalink.
- **Full method write-up:** [`docs/METHOD.md`](docs/METHOD.md) — data
  cleaning, control selection, the estimator and its uncertainty, the placebo
  checks, the verdict thresholds, known limits and validation to date, for
  anyone who wants to check the reasoning rather than take the verdict on
  trust.
- **What we could not defend:** [`docs/REDTEAM.md`](docs/REDTEAM.md) — an adversarial review of our own method, with numbers. Two of its attacks defeat the method as it stands (pre-trends are still called REAL; floods shorter than about a month are deleted by the haze filter). Both are listed in [`docs/METHOD.md`](docs/METHOD.md) §9 and neither fix is applied yet.

## For institutional users

Carbon-credit checkers, journalists and researchers who need more than one
verdict at a time can upload a GeoJSON FeatureCollection of areas at `/batch`
and get every feature run through the same pipeline as a single draw-an-area
request — no manual repeats. Each run, batch or single, can be exported as a
Markdown report (`report.md`) or the raw numbers behind it (`run.json`), so a
verdict can be filed, attached or diffed without screenshotting the page.
Batch runs use the same pipeline as a live run, one area at a time on the free
host, so a batch of N areas takes roughly N live runs back to back.

## Run it

```bash
pip install -r requirements.txt
make serve                      # http://127.0.0.1:8000
python -m pytest -q             # test suite
python -m scripts.fetch_area --bbox=-1.290,52.905,-1.282,52.911 --start 2021-01-01 --end 2023-12-31
python -m scripts.run_sites     # recompute the showcase / known-answer sites
python -m scripts.power         # land detection-power table on cached real data
# air (in development; set APP_AIR_ENABLED=1 to see it in the local UI)
python -m scripts.run_air_case ulez-central-2019 --post-months 3
python -m scripts.air_redteam          # adversarial synthetic failure tests
python -m scripts.air_power --seeds 30 --effect -6
python -m scripts.air_known_answers  # writes the air known-answer table after live runs
```

Deployment (Hugging Face Spaces or Render, free tiers) is in `DEPLOY.md`.

## Where things are

| Path | What |
|---|---|
| `src/app/` | shared app + land pipeline; `src/app/air/` is the in-development NO₂/ULEZ pipeline, off by default (providers, weather adjustment, fixed-cohort aggregation, hardened symmetric placebo inference, registered ULEZ cases, run orchestration) |
| `web/` | the frontend: map landing page, verdict page, track record |
| `showcase/` | precomputed verdicts for the showcase and the track-record page |
| `SPEC.md`, `PLAN.md`, `DECISIONS.md`, `SITES.md` | what we are building, how, why, and the known-answer sites |
| `docs/METHOD.md` | land method; [`docs/AIR_METHOD.md`](docs/AIR_METHOD.md) is the ground-NO₂ / ULEZ method and validation protocol |
| `docs/REDTEAM.md` | adversarial review of the method by us, including the two attacks that break it |
| `src/scm.py`, `src/inference.py`, … | the original CarbonTwin engine (below) |

## Honesty notes

- No number in the app is invented: effect sizes, intervals, placebo rates and
  the track record are computed from the data on each run.
- Known-answer sites in `SITES.md` are labelled *candidate* until confirmed.
- Measured detection power on a cloudy UK area is in `DECISIONS.md`; a 0.05
  NDVI change is usually below the method's power, and the app says so.

---

## CarbonTwin (the original engine)

A causal-inference engine for verifying field-scale carbon-farming claims from
satellite time series, built for a hackathon. It builds each field a
**synthetic control** from its neighbours, measures the post-adoption
divergence, and tests significance with an Abadie-style permutation test.
`carbon.py`, `actuary.py` and `portfolio.py` (tonnage bands and pricing) are
kept for reference and are not part of the app.

| Module | Role |
|---|---|
| `contract.py` | `FieldSeries` / `Dataset` data contract; off-season mask |
| `adapter.py` | Sentinel-2 zarr, CSV and GeoTIFF loaders |
| `scm.py` | synthetic control with convex weights (SLSQP) |
| `inference.py` | placebo permutation p-value; Benjamini-Hochberg FDR |
| `audit.py` | five-state verdict for carbon claims |
| `monitor.py` | reversal and onset detection |
| `spectral.py` | Sentinel-2 index stack with the Baseline-04.00 fix |
| `radar.py` | **simulated** radar channel (not used by the app) |
| `dashboard.py` | the old Streamlit demo (`make run`) |

References for the method are in `REFERENCES.md`.
