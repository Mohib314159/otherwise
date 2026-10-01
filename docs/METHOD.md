# Method

> This document is the **land-change** method. The second signal family, ground-level NO₂ / ULEZ policy evaluation, is documented separately in [`AIR_METHOD.md`](AIR_METHOD.md).

What Otherwise computes, for readers checking the reasoning rather than
taking the verdict on trust. Every number below is a constant in the source
(file cited in parentheses) or a result recorded in `DECISIONS.md`; nothing
is invented for this write-up.

## 1. The question

A user claims an event happened in a drawn area on a given date. The
observed series will usually show *some* change afterwards almost anywhere,
because land is never static — phenology, weather and regional trends move
every pixel, event or not. The question is not "did the series change?" but
"did it change more than it would have anyway?" That "anyway" is a
counterfactual: the trajectory the area would have followed with no event,
built from similar nearby places that were not treated. The effect is the
gap between the observed post-event series and that counterfactual, and the
verdict says whether the gap is large and reliable enough to call the event
real.

## 2. Data and cleaning

Optical data is Sentinel-2 L2A. Per scene, the 20 m SCL (Scene
Classification Layer) is read first; 10 m bands (B03, B04, B08, B12) are
read only if the area's clear fraction is ≥80% (`CLEAR_MIN`, `src/app/s2.py`).
"Clear" keeps SCL classes 4 (vegetation), 5 (bare), 6 (water); everything
else, including 7 (unclassified), is unusable, since a missed thin cloud
lowers NDVI exactly as a clearing would (`SCL_CLEAR`). NDVI, NDWI, NBR are
averaged over clear pixels per zone. Reflectance correction removes the
Baseline-04.00 offset by comparing each scene's own `s2:processing_baseline`
against 04.00 (`needs_offset`, `DN_OFFSET`), not by date — Planetary
Computer reprocesses old scenes under newer baselines. A local despike pass
catches haze SCL missed: an NDVI value more than max(0.12, 3×MAD) below its
neighbours' median within 40 days is dropped (`despike`), one-sided since
cloud only pulls NDVI down while a real clearing keeps its neighbours low
too.

Radar is Sentinel-1 RTC (terrain-corrected gamma0), VV and VH. Only the
relative orbit with the most passes is kept — mixing orbits mixes incidence
angles into a saw-tooth (`select_orbit`, `src/app/s1.py`) — and means are
taken in linear power then converted to dB (`to_db`), never averaged in dB.

Every dropped observation — cloud, haze, duplicate, wrong orbit, edge,
read-error — is a receipt with a reason (`Receipt`) shown on the verdict
page.

## 3. Units and binning

The area and every donor cell share the treated footprint's shape
(side = sqrt(area), `src/app/geometry.py`), for comparable noise. Donor
cells sit in a ring 1–12 km out (`inner_m = 1000.0`, `outer_m = 12000.0`):
the inner gap is a spillover buffer, the outer ring keeps climate and
phenology shared. The inner gap is measured edge to edge (no part of a
donor cell comes within `inner_m` of the drawn polygon); the outer limit
is measured from the cell's centre. Wide mode applies the same edge-to-edge
rule to its per-site inner radius.

Series are binned into 10-day windows anchored on the event date
(`bin_days = 10`, `src/app/prep.py`), median per bin. The treated column is
never interpolated — a bin without a real treated observation is dropped, so
every plotted treated point is an actual observation (`complete`). Donor
gaps are interpolated (donors are only ever averaged), and a donor column is
dropped below 70% coverage (`min_cov = 0.70`); the same threshold also gates
which donor cells reach selection (`src/app/donors.py`).

## 4. Control selection

`src/app/donors.py` filters, then ranks. Coverage: donor cells need ≥70%
observed dates. Land cover: same dominant ESA WorldCover class as the area
(2020 map before 2022, 2021 map after, always pre-event). Terrain: within
150 m of the area's Copernicus DEM elevation (`elev_tol_m = 150.0`). Land
cover and elevation are each relaxed, in order, if they would leave fewer
than 30 cells (`min_pool = 30`), and the relaxation is recorded. Survivors
are ranked by pre-event RMSE to the treated series and the best 80 kept
(`k = 80`) — similarity, not land cover or terrain, is the final cut.

## 5. Estimator

The counterfactual is an augmented synthetic control (Ben-Michael, Feller &
Rothstein 2021). Convex weights w (w ≥ 0, sum(w) = 1) minimise the squared
pre-event fit error between the treated series and a weighted donor average,
solved as non-negative least squares with an extra, heavily-weighted row
enforcing sum(w) = 1 — the same loss as the existing SLSQP solver, ~1000x
faster (`solve_weights`, `src/app/estimator.py`). A ridge correction is
added, regressing the pre-event residual the convex fit missed against the
centred donor pre-event series and projecting that forward (`_ridge_eta`,
`fit_ascm`). Its penalty is chosen by holding out the last 25% of the
pre-period, fitting on the first 75% for each candidate in
{0, 0.03, 0.1, 0.3, 1.0, 3.0} and keeping the lowest holdout error
(`_choose_lambda`); 0 recovers plain convex SCM. Effect at any period is
observed minus counterfactual; the point estimate is the mean over
post-event bins.

