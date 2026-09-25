# Codex handoff: air / ULEZ validation checkpoint

Date: 25 September 2026. Branch: `codex/air-ulez`.
Implementation commit: `43cf8b51066ed740d7fa985579605bfb208affb9`.
Base: `main` at `9e525ee05554c373fa828c5690dd751e66b4c66c`.

**This is a reviewable work-in-progress checkpoint, not a finished validation or a claim that ULEZ did/did not work.** The implementation and evidence have been pushed to the requested branch. Main has not been merged into, updated, or deployed by this work. Existing `WORKFLOW.md` and `ULEZ-DESIGN.md` from main are preserved.

## Source and scope

The user supplied `carbon-twin-otherwise-air-v2.2.zip` as the canonical implementation and `Otherwise-UI-Desktop-Flagship.zip` as the UI reference. Work was performed in an isolated extracted copy, then overlaid onto a new worktree based on the real main commit so this branch retains repository history. `carbon-twin-main.zip` is retained as another original input, not used to replace the canonical air source.

The flagship UI archive is an older land-only fork. Its server and JavaScript must not replace the air-aware versions wholesale. Selected styles and shell markup were integrated; land and air functional routes remain.

The archive already supplied the air estimator, registry, UI, tests, deployment configuration and method documents. This branch includes that implementation relative to main, plus the fixes below. Documents named `AIR_V2_2_RELEASE.md`, the historical red-team report and `showcase/air_power_synthetic.json` are inherited records: their historical claims are not fresh validation of the current protocol.

## What changed

- Official policy boundaries now use the GLA `MapServer` query endpoint. The configured `FeatureServer` returned an upstream error; the MapServer exposed the same registered layer and geometry.
- DEFRA annual CSV parsing now respects GMT **hour-ending** timestamps, including 24:00 and year-end. It checks the status column adjacent to NO2, emits rejected-row receipts, distinguishes NOx-as-NO2 from actual nitrogen dioxide, and strips table row ranks from station names. A real BR11 2019 file reconciled to 8,726 valid + 34 rejected = 8,760 observations.
- LAQN `EndDate` was verified exclusive using downloaded response dates. The previous chunking lost a day between annual chunks and the requested final day. Requests now account for the exclusive end and clip to the requested inclusive range. NO2 instrument start/end dates now constrain station activity, with original station/instrument metadata preserved.
- Weather adjustment rejects missing core ERA5 data rather than silently imputing an entirely absent weather series. It permits only complete internal gaps up to three days, repaired separately pre/post event. Optional unavailable boundary-layer height and repair counts are explicit.
- The documented single internal weekly donor repair is enforced. Calendar gaps cannot be bridged, and mixed pre/post policy weeks remain excluded at the analysis boundary. Imputation fractions reflect actual repairs in used weeks.
- A positive point estimate with a wide interval containing meaningful reductions no longer produces an unjustified negative verdict. This is a correction requiring method-owner review, not a tuned threshold.
- Protocol is `air-ground-no2-v2.3.1`. Cohort fetch budgets enter run identity. Existing saved results are reused rather than overwritten; atomic saves preserve JSON integrity. Concurrent HTTP cache writes use distinct temporary files.
- Missing chart/diagnostic floating values are represented as JSON null. Station rejection receipts retain their coverage explanation, and excluded-station diagnostics are retained.
- Mixed-case air requests reach the correct worker. Windows fixes cover date formatting, UTF-8 CLI output, UTF-8 generated-table comparisons, monotonic timeout checks and trailing-separator cache-path handling. No new land estimator redesign was performed; the shared conformal extension is inherited from the supplied v2.2 implementation and its branch diff still needs review.
- Selected flagship desktop styling, air evidence cards, responsive styling, favicon and page classes added. Null chart values no longer become zero; discontinuous lines/bands are split. Air metadata loading no longer pans the land map, and air mode hides irrelevant land showcase cards.
- Regression tests, dependency constraints, exact environment versions, test logs and live result JSON are committed.

## Air / ULEZ file map

