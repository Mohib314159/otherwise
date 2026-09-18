# Otherwise — did it really change?

**A public web app.** Draw an area on a map, say what supposedly happened there
and when ("forest cleared in February 2020", "this field flooded"), and get a
verdict: **real change / not real / can't tell**, with the evidence behind it.

Most tools tell you *something changed*. Otherwise tells you whether it changed
**more than it would have anyway**, by comparing the area with matched control
areas that did not get the event, and by running the same test on untouched
areas and fake dates to show how often the method finds effects that are not there.

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

## Run it

```bash
pip install -r requirements.txt
make serve                      # http://127.0.0.1:8000
python -m pytest -q             # test suite
python -m scripts.fetch_area --bbox=-1.290,52.905,-1.282,52.911 --start 2021-01-01 --end 2023-12-31
python -m scripts.run_sites     # recompute the showcase / known-answer sites
python -m scripts.power         # detection-power table on cached real data
```

Deployment (Hugging Face Spaces or Render, free tiers) is in `DEPLOY.md`.

## Where things are

| Path | What |
|---|---|
| `src/app/` | the app: `fetch` (data), `estimator` (method), `verdict` (rules), `run` (one verdict), `server` (API) |
| `web/` | the frontend: map landing page, verdict page, track record |
| `showcase/` | precomputed verdicts for the showcase and the track-record page |
| `SPEC.md`, `PLAN.md`, `DECISIONS.md`, `SITES.md` | what we are building, how, why, and the known-answer sites |
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
