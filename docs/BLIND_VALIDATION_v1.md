> **Superseded.** This is blind validation v1 (method at `fc65e7d`, 40 of 247
> items, before the symmetric-placebo fix and with a runner bug that marked
> unrun items as timeouts). The current result is `docs/BLIND_VALIDATION.md`
> (v3, method v2, all 247 items, same sample and seed). An unfinished v2 run
> (100 items, method at `4c98145`) is kept in `showcase/blind_v2/` for the record.

# Blind validation of the Otherwise verdict

*Generated 2026-09-19T06:43:55+00:00 by `scripts/blind_validation.py` at commit `fc65e7d`.
This file is rewritten after every finished item; the numbers below cover
40 of 247 sampled items (207 still pending).*

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
python -m scripts.blind_validation --sample showcase/blind/sample.json --parallel 3 --out showcase/blind/
```

The outstanding items are run in a seeded random order (`--shuffle-seed`,
recorded as `run_order_seed` in `summary.json`), so a run stopped part-way
leaves a random subsample of the draw rather than, say, every event and no
control. **The verdicts are tied to the commit above**: another track was
changing the fetch and estimator path in parallel, so re-running at a later
commit can legitimately give different numbers.

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

## Results so far (40 of 247 items; median run 487.6 s)

Tool alone, over finished runs only, with 95% Wilson intervals:

| Rate | Value |
|---|---|
| Detection (REAL on an event) | 18 of 34 = 52.9% (95% CI 36.7-68.5%) |
| Miss (NOT REAL on an event) | 1 of 34 = 2.9% (95% CI 0.5-14.9%) |
| Can't tell on an event | 15 of 34 = 44.1% (95% CI 28.9-60.5%) |
| False alarm (REAL on a control) | not measured (no finished runs of this kind) |
| Correct on a control | not measured (no finished runs of this kind) |
| Can't tell on a control | not measured (no finished runs of this kind) |

6 of the items attempted so far produced no verdict (raised or timed
out); they are excluded from every rate above and listed below. A rate shown as
"not measured" has no finished runs behind it and no number is invented for it.

So far 40 event items and 0 control items have been
attempted, of which 34 and 0 finished. No control (no-change) item has finished yet, so the false-alarm rate below is not measured. Until it is, the detection rate on its own says nothing about how often the tool cries wolf, and should not be quoted alone.

**By change type**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| clearing | 34 | 18 (53%) | 1 (3%) | 15 (44%) | 0 | 0 (-) | 0 (-) | 0 (-) |

**By source and date precision**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| hansen (source) | 34 | 18 (53%) | 1 (3%) | 15 (44%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| year (date precision) | 34 | 18 (53%) | 1 (3%) | 15 (44%) | 0 | 0 (-) | 0 (-) | 0 (-) |

**By polygon size**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| <50 ha | 26 | 13 (50%) | 0 (0%) | 13 (50%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| 50-150 ha | 7 | 5 (71%) | 1 (14%) | 1 (14%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| >150 ha | 1 | 0 (0%) | 0 (0%) | 1 (100%) | 0 | 0 (-) | 0 (-) | 0 (-) |

**By climate**

| Group | Events (done) | Detected (REAL) | Missed (NOT REAL) | Can't tell | Nulls (done) | False alarms (REAL) | Correct (NOT REAL) | Can't tell |
|---|---|---|---|---|---|---|---|---|
| tropical | 7 | 2 (29%) | 1 (14%) | 4 (57%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| temperate | 13 | 7 (54%) | 0 (0%) | 6 (46%) | 0 | 0 (-) | 0 (-) | 0 (-) |
| boreal | 14 | 9 (64%) | 0 (0%) | 5 (36%) | 0 | 0 (-) | 0 (-) | 0 (-) |


**Errors**

| Item | Error |
|---|---|
| ev-hansen-001 | timeout after 1500 s |
| ev-hansen-002 | timeout after 1500 s |
| ev-hansen-003 | timeout after 1500 s |
| ev-hansen-032 | timeout after 1500 s |
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
| ev-hansen-009 | clearing | REAL | CANT_TELL | NDVI | -0.143 (-0.251 to +0.276) | 0.08 | 43/18 | 80 | 34.54 ha | temperate | 2022-01-01 | 466.3 |
| ev-hansen-010 | clearing | REAL | CANT_TELL | NDVI | -0.057 (-0.104 to +0.038) | 0.13 | 28/21 | 30 | 45.5 ha | tropical | 2019-01-01 | 516.3 |
| ev-hansen-011 | clearing | REAL | REAL | NDVI | -0.305 (-0.346 to -0.014) | 0.02 | 45/42 | 80 | 59.81 ha | temperate | 2019-01-01 | 472.0 |
| ev-hansen-012 | clearing | REAL | CANT_TELL | NDVI | -0.234 (-0.428 to +0.227) | 0.02 | 66/39 | 80 | 30.24 ha | temperate | 2020-01-01 | 857.3 |
| ev-hansen-013 | clearing | REAL | CANT_TELL | NDVI | -0.151 (-0.273 to -0.133) | 0.25 | 31/13 | 80 | 44.0 ha | boreal | 2022-01-01 | 323.7 |
| ev-hansen-014 | clearing | REAL | REAL | NDVI | -0.214 (-0.261 to -0.047) | 0.03 | 42/27 | 80 | 47.96 ha | temperate | 2019-01-01 | 457.6 |
| ev-hansen-015 | clearing | REAL | CANT_TELL | NDVI | -0.056 (-0.147 to +0.036) | 0.03 | 65/30 | 80 | 24.6 ha | temperate | 2022-01-01 | 579.1 |
| ev-hansen-016 | clearing | REAL | REAL | NDVI | -0.274 (-0.389 to -0.006) | 0.03 | 68/33 | 80 | 75.23 ha | temperate | 2022-01-01 | 641.8 |
| ev-hansen-017 | clearing | REAL | CANT_TELL | NDVI | -0.282 (-0.300 to -0.049) | 0.02 | 15/23 | 80 | 36.3 ha | temperate | 2018-01-01 | 269.4 |
| ev-hansen-018 | clearing | REAL | REAL | NDVI | -0.202 (-0.213 to -0.086) | 0.02 | 29/17 | 80 | 32.67 ha | boreal | 2020-01-01 | 397.5 |
| ev-hansen-019 | clearing | REAL | REAL | NDVI | -0.278 (-0.289 to -0.130) | 0.02 | 65/35 | 80 | 31.38 ha | temperate | 2022-01-01 | 622.2 |
| ev-hansen-020 | clearing | REAL | CANT_TELL | NDVI | -0.206 (-0.278 to +0.009) | 0.23 | 19/16 | 80 | 31.49 ha | boreal | 2019-01-01 | 347.9 |
| ev-hansen-021 | clearing | REAL | CANT_TELL | NDVI | -0.136 (-0.179 to +0.099) | 0.02 | 22/16 | 80 | 36.02 ha | boreal | 2020-01-01 | 398.4 |
| ev-hansen-022 | clearing | REAL | CANT_TELL | NDVI | -0.080 (-0.004 to +0.037) | 0.57 | 53/22 | 80 | 29.7 ha | temperate | 2020-01-01 | 507.4 |
| ev-hansen-023 | clearing | REAL | CANT_TELL | NDVI | -0.052 (-0.080 to +0.006) | 0.38 | 38/13 | 80 | 42.2 ha | tropical | 2021-01-01 | 487.6 |
| ev-hansen-024 | clearing | REAL | REAL | NDVI | -0.183 (-0.165 to -0.103) | 0.02 | 38/21 | 80 | 50.37 ha | boreal | 2023-01-01 | 333.0 |
| ev-hansen-025 | clearing | REAL | CANT_TELL | NDVI | -0.102 (-0.129 to -0.030) | 0.02 | 49/22 | 80 | 84.1 ha | tropical | 2020-01-01 | 457.4 |
| ev-hansen-026 | clearing | REAL | REAL | NDVI | -0.074 (-0.109 to -0.013) | 0.03 | 50/36 | 80 | 33.81 ha | temperate | 2019-01-01 | 1024.7 |
| ev-hansen-027 | clearing | REAL | REAL | NDVI | -0.401 (-0.462 to -0.195) | 0.02 | 30/8 | 80 | 44.86 ha | boreal | 2022-01-01 | 340.4 |
| ev-hansen-028 | clearing | REAL | CANT_TELL | NDVI | -0.107 (-0.154 to -0.055) | 0.03 | 49/31 | 80 | 44.22 ha | temperate | 2021-01-01 | 762.4 |
| ev-hansen-029 | clearing | REAL | NOT_REAL | NDVI | -0.007 (-0.009 to +0.017) | 0.31 | 66/25 | 80 | 112.85 ha | tropical | 2021-01-01 | 1008.1 |
| ev-hansen-030 | clearing | REAL | CANT_TELL | NDVI | -0.276 (-0.309 to +0.064) | 0.02 | 28/19 | 80 | 42.68 ha | boreal | 2020-01-01 | 443.3 |
| ev-hansen-031 | clearing | REAL | REAL | NDVI | -0.297 (-0.341 to -0.112) | 0.02 | 32/23 | 80 | 22.66 ha | boreal | 2023-01-01 | 298.4 |
| ev-hansen-032 | clearing | REAL | error | - | - | - | -/- | - | 63.33 ha | temperate | 2020-01-01 | 1501.0 |
| ev-hansen-033 | clearing | REAL | REAL | NDVI | -0.199 (-0.189 to -0.139) | 0.08 | 32/17 | 80 | 27.77 ha | boreal | 2023-01-01 | 257.9 |
| ev-hansen-034 | clearing | REAL | REAL | NDVI | -0.331 (-0.360 to -0.193) | 0.02 | 35/26 | 80 | 39.74 ha | temperate | 2020-01-01 | 420.5 |
| ev-hansen-035 | clearing | REAL | REAL | NDVI | -0.217 (-0.225 to -0.127) | 0.02 | 24/12 | 80 | 73.84 ha | boreal | 2021-01-01 | 423.5 |
| ev-hansen-036 | clearing | REAL | REAL | NDVI | -0.182 (-0.237 to -0.017) | 0.02 | 31/12 | 80 | 34.95 ha | boreal | 2021-01-01 | 354.5 |
| ev-hansen-037 | clearing | REAL | REAL | NDVI | -0.234 (-0.373 to -0.131) | 0.03 | 44/39 | 80 | 45.1 ha | temperate | 2019-01-01 | 440.8 |
| ev-hansen-038 | clearing | REAL | CANT_TELL | NDVI | -0.231 (-0.244 to +0.048) | 0.03 | 28/14 | 80 | 35.56 ha | boreal | 2022-01-01 | 427.5 |
| ev-hansen-039 | clearing | REAL | error | - | - | - | -/- | - | 42.67 ha | temperate | 2023-01-01 | 1501.1 |
| ev-hansen-040 | clearing | REAL | error | - | - | - | -/- | - | 56.85 ha | temperate | 2022-01-01 | 1501.1 |

*Sources: Hansen, M. C. et al. (2013) High-Resolution Global Maps of 21st-Century Forest Cover Change, Science 342, 850-853; data GFC-2023 v1.11. MTBS: Monitoring Trends in Burn Severity, USGS/USFS, burned area boundaries dataset.*
