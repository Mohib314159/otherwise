# CarbonTwin → "Did it really change?"

**Now being turned into a public web app:** draw an area, name the event and its
date, and get a verdict on whether the area changed *more than it would have
anyway*, with receipts and a placebo check. See `SPEC.md`, `PLAN.md` and
`DECISIONS.md`. The app code lives in `src/app/`; the original CarbonTwin engine
below is reused for the synthetic control and placebo inference.

**Milestone 1 (done): data in and cleaned for one area.**

```bash
pip install -r requirements.txt
python -m scripts.fetch_area --bbox=-1.290,52.905,-1.282,52.911 --start 2021-01-01 --end 2023-12-31
```

Pulls Sentinel-2 L2A and Sentinel-1 RTC from Microsoft Planetary Computer for
the polygon and a ring of same-size donor cells around it, masks cloud with the
scene classification, removes the Baseline-04 offset, keeps one radar orbit,
merges tile overlaps, and prints every observation it threw out and why.

---

# CarbonTwin (original engine)

A causal-inference engine for verifying field-scale carbon-farming claims from
satellite time series. Where most tools ask *"did this field get greener?"* — which a
wet season can fake — CarbonTwin asks *"did the practice **cause** an additional change,
and can we put a p-value on it?"*

It builds each field a **synthetic control** ("twin") from its conventional neighbours,
measures the post-adoption divergence, and tests significance with an Abadie-style
**permutation (placebo) test**. On top of that sit a fraud/false-claim verdict, a
reversal monitor, and an indicative carbon/risk layer.

## Design

One data contract, one engine, many interchangeable signals:

```
satellite data ──[adapter]──▶ Dataset (per-field time series)
                                  │
                                  ▼
                 synthetic control  →  placebo test (p-value)  →  verdict
                                  │
            ┌─────────────────────┼─────────────────────┐
        reversal monitor      carbon band          portfolio / risk
```

Any signal that can be reduced to a 1-D per-field series — NDVI, red-edge, a tillage
index, radar backscatter, biomass, within-field texture — flows through the *same*
engine unchanged. Adding a data source means writing a thin adapter, not touching the core.

## Install

```bash
pip install -r requirements.txt      # numpy, scipy, pandas, matplotlib, pytest
                                     # optional: xarray + zarr (Sentinel-2 cubes), streamlit (dashboard)
```

## Run

```bash
python -m pytest -q                  # test suite (48 tests)
python -m scripts.validate           # recover planted ground truth on synthetic data
python -m scripts.render             # render example figures to assets/
python scripts/run_real_s2.py <cube.zarr>          # six-signal extraction from a real Sentinel-2 cube
python -m scripts.run_on_the_day                   # edit CONFIG, then audit real data end-to-end
```

## Module map (`src/`)

| Module | Role |
|---|---|
| `contract.py` | `FieldSeries` / `Dataset` — the internal data contract; latitude-aware off-season mask |
| `adapter.py` | Read real formats (Sentinel-2 zarr, long/wide CSV, GeoTIFF stack) → `Dataset` |
| `scm.py` | Synthetic control: convex weights via SLSQP (non-negative, sum to 1 — no extrapolation) |
| `inference.py` | Permutation/placebo test → p-value; Benjamini-Hochberg FDR for batches |
| `audit.py` | Five verdicts: VERIFIED / PARTIAL / INCONCLUSIVE / REJECTED / BASELINE |
| `monitor.py` | Reversal detection and adoption-year onset detection |
| `carbon.py` | Verified effect → indicative tCO₂e band (literature-bounded triage, not a measurement) |
| `actuary.py` | Reversal hazard → survival curve and illustrative premium |
| `portfolio.py` | Roll-up: verified tonnage, at-risk tonnage, unverifiable exposure |
| `spectral.py` | Sentinel-2 index stack (NDVI/EVI/NDRE/NDWI/NDMI/NDTI/BSI); Baseline-04.00 harmonisation |
| `field_signals.py` | Sub-5m extractors: texture, contrast, albedo, perimeter ratio, distribution shape |
| `phenology.py` | Per-field season metrics (start/peak/end/length/amplitude) from the NDVI curve |
| `radar.py` | Dual-channel fusion (optical + radar tillage) for cover-crop **and** no-till detection |
| `management.py` | Intentionality discriminator: within-field texture separates cover crop from weeds |
| `scenarios.py` | Generalisation harness (aquifer depletion, pre-symptomatic crop disease) |
| `pipeline.py` | `run_audit` / `audit_all_claims` — orchestration |
| `plots.py`, `dashboard.py` | Figures and a Streamlit dashboard |

## Method notes

- **Why convex weights:** forcing weights ≥ 0 and summing to 1 makes the twin a
  weighted *average* of real fields (the convex hull), which forbids the extrapolation
  that ordinary regression would use to overfit a small, collinear donor pool.
- **Why a permutation p-value:** with one treated unit there is no parametric standard
  error, so significance is the rank of the field's post/pre RMSPE ratio against every
  donor re-tested as a placebo. It floors at 1/(donors+1), so thin pools return
  INCONCLUSIVE rather than a false accusation.
- **Honest carbon caveat:** NDVI is greenness, not carbon. The statistics establish
  *additionality*; the tonnage is a deliberately conservative literature band
  (~1.3 tCO₂e/ha/yr for cover crops) that requires soil-core calibration. Greenness is
  never presented as a measured tonnage.

## References

See `REFERENCES.md` (Abadie synthetic control; Fick et al. 2021 SCM on satellite data;
cover-crop sequestration literature; ESA Sentinel-2 Baseline-04.00 offset).
