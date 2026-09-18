# Red-team review of the change verdict

Adversarial review of the method in `src/app/` (prep → donors → augmented SCM →
conformal interval → placebos → `verdict.decide`). Written for readers who
will put the verdict in front of a committee and need to know where it can be
wrong. Every number below comes from `scripts/redteam.py` run on 2026-09-18
against the code on `main` at that date (conformal statistic = absolute mean
of post-event residuals, `estimator._stat`), or from
`tests/test_redteam.py`. Nothing in `src/` was changed for this review.

Data: cached real Sentinel-2 NDVI series, 400 donor cells each.
"Midlands" = `data/cache/5f0bbacbdf08fe51` (36 ha arable, 2020-2024, 79 clear
observations, the cloudiest case); "Austin" = `data/cache/52694d610e86d9fe`
(53 ha, 2017-2021, 213 clear observations); "Richmond" =
`data/cache/2fdf10a60e49000a`; "Sindh" = `data/cache/5fbfbf9d6b6f9eaa` (real
flood, 2022). "Null cells" are 15 (E6: 20) randomly chosen donor cells, each
treated as if it were the drawn area, with the remaining cells as its pool.
They are assumed untouched; nobody has checked each one, so a single REAL on
a null cell may be a genuine land-use change rather than a false alarm.
Intervals used an 11-point grid; the app uses 41, which only makes the
interval edges finer.

Reproduce: `python3 -m scripts.redteam` (about 75 s for all experiments) and
`python3 -m pytest -q tests/test_redteam.py`.

## Summary table