| Area | Files | Purpose |
|---|---|---|
| Registry | `src/app/air/cases.py` | Registered dates, geometries, horizons and published answer-key metadata |
| Station model | `src/app/air/models.py` | Station identity, type and active-date logic |
| Ingestion | `src/app/air/providers.py` | LAQN, DEFRA AURN, ERA5/Open-Meteo, GLA boundaries, HTTP cache, daily/weekly aggregation |
| Weather | `src/app/air/weather.py` | Pre-policy-only ridge weather adjustment, seasonal reference and coverage checks |
| Analysis | `src/app/air/analysis.py` | Fixed cohorts, matching, ASCM, conformal intervals, symmetric placebos, pretrend and sensitivity diagnostics, verdict rules |
| Orchestration | `src/app/air/run.py`, `src/app/air/__init__.py` | Case execution, receipts, immutable IDs/results, post-estimation study comparison |
| Shared method | `src/app/estimator.py` | Land-compatible interface plus supplied air-scale conformal options |
| API/report | `src/app/server.py`, `src/app/report.py` | Air case/boundary/validation routes, worker, permalink/report support |
| Commands | `scripts/run_air_case.py`, `scripts/air_known_answers.py`, `scripts/air_redteam.py`, `scripts/air_power.py` | Live cases, generated comparison table, adversarial and synthetic power checks |
| Frontend | `web/index.html`, `web/landing.js`, `web/verdict.js`, `web/chart.js`, `web/common.js`, `web/track.js` | Land/air selection, evidence rendering, charts and track record |
| Styling | `web/desktop.css`, `web/evidence.css`, existing app/landing/mobile styles | Selective flagship integration and air cards |
| Tests | `tests/test_air_*.py`, `web/air_render_test.mjs` | Provider, weather, inference, orchestration, server, report and null-rendering regressions |
| Evidence | `docs/validation/air-ulez-2026-09-25/` | Saved results, logs, validation README, exact environment freeze |
| Method | `docs/AIR_METHOD.md`, `docs/AIR_REDTEAM_REPORT.md`, `docs/AIR_V2_2_RELEASE.md` | Supplied methodology/history; reconcile with current fixes before release |
| Dependencies | `requirements-validation.txt` | Tested compatible Windows package constraints, atop full requirements |

## Latest live runs: v2.3.1

Both commands ran through to saved JSON. Both returned `CANT_TELL`. **Acquisition failures mean neither is a completed literature replication.** Exact complete outputs and receipts are in the committed evidence directory.

### Central London 2019, three months

- Run ID `2f1f5b972f78cc61`.
- Window 2018-03-08 through 2019-07-08.
- Requested 12 London and 80 control stations; 0 London and 48 controls usable after daily QC.
- LAQN annual requests hit 75-second read timeouts (12 timeout receipts), leaving insufficient pre-policy London data.
- **No traffic/background estimate.** Do not call this a zero effect or replace it with the earlier estimate.

### Outer London 2023, three months

- Run ID `34d89f77f1989209`.
- Window 2021-07-19 through 2023-11-29; official London-wide footprint minus the 2021 zone.
- Requested 32 London and 80 control stations; 11 London and 50 controls usable after daily QC. This run also contains 32 LAQN timeout receipts.

| Stratum | Effect, ug/m3 | 90% interval | Relative | Treated / selected controls | Pre / post weeks | Exact-size placebos |
|---|---:|---|---:|---:|---:|---:|
| Traffic | -1.929654899701831 | [-4.008251546326518, +0.42608796647281366] | -6.888697221650334% | 4 / 9 | 88 / 10 | 0 |
| Background | +0.46491451925396715 | [-0.962965615591421, +2.1524092240712456] | +2.783848219677247% | 7 / 6 | 109 / 11 | 0 |

Selected donor counts are below the required 12. Exact-size placebo inference and pretrend assessment are unavailable; sensitivity refits are not estimable. Intervals include zero. The current CLI prints p=1.000 when there are zero placebos: that is an internal sentinel, **not a valid completed placebo test**. Do not describe this as confirmation of the published 2023 null finding.

### Superseded debugging runs: v2.3

`14411a7b6a8ceb55.json` (2019) and `2a0403c2bd026b93.json` (2023) are retained for traceability. Both were CANT_TELL and precede the LAQN exclusive-end correction. The initial 2019 traffic estimate was -7.75415 ug/m3 (~-10.05%), whose interval excluded the registered -19.6% study estimate; initial background and 2023 estimates were inconclusive. These numbers must not be used as final evidence. Published comparisons were attached after computation; the estimator was not retuned to agree.

## What is tested

- Full Python suite: **308 passed, 20 skipped, 8 expected failures**, 263.38 seconds. Includes legacy pipeline tests with zarr available. Log: `tests-release-v231.log`.
- Earlier focused analysis run: **12 passed**. Adversarial identifiable attacks: **6/6 passed**; a coincident London-only shock remains an unidentifiable residual risk, explicitly not a passing validation case.
- Focused provider run after exclusive-end/species fixes: **10 passed** (also covered by the full suite).
- Focused Windows compatibility and calibration checks: **4 passed** and **13 passed**.
- `node web/air_render_test.mjs` passed again in the publication worktree before the first commit. Static frontend smoke and JS syntax checks passed earlier.
- Full suite ran in the source copy. Publication overlay preserves those code contents and adds only validation documents/dependency records, while retaining main's two additional workflow/design documents.
- **Not completed:** fresh synthetic power calibration for v2.3.1. The planned `air_power --seeds 10 --effect -6` run did not finish/start before interruption; do not claim the inherited power JSON is a fresh result.
- **Visual:** preliminary real 2019 desktop evidence was inspected. A 390px screenshot was attempted, but final mobile layout and the latest real result pages are not signed off. Browser/runtime availability was interrupted repeatedly.