## 6. Uncertainty

The interval comes from conformal inference (Chernozhukov, Wüthrich & Zhu
2021): no distributional assumption, valid with one treated unit. To test
"mean post-event effect = θ₀": subtract θ₀ from the treated post-event
values, refit treating the whole series as pre-period, and compare the
post-event residual size with the same statistic on every cyclic block shift
of the residual sequence (`conformal_p`); the p-value is the share of
shifts at least as large as observed. Inverting this over a grid of θ₀ gives
a 90% interval (`ALPHA = 0.10`, `conformal_interval`). This interval is for
a *constant* post-event shift. When the true effect varies within the
window — a clearing that starts to regrow — the reported mean gap can fall
outside its own interval, because the interval tests a step-shift, not the
time-varying path. Both numbers are always shown, neither adjusted to look
tidier.

## 7. Placebo checks

Two families run alongside every verdict, on the same estimator as the real
fit (`space_placebo`, `time_placebos`). In-space: each donor is treated as
if it were the area, fitted on the rest. The p-value is the rank of the
treated unit's post/pre RMSPE ratio among all placebo ratios, Abadie's
conservative "+1" convention — p = (#{ratio ≥ treated ratio} + 1) / (n + 1),
never exactly zero. A second figure, the effect-rank share, applies the same
+1 convention to the signed effect size: how many untouched cells shifted at
least this far the same way. In-time: the event date is faked at three
points inside the pre-period only (skipped under 24 pre-event bins), each
refit with its own 90% interval; a fake date whose interval excludes zero is
flagged as a false alarm and lowers confidence in the real verdict.

## 8. Verdict rules

All thresholds live in `src/app/verdict.py`, fixed for every run. CAN'T
TELL, with the reason named, unless there are ≥20 usable donors
(`MIN_DONORS`), ≥20 pre-event bins (`MIN_PRE_BINS`), ≥3 post-event bins
(`MIN_POST_BINS`), and the pre-fit passes: RMSE at most 1.5× the placebo
median (or a signal floor, `PRE_RMSE_FLOOR`) — *unless* the effect is ≥4× the
pre-event RMSE, which skips the gate because the interval and placebo ratio
already scale with that error. CAN'T TELL also fires if the donors
themselves moved by at least the minimum effect in the same direction at the
event date (the "controls shifted" rule): a sign the event outgrew the
12 km ring. Given all that, REAL needs the 90% interval to exclude zero in
the claimed direction, a point effect ≥0.05 index units for optical or
1.0 dB for radar (`MIN_EFFECT`), and in-space placebo p ≤0.10
(`PLACEBO_P_MAX`). NOT REAL needs the interval to rule out a change of that
size. Everything else is CAN'T TELL. `combine` additionally stops a radar
NOT REAL from overriding an optical signal showing ≥2× the optical minimum
effect on fewer than 3 post-event bins — too few to confirm alone, too large
to dismiss.

None of this loosens case-by-case to reach REAL: the constants are fixed at
import time. The one exception with real judgement in it — the 4× pre-fit
rule — was added once, as a logged code change (`DECISIONS.md`, milestone 3),
after it blocked a correctly-drawn Grünheide polygon whose interval and
placebo p already passed on their own; it now applies to every future run,
not just retroactively to that site. Donor-filter relaxations only widen the
pool when a stricter filter would leave too few cells, making REAL harder to
reach, never easier.

## 9. Known limits

- **Events larger than the control ring.** Rhodes 2023 burnt ~17,600 ha
  (`SITES.md`), far beyond the 12 km ring, so the ring's own controls burnt
  too and "controls shifted" fired: the ring run is CAN'T TELL. Wide mode
  exists for exactly this case and re-ran it against 42 cells 20-150 km away,
  which does reach REAL (NBR -0.47, -0.49 to -0.31, placebo p 0.023). Two
  caveats a reader should carry: those control radii were set per site by hand
  in `scripts/run_sites.py`, not chosen by the tool, and a user drawing an area
  cannot reach that configuration. Sindh's 2022 flood hits the same limit. Its
  wide re-run (150–400 km, set by hand), last re-run on 30 Sep 2026 under method
  v2: surface water rose (NDWI +0.61, 90% interval +0.22 to +0.83), but only 12
  control cells were usable against the 20 required, so it stays CAN'T TELL.
- **Thin optical archive before 2018.** Saddleworth Moor (2018-06-24): NBR
  had only two usable post-event bins, the UK archive being thin that early;
  VH was the only signal with enough bins (`DECISIONS.md`, milestone 4;
  `SITES.md`).
- **0.05 is usually below power in cloudy sites.** The power table (section
  10) detects an injected -0.05 NDVI effect in 3/20 cases on the Midlands test
  area; Richmond Park and Jaú NP, both null, came back CAN'T TELL
  rather than NOT REAL for the same reason (`DECISIONS.md`, milestone 4).
- **The interval is for a constant shift, not a time-varying one.** When the
  effect is not a flat step across the window, the reported mean gap can sit
  outside its own interval. An earlier Grünheide run did (-0.61 against -0.57 to
  -0.45, `DECISIONS.md`, milestone 3); the current run's interval contains it.

### Two failures our own red team graded as "breaks", now fixed

`docs/REDTEAM.md` is an adversarial self-review with numbers. Two of its
attacks defeated the method as it stood. Both are fixed in "method v2"
(`DECISIONS.md`, 30 Sep 2026), and every published showcase run was re-run
under it on 30 Sep–1 Oct 2026:

- **A decline that began before the claimed date was called REAL** (REDTEAM
  E5). The in-time placebo detected most such pre-trends, but the verdict
  appended a caveat and returned REAL anyway. Now a flagged in-time placebo
  forces CAN'T TELL and switches off the 4x pre-fit bypass. The in-time
  placebo itself also no longer leaks: each fake date re-selects donors and
  re-tunes the ridge penalty on data before that date only.
- **Short floods were deleted by the haze filter** (REDTEAM E7). The NDVI
  despike now keeps an NDVI dip when the same observation's NDWI rises above
  its neighbours by the same margin and is above 0 (water, not haze).

The red-team tests for both now pass (`tests/test_redteam.py`). The numbers in
`docs/REDTEAM.md` were measured before the fixes and have not been re-run, so
they describe the old method.

Also fixed in v2: the spillover buffer is measured edge to edge (E2), so no
kept control can sit closer than 1 km to the area; and the evidence sentence
can no longer read "optical and radar agree" under a CAN'T TELL (E9). Still
open: the 4x pre-fit bypass is reachable on null cells (E6). A REAL that passes
the fit check only through it now says so on its page; in the current showcase
that is Grünheide and Rhodes.

### Limits of the live (in-browser) path specifically

A run you trigger by drawing an area uses the memory-bounded "live" profile:
the drawn area is read at 10 m but its controls are read at 40 m, from a
separate catalogue search with its own dates. Full mode — used for the
showcase, the track record and the validation runs — reads the area and all of
its controls from the same window at 10 m, which cancels most atmosphere,
sun-angle and view-geometry effects between them. The live path gives that up,
and what it costs has not yet been measured across sites. Live verdicts should
be read as a quick check, not as equivalent to the published runs.

## 10. Validation to date

**Detection power** (`scripts/power.py`, re-run 1 Oct 2026 under method v2, counting the product's own verdict, under both placebo procedures):

<!-- BEGIN power table (generated by scripts/method_tables.py from showcase/power.json) -->

Real, untouched cells around the Midlands test area (bbox [-1.29, 52.905, -1.28, 52.912], 2020-01-01 to 2024-12-31, 400 cells; 95 clear optical and 211 radar observations). 20 randomly chosen real control cells treated as the area; step effect injected after a fake event at 70% of the window; each unit judged by the product's own verdict rules (verdict.combine via run.signal_result: donor, pre-bin, pre-fit, controls-shifted, interval, minimum-effect, in-space and leak-free in-time placebo checks; method v2). 'old_gate_detected' gives the earlier three-condition gate on the same units for comparison. Both procedures run on the same cache, so the columns differ only in the placebo test. Rebuilt Midlands test area. The cache behind the earlier table (5f0bbacbdf08fe51) is gone and its geometry was not recorded, so this is not the identical area; compare procedures within this file, not against the old table.

| Signal | Injected effect | REAL, symmetric placebo (current) | REAL, asymmetric placebo (old) |
|---|---|---|---|
| NDVI | +0.00 | 0 / 20 (false alarms) | 0 / 20 (false alarms) |
| NDVI | -0.05 | 3 / 20 | 4 / 20 |
| NDVI | -0.10 | 10 / 20 | 13 / 20 |
| NDVI | -0.20 | 15 / 20 | 15 / 20 |
| VH | +0.00 dB | 0 / 20 (false alarms) | 0 / 20 (false alarms) |
| VH | -0.50 dB | 0 / 20 | 0 / 20 |
| VH | -1.00 dB | 6 / 20 | 6 / 20 |
| VH | -2.00 dB | 18 / 20 | 18 / 20 |

<!-- END power table -->

The earlier table (18 Sep 2026, old Midlands cache, asymmetric placebo only) is in `DECISIONS.md`
for the record; it is superseded by the table above.

**Known-answer sites** (candidate, unconfirmed by Mohib as of this writing):

<!-- BEGIN known-answer table (generated by scripts/method_tables.py) -->

| Site | Type | Expected | Verdict | Mode | Lead signal | Effect (90% interval) | Placebo p |
|---|---|---|---|---|---|---|---|
| Grünheide, Germany | clearing | REAL | **REAL** | ring | NDVI | -0.60 (-0.71 to -0.50) | 0.016 |
| Rhodes, Greece | burn | REAL | **REAL** | wide | NBR | -0.47 (-0.49 to -0.31) | 0.023 |
| Cape Town | burn | REAL | **REAL** | ring | NBR | -0.46 (-0.60 to -0.25) | 0.016 |
| Austin, Texas | construction | REAL | **REAL** | ring | NDVI | -0.19 (-0.22 to -0.11) | 0.016 |
| Saddleworth Moor, England | burn | REAL | **REAL** | ring | VH | -1.06 dB (-1.34 dB to -0.04 dB) | 0.033 |
| Lützerath, Germany | clearing | REAL | CAN'T TELL | ring | NDVI | -0.10 (-0.13 to -0.05) | 0.721 |
| Hasankeyf, Turkey | flood | REAL | CAN'T TELL | ring | NDWI | +0.47 (-0.56 to +1.49) | 0.082 |
| Sindh, Pakistan | flood | REAL | CAN'T TELL | wide | NDWI | +0.61 (+0.22 to +0.83) | 0.077 |
| Richmond Park, London | clearing | NOT_REAL | CAN'T TELL | ring | NDVI | -0.03 (-0.07 to +0.03) | 0.836 |
| Jaú National Park, Brazil | clearing | NOT_REAL | CAN'T TELL | ring | NDVI | -0.01 (-0.02 to +0.03) | 0.672 |

**10 sites counted: 5 correct, 0 missed, 0 false alarms, 5 can't tell.** The can't-tell count is the honest headline here, and a clean "0 misses, 0 false alarms" should be read alongside it, because a failure to detect lands in can't-tell rather than in misses. Sites remain candidates until confirmed. Generated from the committed runs in `showcase/` by `scripts/method_tables.py`; `showcase/track_record.json` is the same data and must agree.

<!-- END known-answer table -->

`showcase/validation.md` holds a separate, smaller re-run of these tables.
It was generated at commit `1865e81` from a cache that is gitignored, so it
cannot currently be reproduced by anyone else (and predates the wide-mode
Rhodes re-run). Treat `showcase/track_record.json` and the table above as
authoritative; `validation.md` is superseded until it is regenerated from
committed inputs.

## 11. Prior art and how this differs

**PWTT (Ballinger)** runs a Sentinel-1 pixel-wise t-test for building damage
in a draw-an-area app, comparing each pixel only with its own history. It
has no matched controls, so it cannot separate a real change from a
region-wide trend; Otherwise's counterfactual comes from other places, not
the same pixel's past.

**Cambridge 4C PACT / tmf-implementation** builds pixel-matching
counterfactuals for tropical forest carbon, but as a command-line pipeline
on the JRC forest-cover map, targeting deforestation specifically. Otherwise
reads raw Sentinel-1/2 pixels in a browser-facing app across several change
types (clearing, flooding, burning, construction).

**Placebo evaluation of counterfactual methods (4C, 2025)** is the source of
the placebo-testing idea used here. Otherwise makes that discipline a
permanent, visible part of every verdict, not a one-off exercise run
separately from the tool.

**Commercial tools** — Pachama's dynamic baselines, Global Forest Watch
(stats, no counterfactual), CTrees LUCA (radar alerts), Earth Blox (paid,
no-code) — build no matched counterfactual, or do not expose the method,
thresholds or placebo rate behind the output. Otherwise publishes both.

## 12. References

- Abadie, A., Diamond, A. & Hainmueller, J. (2010). *Synthetic Control
  Methods for Comparative Case Studies.* Journal of the American Statistical
  Association.
- Ben-Michael, E., Feller, A. & Rothstein, J. (2021). The augmented
  synthetic control method.
- Chernozhukov, V., Wüthrich, K. & Zhu, Y. (2021). An exact and robust
  conformal inference method for counterfactual and synthetic controls.
- Fick, S. E., et al. (2021). *Evaluating natural experiments in ecology:
  using synthetic controls in assessments of remotely sensed land
  treatments.* Ecological Applications.
- ESA Sentinel-2 Scene Classification Layer (SCL) documentation, Copernicus.
- Microsoft Planetary Computer STAC catalogue, Sentinel-1 RTC and
  Sentinel-2 L2A collections.