| # | Attack | Result | Verdict |
|---|---|---|---|
| E1 | Date selection: 5 candidate dates per null cell, best one reported | 0 REAL in 300 fits (2 sites × 2 change types × 15 cells × 5 dates), with dates spread over 80 days or over 400 days | **holds** |
| E3 | Common regional shock: every cell drops 0.10 after the date | 0 REAL in 30 fits; median gap 0.00; synthetic 0/45 REAL | **holds** |
| E3b | Local shock: the area *and* every cell within 3 km drop 0.10 | REAL 2/15 (Midlands), 8/15 (Austin); "controls shifted" never fires | **partial** |
| E4 | Seasonal misalignment: treated phenology 20 days out of phase | 0 REAL in 30 synthetic fits (13 NOT REAL, 2 CAN'T TELL); real Austin series resampled 20 days: 15/15 CAN'T TELL | **holds** (loses power, never over-claims) |
| E5 | Pre-trend: a linear decline that began 12 months before the claimed date | REAL 9/15 at -0.10/yr and 14/15 at -0.20/yr (Midlands); 6/15 and 9/15 (Austin). The in-time placebo flagged most of them and the verdict stayed REAL | **breaks** |
| E6 | Chance |point| ≥ 4 × pre_rmse on null cells (the pre-fit gate bypass) | 3 of 180 null fits (1.7%) reached it; in 2 of those the bypass was what let the fit past the gate; none became REAL. One null fit (Midlands cell 20, date at 75%) was REAL on its own merits | **partial** |
| E7 | One-sided NDVI haze despike vs. flood evidence in NDWI | Deletes 100% of the observations of a ≤20-day flood, 88% at 30 days, 41% at 45 days; on the real Sindh series the three peak-flood observations (10, 15, 23 Sep 2022) were deleted as "haze". End to end, a 25-day synthetic flood: REAL 5/15 with the despike, 14/15 without | **breaks** |
| E2 | Spillover buffer and duplicate donors | For areas ≥ ~200 ha ring cells can touch the drawn area (edge gap 0 m at 200, 350, 400 and 500 ha). `wide_candidates` at 1-12 km: 763 overlapping cell pairs (at the app's 20-150 km: 6) | **partial** |
| E8/E9 | Any path to REAL with < 20 donors or < 3 post bins | None through `decide`. But `evidence.status_of` calls a signal "supportive" with 19 donors, a failed pre-fit gate or shifted controls, so the page's evidence sentence can read "Optical and radar agree" under a CAN'T TELL. Three flagged in-time placebos still give REAL | **partial** |

## E1 — date selection

**Tried.** For each of 15 null cells per site, five event dates were tested
(offsets 0/20/40/60/80 days from the 65% point of the window, then a second
run at -200/-100/0/+100/+200 days) for change types "other" (two-sided) and
"clearing" (one-sided). The question is not the per-date false-alarm rate but
whether a user who tries five dates and keeps the best one gets a REAL.

**Numbers.** 0 REAL in 300 fits per run (both spreads). NOT REAL was reached
for 8-10 of 15 cells; the rest were CAN'T TELL. The loose pre-fit gate
(RMSE ≤ 1.5 × placebo median) failed in 20-35 of 75 fits per site, and the
4× bypass rescued none of them. In-time placebo false-alarm rate on the
true-null date: 0% (Midlands), 7% (Austin). Largest |point|/pre_rmse seen:
3.51.

**Verdict: holds.** The one-sided "clearing" rule costs nothing here because
the null gaps are tiny. Caveat: E6 (below) found one REAL on a null cell at a
date the E1 grid did not include, so "0/300" is a bound on the rate under
gaming, not proof of zero.

**Fix.** None required. Worth stating on the page that a verdict is for the
date entered, and logging every date a user tries for the same polygon so
repeated attempts are visible in the run history (`src/app/server.py`, run
creation; store `event_date` per polygon hash and show earlier attempts on
the verdict page).

## E3 — common regional shock

**Tried.** Every cell (treated and all 400 donors) drops by 0.10 NDVI after
the date; the verdict asks for a "clearing". Also a pure synthetic panel with
the same shock (`e10`, `tests/test_redteam.py`).

**Numbers.** Midlands: 7 NOT REAL, 8 CAN'T TELL, 0 REAL; median gap +0.004,
median placebo p 0.43. Austin: 8 NOT REAL, 7 CAN'T TELL, 0 REAL; median gap
-0.001. Synthetic: 15/15 NOT REAL with the shock alone, 15/15 REAL when a real
-0.10 is added on the treated cell on top of the shock (so the NOT REAL is
not blindness).

**Verdict: holds.** Convex weights sum to one, so a shift common to every
donor is reproduced exactly in the counterfactual. Note that the "controls
shifted" rule (`decide`, placebo_effect_median) did not fire in any of these
runs and cannot: placebo gaps are measured against controls that shifted
too. That rule only catches *partial* shocks (Rhodes, Sindh), which is what it
was written for.

**Fix.** None. Keep `tests/test_redteam.py::test_common_regional_shock_is_never_real`
as the regression guard.

## E3b — local (spatially correlated) shock

**Tried.** The treated cell and every donor within 3 km drop 0.10; cells
further out are untouched (a local hailstorm, a local irrigation failure).
Also a graded version (shock × exp(-d/3 km)).

**Numbers.** Local: REAL 2/15 (Midlands), 8/15 (Austin); median placebo p
0.07 and 0.03; placebo_effect_median 0.003, so "controls shifted" never fires.
Graded: REAL 1/15 on each site.

**Verdict: partial.** Whether this is a false alarm is a question of framing:
the area did change relative to its counterfactual, but so did every
neighbour, and a user claiming "my project caused this" is wrong. The
existing rule looks at the median placebo gap over up to 60 cells drawn
evenly across the whole 1-12 km ring, so a shock that only reaches 3 km
shifts a minority and is invisible to the median.

**Fix.** `src/app/run.py::_analyse` / `verdict.SignalResult`: alongside
`placebo_effect_median`, compute the median placebo gap over the nearest 20%
of placebo cells by `distance_m` (the cell distances are already in
`AreaData.cell_distance_m`) and pass it as `placebo_effect_median_near`.
`verdict.decide`: apply the same "controls shifted" test to it, with wording
"the nearest control cells shifted with the area". Alternatively show the
placebo gap against distance on the page and let the reader see the halo.

## E4 — seasonal misalignment

**Tried.** Synthetic seasonal series (amplitude 0.25, AR(1) noise 0.03, 45%
dropout) with the treated cell's phenology shifted 0/10/20/30 days relative
to every donor (donor phases ~N(0, 4 d)). Then the real Austin null cells,
each treated series resampled 20 days later than its own observations.

**Numbers.** Shift 0 and 10 d: 15/15 NOT REAL. 20 d: 13 NOT REAL, 2 CAN'T
TELL (pre_rmse 0.031 vs placebo median 0.023). 30 d: 15/15 CAN'T TELL (pre-fit
gate; pre_rmse 0.042). Real Austin, 20 d shift: 15/15 CAN'T TELL (0 pass the
pre-fit gate; unshifted 8/15 NOT REAL). No REAL anywhere.

