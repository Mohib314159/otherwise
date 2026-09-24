# Air/ULEZ validation checkpoint — 25 September 2026

This is unfinished validation work submitted for review, not a validated causal finding or final release. All numbers below come from committed run JSON. Benchmarks were read only after computation; no thresholds or cohort budgets were loosened to agree with them.

## Latest protocol: air-ground-no2-v2.3.1

- 2019: `2f1f5b972f78cc61.json`, three months, CANT_TELL. Zero treated monitors survived daily QC because annual LAQN fetches timed out; no stratum estimates. This is a failed acquisition, not evidence of no ULEZ effect.
- 2023: `34d89f77f1989209.json`, three months, CANT_TELL. Traffic -1.929654899701831 ug/m3, 90% [-4.008251546326518, 0.42608796647281366]; background +0.46491451925396715, [-0.962965615591421, 2.1524092240712456]. This run also contains LAQN timeouts and cannot be called a completed replication.
- 2023 traffic/background: 4/7 treated monitors, 9/6 selected donors; zero exact-size placebo cohorts. Pretrend checks unavailable because fewer than 12 donors. These are unavailable diagnostics, not passes.

## Superseded diagnostic runs (protocol v2.3)

`14411a7b6a8ceb55.json` (2019) and `2a0403c2bd026b93.json` (2023) both return CANT_TELL. They precede the verified exclusive-EndDate LAQN fix and must not be presented as final estimates. Retained to explain the debugging history, never overwritten.

## Tests

- Latest complete suite: 308 passed, 20 skipped, 8 expected failures (263.38 seconds). See tests-release-v231.log.
- Earlier focused analysis suite: 12 passed; adversarial suite: 6/6 identifiable attacks passed. Coincident London-only shock remains an acknowledged identification limit.
- Focused Windows compatibility and calibration checks: 4 and 13 passed.
- The archive's pre-existing synthetic power file is not a newly executed calibration of v2.3.1; the planned fresh power run did not complete.
- Browser: desktop preliminary evidence inspected. A 390px screenshot was attempted, but final mobile QA is incomplete. Do not claim visual sign-off.

## Reproduce

Use Python 3.12 and `pip install -r requirements-validation.txt`; exact installed versions in environment-freeze.txt. On Windows use a short virtualenv path. Set OPENBLAS_NUM_THREADS=1, OMP_NUM_THREADS=1 and MKL_NUM_THREADS=1 when running parallel work.

```sh
python -m pytest -q -p no:cacheprovider --basetemp=./work/pytest-fresh
python -m scripts.run_air_case ulez-central-2019 --post-months 3
python -m scripts.run_air_case ulez-londonwide-2023 --post-months 3
python -m scripts.air_redteam
python -m scripts.air_power --seeds 10 --effect -6
python -m uvicorn src.app.server:app --host 127.0.0.1 --port 8765
```

Use a new APP_RUNS_DIR for deliberate reacquisition: saved results are immutable and the runner otherwise reuses them. Preserve the original run JSON; do not overwrite a published permalink. Cache is under APP_AIR_CACHE_DIR (default data/air_cache). Copy desired committed run JSON from this directory to data/runs to inspect its /v/<id> page locally.

## Inputs and scope

Canonical input SHA256: F16804C562C300C8534F6E0F64989B8AB518D47754B96C3BED71D175AA68654B (carbon-twin-otherwise-air-v2.2.zip). Flagship UI input SHA256: F0FF317E787BCF0FD54885BF75F9EF0DC93509F8CAFD277932347CFA5C8E65ED. Original archives and raw cache are retained in the user's local 245 MB checkpoint ZIP, not committed to Git. No credentials or virtual environments belong in this repository.
