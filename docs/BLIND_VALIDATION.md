# Blind validation of the Otherwise verdict

*Generated 2026-09-18T23:36:08+00:00 by `scripts/blind_validation.py` at commit `6d8776d`.
This file is rewritten after every finished item; the numbers below cover
40 of 80 sampled items (40 still pending).*

## Why a blind sample

The known-answer sites in `SITES.md` were chosen by hand, which is fine for
checking that the method works at all but says nothing about how it behaves
on events nobody picked. This track draws events and no-change areas at
random from public ground-truth datasets with a fixed seed, runs the
unchanged verdict pipeline on each, and reports the hit rate, the miss rate,
the false-alarm rate and the "can't tell" rate. Nothing is filtered after the
fact; every drawn item is listed, misses and errors included.

## Ground truth and sampling

Seed **20260918**, sample drawn 2026-09-18T21:07:58+00:00 at commit
`None`: 40 hansen events, 40 hansen nulls (80 items).

**Hansen Global Forest Change GFC-2023-v1.11** (Hansen et al. 2013, updated; 30 m
`lossyear` and `treecover2000` tiles read as windows from Google Cloud Storage).
Tiles used: 00N_060W, 00N_020E, 00N_110E, 20N_100W, 50N_010E, 50N_130W, 60N_100E, 30S_060W, 30S_150E.
Climate class is a fixed per-tile mapping: 00N_060W = tropical, 00N_020E = tropical, 00N_110E = tropical, 20N_100W = tropical, 50N_010E = temperate, 50N_130W = temperate, 60N_100E = boreal, 30S_060W = temperate, 30S_150E = temperate.

- *Events (clearing, expected REAL).* Each attempt draws a tile, a band of
  200 rows and a loss year uniformly (years [2018, 2019, 2020, 2021, 2022, 2023]). The
  200 x 200 pixel window is drawn uniformly among the windows of
  that band holding at least 20.0 ha of that year's loss. Connected
  components (8-connectivity) of `lossyear == year` with `treecover2000 >= 30`
  are labelled; those of 20.0-400.0 ha not touching the
  window edge are candidates and one is picked uniformly. The polygon is the
  component's bounding box shrunk by one pixel per side, cropped symmetrically
  around the component centroid to at most 400.0 ha, and kept only if at
  least 60% of its pixels belong to the component. Attempts that
  produce nothing are discarded; the sample file records every accepted draw
  with its tile, band, window, component size and loss fraction.
- *Year-only dates.* Hansen gives the loss **year**, not the day. The event
  date passed to the tool is `{year}-01-01` with `post_months = 18`, so the
  post-event window spans the whole loss year and the first half of the next.
  A clearing late in the year therefore contributes only a few post-event
  months of signal and dilutes the average effect; this is a known handicap
  of the label, not of the site, and is reported as such.
- *Nulls (expected NOT REAL).* Same tiles, same band design. A box whose size
  is drawn from the accepted events' box sizes (in metres) is placed uniformly
  where `treecover2000 >= 50` over the whole box and `lossyear == 0`
  over the box plus a 300.0 m buffer (no mapped loss 2001-2023). The
  fake event date is drawn from the events' year distribution.

**MTBS burned-area perimeters** (USGS/USFS Monitoring Trends in Burn Severity,
`mtbs_perimeter_data.zip`): not used.


EFFIS burnt areas were not used.

## Commands

```
python -m scripts.blind_sample --seed 20260918 --n-events 60 --n-null 60 --out showcase/blind/sample.json
python -m scripts.blind_validation --sample showcase/blind/sample.json --parallel 3 --out showcase/blind/
```

Each item calls `run_verdict(geojson, event_date, change_type, post_months, mode="auto")`
unchanged, in its own process with `APP_FETCH_WORKERS=8` and `APP_CACHE_DIR=data/cache_blind`,
with a 25-minute timeout. Results are cached by run id in `showcase/blind/runs/`, so
re-running the command only processes items without a result. The second
command with `--summary-only` rebuilds the tables from `results.jsonl`.

## What the outcomes mean

| Item kind | REAL | NOT REAL | CAN'T TELL |
|---|---|---|---|
| Event (documented loss/burn) | hit (detected) | miss | can't tell |
| Null (no documented change) | false alarm | correct | can't tell |

Rates are over finished runs of that kind; runs that raised or timed out are
counted separately as errors. "Can't tell" is not a miss: the tool declined
to answer, and the reason is stored with every run.

## Results so far (40 of 80 items; median run 1501.0 s)

Overall: **4 of 5 events detected (80%)**,
0 missed (0%), 1 can't tell (20%);
**0 of 0 nulls raised a false alarm (-)**,
0 correctly NOT REAL (-), 0 can't tell (-);
35 errors.

**By change type**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| clearing | 5 | 4 (80%) | 0 (0%) | 1 (20%) | 0 | 0 (-) | 0 (-) | 0 (-) |