**Verdict: holds.** Misalignment shows up as a bad pre-event fit, and the
gate turns it into CAN'T TELL. The cost is power, not truth: a genuine event
on a field whose crop calendar differs from its neighbours (a different crop
in the ring) will come back CAN'T TELL with the "does not track" reason.

**Fix.** None for safety. For power, a lag-tolerant donor match (allow each
donor a ±1 bin shift when ranking by pre-RMSE in `donors.select_donors`)
would recover some of these; log it as a future improvement, not a bug.

## E5 — pre-trend in the treated cell

**Tried.** A linear decline in the treated cell of -0.05, -0.10 or -0.20 NDVI
per year that starts 365 days *before* the claimed date and continues
through it. No step at the date. The honest answer is CAN'T TELL or, better,
"the change began before the date you gave".

**Numbers** (15 null cells per site, change type "clearing", in-time
placebos on):

| Site | Slope /yr | REAL | In-time placebo flagged | REAL despite a flag | Rescued by the 4× bypass | Median |point|/pre_rmse |
|---|---|---|---|---|---|---|
| Midlands | -0.05 | 3/15 | 1 | 1 | 1 | 2.9 |
| Midlands | -0.10 | 9/15 | 6 | 5 | 2 | 4.7 |
| Midlands | -0.20 | 14/15 | 10 | 10 | 9 | 5.6 |
| Austin | -0.05 | 6/15 | 4 | 1 | 0 | 2.7 |
| Austin | -0.10 | 6/15 | 12 | 4 | 1 | 3.5 |
| Austin | -0.20 | 9/15 | 15 | 9 | 10 | 4.6 |

Two mechanisms. (1) The in-time placebo does its job (flags 6-15 of 15 at
≥ -0.10/yr) but `decide` only appends a sentence and still returns REAL. (2)
The pre-trend inflates pre_rmse, the loose gate fails, and the 4× bypass
(`SignalResult.pre_fit_ok`) rescues 9-10 of 15 at -0.20/yr; the bypass was
designed for a sharp, huge step (Grünheide) and does not distinguish that
from a drift that makes both the pre-fit and the "effect" large.

What the two obvious fixes would do, recomputed on the same fits:

| Site | Slope /yr | REAL now | REAL if any flag → CAN'T TELL | ... and no 4× bypass when flagged |
|---|---|---|---|---|
| Midlands | -0.10 | 9 | 4 | 4 |
| Midlands | -0.20 | 14 | 4 | 0 |
| Austin | -0.10 | 6 | 2 | 2 |
| Austin | -0.20 | 9 | 0 | 0 |

The cost on true nulls is small: the in-time false-alarm rate on null cells
at the true-null date was 0% (Midlands) and 7% (Austin) in E1, and a genuine
step at the date cannot trip a placebo that uses pre-period data only. The
synthetic version (`tests/test_redteam.py::test_pretrend_*`) is
deterministic: seed 0 gives REAL with 2 of 3 placebos flagged and the 4×
bypass engaged.

