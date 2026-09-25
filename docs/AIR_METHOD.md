# Air-pollution method — ground NO₂ / ULEZ protocol (in development)

> **Status, 25 Sep 2026.** Code protocol is `air-ground-no2-v2.3.1` (this document was
> written for v2.2; the v2.3.1 differences and their review are in `DECISIONS.md`,
> "Codex air changes: triage"). Air is **not public**: it is switched off on the live
> site (`APP_AIR_ENABLED=0`), no ULEZ run has produced a usable estimate, and it has no
> known-answer set or false-alarm test yet. Nothing here is a finding.

This is the in-development protocol for Otherwise's second signal family. It answers a deliberately narrow question:

> **After a registered policy date, did NO₂ at exposed monitoring sites change more than a matched no-policy trajectory suggests it would have changed anyway?**

It does **not** prove that the policy is the only possible cause, and it is not a population-exposure model. A concurrent, unmeasured London-only shock beginning at the same time remains fundamentally unidentifiable from these observational time series alone.

## 1. Why ground monitors are primary

The 2019 central ULEZ is far smaller than a clean Sentinel-5P causal unit, and roadside effects can vary over very short distances. The production estimate therefore uses:

- LAQN / Imperial ERG hourly NO₂ for treated London monitors;
- DEFRA AURN hourly NO₂ for controls in other UK cities;
- ERA5 meteorology, accessed through the configured historical provider;
- official GLA/TfL zone geometries.

Sentinel-5P/TROPOMI is intentionally **not** mixed into the ground estimate. It is a later independent cross-sensor check for large spatial interventions.

## 2. Registered cases

The case registry is code (`src/app/air/cases.py`), not a UI default that can drift after seeing results.

### Central ULEZ — 8 April 2019

- treated geometry: official 2019 ULEZ layer;
- registered analysis start: **8 March 2018**;
- default effect horizon: 3 months.

The baseline starts after London's October-2017 T-Charge transition is established, rather than fitting across another central-London emissions intervention.

### Inner-London expansion — 25 October 2021

This case is **exploratory only** and is forced to `CANT_TELL`. The clean pre-policy period after the end of English COVID restrictions is too short to support the same causal claim. The estimate can be inspected as sensitivity evidence, but the product will not print a decisive headline.

### London-wide expansion — 29 August 2023

- registered analysis start: **19 July 2021**;
- treated geometry: official London-wide LEZ/2023 ULEZ footprint **minus the already-treated 2021 ULEZ polygon**;
- default effect horizon: 3 months.

This makes the primary estimand the newly covered outer-London area, instead of diluting the treatment with central and inner monitors that were already subject to ULEZ.

## 3. Answer-key separation

Published estimates are never imported by `air/analysis.py` and never participate in:

- station inclusion;
- weather normalisation;
- donor selection;
- ASCM lambda selection;
- interval construction;
- placebo tests;
- verdict thresholds.

Only after an Otherwise result exists does `run.py::_research_comparison()` attach the registered literature. A disagreement remains a disagreement.

## 4. Monitor strata are never pooled

Traffic/roadside and urban-background stations are analysed independently:

- `NO2_TRAFFIC`
- `NO2_BACKGROUND`

They receive independent treated cohorts, donor pools, ASCM fits, intervals and placebo distributions. If their evidence states disagree, the combined headline is `CANT_TELL — mixed evidence by monitor type`.

## 5. Raw-data QC and receipts

### Hourly → daily

A daily NO₂ mean requires **at least 19 valid hourly values**, i.e. more than 75% of the 24 hourly slots.

### Station inclusion

Before weather normalisation, a station must have at least **80% valid daily means separately in both the registered pre-policy and post-policy periods**. This prevents a station that disappears after implementation from changing the composition of the treated average and manufacturing a drop.

Every rejected/invalid observation and station-level coverage failure becomes a receipt. It is not silently converted to zero.

### Daily → weekly

A weekly value requires at least four valid daily values. If the policy starts mid-week, the single week that straddles the implementation date is dropped for every station and logged as an `event-bin` receipt instead of being assigned to pre or post.

## 6. Weather normalisation: pre-policy only

Each station gets an interpretable ridge model with nonlinear meteorological terms and calendar structure. Lambda is selected with blocked validation using **pre-policy outcomes only**.

The normalised outcome is:

`observed NO₂ - [prediction(actual weather) - prediction(reference weather)]`

Reference weather is not one global median. For each calendar date it is the median **pre-policy** weather within ±14 day-of-year, with a pre-policy overall median only as fallback. This preserves plausible seasonality while preventing post-policy weather or outcomes from defining the counterfactual weather state.

Weather adjustment can remove measured meteorological variation. It cannot remove an unmeasured concurrent London-specific intervention.

## 7. Fixed treated cohort

Within each stratum, a treated monitor must retain ≥80% weekly coverage on both sides of implementation. The eligible cohort is then fixed.

To prevent week-to-week monitor composition from generating a level shift, each monitor is baseline-aligned to the fixed cohort's mean using its **pre-policy mean** before aggregation. A week is used only when at least 80% of the fixed eligible cohort is observed.

This rule was added after an adversarial test demonstrated a real false positive in the first air implementation: a high-NO₂ London monitor disappeared at the intervention date and the changing cohort mean was incorrectly called an improvement.

