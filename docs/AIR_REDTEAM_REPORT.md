# Air / ULEZ red-team report — protocol v2.2

**Status:** hardened implementation; no live ULEZ estimate fabricated in the offline test environment.

## What was attacked

The ground-NO₂ implementation was subjected to adversarial scenarios intended to create plausible but false causal claims, not only random-noise nulls.

### 1. Treated-monitor composition shift — real bug found and fixed

Attack: add a high-baseline London monitor with **no true policy effect**, then make it stop reporting at implementation.

The pre-hardening implementation could call this `REAL` because the treated-network mean changed composition. v2.2 requires strong pre/post station coverage, fixes the eligible treated cohort, baseline-aligns monitors using pre-policy means, and requires at least 80% of the fixed cohort to be observed for a weekly treated value.

The attack no longer returns a positive verdict.

### 2. One London station drives the whole effect — fixed

Attack: only one treated monitor receives a large negative shock.

Fix: leave-one-treated-monitor-out sensitivity. A positive verdict is withheld when removing any single treated monitor collapses or reverses the effect.

### 3. Pre-existing London decline — fixed

Attack: London starts diverging downward before policy launch and simply continues afterward.

Fix: recent pre-trend projection, anticipation diagnostics and in-time placebo dates. A clear pre-existing divergence blocks a positive headline.

### 4. Donor missingness creates the counterfactual — fixed

Long post-event outcome gaps are not seasonally filled. At most one internal weekly donor gap may be interpolated; donors with unresolved used-week gaps are excluded.

### 5. Placebo cohort silently shrinks — fixed

Every fake-treated cohort must have exactly the real treated-cohort size. Each placebo removes its own fake-treated units, re-runs donor selection and re-tunes ASCM lambda. A positive verdict requires at least 19 valid placebo cohorts and rarity under both the RMSPE-ratio and signed-effect placebo tests.

### 6. NO₂ interval grid inherited land-scale units — fixed

Air uses an air-specific conformal inversion that expands far enough to span zero with margin. If the accepted interval reaches the numerical search boundary, interval resolution is marked unresolved and a positive verdict is withheld.

### 7. Control city receives its own air-quality policy — screened and exposed

Known UK CAZ/LEZ/ZEZ launches overlapping the registered analysis window are screened geographically from the candidate control network. Every exclusion is stored in run JSON and shown on the evidence page. The screen is explicitly documented as incomplete rather than treated as proof that every remaining city is policy-free.

### 8. Registered ULEZ protocols — corrected

- **2019** begins on **2018-03-08**, after the earlier central-London T-Charge transition was established.
- **2021** is exploratory and forcibly `CANT_TELL` because the available clean pre-period is too entangled with COVID-era mobility changes.
- **2023** begins on **2021-07-19** and defines treatment as the official London-wide/LEZ footprint minus the already-treated 2021 ULEZ polygon. The estimand is the incremental post-29-Aug-2023 change in newly covered outer London.

### 9. Daily completeness — hardened

A valid daily NO₂ mean requires at least **19/24 hourly values**. A station also needs at least 80% valid daily coverage separately before and after implementation.

### 10. Weather reference — improved without post-treatment fitting

Weather normalisation is selected and fitted using pre-policy observations only. Actual meteorology is replaced by a season-matched pre-policy reference based on nearby day-of-year values rather than one global weather median.

### 11. Mid-week implementation bins — fixed in v2.2

Weekly values are Monday-to-Sunday bins. If implementation begins mid-week (notably the Tuesday 29-Aug-2023 expansion), the mixed pre/post weekly bin is excluded for every station and logged as an `event-bin` receipt rather than assigned to either regime.

### 12. Stale permalink semantics — fixed

Air run IDs include `air-ground-no2-v2.2`. Methodological changes therefore create new evidence IDs instead of silently changing the meaning of an existing permalink.

## Current deterministic adversarial outcome

`python -m scripts.air_redteam` currently gives:

| Attack | v2.2 behaviour |
|---|---|
| ordinary null | `CANT_TELL` |
| genuine −6 µg/m³ effect | `REAL` |
| high-NO₂ monitor disappears at event | `CANT_TELL` |
| only one London monitor changes | `CANT_TELL` |
| decline begins before implementation | `CANT_TELL` |
| common national pollution drop | `CANT_TELL` |
| unmeasured London-only shock starting exactly at ULEZ date | **`REAL` — residual identification limit** |

The first six attacks are identifiable from the available design and all pass the release gate. The last is deliberately retained as a failure demonstration: observational time series cannot distinguish ULEZ from an unmeasured London-only cause with the same onset and outcome signature.

## Synthetic calibration release gate

A 10-seed offline calibration on the hardened inference path produced:

- null panels: **0/10 false `REAL`**, 10/10 `CANT_TELL`;
- injected −6 µg/m³ panels: **10/10 `REAL`**.

This is a wiring/power sanity check, not evidence about ULEZ.

## Residual limitations that are not solved

1. **Coincident local confounding.** A London-only intervention or shock with the same onset and sign as ULEZ can masquerade as a policy effect.
2. **Control covariates remain incomplete.** Matching uses site type and pre-policy NO₂ trajectory/level/trend/variability plus policy screens; road density, fleet mix, population and socioeconomic context are not yet donor covariates.
3. **Ground monitors are not population exposure.** Results describe the measured monitoring network.
4. **No cross-sensor confirmation yet.** Sentinel-5P/TROPOMI should be independent evidence for large-area cases, not pooled pseudo-replication.
5. **NO₂ alone is not a complete mechanism check.** NOx, traffic increments and traffic-volume outcomes would provide useful independent evidence.
6. **ULEZ is known-answer validation, not blind validation.** Published values are isolated from estimation, but a separate blind air benchmark is still required.

## Test state for this release

- dedicated air tests: **25 passed**;
- broader app/web regression group: **182 passed, 20 skipped, 1 expected xfail**;
- red-team unit tests: **13 passed, 7 expected xfails**;
- executable adversarial runner: **6/6 identifiable attacks pass**;
- Python compile and frontend JavaScript syntax checks: pass.

The complete historical suite also contains legacy zarr-backed cube tests. `zarr` is now declared in `requirements.txt`; this offline sandbox could not install missing packages from PyPI, so release verification here uses the groups above. GitHub Actions installs the full requirements file and runs `pytest -q`.

## Real ULEZ execution

This environment cannot resolve the external LAQN/DEFRA/ERA5 hosts, so **no real ULEZ result is claimed here**. On a networked machine:

```bash
python -m scripts.run_air_case ulez-central-2019 --post-months 3
python -m scripts.run_air_case ulez-londonwide-2023 --post-months 3
python -m scripts.air_known_answers
```

Only after Otherwise has produced its own estimate does the evidence page reveal the published answer key.