**Verdict: breaks.** This is the most serious finding. A committee shown a
REAL for "clearing on 2023-03-01" would not know that the decline started
in 2022, and the tool already has the evidence in hand.

**Fix (three lines and one new gate).**
1. `src/app/verdict.py::decide`, the block at lines 146-149: when
   `any(r.time_placebo_flags)`, return CAN'T TELL with the reason "the same
   test finds a 'change' at a fake date before the event, so the shift began
   before the date given" instead of REAL. Do not just soften the wording.
2. `src/app/verdict.py::SignalResult.pre_fit_ok`: the 4× bypass must not
   apply when any in-time placebo is flagged
   (`return loose or (abs(self.point) >= 4.0 * self.pre_rmse and not any(self.time_placebo_flags))`).
3. `src/app/estimator.py::time_placebos`: the placebos are skipped below 24
   pre-event bins, so a run with 20-23 pre bins has no pre-trend check at all
   and can still be REAL. Lower the threshold to `MIN_PRE_BINS` (20) with
   `n=2` fake dates when 20 ≤ Tpre < 24, or make `decide` treat an empty
   flag list as "not checked" and refuse REAL.
4. Longer term: an explicit pre-trend statistic (slope of the last 12 pre
   bins of `f.effect` against the placebo distribution of the same slope) so
   the page can say "began N months earlier" rather than "can't tell".

## E6 — the 4× pre-fit bypass on null cells

**Tried.** |point|/pre_rmse on 60 null fits per site (20 cells × 3 event
dates at 55/65/75% of the window), change type "other". Plus 2000 i.i.d.
Gaussian draws (36 pre, 12 post) as the naive baseline.

**Numbers.** Ratio ≥ 4: Midlands 1/60 (max 4.66), Austin 2/60 (max 6.27),
Richmond 0/60 (max 2.22); i.i.d. Gaussian 0/2000. The loose gate failed in
12-15 of 60 fits per site; the bypass rescued 2 (Austin), neither became
REAL (placebo p and interval still stopped them). One null fit was REAL:
Midlands cell 20 at the 75% date, gap -0.17, interval -0.27 to -0.02, placebo
p 0.016, pre-fit fine (ratio 3.2). The same cell at the 65% date had ratio
4.66 and CAN'T TELL.

**Verdict: partial.** On real, autocorrelated series a ratio ≥ 4 happens by
chance in about 1-2% of fits, twenty times more often than white noise
suggests, so the bypass is not the "never on a null" rule it was assumed to
be. It did not produce a REAL here because the other rules held, but it is
the rule E5 shows being exploited by a pre-trend. Midlands cell 20 is either
a real land-use change in an "untouched" cell (arable land, so plausible) or
a 1-in-180 false alarm; the power table in DECISIONS.md (0/20) cannot tell
them apart either, and should say so.

**Fix.** `src/app/verdict.py::SignalResult.pre_fit_ok`: keep the bypass but
(a) require `not any(time_placebo_flags)` as in E5, and (b) raise the
multiplier or make it relative to the placebo distribution: bypass only if
|point| exceeds every placebo cell's |mean post gap| (`placebo_p_effect` ≤
1/(n+1)), which is already computed and is the quantity the bypass is
implicitly appealing to. Document in `docs/METHOD.md` §8 that the 4× rule
is reached by chance in ~1.7% of null fits on real data.

## E7 — the one-sided NDVI despike versus flood evidence

**Reasoning.** `s2.despike` flags an observation whose NDVI sits more than
max(0.12, 3 × MAD) below the median of its neighbours within ±40 days. It is
one-sided because cloud only lowers NDVI. Standing water also lowers NDVI,
to about -0.1 to -0.4, and does it for exactly the observations that carry
the flood signal. For a flood shorter than the ±40-day window, most
neighbours are dry, the neighbour median is the dry value, and every wet
observation is more than 0.12 below it. `fetch.fetch_area` (lines 243-258)
then drops the whole observation, NDWI and NBR included, with a "haze"
receipt, and applies the same deletion to every donor cell. So the flood
verdict, which is decided on NDWI, is computed on a series from which the
flood has been surgically removed. The despike does not know NDWI exists.

