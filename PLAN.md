# Plan

Working name: **Did it really change?** Draw an area, name the event and date,
get a verdict with receipts and a placebo check. Built on the CarbonTwin engine.

## Architecture

```
browser (static site: map + verdict page)  ──HTTP──▶  FastAPI backend
                                                        │  job queue (in-process)
                                                        ▼
                                          src/app/ pipeline
                                          fetch  ▶ clean ▶ donors ▶ estimate ▶ verdict
                                              │
                          Planetary Computer STAC (S2 L2A + S1 RTC), Earth Search (S2 fallback)
                                          results cached as JSON per run id  →  permalinks
```

- **Backend:** Python, FastAPI, one process. Runs live jobs in a background thread
  pool, writes each result to `data/runs/<id>.json`. Permalink = `/v/<id>`.
- **Frontend:** hand-written HTML/CSS/JS with Leaflet and a small chart component.
  No framework, no build step, so it deploys anywhere and loads in under a second.
- **Old CarbonTwin modules stay untouched.** The app lives in `src/app/` and
  imports `scm.py` and `inference.py`; `carbon.py`, `actuary.py`, `portfolio.py`
  are not on the product path.

## Data (milestone 1)

- Sentinel-2 L2A from Planetary Computer: SCL read first at 20 m, then B03/B04/
  B08/B12 only when the area is mostly clear. Per-observation area means of NDVI,
  NDWI and NBR for the drawn area **and** every candidate donor cell in one read.
  Baseline-04 offset removed using `s2:processing_baseline`. Duplicate tile
  overlaps deduplicated. Every dropped observation gets a receipt.
- Sentinel-1 RTC from Planetary Computer: VV and VH gamma0, area mean in linear
  power then dB. One relative orbit kept (the one with the most coverage), other
  orbits recorded as receipts.
- Limits: area 0.5-500 ha, event date from 2018-01 onward, window = 3 years
  before to up to 18 months after the event.
- On-disk cache keyed by (polygon, window, source), so showcase sites and repeat
  runs are instant.

## Method (milestone 2)

1. **Candidate donors:** grid of cells the size of the drawn area, in a ring from
   1 km to ~15 km, excluding the area itself and its buffer.
2. **Shortlist:** same dominant WorldCover class, similar elevation and slope,
   then top-K by pre-event series similarity.
3. **Estimate:** augmented synthetic control (ridge-corrected convex weights) on
   the pre-event series, effect = observed minus counterfactual after the event.
4. **Uncertainty:** conformal inference (moving-block permutation of post-event
   residuals) gives a confidence interval for the mean post-event effect.
5. **Placebo checks:** in-space (each donor treated as if it were the area) and
   in-time (fake event dates in the pre period). Their false-alarm rate is shown.
6. **Verdict:** REAL if the interval excludes zero in the claimed direction and
   the effect exceeds the placebo noise; NOT REAL if the interval is tight around
   zero; CAN'T TELL if the pre-fit is poor, coverage is thin, or the pool is small.
7. **Validation:** known-answer sites (a clearing, a flood, a burn, a no-change
   site, proposed for Mohib's confirmation) plus injected effects on real
   untouched cells to measure power. Results go in DECISIONS.md and the
   track-record page.

## Hosting (milestone 5)

Simplest free option that runs Python: a single web service (Render or Fly free
tier) serving both the static frontend and the API, deployed from GitHub on push.
Showcase results are precomputed and committed, so the landing page never waits
on a satellite read. Live runs are rate-limited and capped by area.

## Biggest risks

1. **Live-run latency.** Hundreds of scene reads at a few MB/s. Mitigation: SCL
   first, parallel reads, cache, and honest progress in the UI.
2. **Donor quality.** A bad pool gives a confident wrong answer. Mitigation: the
   placebo false-alarm rate is computed and shown on every verdict.
3. **Free-tier limits.** If a live run does not fit, the app falls back to
   showcase-only plus a queue, and says so.
4. **Known-answer sites need Mohib's confirmation** before they are called ground truth.
