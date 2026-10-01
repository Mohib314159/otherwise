# Blind validation of the Otherwise verdict

*Generated 2026-10-01T21:38:22+00:00 by `scripts/blind_validation.py` at commit `b5377c0`.
The numbers below cover all 247 sampled items (0 pending). The run started at
`8c1f2e9` and moved to `b5377c0` (S2 read speed-up, bit-identical outputs);
`8f73efa` only added resumable wide fetches. All three give the same numbers.
This supersedes v1 (`docs/BLIND_VALIDATION_v1.md`) and the unfinished v2.*

## Why a blind sample

The known-answer sites in `SITES.md` were chosen by hand, which is fine for
checking that the method works at all but says nothing about how it behaves
on events nobody picked. This track draws events and no-change areas at
random from public ground-truth datasets with a fixed seed, runs the
unchanged verdict pipeline on each, and reports the hit rate, the miss rate,
the false-alarm rate and the "can't tell" rate. Nothing is filtered after the
fact; every drawn item is listed, misses and errors included.

## Ground truth and sampling

Seed **20260918**, sample drawn 2026-09-18T23:29:35+00:00 at commit
`6d8776d`: 115 hansen events, 115 hansen nulls, 15 mtbs events, 2 mtbs nulls (247 items). The draw is
scripted and seeded end to end; no item was hand-picked, kept or dropped after
being seen. Re-running `scripts/blind_sample.py` with the same seed against the
same fixed dataset releases reproduces it.

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
`mtbs_perimeter_data.zip`): used.
Events are wildfires (Incid_Type = Wildfire) with ignition date between 2018-06-01 and 2023-06-01 and 700-12000 acres, drawn uniformly (1719 eligible). The polygon is a box centred on the largest part of the perimeter shrunk by 200.0 m, capped at 400.0 ha and shrunk further until at least 80% of it lies inside the perimeter; the event date is the MTBS ignition date (day precision) with post_months = 6. Nulls are boxes of the same sizes placed 10-120 km from a sampled fire, at least 5000.0 m from every MTBS perimeter of any year, with at least 80% of pixels tree-covered (Hansen treecover2000 >= 30) and no Hansen loss in the box or its 300 m buffer. Climate: latitude >= 55 N is boreal (Alaska), longitude 118 W-100 W is dry (interior West), else temperate.

**Sources considered and not used**, so a reader knows what is missing rather
than assuming it was tried:

- *Copernicus EMS rapid mapping* (floods). Not used: the delineation products
  are per-activation archives meant for manual download, with no stable
  programmatic index that a seeded sampler could draw from mechanically. One
  EMS flood (Sindh 2022) is in the hand-picked known-answer set instead.
- *EFFIS / GWIS burnt areas* (Europe). Not used: the download endpoint
  redirected to an interactive request form and the WFS endpoint timed out from
  this environment on 2026-09-18, so nothing could be scripted against it.
  MTBS covers burns instead, for the USA only.
- *JRC Global Surface Water* (water change and stable-water/stable-land
  controls). Reachable -- the public bucket lists
  `downloads2021/change/change_<lon>_<lat>v1_4_2021.tif` -- but not used: the
  change and transitions layers describe 1984-2021 as a whole and carry no
  event year, so they cannot give a dated event the tool can be asked about.
  The yearly-classification product could, and is the obvious next source to
  add; it was not implemented here.

Water and flood events are therefore **absent from this blind sample**, and the
numbers below say nothing about how the tool behaves on them.

## Commands

```
python -m scripts.blind_sample --seed 20260918 --n-events 60 --n-null 60 --out showcase/blind/sample.json --mtbs <path>/mtbs_perimeter_data.zip
python -m scripts.blind_validation --sample showcase/blind/sample.json --parallel 4 --out showcase/blind_v3/
```

The outstanding items are run in a seeded random order (`--shuffle-seed`,
recorded as `run_order_seed` in `summary.json`), so a run stopped part-way
leaves a random subsample of the draw rather than, say, every event and no
control. **The verdicts are tied to the commit above**: another track was
changing the fetch and estimator path in parallel, so re-running at a later
commit can legitimately give different numbers.

Each item calls `run_verdict(geojson, event_date, change_type, post_months, mode="auto")`
unchanged, in its own process with `APP_FETCH_WORKERS=8` and `APP_CACHE_DIR=data/cache_blind`,
with a 25-minute timeout. Results are cached by run id in `showcase/blind_v3/runs/`, so
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

## Results so far (247 of 247 items; median run 416.9 s)

Tool alone, over finished runs only, with 95% Wilson intervals:

| Rate | Value |
|---|---|
| Detection (REAL on an event) | 69 of 130 = 53.1% (95% CI 44.5-61.4%) |
| Miss (NOT REAL on an event) | 6 of 130 = 4.6% (95% CI 2.1-9.7%) |
| Can't tell on an event | 55 of 130 = 42.3% (95% CI 34.2-50.9%) |
| False alarm (REAL on a control) | 1 of 117 = 0.9% (95% CI 0.2-4.7%) |
| Correct on a control | 78 of 117 = 66.7% (95% CI 57.7-74.6%) |
| Can't tell on a control | 38 of 117 = 32.5% (95% CI 24.7-41.4%) |

0 of the items attempted so far produced no verdict (raised or timed
out); they are excluded from every rate above and listed below. A rate shown as
"not measured" has no finished runs behind it and no number is invented for it.

So far 130 event items and 117 control items have been
attempted, of which 130 and 117 finished.

**By change type**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| burn | 15 | 10 (67%) | 3 (20%) | 2 (13%) | 2 | 0 (0%) | 1 (50%) | 1 (50%) |
| clearing | 115 | 59 (51%) | 3 (3%) | 53 (46%) | 115 | 1 (1%) | 77 (67%) | 37 (32%) |

**By source and date precision**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| hansen (source) | 115 | 59 (51%) | 3 (3%) | 53 (46%) | 115 | 1 (1%) | 77 (67%) | 37 (32%) |
| mtbs (source) | 15 | 10 (67%) | 3 (20%) | 2 (13%) | 2 | 0 (0%) | 1 (50%) | 1 (50%) |
| day (date precision) | 15 | 10 (67%) | 3 (20%) | 2 (13%) | 2 | 0 (0%) | 1 (50%) | 1 (50%) |
| year (date precision) | 115 | 59 (51%) | 3 (3%) | 53 (46%) | 115 | 1 (1%) | 77 (67%) | 37 (32%) |

**By polygon size**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| <50 ha | 82 | 45 (55%) | 2 (2%) | 35 (43%) | 88 | 1 (1%) | 60 (68%) | 27 (31%) |
| 50-150 ha | 29 | 13 (45%) | 1 (3%) | 15 (52%) | 24 | 0 (0%) | 16 (67%) | 8 (33%) |
| >150 ha | 19 | 11 (58%) | 3 (16%) | 5 (26%) | 5 | 0 (0%) | 2 (40%) | 3 (60%) |

**By climate**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| tropical | 23 | 5 (22%) | 1 (4%) | 17 (74%) | 69 | 0 (0%) | 48 (70%) | 21 (30%) |
| temperate | 51 | 27 (53%) | 5 (10%) | 19 (37%) | 23 | 0 (0%) | 16 (70%) | 7 (30%) |
| boreal | 49 | 31 (63%) | 0 (0%) | 18 (37%) | 25 | 1 (4%) | 14 (56%) | 10 (40%) |
| dry | 7 | 6 (86%) | 0 (0%) | 1 (14%) | 0 | 0 (-) | 0 (-) | 0 (-) |