**Numbers.** Synthetic (5-day cadence, 50% dropout, water NDVI -0.1): share
of flooded observations deleted as haze = 100% for 10- and 20-day floods,
88% at 30 days, 41% at 45, 13% at 60, 8% at 90. End to end on synthetic NDWI
(60 donors, 25-day flood, 1-month post window): REAL 5/15 with the despike,
14/15 without. Real Sindh cache (event 2022-08-25): the three treated
observations deleted as haze after the event are 10, 15 and 23 September
2022 with NDVI -0.38, -0.37, -0.33, the peak of the flood (kept neighbours
show NDWI rising from -0.16 on 26 Aug to +0.46 on 28 Sep). Sindh survived as
a series only because the 2022 flood lasted months. The same one-sidedness
also delays clearing evidence (E2c): after a permanent -0.2 to -0.5 step,
0.16-0.39 of the first eight post-event observations are deleted, in 13-32%
of runs at least one.

**Verdict: breaks** for floods under about a month, which is most river and
flash floods; **partial** for clearings (a delayed onset, not a lost verdict).

**Fix.** `src/app/s2.py::despike`: add an `ndwi` argument and do not flag an
observation whose NDWI is above its own neighbour median by more than the
same threshold (cloud raises NDWI only modestly, from about -0.5 to about 0;
open water pushes it above +0.2), or equivalently do not flag when NDVI is
below 0 *and* NDWI is above 0. `src/app/fetch.py::fetch_area` lines 244 and
256, and `_despike_donors`, `_fetch_wide` line 315: pass `values["NDWI"]`
alongside NDVI. Both index arrays are already in the cache
(`s2.npz` keys: NDVI, NDWI, NBR, clear_frac), so cached sites can be
re-cleaned without a refetch. Until then the flood path should say on the
page that short floods are likely to be removed by cloud screening.

## E2 — spillover buffer and duplicate donors

**Tried.** `geometry.donor_grid` on square areas of 1-500 ha and a 50 ha
strip (1:25); `geometry.wide_candidates` at 1-12 km and 20-150 km.

**Numbers.** The 1 km inner buffer is measured from the *cell centroid* to
the area polygon. Edge-to-edge gap of the nearest kept cell: 949 m (1-10 ha),
707 m (50 ha), 1000 m (100 ha), **0 m** at 200, 350, 400 and 500 ha (2-3
cells sharing an edge or a corner with the area; at 401-450 ha float rounding
happened to make `intersects` true and they were dropped). Wide candidates
at 1-12 km: 763 overlapping pairs out of 600 cells, i.e. the same land
appears as several donors; at the app's 20-150 km, 6 pairs.

**Verdict: partial.** For the app's typical 10-100 ha areas the buffer is
0.7-1 km edge to edge, close to what is documented. Above ~200 ha adjacent
land can be a control, and adjacent land is where spillover (smoke, silt,
access roads, drainage) lands. That biases the gap toward zero, so it
weakens detection, not the false-alarm rate. The `wide_candidates` overlap
only matters if someone lowers `inner_m`; at the defaults it is negligible.

**Fix.** `src/app/geometry.py::donor_grid` line 109: measure
`d = cell.distance(area.utm)` (edge to edge) instead of
`cell.centroid.distance(area.utm)`, and keep `distances_m` as the edge gap;
this removes 2-3 cells at 200-500 ha and none below. Same one-line change in
`wide_candidates` is unnecessary (inner_m there is 20 km). For duplicates,
snap `wide_candidates` to a grid of `side` metres before sampling.

## E8/E9 — routes to REAL with too few donors or post bins