## Known bugs, limitations and next steps

1. **Fix/verify LAQN acquisition resilience first.** Newly requested annual windows timed out after the exclusive-end fix. Investigate whether the endpoint dislikes a full 365-day range; test smaller bounded chunks and modest retry/backoff rather than simply lengthening every timeout. Verify hour continuity on cached real responses. Keep network failure distinct from genuinely missing measurements.
2. **Recompute in a new results directory, preserving failed-run evidence.** The current runner deliberately returns an existing saved ID. Set a fresh `APP_RUNS_DIR` for deliberate reacquisition and retain old JSON; do not silently replace a public permalink. A proper immutable data-snapshot/retry identity is still a product design decision. Changed dependency/data vintages are not included in the current deterministic ID.
3. **AURN metadata is current and all-pollutant.** Some candidate stations only opened recently or only measure PM. Verified example: BLWD began PM2.5 in November 2024, so 2018/2019 files genuinely 404. QC rejects these safely, but they consume the finite fetch budget and make requested counts less useful. Improve historical NO2 eligibility from authoritative metadata; do not increase budgets opportunistically to force significance.
4. **Finish UI honesty/polish.** With placebo_n=0, hide sentinel p-values and unavailable placebo-band legends. Distinguish “not estimable” sensitivity from demonstrated non-robustness. A study with no point value currently repeats its finding text. The verdict hero can become an oversized paragraph; retain full reasoning in an accessible disclosure while shortening the summary. These final requested UI changes were not completed before agent interruption; inspect current code rather than assuming they were applied.
5. **Conservative weather handling needs review.** The new core-weather guard excludes a station for unrepaired missing core weather; optional absent boundary-layer height is recorded. Audit actual coverage receipts and keep inference trained pre-policy only.
6. **Method review remains required.** Review the supplied shared conformal extension and newly corrected abstention/repair logic under WORKFLOW.md. Thresholds were not loosened. `ULEZ-DESIGN.md` proposes a different roadside-minus-background/ramp design; it is deliberately not implemented by this checkpoint and needs an explicit design decision/calibration rather than being conflated with this estimator.
7. **Rerun tests, red-team and new power calibration after further changes.** Record false REAL, true REAL and CANT_TELL rates. Do not present agreement with literature unless the real-data run is estimable and horizons/strata align.
8. **Finish final desktop + 390px checks** of both live permalinks, land landing/showcase, maps, receipts, report links, and navigation. Avoid replacing air-aware JS with the older flagship fork.
9. **Finish release deliverables** after acquisition/QA: final tested repo ZIP, patch against canonical v2.2, concise results/limitations report, and another complete checkpoint. The user's original checkpoint ZIP is available locally; this branch is now the review/handoff source of truth.

## Reproduction and local recovery

Use Python 3.12 and a short virtualenv path on Windows:

```sh
python -m venv .venv
# Activate it, then:
python -m pip install -r requirements-validation.txt
python -m pytest -q -p no:cacheprovider --basetemp=./work/pytest-fresh
python -m scripts.run_air_case ulez-central-2019 --post-months 3
python -m scripts.run_air_case ulez-londonwide-2023 --post-months 3
python -m scripts.air_redteam
python -m scripts.air_power --seeds 10 --effect -6
node web/air_render_test.mjs
python -m uvicorn src.app.server:app --host 127.0.0.1 --port 8765
```

Set `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` for parallel runs. Use an unused workspace basetemp path; the machine's shared pytest temp directory had ownership conflicts. Newest NumPy/pyarrow binaries failed on this host; the tested constraints and exact freeze are committed. Do not commit a virtualenv.

Copy a chosen committed JSON from `docs/validation/air-ulez-2026-09-25/` into `data/runs/` to inspect `/v/<id>` without recomputing. The committed logs distinguish latest v2.3.1 from superseded v2.3 outputs.

Local source copy: `C:/Users/Gamer/Documents/Codex/2026-09-20/referenced-chatgpt-conversation-this-is-an/work/ulez-validation/source/carbon-twin`.
Publication worktree: `.../work/ulez-validation/github-publish`.
Working environment: `C:/Users/Gamer/Documents/Codex/ulez-env`.
Checkpoint: `.../outputs/Otherwise-checkpoint-2026-09-24-01.zip` (244,631,953 bytes; SHA256 `896802debd2d5e1092e05e80ce03fce2894295756dd58a57313ac287f85469c4`). It contains all three original archives, working source, raw public cache and intermediate results; it predates this handoff and is explicitly in progress. Raw cache, original ZIPs, virtualenvs and the synthetic UI-only fixture are intentionally excluded from Git.