## Every item

| Item | Type | Expected | Verdict | Lead | Effect (90% interval) | Placebo p | Pre/post bins | Donors | Size | Climate | Date | Seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ev-hansen-001 | clearing | REAL | REAL | NDVI | -0.139 (-0.152 to -0.121) | 0.02 | 34/17 | 80 | 43.65 ha | boreal | 2020-01-01 | 399.0 |
| ev-hansen-002 | clearing | REAL | REAL | NDVI | -0.255 (-0.273 to -0.070) | 0.03 | 22/14 | 80 | 34.04 ha | boreal | 2019-01-01 | 289.0 |
| ev-hansen-003 | clearing | REAL | REAL | NDVI | -0.188 (-0.204 to -0.015) | 0.02 | 24/18 | 80 | 49.28 ha | boreal | 2019-01-01 | 347.4 |
| ev-hansen-004 | clearing | REAL | REAL | NDVI | -0.160 (-0.192 to -0.022) | 0.02 | 25/13 | 80 | 26.52 ha | boreal | 2022-01-01 | 237.9 |
| ev-hansen-005 | clearing | REAL | CANT_TELL | NDVI | -0.060 (-0.057 to +0.054) | 0.10 | 58/32 | 80 | 283.44 ha | tropical | 2023-01-01 | 748.7 |
| ev-hansen-006 | clearing | REAL | REAL | NDVI | -0.135 (-0.120 to -0.042) | 0.02 | 39/19 | 80 | 38.85 ha | tropical | 2022-01-01 | 460.5 |
| ev-hansen-007 | clearing | REAL | CANT_TELL | NDVI | -0.123 (-0.130 to +0.006) | 0.02 | 53/21 | 80 | 77.52 ha | tropical | 2021-01-01 | 574.4 |
| ev-hansen-008 | clearing | REAL | REAL | NDVI | -0.265 (-0.288 to -0.172) | 0.02 | 35/14 | 80 | 21.9 ha | boreal | 2021-01-01 | 415.9 |
| ev-hansen-009 | clearing | REAL | REAL | NDVI | -0.191 (-0.235 to -0.132) | 0.08 | 43/18 | 80 | 34.54 ha | temperate | 2022-01-01 | 416.9 |
| ev-hansen-010 | clearing | REAL | CANT_TELL | NDVI | -0.033 (-0.084 to +0.058) | 0.26 | 28/21 | 32 | 45.5 ha | tropical | 2019-01-01 | 396.6 |
| ev-hansen-011 | clearing | REAL | REAL | NDVI | -0.248 (-0.368 to -0.016) | 0.02 | 45/42 | 80 | 59.81 ha | temperate | 2019-01-01 | 414.1 |
| ev-hansen-012 | clearing | REAL | CANT_TELL | NDVI | -0.240 (-0.382 to +0.028) | 0.02 | 66/39 | 80 | 30.24 ha | temperate | 2020-01-01 | 781.6 |
| ev-hansen-013 | clearing | REAL | REAL | NDVI | -0.218 (-0.289 to -0.016) | 0.08 | 31/13 | 80 | 44.0 ha | boreal | 2022-01-01 | 264.0 |
| ev-hansen-014 | clearing | REAL | REAL | NDVI | -0.219 (-0.207 to -0.017) | 0.02 | 42/27 | 80 | 47.96 ha | temperate | 2019-01-01 | 392.8 |
| ev-hansen-015 | clearing | REAL | CANT_TELL | NDVI | -0.072 (-0.151 to +0.031) | 0.03 | 65/30 | 80 | 24.6 ha | temperate | 2022-01-01 | 538.4 |
| ev-hansen-016 | clearing | REAL | REAL | NDVI | -0.278 (-0.343 to -0.111) | 0.02 | 68/33 | 80 | 75.23 ha | temperate | 2022-01-01 | 570.8 |
| ev-hansen-017 | clearing | REAL | CANT_TELL | NDVI | -0.248 (-0.311 to -0.008) | 0.03 | 15/23 | 80 | 36.3 ha | temperate | 2018-01-01 | 239.2 |
| ev-hansen-018 | clearing | REAL | REAL | NDVI | -0.202 (-0.213 to -0.066) | 0.02 | 29/17 | 80 | 32.67 ha | boreal | 2020-01-01 | 340.9 |
| ev-hansen-019 | clearing | REAL | REAL | NDVI | -0.278 (-0.310 to -0.118) | 0.02 | 65/35 | 80 | 31.38 ha | temperate | 2022-01-01 | 539.8 |
| ev-hansen-020 | clearing | REAL | CANT_TELL | NDVI | -0.182 (-0.323 to +0.025) | 0.18 | 19/16 | 80 | 31.49 ha | boreal | 2019-01-01 | 355.1 |
| ev-hansen-021 | clearing | REAL | CANT_TELL | NDVI | -0.150 (-0.158 to +0.036) | 0.03 | 22/16 | 80 | 36.02 ha | boreal | 2020-01-01 | 348.1 |
| ev-hansen-022 | clearing | REAL | NOT_REAL | NDVI | -0.065 (+0.002 to +0.062) | 0.46 | 53/22 | 80 | 29.7 ha | temperate | 2020-01-01 | 442.7 |
| ev-hansen-023 | clearing | REAL | CANT_TELL | NDVI | -0.052 (-0.092 to +0.019) | 0.34 | 38/13 | 80 | 42.2 ha | tropical | 2021-01-01 | 431.0 |
| ev-hansen-024 | clearing | REAL | CANT_TELL | NDVI | -0.179 (-0.161 to +0.005) | 0.02 | 38/21 | 80 | 50.37 ha | boreal | 2023-01-01 | 290.3 |
| ev-hansen-025 | clearing | REAL | CANT_TELL | NDVI | -0.105 (-0.123 to -0.018) | 0.02 | 49/22 | 80 | 84.1 ha | tropical | 2020-01-01 | 386.7 |
| ev-hansen-026 | clearing | REAL | REAL | NDVI | -0.082 (-0.117 to -0.020) | 0.03 | 50/36 | 80 | 33.81 ha | temperate | 2019-01-01 | 862.2 |
| ev-hansen-027 | clearing | REAL | REAL | NDVI | -0.379 (-0.418 to -0.230) | 0.02 | 30/8 | 80 | 44.86 ha | boreal | 2022-01-01 | 306.5 |
| ev-hansen-028 | clearing | REAL | REAL | NDVI | -0.114 (-0.172 to -0.067) | 0.08 | 49/31 | 80 | 44.22 ha | temperate | 2021-01-01 | 680.2 |
| ev-hansen-029 | clearing | REAL | NOT_REAL | NDVI | -0.007 (-0.009 to +0.017) | 0.11 | 66/25 | 80 | 112.85 ha | tropical | 2021-01-01 | 851.3 |
| ev-hansen-030 | clearing | REAL | REAL | NDVI | -0.268 (-0.306 to -0.097) | 0.03 | 28/19 | 80 | 42.68 ha | boreal | 2020-01-01 | 386.8 |
| ev-hansen-031 | clearing | REAL | CANT_TELL | NDVI | -0.294 (-0.319 to +0.028) | 0.05 | 32/24 | 70 | 22.66 ha | boreal | 2023-01-01 | 271.8 |
| ev-hansen-032 | clearing | REAL | REAL | NDVI | -0.320 (-0.400 to -0.081) | 0.02 | 47/28 | 80 | 63.33 ha | temperate | 2020-01-01 | 446.9 |
| ev-hansen-033 | clearing | REAL | REAL | NDVI | -0.195 (-0.200 to -0.138) | 0.02 | 32/17 | 80 | 27.77 ha | boreal | 2023-01-01 | 239.2 |
| ev-hansen-034 | clearing | REAL | REAL | NDVI | -0.311 (-0.348 to -0.127) | 0.02 | 35/26 | 80 | 39.74 ha | temperate | 2020-01-01 | 367.2 |
| ev-hansen-035 | clearing | REAL | REAL | NDVI | -0.208 (-0.222 to -0.101) | 0.02 | 24/12 | 80 | 73.84 ha | boreal | 2021-01-01 | 384.0 |
| ev-hansen-036 | clearing | REAL | REAL | NDVI | -0.169 (-0.204 to -0.019) | 0.02 | 31/12 | 80 | 34.95 ha | boreal | 2021-01-01 | 299.7 |
| ev-hansen-037 | clearing | REAL | CANT_TELL | NDVI | -0.395 (-0.458 to +0.020) | 0.02 | 44/39 | 80 | 45.1 ha | temperate | 2019-01-01 | 388.5 |
| ev-hansen-038 | clearing | REAL | REAL | NDVI | -0.208 (-0.256 to -0.093) | 0.02 | 28/14 | 80 | 35.56 ha | boreal | 2022-01-01 | 343.3 |
| ev-hansen-039 | clearing | REAL | CANT_TELL | NDVI | -0.241 (-0.366 to -0.083) | 0.02 | 87/43 | 80 | 42.67 ha | temperate | 2023-01-01 | 731.5 |
| ev-hansen-040 | clearing | REAL | REAL | NDVI | -0.323 (-0.360 to -0.110) | 0.02 | 64/28 | 80 | 56.85 ha | temperate | 2022-01-01 | 621.4 |
| ev-hansen-041 | clearing | REAL | REAL | NDVI | -0.202 (-0.205 to -0.155) | 0.02 | 25/18 | 80 | 41.13 ha | boreal | 2021-01-01 | 384.4 |
| ev-hansen-042 | clearing | REAL | CANT_TELL | NDVI | -0.089 (-0.124 to +0.109) | 0.07 | 43/50 | 80 | 26.73 ha | tropical | 2018-01-01 | 715.0 |
| ev-hansen-043 | clearing | REAL | REAL | NDVI | -0.276 (-0.310 to -0.232) | 0.02 | 20/15 | 80 | 62.44 ha | boreal | 2019-01-01 | 268.3 |
| ev-hansen-044 | clearing | REAL | CANT_TELL | NDVI | -0.138 (-0.241 to +0.006) | 0.02 | 54/30 | 80 | 36.45 ha | temperate | 2020-01-01 | 588.0 |
| ev-hansen-045 | clearing | REAL | REAL | NDVI | -0.210 (-0.246 to -0.157) | 0.02 | 51/19 | 80 | 32.0 ha | temperate | 2022-01-01 | 767.9 |
| ev-hansen-046 | clearing | REAL | REAL | NDVI | -0.250 (-0.347 to -0.068) | 0.02 | 64/27 | 80 | 35.35 ha | temperate | 2022-01-01 | 666.7 |
| ev-hansen-047 | clearing | REAL | CANT_TELL | NDVI | -0.137 (-0.166 to +0.030) | 0.02 | 25/22 | 80 | 51.99 ha | tropical | 2019-01-01 | 333.2 |
| ev-hansen-048 | clearing | REAL | REAL | NDVI | -0.140 (-0.243 to -0.037) | 0.07 | 38/17 | 80 | 34.57 ha | boreal | 2023-01-01 | 338.8 |
| ev-hansen-049 | clearing | REAL | CANT_TELL | NDVI | -0.048 (-0.089 to +0.007) | 0.30 | 29/14 | 22 | 174.66 ha | tropical | 2021-01-01 | 413.6 |
| ev-hansen-050 | clearing | REAL | REAL | NDVI | -0.209 (-0.250 to -0.174) | 0.02 | 28/18 | 80 | 37.58 ha | boreal | 2020-01-01 | 370.3 |
| ev-hansen-051 | clearing | REAL | CANT_TELL | NDVI | -0.352 (-0.458 to +0.004) | 0.02 | 55/26 | 80 | 33.13 ha | temperate | 2020-01-01 | 561.9 |
| ev-hansen-052 | clearing | REAL | CANT_TELL | NDVI | -0.182 (-0.407 to +0.393) | 0.41 | 20/21 | 80 | 26.08 ha | boreal | 2019-01-01 | 334.4 |
| ev-hansen-053 | clearing | REAL | REAL | NDVI | -0.111 (-0.155 to -0.027) | 0.05 | 37/22 | 80 | 29.1 ha | boreal | 2023-01-01 | 233.4 |
| ev-hansen-054 | clearing | REAL | REAL | NDVI | -0.338 (-0.372 to -0.072) | 0.02 | 31/13 | 80 | 22.7 ha | boreal | 2022-01-01 | 256.9 |
| ev-hansen-055 | clearing | REAL | CANT_TELL | NDVI | -0.093 (-0.127 to +0.037) | 0.02 | 45/43 | 80 | 52.27 ha | temperate | 2019-01-01 | 477.7 |
| ev-hansen-056 | clearing | REAL | CANT_TELL | NDVI | -0.413 (-0.538 to +0.262) | 0.02 | 76/33 | 80 | 63.32 ha | temperate | 2022-01-01 | 702.0 |
| ev-hansen-057 | clearing | REAL | REAL | NDVI | -0.197 (-0.266 to -0.085) | 0.02 | 27/10 | 56 | 325.87 ha | tropical | 2021-01-01 | 8.8 |
| ev-hansen-058 | clearing | REAL | CANT_TELL | NDVI | -0.064 (-0.273 to +0.171) | 0.70 | 19/6 | 80 | 39.45 ha | boreal | 2020-01-01 | 309.0 |
| ev-hansen-059 | clearing | REAL | CANT_TELL | NDVI | -0.183 (-0.419 to +0.009) | 0.02 | 60/33 | 80 | 106.98 ha | tropical | 2021-01-01 | 812.1 |
| ev-hansen-060 | clearing | REAL | REAL | NDVI | -0.315 (-0.398 to -0.031) | 0.02 | 66/39 | 80 | 29.29 ha | temperate | 2020-01-01 | 621.6 |
| ev-hansen-061 | clearing | REAL | CANT_TELL | NDVI | -0.181 (-0.289 to +0.101) | 0.02 | 30/17 | 80 | 35.91 ha | boreal | 2023-01-01 | 275.1 |
| ev-hansen-062 | clearing | REAL | REAL | NDVI | -0.140 (-0.146 to -0.070) | 0.02 | 42/21 | 80 | 144.27 ha | tropical | 2020-01-01 | 500.3 |
| ev-hansen-063 | clearing | REAL | CANT_TELL | NDVI | -0.051 (-0.154 to -0.025) | 0.72 | 10/22 | 80 | 27.83 ha | tropical | 2018-01-01 | 275.7 |
| ev-hansen-064 | clearing | REAL | CANT_TELL | NDVI | -0.144 (-0.280 to +0.139) | 0.03 | 41/24 | 80 | 34.2 ha | temperate | 2019-01-01 | 412.6 |
| ev-hansen-065 | clearing | REAL | REAL | NDVI | -0.302 (-0.335 to -0.116) | 0.03 | 30/15 | 80 | 29.4 ha | boreal | 2022-01-01 | 319.3 |
| ev-hansen-066 | clearing | REAL | REAL | NDVI | -0.242 (-0.285 to -0.035) | 0.02 | 25/16 | 80 | 35.38 ha | boreal | 2021-01-01 | 375.9 |
| ev-hansen-067 | clearing | REAL | REAL | NDVI | -0.322 (-0.483 to -0.072) | 0.02 | 27/17 | 80 | 25.9 ha | boreal | 2020-01-01 | 371.4 |
| ev-hansen-068 | clearing | REAL | REAL | NDVI | -0.101 (-0.267 to -0.058) | 0.02 | 32/26 | 80 | 62.87 ha | temperate | 2018-01-01 | 732.1 |
| ev-hansen-069 | clearing | REAL | CANT_TELL | NDVI | -0.101 (-0.286 to +0.095) | 0.15 | 12/20 | 80 | 35.69 ha | boreal | 2018-01-01 | 321.9 |
| ev-hansen-070 | clearing | REAL | CANT_TELL | NDVI | -0.170 (-0.367 to +0.027) | 0.02 | 79/35 | 80 | 35.37 ha | temperate | 2021-01-01 | 1027.8 |
| ev-hansen-071 | clearing | REAL | REAL | NDVI | -0.208 (-0.230 to -0.112) | 0.03 | 26/17 | 80 | 30.95 ha | boreal | 2019-01-01 | 286.4 |
| ev-hansen-072 | clearing | REAL | CANT_TELL | NDVI | -0.410 (-0.618 to -0.064) | 0.02 | 18/25 | 32 | 68.64 ha | tropical | 2019-01-01 | 381.1 |
| ev-hansen-073 | clearing | REAL | REAL | NDVI | -0.255 (-0.300 to -0.067) | 0.02 | 35/21 | 80 | 44.5 ha | boreal | 2023-01-01 | 265.9 |
| ev-hansen-074 | clearing | REAL | REAL | NDVI | -0.371 (-0.446 to -0.273) | 0.03 | 68/25 | 80 | 37.53 ha | temperate | 2020-01-01 | 635.9 |
| ev-hansen-075 | clearing | REAL | CANT_TELL | NDVI | -0.028 (-0.103 to +0.039) | 0.21 | 42/29 | 80 | 65.58 ha | tropical | 2019-01-01 | 642.7 |
| ev-hansen-076 | clearing | REAL | CANT_TELL | NDVI | -0.124 (-0.145 to +0.006) | 0.02 | 91/51 | 80 | 33.09 ha | temperate | 2020-01-01 | 1662.6 |
| ev-hansen-077 | clearing | REAL | REAL | NDVI | -0.279 (-0.337 to -0.194) | 0.02 | 65/30 | 80 | 33.23 ha | temperate | 2022-01-01 | 467.3 |
| ev-hansen-078 | clearing | REAL | CANT_TELL | NDVI | -0.205 (-0.241 to +0.025) | 0.02 | 35/14 | 80 | 31.02 ha | boreal | 2021-01-01 | 374.4 |
| ev-hansen-079 | clearing | REAL | REAL | NDVI | -0.344 (-0.386 to -0.010) | 0.02 | 57/35 | 80 | 42.94 ha | temperate | 2023-01-01 | 701.3 |
| ev-hansen-080 | clearing | REAL | CANT_TELL | NDVI | -0.114 (-0.251 to +0.041) | 0.02 | 92/48 | 80 | 51.84 ha | tropical | 2021-01-01 | 1091.7 |
| ev-hansen-081 | clearing | REAL | CANT_TELL | NDVI | -0.265 (-0.285 to +0.081) | 0.05 | 47/25 | 80 | 34.47 ha | temperate | 2019-01-01 | 514.3 |
| ev-hansen-082 | clearing | REAL | REAL | NDVI | -0.277 (-0.310 to -0.178) | 0.02 | 31/17 | 80 | 75.72 ha | boreal | 2021-01-01 | 383.9 |
| ev-hansen-083 | clearing | REAL | CANT_TELL | NDVI | -0.102 (-0.147 to -0.037) | 0.11 | 37/21 | 8 | 60.5 ha | tropical | 2019-01-01 | 409.8 |
| ev-hansen-084 | clearing | REAL | REAL | NDVI | -0.153 (-0.187 to -0.062) | 0.03 | 53/27 | 80 | 52.83 ha | tropical | 2020-01-01 | 670.7 |
| ev-hansen-085 | clearing | REAL | CANT_TELL | NDVI | -0.133 (-0.168 to +0.010) | 0.03 | 101/49 | 80 | 33.67 ha | temperate | 2022-01-01 | 1069.7 |
| ev-hansen-086 | clearing | REAL | REAL | NDVI | -0.147 (-0.176 to -0.088) | 0.05 | 37/15 | 80 | 26.26 ha | boreal | 2022-01-01 | 215.1 |
| ev-hansen-087 | clearing | REAL | REAL | NDVI | -0.233 (-0.367 to -0.137) | 0.02 | 63/29 | 80 | 31.67 ha | temperate | 2020-01-01 | 582.9 |
| ev-hansen-088 | clearing | REAL | REAL | NDVI | -0.290 (-0.339 to -0.143) | 0.02 | 23/17 | 80 | 51.5 ha | boreal | 2020-01-01 | 517.5 |
| ev-hansen-089 | clearing | REAL | REAL | NDVI | -0.173 (-0.187 to -0.024) | 0.02 | 68/36 | 80 | 28.48 ha | temperate | 2020-01-01 | 634.5 |
| ev-hansen-090 | clearing | REAL | CANT_TELL | NDVI | -0.194 (-0.203 to -0.117) | 0.02 | 24/16 | 80 | 31.11 ha | boreal | 2020-01-01 | 355.9 |
| ev-hansen-091 | clearing | REAL | CANT_TELL | NDVI | -0.204 (-0.258 to +0.126) | 0.05 | 15/14 | 80 | 48.14 ha | boreal | 2019-01-01 | 246.0 |
| ev-hansen-092 | clearing | REAL | REAL | NDVI | -0.283 (-0.308 to -0.257) | 0.02 | 25/17 | 80 | 31.29 ha | boreal | 2020-01-01 | 339.1 |
| ev-hansen-093 | clearing | REAL | REAL | NDVI | -0.184 (-0.200 to -0.061) | 0.02 | 41/19 | 80 | 29.14 ha | temperate | 2020-01-01 | 684.6 |
| ev-hansen-094 | clearing | REAL | CANT_TELL | NDVI | -0.243 (-0.288 to +0.184) | 0.02 | 53/30 | 80 | 66.78 ha | temperate | 2020-01-01 | 451.2 |
| ev-hansen-095 | clearing | REAL | REAL | NDVI | -0.121 (-0.146 to -0.079) | 0.02 | 63/28 | 80 | 33.72 ha | temperate | 2021-01-01 | 740.9 |
| ev-hansen-096 | clearing | REAL | CANT_TELL | NDVI | -0.227 (-0.312 to +0.104) | 0.05 | 19/16 | 80 | 37.03 ha | boreal | 2019-01-01 | 382.4 |
| ev-hansen-097 | clearing | REAL | REAL | NDVI | -0.172 (-0.167 to -0.070) | 0.02 | 62/36 | 80 | 62.16 ha | tropical | 2023-01-01 | 576.1 |
| ev-hansen-098 | clearing | REAL | REAL | NDVI | -0.183 (-0.206 to -0.048) | 0.02 | 69/22 | 80 | 39.96 ha | temperate | 2021-01-01 | 568.6 |
| ev-hansen-099 | clearing | REAL | NOT_REAL | NDVI | -0.119 (-0.029 to +0.011) | 0.03 | 49/21 | 80 | 30.75 ha | temperate | 2020-01-01 | 498.6 |
| ev-hansen-100 | clearing | REAL | CANT_TELL | NDVI | -0.147 (-0.217 to -0.077) | 0.10 | 46/12 | 9 | 43.61 ha | boreal | 2022-01-01 | 354.8 |
| ev-hansen-101 | clearing | REAL | CANT_TELL | NDVI | -0.180 (-0.208 to +0.033) | 0.10 | 28/18 | 80 | 30.67 ha | boreal | 2020-01-01 | 392.3 |
| ev-hansen-102 | clearing | REAL | CANT_TELL | NDVI | -0.337 (-0.385 to -0.288) | 0.07 | 76/26 | 30 | 26.7 ha | temperate | 2021-01-01 | 602.1 |
| ev-hansen-103 | clearing | REAL | REAL | NDVI | -0.259 (-0.279 to -0.088) | 0.02 | 31/13 | 80 | 23.45 ha | boreal | 2021-01-01 | 337.2 |
| ev-hansen-104 | clearing | REAL | CANT_TELL | NDVI | -0.106 (-0.150 to +0.131) | 0.02 | 85/38 | 80 | 29.51 ha | temperate | 2022-01-01 | 645.0 |
| ev-hansen-105 | clearing | REAL | CANT_TELL | NDVI | -0.075 (-0.100 to +0.011) | 0.05 | 40/17 | 80 | 208.13 ha | tropical | 2021-01-01 | 517.7 |
| ev-hansen-106 | clearing | REAL | REAL | NDVI | -0.169 (-0.420 to -0.062) | 0.02 | 26/23 | 80 | 35.97 ha | temperate | 2018-01-01 | 552.2 |
| ev-hansen-107 | clearing | REAL | REAL | NDVI | -0.273 (-0.339 to -0.088) | 0.02 | 28/30 | 80 | 38.16 ha | temperate | 2018-01-01 | 337.6 |
| ev-hansen-108 | clearing | REAL | REAL | NDVI | -0.300 (-0.344 to -0.119) | 0.02 | 28/15 | 80 | 54.49 ha | boreal | 2021-01-01 | 351.5 |
| ev-hansen-109 | clearing | REAL | CANT_TELL | NDVI | -0.145 (-0.170 to -0.094) | 0.13 | 30/15 | 80 | 32.31 ha | boreal | 2022-01-01 | 241.4 |
| ev-hansen-110 | clearing | REAL | CANT_TELL | NDVI | -0.034 (-0.123 to +0.082) | 0.11 | 97/51 | 80 | 64.33 ha | tropical | 2023-01-01 | 756.4 |
| ev-hansen-111 | clearing | REAL | CANT_TELL | NDVI | -0.040 (-0.071 to +0.053) | 0.18 | 18/12 | 80 | 39.65 ha | tropical | 2019-01-01 | 341.7 |
| ev-hansen-112 | clearing | REAL | CANT_TELL | NDVI | -0.104 (-0.143 to +0.028) | 0.07 | 33/17 | 80 | 40.17 ha | boreal | 2023-01-01 | 250.8 |
| ev-hansen-113 | clearing | REAL | CANT_TELL | NDVI | -0.193 (-0.239 to +0.008) | 0.02 | 24/19 | 80 | 56.65 ha | boreal | 2020-01-01 | 494.7 |
| ev-hansen-114 | clearing | REAL | CANT_TELL | NDVI | -0.251 (-0.314 to -0.037) | 0.11 | 17/17 | 80 | 83.61 ha | temperate | 2018-01-01 | 237.5 |
| ev-hansen-115 | clearing | REAL | CANT_TELL | NDVI | -0.190 (-0.307 to +0.015) | 0.67 | 5/15 | 80 | 49.8 ha | boreal | 2018-01-01 | 269.9 |
| ev-mtbs-001 | burn | REAL | NOT_REAL | NBR | +0.002 (-0.035 to +0.015) | 0.52 | 60/10 | 80 | 296.31 ha | temperate | 2021-03-08 | 350.5 |
| ev-mtbs-002 | burn | REAL | NOT_REAL | VH | -0.720 (-0.984 to -0.429) | 0.02 | 44/15 | 80 | 400.0 ha | temperate | 2018-08-02 | 192.0 |
| ev-mtbs-003 | burn | REAL | NOT_REAL | NBR | -0.087 (-0.050 to +0.054) | 0.25 | 56/5 | 30 | 400.0 ha | temperate | 2021-08-12 | 831.9 |
| ev-mtbs-004 | burn | REAL | REAL | NBR | -0.130 (-0.137 to -0.067) | 0.02 | 42/13 | 67 | 400.0 ha | dry | 2019-07-16 | 393.3 |
| ev-mtbs-005 | burn | REAL | REAL | NBR | -0.490 (-0.526 to -0.407) | 0.02 | 33/12 | 41 | 400.0 ha | dry | 2021-06-13 | 361.1 |
| ev-mtbs-006 | burn | REAL | REAL | NBR | -0.375 (-0.397 to -0.347) | 0.02 | 72/15 | 48 | 400.0 ha | temperate | 2019-06-25 | 591.4 |
| ev-mtbs-007 | burn | REAL | REAL | NBR | -0.084 (-0.114 to -0.048) | 0.03 | 35/3 | 73 | 232.54 ha | temperate | 2019-11-14 | 308.8 |
| ev-mtbs-008 | burn | REAL | REAL | NBR | -0.146 (-0.201 to -0.125) | 0.02 | 72/14 | 80 | 400.0 ha | dry | 2021-07-13 | 718.1 |
| ev-mtbs-009 | burn | REAL | REAL | NBR | -0.228 (-0.445 to -0.036) | 0.02 | 28/11 | 57 | 400.0 ha | boreal | 2020-06-04 | 411.9 |
| ev-mtbs-010 | burn | REAL | REAL | NBR | -0.222 (-0.297 to -0.231) | 0.02 | 72/8 | 80 | 225.0 ha | dry | 2022-08-20 | 637.0 |
| ev-mtbs-011 | burn | REAL | REAL | NBR | -0.174 (-0.198 to -0.158) | 0.03 | 50/5 | 80 | 400.0 ha | dry | 2018-09-13 | 323.5 |
| ev-mtbs-012 | burn | REAL | CANT_TELL | NBR | -0.081 (-0.285 to +0.014) | 0.03 | 43/6 | 80 | 400.0 ha | dry | 2019-09-06 | 333.5 |
| ev-mtbs-013 | burn | REAL | REAL | NBR | -0.291 (-0.392 to -0.074) | 0.02 | 24/3 | 44 | 400.0 ha | dry | 2018-08-02 | 330.0 |
| ev-mtbs-014 | burn | REAL | CANT_TELL | NBR | +0.052 (-0.153 to +0.158) | 0.06 | 54/10 | 46 | 400.0 ha | temperate | 2022-03-26 | 398.6 |
| ev-mtbs-015 | burn | REAL | REAL | NBR | -0.069 (-0.106 to -0.035) | 0.02 | 69/11 | 80 | 291.72 ha | temperate | 2022-04-14 | 413.7 |
| nl-hansen-001 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.003 (-0.013 to +0.007) | 0.80 | 83/50 | 43 | 36.66 ha | tropical | 2020-01-01 | 865.3 |
| nl-hansen-002 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.016 (-0.002 to +0.024) | 0.69 | 66/41 | 80 | 45.32 ha | tropical | 2019-01-01 | 505.4 |
| nl-hansen-003 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.003 (-0.009 to +0.024) | 0.64 | 23/19 | 80 | 33.37 ha | boreal | 2019-01-01 | 367.0 |
| nl-hansen-004 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.008 (-0.025 to +0.028) | 0.66 | 45/17 | 80 | 63.42 ha | tropical | 2022-01-01 | 493.0 |
| nl-hansen-005 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.002 (-0.016 to +0.013) | 0.92 | 45/16 | 80 | 62.91 ha | temperate | 2023-01-01 | 525.7 |
| nl-hansen-006 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.006 (-0.035 to +0.018) | 0.62 | 39/24 | 80 | 43.79 ha | tropical | 2020-01-01 | 369.3 |
| nl-hansen-007 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.063 (-0.028 to +0.021) | 0.13 | 37/23 | 80 | 77.12 ha | boreal | 2021-01-01 | 411.8 |
| nl-hansen-008 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.004 (-0.038 to +0.030) | 0.82 | 17/23 | 34 | 27.38 ha | tropical | 2019-01-01 | 367.5 |
| nl-hansen-009 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.078 (-0.071 to +0.038) | 0.08 | 24/12 | 73 | 283.03 ha | boreal | 2021-01-01 | 356.1 |
| nl-hansen-010 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.003 (-0.010 to +0.017) | 0.46 | 60/28 | 80 | 26.96 ha | tropical | 2021-01-01 | 416.6 |
| nl-hansen-011 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.006 (-0.022 to +0.009) | 0.79 | 69/38 | 80 | 33.4 ha | tropical | 2023-01-01 | 517.7 |
| nl-hansen-012 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.001 (-0.017 to +0.008) | 0.79 | 57/34 | 80 | 74.03 ha | tropical | 2019-01-01 | 471.0 |
| nl-hansen-013 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.026 (-0.035 to -0.012) | 0.48 | 68/35 | 72 | 46.97 ha | tropical | 2020-01-01 | 693.1 |
| nl-hansen-014 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.041 (-0.020 to +0.061) | 0.46 | 41/21 | 80 | 34.19 ha | boreal | 2020-01-01 | 547.0 |
| nl-hansen-015 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.012 (-0.021 to +0.025) | 0.15 | 19/32 | 62 | 60.99 ha | temperate | 2018-01-01 | 234.6 |
| nl-hansen-016 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.002 (-0.015 to +0.019) | 0.92 | 48/33 | 80 | 174.01 ha | tropical | 2021-01-01 | 571.0 |
| nl-hansen-017 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.010 (-0.016 to +0.012) | 0.77 | 37/23 | 80 | 34.49 ha | tropical | 2020-01-01 | 399.0 |
| nl-hansen-018 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.001 (-0.014 to +0.026) | 1.00 | 33/27 | 80 | 48.69 ha | boreal | 2023-01-01 | 239.1 |
| nl-hansen-019 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.001 (-0.012 to +0.006) | 0.87 | 60/32 | 80 | 38.77 ha | tropical | 2022-01-01 | 483.7 |
| nl-hansen-020 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.002 (-0.029 to +0.020) | 0.98 | 40/36 | 72 | 22.94 ha | tropical | 2019-01-01 | 331.5 |
| nl-hansen-021 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.013 (-0.027 to -0.004) | 0.20 | 27/18 | 80 | 32.43 ha | boreal | 2019-01-01 | 456.7 |
| nl-hansen-022 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.008 (-0.022 to +0.020) | 0.95 | 26/13 | 80 | 64.52 ha | boreal | 2020-01-01 | 486.9 |
| nl-hansen-023 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.035 (-0.042 to -0.007) | 0.11 | 29/23 | 80 | 45.61 ha | tropical | 2019-01-01 | 361.9 |
| nl-hansen-024 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.008 (-0.013 to +0.001) | 0.51 | 59/29 | 80 | 83.8 ha | tropical | 2021-01-01 | 636.5 |
| nl-hansen-025 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.050 (-0.063 to +0.104) | 0.33 | 11/3 | 80 | 40.66 ha | tropical | 2022-01-01 | 267.2 |
| nl-hansen-026 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.009 (-0.009 to +0.035) | 0.41 | 86/46 | 80 | 207.04 ha | tropical | 2021-01-01 | 867.0 |
| nl-hansen-027 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.018 (-0.005 to +0.026) | 0.31 | 60/38 | 80 | 21.89 ha | tropical | 2019-01-01 | 362.8 |
| nl-hansen-028 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.023 (-0.050 to +0.011) | 0.71 | 40/16 | 57 | 50.03 ha | tropical | 2023-01-01 | 608.6 |
| nl-hansen-029 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.003 (-0.002 to +0.007) | 0.90 | 49/33 | 80 | 42.28 ha | tropical | 2020-01-01 | 701.1 |
| nl-hansen-030 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.001 (-0.018 to +0.002) | 0.75 | 62/45 | 70 | 33.37 ha | temperate | 2019-01-01 | 525.7 |
| nl-hansen-031 | clearing | NOT_REAL | REAL | NDVI | -0.067 (-0.123 to -0.007) | 0.02 | 20/16 | 80 | 28.99 ha | boreal | 2019-01-01 | 342.4 |
| nl-hansen-032 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.009 (-0.001 to +0.032) | 0.90 | 32/26 | 30 | 29.5 ha | boreal | 2022-01-01 | 370.4 |
| nl-hansen-033 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.000 (-0.016 to +0.022) | 0.54 | 72/38 | 80 | 44.79 ha | temperate | 2021-01-01 | 762.8 |
| nl-hansen-034 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.014 (-0.019 to +0.012) | 0.15 | 50/33 | 80 | 75.79 ha | tropical | 2022-01-01 | 538.0 |
| nl-hansen-035 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.002 (-0.012 to +0.016) | 0.52 | 53/28 | 80 | 29.42 ha | temperate | 2022-01-01 | 721.3 |
| nl-hansen-036 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.004 (-0.024 to +0.013) | 0.39 | 37/16 | 80 | 39.01 ha | boreal | 2020-01-01 | 390.4 |
| nl-hansen-037 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.005 (-0.021 to +0.020) | 0.97 | 37/21 | 80 | 50.34 ha | boreal | 2020-01-01 | 544.3 |
| nl-hansen-038 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.010 (-0.048 to +0.112) | 0.79 | 13/11 | 80 | 28.43 ha | boreal | 2019-01-01 | 288.8 |
| nl-hansen-039 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.024 (-0.040 to +0.001) | 0.85 | 36/28 | 80 | 30.45 ha | boreal | 2022-01-01 | 314.9 |
| nl-hansen-040 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.028 (-0.043 to -0.007) | 0.10 | 62/35 | 80 | 40.16 ha | tropical | 2021-01-01 | 546.9 |
| nl-hansen-041 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.011 (-0.011 to +0.033) | 0.52 | 27/24 | 80 | 33.91 ha | boreal | 2019-01-01 | 360.7 |
| nl-hansen-042 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.001 (-0.023 to +0.016) | 0.72 | 43/11 | 80 | 55.73 ha | tropical | 2021-01-01 | 250.6 |
| nl-hansen-043 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.032 (-0.007 to +0.014) | 0.23 | 41/24 | 80 | 31.17 ha | boreal | 2021-01-01 | 302.5 |
| nl-hansen-044 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.000 (-0.050 to +0.026) | 0.36 | 76/40 | 80 | 33.76 ha | tropical | 2020-01-01 | 767.6 |
| nl-hansen-045 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.003 (-0.007 to +0.013) | 0.66 | 98/46 | 79 | 33.71 ha | temperate | 2023-01-01 | 1016.7 |
| nl-hansen-046 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.027 (-0.034 to +0.017) | 0.23 | 42/15 | 80 | 31.1 ha | temperate | 2021-01-01 | 568.8 |
| nl-hansen-047 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.018 (-0.026 to +0.016) | 0.05 | 47/19 | 80 | 33.74 ha | tropical | 2021-01-01 | 567.6 |
| nl-hansen-048 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.008 (-0.020 to +0.052) | 0.97 | 26/15 | 69 | 28.97 ha | tropical | 2019-01-01 | 292.4 |
| nl-hansen-049 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.027 (-0.061 to -0.006) | 0.08 | 28/18 | 80 | 35.14 ha | boreal | 2023-01-01 | 238.6 |
| nl-hansen-050 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.006 (-0.022 to +0.004) | 0.03 | 81/38 | 80 | 83.13 ha | tropical | 2023-01-01 | 767.6 |
| nl-hansen-051 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.133 (-0.560 to +0.348) | 0.62 | 33/13 | 7 | 21.68 ha | tropical | 2022-01-01 | 324.1 |
| nl-hansen-052 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.003 (-0.010 to +0.015) | 0.51 | 32/23 | 55 | 43.24 ha | temperate | 2020-01-01 | 476.6 |
| nl-hansen-053 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.001 (-0.006 to +0.009) | 0.39 | 63/33 | 80 | 40.04 ha | temperate | 2021-01-01 | 777.9 |
| nl-hansen-054 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.005 (-0.021 to +0.029) | 0.82 | 55/25 | 80 | 39.9 ha | tropical | 2021-01-01 | 350.4 |
| nl-hansen-055 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.000 (-0.007 to +0.012) | 0.56 | 73/37 | 80 | 63.91 ha | temperate | 2023-01-01 | 884.2 |
| nl-hansen-056 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.019 (-0.007 to +0.058) | 0.72 | 80/35 | 80 | 63.95 ha | tropical | 2021-01-01 | 755.2 |
| nl-hansen-057 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.021 (-0.028 to +0.029) | 0.75 | 44/12 | 59 | 30.87 ha | tropical | 2021-01-01 | 384.1 |
| nl-hansen-058 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.013 (-0.014 to +0.027) | 0.49 | 49/20 | 80 | 58.21 ha | tropical | 2022-01-01 | 533.6 |
| nl-hansen-059 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.019 (-0.041 to +0.015) | 0.23 | 36/16 | 34 | 27.96 ha | tropical | 2021-01-01 | 396.8 |
| nl-hansen-060 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.011 (-0.019 to +0.000) | 0.51 | 66/36 | 80 | 40.05 ha | temperate | 2023-01-01 | 572.6 |
| nl-hansen-061 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.011 (-0.016 to +0.005) | 0.44 | 35/30 | 80 | 43.53 ha | tropical | 2019-01-01 | 327.4 |
| nl-hansen-062 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.020 (-0.039 to +0.138) | 0.57 | 26/14 | 80 | 40.05 ha | boreal | 2020-01-01 | 394.2 |
| nl-hansen-063 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.008 (-0.052 to +0.058) | 0.95 | 14/23 | 80 | 45.58 ha | tropical | 2018-01-01 | 289.3 |
| nl-hansen-064 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.003 (-0.016 to +0.035) | 0.61 | 75/40 | 80 | 26.79 ha | tropical | 2021-01-01 | 645.7 |
| nl-hansen-065 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.019 (-0.030 to +0.004) | 0.26 | 39/24 | 80 | 41.81 ha | tropical | 2020-01-01 | 470.9 |
| nl-hansen-066 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.006 (-0.020 to +0.011) | 0.44 | 47/21 | 80 | 40.08 ha | tropical | 2023-01-01 | 465.1 |
| nl-hansen-067 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.018 (-0.039 to +0.026) | 0.44 | 28/19 | 80 | 28.55 ha | boreal | 2021-01-01 | 484.5 |
| nl-hansen-068 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.001 (-0.058 to +0.042) | 0.70 | 84/49 | 80 | 28.83 ha | temperate | 2023-01-01 | 712.4 |
| nl-hansen-069 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.010 (-0.015 to -0.002) | 0.70 | 43/20 | 80 | 42.09 ha | tropical | 2022-01-01 | 467.1 |
| nl-hansen-070 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.015 (-0.059 to +0.020) | 0.48 | 43/30 | 80 | 67.31 ha | tropical | 2019-01-01 | 376.9 |
| nl-hansen-071 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.016 (-0.008 to +0.034) | 0.46 | 15/19 | 80 | 43.0 ha | boreal | 2018-01-01 | 250.1 |
| nl-hansen-072 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.024 (-0.026 to +0.012) | 0.15 | 49/13 | 80 | 40.12 ha | tropical | 2021-01-01 | 572.2 |
| nl-hansen-073 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.008 (-0.011 to +0.001) | 0.48 | 52/44 | 80 | 35.53 ha | tropical | 2019-01-01 | 611.9 |
| nl-hansen-074 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.015 (-0.009 to +0.034) | 0.77 | 43/27 | 80 | 55.23 ha | tropical | 2019-01-01 | 365.9 |
| nl-hansen-075 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.012 (-0.028 to +0.004) | 0.59 | 86/42 | 80 | 44.59 ha | tropical | 2020-01-01 | 626.7 |
| nl-hansen-076 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.008 (-0.008 to +0.032) | 0.93 | 39/24 | 80 | 36.46 ha | temperate | 2020-01-01 | 469.0 |
| nl-hansen-077 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.005 (-0.006 to +0.028) | 0.66 | 48/28 | 80 | 43.95 ha | tropical | 2020-01-01 | 736.5 |
| nl-hansen-078 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.011 (-0.019 to +0.065) | 0.36 | 53/19 | 80 | 35.77 ha | tropical | 2021-01-01 | 602.1 |
| nl-hansen-079 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.008 (-0.036 to +0.020) | 0.57 | 64/33 | 80 | 48.46 ha | tropical | 2023-01-01 | 506.4 |
| nl-hansen-080 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.007 (-0.013 to +0.004) | 0.16 | 69/44 | 80 | 39.17 ha | tropical | 2019-01-01 | 535.4 |
| nl-hansen-081 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.001 (-0.007 to +0.011) | 0.90 | 29/11 | 80 | 30.91 ha | temperate | 2020-01-01 | 469.8 |
| nl-hansen-082 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.038 (-0.001 to +0.259) | 0.66 | 20/7 | 80 | 49.48 ha | boreal | 2019-01-01 | 418.8 |
| nl-hansen-083 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.010 (-0.013 to -0.002) | 0.08 | 47/23 | 80 | 21.62 ha | tropical | 2020-01-01 | 457.0 |
| nl-hansen-084 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.005 (-0.014 to +0.007) | 0.87 | 55/20 | 80 | 32.07 ha | tropical | 2021-01-01 | 626.5 |
| nl-hansen-085 | clearing | NOT_REAL | NOT_REAL | VH | -0.001 (-0.060 to +0.018) | 0.84 | 89/45 | 80 | 114.32 ha | tropical | 2021-01-01 | 375.7 |
| nl-hansen-086 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.008 (-0.013 to +0.001) | 0.61 | 41/25 | 80 | 39.73 ha | tropical | 2023-01-01 | 384.7 |
| nl-hansen-087 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.011 (-0.010 to +0.066) | 0.38 | 8/11 | 80 | 38.28 ha | tropical | 2019-01-01 | 343.6 |
| nl-hansen-088 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.011 (-0.045 to +0.043) | 0.21 | 68/36 | 80 | 25.42 ha | temperate | 2020-01-01 | 434.3 |
| nl-hansen-089 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.035 (-0.042 to +0.017) | 0.38 | 27/12 | 80 | 28.76 ha | boreal | 2022-01-01 | 284.4 |
| nl-hansen-090 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.003 (-0.009 to +0.067) | 0.11 | 27/16 | 80 | 39.95 ha | boreal | 2020-01-01 | 419.1 |
| nl-hansen-091 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.001 (-0.019 to +0.016) | 0.90 | 55/30 | 80 | 30.79 ha | tropical | 2023-01-01 | 472.1 |
| nl-hansen-092 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.002 (-0.011 to +0.004) | 1.00 | 68/35 | 80 | 66.15 ha | temperate | 2023-01-01 | 533.4 |
| nl-hansen-093 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.011 (-0.013 to +0.031) | 0.84 | 38/8 | 80 | 27.63 ha | tropical | 2022-01-01 | 333.3 |
| nl-hansen-094 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.034 (-0.077 to -0.000) | 0.26 | 10/16 | 26 | 55.69 ha | tropical | 2018-01-01 | 253.3 |
| nl-hansen-095 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.007 (-0.011 to +0.036) | 0.31 | 41/20 | 80 | 42.38 ha | temperate | 2021-01-01 | 675.7 |
| nl-hansen-096 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.031 (-0.107 to +0.009) | 0.42 | 20/23 | 23 | 45.61 ha | tropical | 2019-01-01 | 386.0 |
| nl-hansen-097 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.006 (-0.020 to +0.016) | 0.98 | 52/38 | 80 | 43.49 ha | tropical | 2019-01-01 | 448.9 |
| nl-hansen-098 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.003 (-0.018 to +0.018) | 0.82 | 91/41 | 80 | 63.73 ha | tropical | 2022-01-01 | 804.9 |
| nl-hansen-099 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.004 (-0.027 to +0.015) | 0.20 | 24/21 | 80 | 57.15 ha | tropical | 2019-01-01 | 335.4 |
| nl-hansen-100 | clearing | NOT_REAL | NOT_REAL | VH | -0.025 (-0.077 to +0.006) | 0.74 | 68/43 | 80 | 22.44 ha | tropical | 2019-01-01 | 278.7 |
| nl-hansen-101 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.005 (-0.204 to +0.465) | 0.87 | 27/28 | 80 | 23.91 ha | temperate | 2019-01-01 | 318.8 |
| nl-hansen-102 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.001 (-0.019 to +0.006) | 0.92 | 32/22 | 80 | 34.85 ha | tropical | 2020-01-01 | 400.5 |
| nl-hansen-103 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.007 (-0.010 to +0.020) | 0.48 | 45/18 | 80 | 29.26 ha | tropical | 2022-01-01 | 432.3 |
| nl-hansen-104 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.017 (-0.025 to +0.017) | 0.07 | 53/24 | 80 | 30.04 ha | tropical | 2022-01-01 | 478.6 |
| nl-hansen-105 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.006 (-0.020 to +0.087) | 0.84 | 37/25 | 80 | 43.11 ha | boreal | 2021-01-01 | 561.6 |
| nl-hansen-106 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.002 (-0.059 to +0.031) | 0.80 | 21/31 | 80 | 26.69 ha | temperate | 2018-01-01 | 302.3 |
| nl-hansen-107 | clearing | NOT_REAL | NOT_REAL | NDVI | +0.006 (-0.025 to +0.021) | 0.95 | 44/17 | 80 | 30.9 ha | temperate | 2021-01-01 | 368.9 |
| nl-hansen-108 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.002 (-0.017 to +0.022) | 0.95 | 43/21 | 80 | 27.54 ha | tropical | 2019-01-01 | 365.1 |
| nl-hansen-109 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.007 (-0.015 to +0.025) | 0.20 | 24/22 | 80 | 50.73 ha | boreal | 2019-01-01 | 461.6 |
| nl-hansen-110 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.003 (-0.018 to +0.018) | 0.85 | 48/25 | 78 | 30.92 ha | tropical | 2021-01-01 | 649.9 |
| nl-hansen-111 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.009 (-0.015 to +0.038) | 0.07 | 28/29 | 80 | 43.82 ha | temperate | 2018-01-01 | 631.9 |
| nl-hansen-112 | clearing | NOT_REAL | CANT_TELL | NDVI | +0.001 (-0.047 to +0.036) | 0.90 | 25/9 | 36 | 65.89 ha | tropical | 2022-01-01 | 530.5 |
| nl-hansen-113 | clearing | NOT_REAL | CANT_TELL | NDVI | -0.012 (-0.022 to +0.011) | 0.95 | 58/23 | 80 | 42.38 ha | tropical | 2021-01-01 | 570.3 |
| nl-hansen-114 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.023 (-0.028 to +0.004) | 0.33 | 29/26 | 80 | 26.43 ha | boreal | 2022-01-01 | 693.3 |
| nl-hansen-115 | clearing | NOT_REAL | NOT_REAL | NDVI | -0.003 (-0.008 to +0.015) | 0.97 | 55/26 | 80 | 32.24 ha | tropical | 2023-01-01 | 422.1 |
| nl-mtbs-001 | burn | NOT_REAL | CANT_TELL | NBR | -0.035 (-0.072 to +0.036) | 0.47 | 31/4 | 42 | 232.93 ha | temperate | 2019-11-14 | 411.8 |
| nl-mtbs-002 | burn | NOT_REAL | NOT_REAL | NBR | +0.031 (-0.005 to +0.072) | 0.20 | 36/5 | 80 | 232.97 ha | temperate | 2019-11-14 | 370.1 |

*Sources: Hansen, M. C. et al. (2013) High-Resolution Global Maps of 21st-Century Forest Cover Change, Science 342, 850-853; data GFC-2023 v1.11. MTBS: Monitoring Trends in Burn Severity, USGS/USFS, burned area boundaries dataset.*