**Tried.** Every gate in `verdict.decide` one unit either side of its
threshold; `verdict.combine` with a radar lead; `evidence.status_of` and
`assess`; `run.py`'s lead-signal switch; NaN donors through `fit_ascm` and
`prep.binned_groups`; fewer than 20 columns surviving coverage.

**Numbers.** `decide`: 19 donors, 2 post bins, 19 pre bins, NaN point, NaN
interval: all CAN'T TELL; 20 donors and 3 post bins: REAL. `combine`:
optical lead with 2 post bins: CAN'T TELL. A radar lead that is REAL is
returned as REAL when the optical primary signal has 2 post bins or 19
donors (by design: radar leads when optical cannot, and the radar signal
itself passed the gates; the page names VH as the lead signal). A donor
column with one NaN makes `solve_weights` fall back to equal weights and
`pre_rmse` NaN → CAN'T TELL with the reason text "pre-event error nan vs
typical nan". `binned_groups` drops such columns at the default 70%
coverage. `evidence.status_of` returns "supportive" with 19 donors, with
pre_rmse 0.2 vs placebo median 0.02, and with placebo_effect_median -0.3
(controls shifted); `assess` then writes "Optical and radar agree: greenness
(NDVI) fell by 0.30 …" for a run whose verdict is CAN'T TELL. Three flagged
in-time placebos: still REAL.

**Verdict: partial.** No path yields a REAL *status* below the gates. But the
evidence sentence is shown next to the verdict and applies weaker rules than
the verdict does, so a CAN'T TELL page can carry a sentence that reads as a
confirmation. That is the kind of thing a reader quotes.

**Fix.** `src/app/evidence.py::status_of`: return "unavailable" when
`r.n_donors < MIN_DONORS or r.n_pre < MIN_PRE_BINS or not r.pre_fit_ok`, and
"neutral" when the controls-shifted test fires (import `_controls_shifted`
from run.py or duplicate the two-line test). `verdict.decide` lines
136-138: use `not (r.lo < r.hi)` so a NaN interval is named. Cosmetic:
`decide` line 131, guard the "nan vs typical nan" text.

## The three fixes that matter, ranked

1. **Pre-trends are confirmed as events (E5).** `src/app/verdict.py::decide`:
   a flagged in-time placebo must return CAN'T TELL, not a softer REAL; and
   `SignalResult.pre_fit_ok`: the 4× bypass must not apply when a placebo is
   flagged. Together these cut the pre-trend REAL rate at -0.20/yr from
   14/15 and 9/15 to 0/15 and 0/15 on the two real sites, at a measured cost
   of 0-7% extra CAN'T TELL on nulls. Also lower the 24-bin skip in
   `estimator.time_placebos` to `MIN_PRE_BINS` so every REAL has been
   checked.
2. **Short floods are deleted as haze (E7).** `src/app/s2.py::despike` takes
   NDWI and does not flag water; `src/app/fetch.py` passes it in the three
   places the despike runs. Without this the flood path works only for
   floods that outlast the ±40-day window, and the Sindh showcase lost its
   three peak observations.
3. **The evidence sentence uses weaker rules than the verdict (E9).**
   `src/app/evidence.py::status_of` must apply the donor, pre-bin, pre-fit and
   controls-shifted gates before calling a signal "supportive", or the page
   says "optical and radar agree" under a CAN'T TELL.

Then, in order: edge-to-edge buffer in `geometry.donor_grid` (E2); a
near-cell "controls shifted" test (E3b); document the 1.7% chance rate of
the 4× bypass in METHOD.md (E6); state on the page that the verdict is for
the date entered and record repeated dates per polygon (E1).

## What was not tested

Radar signals (VV/VH) under the same attacks; wide mode end to end (no
cached wide-mode run had donor groups); adversarial polygons drawn to
straddle a field boundary; the pixel-level test in `pixels.py`; the
break-date search (`breakdate.py`, not wired in). Each of E1-E6 used 15-20
cells, so rates below about 5% are not resolved.
