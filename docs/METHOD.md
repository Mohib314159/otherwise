# Method

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
phenology shared.

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
  (`SITES.md`), beyond the 12 km ring: donors burnt too, "controls shifted"
  fired, verdict CAN'T TELL (`DECISIONS.md`, milestone 4). Sindh's 2022
  flood, same limit.
- **Thin optical archive before 2018.** Saddleworth Moor (2018-06-24): NBR
  had only two usable post-event bins, the UK archive being thin that early;
  VH was the only signal with enough bins (`DECISIONS.md`, milestone 4;
  `SITES.md`).
- **0.05 is usually below power in cloudy sites.** The power table (section
  10) detects an injected -0.05 NDVI effect in 6/20 cases on the cloudiest
  real test area; Richmond Park and Jaú NP, both null, came back CAN'T TELL
  rather than NOT REAL for the same reason (`DECISIONS.md`, milestone 4).
- **The interval is for a constant shift, not a time-varying one.** At
  Grünheide the point estimate (-0.61 NDVI) sits just outside its own 90%
  interval (-0.57 to -0.45), since the clearing's effect is not a flat step
  across the window (`DECISIONS.md`, milestone 3).

### Two failures our own red team grades as "breaks"

`docs/REDTEAM.md` is an adversarial self-review with numbers. Two of its
attacks defeat the method as it currently stands. **Neither fix is applied
yet**, so both are limits of the shipped tool, not hypotheticals:

- **A decline that began before the claimed date is still called REAL**
  (REDTEAM E5). On synthetic pre-trends the verdict came back REAL in 9/15
  fits at -0.10/yr and 14/15 at -0.20/yr on the Midlands test area (6/15 and
  9/15 at Austin). The in-time placebo *detects* most of them, but
  `src/app/verdict.py` appends a caveat sentence and returns REAL anyway. The
  fix — a flagged in-time placebo forcing CAN'T TELL and disabling the 4x
  pre-fit bypass — is specified and not yet implemented. Until it is, treat a
  REAL verdict on a gradually declining area as unproven.
- **Short floods are deleted by the haze filter** (REDTEAM E7). The NDVI
  despike is one-sided and NDVI-blind to standing water, so it removes 100% of
  the observations of a flood lasting under 20 days, 88% at 30 days and 41% at
  45 days. On the real Sindh 2022 series it deleted the three peak-flood
  observations (10, 15 and 23 September 2022) as "haze". End to end on a
  25-day synthetic flood: REAL 5/15 with the despike, 14/15 without. The fix
  is to make the despike NDWI-aware. Until then, floods shorter than about a
  month — which is most river and flash flooding — are under-detected.

Two further limits from the same review, not graded "breaks" but real:
the 4x pre-fit bypass is reachable on null cells (E6), and the spillover
buffer is measured centroid-to-polygon, so at 200 ha and above the nearest
kept control can share an edge with the treated area (E2).

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

Reproduced verbatim from `DECISIONS.md`, dated 2026-09-18.

**Detection power** (`scripts/power.py`; 400 real, untouched donor cells
around the Midlands test area, 2020–2024, 79 clear optical observations in
four years; 20 cells per effect size, injected step effect at 70% of the
window, full estimator and verdict rules):

| Signal | Injected effect | Called REAL | False alarms |
|---|---|---|---|
| NDVI | 0.00 | 0 / 20 | 0 / 20 |
| NDVI | -0.05 | 6 / 20 (30%) | |
| NDVI | -0.10 | 17 / 20 (85%) | |
| NDVI | -0.20 | 19 / 20 (95%) | |
| VH (radar, dB) | 0.0 | 0 / 20 | 0 / 20 |
| VH | -0.5 | 0 / 20 | |
| VH | -1.0 | 7 / 20 (35%) | |
| VH | -2.0 | 20 / 20 (100%) | |

**Known-answer sites** (candidate, unconfirmed by Mohib as of this writing):

| Site | Type | Expected | Verdict | Lead signal | Effect (90% interval) | Placebo p |
|---|---|---|---|---|---|---|
| Grünheide 2020 (Tesla site) | clearing | REAL | **REAL** | NDVI | -0.61 (-0.57 to -0.45) | 0.03 |
| Saddleworth Moor 2018 | burn | REAL | CAN'T TELL | VH (NBR had 2 post bins) | NBR -0.40 on 2 observations | 0.03 |
| Rhodes 2023 | burn | REAL | CAN'T TELL | NBR | controls burnt too | 0.61 |
| Sindh 2022 | flood | REAL | CAN'T TELL | NDWI | controls flooded too | 0.51 |
| Richmond Park (null) | none | NOT REAL | CAN'T TELL | NDVI | -0.01 (-0.10 to +0.10) | 0.93 |
| Jaú NP (null) | none | NOT REAL | CAN'T TELL | NDVI | -0.01 (-0.07 to +0.06) | 0.64 |

Zero false alarms, one clean REAL, four honest CAN'T TELLs, each with a
stated reason. `showcase/validation.md` holds a smaller, faster re-run of
these two tables (8 units per effect size), regenerated on demand by
`scripts/validate_app.py`; the figures above are what `DECISIONS.md` records
as the milestone result.

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