## 8. Controls and contamination screen

Controls must:

- be DEFRA AURN monitors outside a 60 km London spillover buffer;
- have the same traffic/background stratum;
- be active at the policy date;
- pass the same daily/weekly coverage discipline;
- have no unresolved used-week outcome gaps after at most **one internal weekly interpolation**.

There is no seasonal outcome filling. Long post-policy gaps exclude the donor.

Known UK CAZ/LEZ/ZEZ launches are conservatively screened by geography and date. A monitor near a city whose clean-air intervention begins inside the registered Otherwise window is excluded and listed in the run JSON. This screen is a protection against obvious policy contamination, not a claim that the list captures every local intervention.

Eligible donors are ranked using **pre-policy data only**: trajectory RMSE, baseline level, trend and variability. Current v2.2 does not yet match directly on road density, fleet composition, population or socioeconomic variables; that limitation is public.

## 9. Counterfactual

The selected panel goes through the shared augmented synthetic-control implementation:

1. convex SCM produces an interpretable weighted combination of real controls;
2. ridge augmentation corrects residual pre-fit bias;
3. the ridge penalty is chosen from pre-policy fit only;
4. the estimand is the mean weather-normalised treated-minus-counterfactual gap over the registered post-policy horizon.

Both absolute µg/m³ and relative % effects are reported.

## 10. Air-scale conformal interval

The 90% moving-block conformal interval is run on an NO₂-specific search scale. The legacy land/radar ±10 numerical cap is **not** used. The search is forced to span zero and can widen repeatedly.

If the accepted set is empty or touches the numerical search boundary, Otherwise does not print `REAL`; it returns `CANT_TELL` because the interval is numerically unresolved.

## 11. Exact-size symmetric in-space placebos

A positive air verdict requires structurally comparable placebo trials.

For every fake treated cohort:

1. use **exactly the same number of monitors** as the real treated cohort;
2. remove those monitors from the candidate pool;
3. rebuild the fake treated trajectory;
4. re-run donor selection from scratch;
5. re-select ASCM lambda;
6. fit the same estimator;
7. record both post/pre fit deterioration and signed post-policy effect.

A fake cohort is never silently shrunk. If the candidate pool cannot support the exact cohort **and** leave at least the minimum donor panel, the placebo test is not valid and a positive verdict is impossible.

`REAL` requires both:

- RMSPE-ratio placebo p ≤ 0.10; and
- signed-effect placebo p ≤ 0.10.

At least 19 valid placebo cohorts are required.

## 12. Pre-trend, time-placebo and sensitivity checks

A positive verdict must also survive:

- fake event dates inside the pre-policy period;
- a dedicated 13-week lead-window diagnostic for pre-existing downward divergence;
- leave-one-treated-monitor-out refits;
- removal/refitting around influential synthetic-control donors.

Failure of an applicable robustness check downgrades the stratum to `CANT_TELL` rather than changing thresholds until the result passes.

## 13. Verdict states

The design minimum meaningful ground-NO₂ effect is currently 1.0 µg/m³. It is an engineering threshold, **not** a health or regulatory standard.

A stratum can be `REAL` only when all quality gates pass, the 90% interval lies below zero, the point estimate is at least 1 µg/m³ lower than counterfactual, and both exact-size placebo tests pass.

`NOT_REAL` is used when the data are sufficiently informative to rule out a meaningful additional improvement or show movement in the opposite direction.

`CANT_TELL` is an explicit outcome, not a failed run. It covers insufficient controls, weak pre-fit, inadequate placebo resolution, pre-trend, station sensitivity, unresolved interval, mixed monitor strata and the forced-exploratory 2021 case.

## 14. Reproducibility and immutable evidence

Air run IDs include the method protocol string (`air-ground-no2-v2.2`). A methodological change therefore creates a new permalink rather than silently changing the meaning of an existing result.

Every evidence page exposes the registered window, treated geography, monitor counts, both placebo p-values, robustness diagnostics, receipts, policy-control exclusions, method version and known limits.

## 15. Validation surfaces

Run locally:

```bash
python -m scripts.air_redteam
python -m scripts.air_power --seeds 30 --effect -6
python -m scripts.run_air_case ulez-central-2019 --post-months 3
python -m scripts.air_known_answers
```

`air_redteam` contains synthetic attacks for monitor dropout, one-monitor domination, pre-existing decline and common national shocks. It also keeps a **coincident London-only shock** as an explicit residual identification failure rather than inventing a threshold to make it disappear.

`air_power` reports false-REAL, detection and abstention rates separately. These are synthetic calibration metrics, not real-world ULEZ accuracy.

`air_known_answers` runs the registered live cases first and only then writes the literature comparison table.

## 16. Known limits / next scientific work

The most important remaining improvements are not another verdict threshold:

1. richer donor covariates (road network, fleet composition, population/socioeconomic context);
2. direct traffic/NOx mechanism checks where reliable data are available;
3. independent TROPOMI/Sentinel-5P evidence for spatially large interventions;
4. blind validation on policies/events that were not used while designing the pipeline;
5. formal reconciliation of the hardened symmetric placebo protocol back into the land pipeline.

The system must remain willing to abstain. A confident-looking answer from an invalid counterfactual is worse than `CANT_TELL`.