**By source and date precision**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| hansen (source) | 5 | 4 (80%) | 0 (0%) | 1 (20%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| year (date precision) | 5 | 4 (80%) | 0 (0%) | 1 (20%) | 0 | 0 (-) | 0 (-) | 0 (-) |

**By polygon size**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| <50 ha | 3 | 3 (100%) | 0 (0%) | 0 (0%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| 50-150 ha | 1 | 1 (100%) | 0 (0%) | 0 (0%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| >150 ha | 1 | 0 (0%) | 0 (0%) | 1 (100%) | 0 | 0 (-) | 0 (-) | 0 (-) |

**By climate**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| tropical | 3 | 2 (67%) | 0 (0%) | 1 (33%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| temperate | 0 | 0 (-) | 0 (-) | 0 (-) | 0 | 0 (-) | 0 (-) | 0 (-) |
| boreal | 2 | 2 (100%) | 0 (0%) | 0 (0%) | 0 | 0 (-) | 0 (-) | 0 (-) |


**Errors**

| Item | Error |
|---|---|
| ev-hansen-001 | timeout after 1500 s |
| ev-hansen-002 | timeout after 1500 s |
| ev-hansen-003 | timeout after 1500 s |
| ev-hansen-009 | timeout after 1500 s |
| ev-hansen-010 | timeout after 1500 s |
| ev-hansen-011 | timeout after 1500 s |
| ev-hansen-012 | timeout after 1500 s |
| ev-hansen-013 | timeout after 1500 s |
| ev-hansen-014 | timeout after 1500 s |
| ev-hansen-015 | timeout after 1500 s |
| ev-hansen-016 | timeout after 1500 s |
| ev-hansen-017 | timeout after 1500 s |
| ev-hansen-018 | timeout after 1500 s |
| ev-hansen-019 | timeout after 1500 s |
| ev-hansen-020 | timeout after 1500 s |
| ev-hansen-021 | timeout after 1500 s |
| ev-hansen-022 | timeout after 1500 s |
| ev-hansen-023 | timeout after 1500 s |
| ev-hansen-024 | timeout after 1500 s |
| ev-hansen-025 | timeout after 1500 s |
| ev-hansen-026 | timeout after 1500 s |
| ev-hansen-027 | timeout after 1500 s |
| ev-hansen-028 | timeout after 1500 s |
| ev-hansen-029 | timeout after 1500 s |
| ev-hansen-030 | timeout after 1500 s |
| ev-hansen-031 | timeout after 1500 s |
| ev-hansen-032 | timeout after 1500 s |
| ev-hansen-033 | timeout after 1500 s |
| ev-hansen-034 | timeout after 1500 s |
| ev-hansen-035 | timeout after 1500 s |
| ev-hansen-036 | timeout after 1500 s |
| ev-hansen-037 | timeout after 1500 s |
| ev-hansen-038 | timeout after 1500 s |
| ev-hansen-039 | timeout after 1500 s |
| ev-hansen-040 | timeout after 1500 s |

## Every item

| Item | Type | Expected | Verdict | Lead | Effect (90% interval) | Placebo p | Pre/post bins | Donors | Size | Climate | Date | Seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ev-hansen-001 | clearing | REAL | error | - | - | - | -/- | - | 43.65 ha | boreal | 2020-01-01 | 1500.9 |
| ev-hansen-002 | clearing | REAL | error | - | - | - | -/- | - | 34.04 ha | boreal | 2019-01-01 | 1500.9 |
| ev-hansen-003 | clearing | REAL | error | - | - | - | -/- | - | 49.28 ha | boreal | 2019-01-01 | 1500.9 |
| ev-hansen-004 | clearing | REAL | REAL | NDVI | -0.150 (-0.212 to -0.017) | 0.02 | 25/13 | 80 | 26.52 ha | boreal | 2022-01-01 | 361.8 |
| ev-hansen-005 | clearing | REAL | CANT_TELL | NDVI | -0.060 (-0.051 to +0.049) | 0.07 | 58/32 | 80 | 283.44 ha | tropical | 2023-01-01 | 1026.6 |
| ev-hansen-006 | clearing | REAL | REAL | NDVI | -0.149 (-0.157 to -0.007) | 0.03 | 39/19 | 80 | 38.85 ha | tropical | 2022-01-01 | 574.8 |
| ev-hansen-007 | clearing | REAL | REAL | NDVI | -0.116 (-0.109 to -0.025) | 0.02 | 53/21 | 80 | 77.52 ha | tropical | 2021-01-01 | 790.1 |
| ev-hansen-008 | clearing | REAL | REAL | NDVI | -0.251 (-0.263 to -0.183) | 0.02 | 35/14 | 80 | 21.9 ha | boreal | 2021-01-01 | 542.1 |
| ev-hansen-009 | clearing | REAL | error | - | - | - | -/- | - | 34.54 ha | temperate | 2022-01-01 | 1501.0 |
| ev-hansen-010 | clearing | REAL | error | - | - | - | -/- | - | 45.5 ha | tropical | 2019-01-01 | 1501.0 |
| ev-hansen-011 | clearing | REAL | error | - | - | - | -/- | - | 59.81 ha | temperate | 2019-01-01 | 1501.0 |
| ev-hansen-012 | clearing | REAL | error | - | - | - | -/- | - | 30.24 ha | temperate | 2020-01-01 | 1501.0 |
| ev-hansen-013 | clearing | REAL | error | - | - | - | -/- | - | 44.0 ha | boreal | 2022-01-01 | 1501.0 |
| ev-hansen-014 | clearing | REAL | error | - | - | - | -/- | - | 47.96 ha | temperate | 2019-01-01 | 1501.0 |
| ev-hansen-015 | clearing | REAL | error | - | - | - | -/- | - | 24.6 ha | temperate | 2022-01-01 | 1501.0 |
| ev-hansen-016 | clearing | REAL | error | - | - | - | -/- | - | 75.23 ha | temperate | 2022-01-01 | 1501.0 |
| ev-hansen-017 | clearing | REAL | error | - | - | - | -/- | - | 36.3 ha | temperate | 2018-01-01 | 1501.0 |
| ev-hansen-018 | clearing | REAL | error | - | - | - | -/- | - | 32.67 ha | boreal | 2020-01-01 | 1501.0 |
| ev-hansen-019 | clearing | REAL | error | - | - | - | -/- | - | 31.38 ha | temperate | 2022-01-01 | 1501.0 |
| ev-hansen-020 | clearing | REAL | error | - | - | - | -/- | - | 31.49 ha | boreal | 2019-01-01 | 1501.0 |
| ev-hansen-021 | clearing | REAL | error | - | - | - | -/- | - | 36.02 ha | boreal | 2020-01-01 | 1501.0 |
| ev-hansen-022 | clearing | REAL | error | - | - | - | -/- | - | 29.7 ha | temperate | 2020-01-01 | 1501.0 |
| ev-hansen-023 | clearing | REAL | error | - | - | - | -/- | - | 42.2 ha | tropical | 2021-01-01 | 1501.0 |
| ev-hansen-024 | clearing | REAL | error | - | - | - | -/- | - | 50.37 ha | boreal | 2023-01-01 | 1501.0 |
| ev-hansen-025 | clearing | REAL | error | - | - | - | -/- | - | 84.1 ha | tropical | 2020-01-01 | 1501.0 |
| ev-hansen-026 | clearing | REAL | error | - | - | - | -/- | - | 33.81 ha | temperate | 2019-01-01 | 1501.0 |
| ev-hansen-027 | clearing | REAL | error | - | - | - | -/- | - | 44.86 ha | boreal | 2022-01-01 | 1501.0 |
| ev-hansen-028 | clearing | REAL | error | - | - | - | -/- | - | 44.22 ha | temperate | 2021-01-01 | 1501.0 |
| ev-hansen-029 | clearing | REAL | error | - | - | - | -/- | - | 112.85 ha | tropical | 2021-01-01 | 1501.0 |
| ev-hansen-030 | clearing | REAL | error | - | - | - | -/- | - | 42.68 ha | boreal | 2020-01-01 | 1501.0 |
| ev-hansen-031 | clearing | REAL | error | - | - | - | -/- | - | 22.66 ha | boreal | 2023-01-01 | 1501.0 |
| ev-hansen-032 | clearing | REAL | error | - | - | - | -/- | - | 63.33 ha | temperate | 2020-01-01 | 1501.0 |
| ev-hansen-033 | clearing | REAL | error | - | - | - | -/- | - | 27.77 ha | boreal | 2023-01-01 | 1501.0 |
| ev-hansen-034 | clearing | REAL | error | - | - | - | -/- | - | 39.74 ha | temperate | 2020-01-01 | 1501.0 |
| ev-hansen-035 | clearing | REAL | error | - | - | - | -/- | - | 73.84 ha | boreal | 2021-01-01 | 1501.0 |
| ev-hansen-036 | clearing | REAL | error | - | - | - | -/- | - | 34.95 ha | boreal | 2021-01-01 | 1501.0 |
| ev-hansen-037 | clearing | REAL | error | - | - | - | -/- | - | 45.1 ha | temperate | 2019-01-01 | 1501.0 |
| ev-hansen-038 | clearing | REAL | error | - | - | - | -/- | - | 35.56 ha | boreal | 2022-01-01 | 1501.0 |
| ev-hansen-039 | clearing | REAL | error | - | - | - | -/- | - | 42.67 ha | temperate | 2023-01-01 | 1501.1 |
| ev-hansen-040 | clearing | REAL | error | - | - | - | -/- | - | 56.85 ha | temperate | 2022-01-01 | 1501.1 |

*Sources: Hansen, M. C. et al. (2013) High-Resolution Global Maps of 21st-Century Forest Cover Change, Science 342, 850-853; data GFC-2023 v1.11. MTBS: Monitoring Trends in Burn Severity, USGS/USFS, burned area boundaries dataset.*
