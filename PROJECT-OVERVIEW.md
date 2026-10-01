# Otherwise: project overview

Written 25 September 2026 and updated the same day after the merges below, for Mohib to reread before posting anything publicly.
Every number here comes from a file in this repo, which is named next to it, or from a command run while writing this and marked **"re-run today"**.
If a number here disagrees with its source file, the source file wins.

---

## 1. What Otherwise does

### In one paragraph

You pick a place and a date, and say what supposedly happened: "this forest was cleared in February 2020", or "London's ULEZ started on 8 April 2019".
Almost any place looks different afterwards anyway: seasons change, weather varies, whole regions drift.
So Otherwise asks a narrower question: **did it change more than it would have anyway?**
It builds a "no-event" version of the place out of similar places that were not affected. It compares the real place with that stand-in, then checks whether the method "finds" effects just as big where nothing happened.
The answer is **REAL**, **NOT REAL** or **CAN'T TELL**, and the evidence is shown on a page with its own link (a permalink).

There are two kinds of signal:

- **Land change** (Sentinel-1 radar and Sentinel-2 optical satellite data). This is the original product, and it is on `main`.
- **Air pollution** (ground-level NO₂ monitors, used for London's ULEZ). Codex added this, and it is **merged but switched off** (`APP_AIR_ENABLED=0`).

### The land method, step by step (drawn area → verdict)

Source: `docs/METHOD.md`. The code for each step is in brackets.

1. **You draw a polygon and give a date and a change type.** The area must be between 0.5 and 500 ha (`src/app/geometry.py`). The date must be 2018 or later, because the method needs three years of history before the event (`src/app/run.py`, `PRE_YEARS = 3`). The "after" window is at most 18 months.
   The change type picks the main signal:

   | Change type | Main signal | Backup (radar) signal |
   |---|---|---|
   | Clearing | NDVI going down | VH |
   | Flood | NDWI going up | VV |
   | Burn | NBR going down | VH |

   These pairings are in `src/app/verdict.py`, `SIGNALS`.
2. **Fetch satellite data** from Microsoft Planetary Computer (`src/app/fetch.py`, `s2.py`, `s1.py`).
   - **Optical (Sentinel-2).** A scene is used only if at least 80% of the area is clear of cloud, using Sentinel-2's own cloud/land classification of each pixel. Old scenes are corrected for a 2022 change in how ESA processes the data.
   - **Haze filter.** A "despike" step drops sudden one-off dips in NDVI, because missed haze looks like a dip.
   - **Radar (Sentinel-1 RTC).** Only one satellite track (orbit) is used, and averaging is done on the raw values before converting to decibels.
   - **Receipts.** Every observation that gets thrown away is recorded with its reason, and shown on the page.
3. **Pick candidate control areas.** These are cells the same shape as your area, in a ring 1–12 km away (`geometry.py`). The 1 km gap is a buffer against spillover from the event.
4. **Bin the time series** into 10-day windows (`src/app/prep.py`). Gaps in your own area are **never filled in**. Gaps in control cells can be filled, but a control cell is dropped if it has less than 70% of its data.
5. **Choose the controls** (`src/app/donors.py`). Keep cells with the same dominant land cover (ESA WorldCover) and an elevation within 150 m of your area. These filters are relaxed if fewer than 30 cells would be left. Then keep the 80 cells whose history best matches your area's before the event (40 cells for live runs).
6. **Build the counterfactual** (`src/app/estimator.py`). This is the "what would have happened anyway" line. It uses an *augmented synthetic control*: a weighted average of the control cells chosen to match your area before the event, plus a small correction term. The effect is the real line minus the counterfactual line, averaged over the period after the event.
7. **Work out the uncertainty.** A 90% interval is built by *conformal inference*, which makes no assumption about how the noise is distributed. This interval assumes the effect is a constant jump. If the effect changes over time (say, regrowth), the reported average can sit outside its own interval, and the page shows both.
8. **Run placebo checks.**
   - *In space:* each control cell is treated as if it were your area and fitted the same way. How unusual your area looks among them gives a p-value.
   - *In time:* the method pretends the event happened on three earlier dates. It should find nothing there. If it does find something, that lowers confidence.
9. **Apply the verdict rules** (`src/app/verdict.py`). These thresholds are fixed and are the same for every run.
   - **CAN'T TELL**, with the reason given, unless all of these hold: at least 20 usable controls, at least 20 ten-day bins before the event, at least 3 after, and a good enough fit before the event.
   - **CAN'T TELL** also if the controls themselves moved at the event date. That means the event was bigger than the 12 km ring.
   - **REAL** needs all three of: the 90% interval excludes zero in the claimed direction, the effect is at least 0.05 index units (or 1.0 dB for radar), and the in-space placebo p is ≤ 0.10.
   - **NOT REAL** needs the interval to rule out an effect that big.
   - Anything else is CAN'T TELL.
10. **Ring vs wide mode.** If the ring's controls moved too ("controls shifted"), "auto" mode can re-run against controls 20–150 km away ("wide" mode).
11. **Save and serve.** The result is saved as `data/runs/<id>.json`. It is served at `/v/<id>` with a chart, before/after imagery, receipts, placebo results, a Markdown report and the raw JSON.

**Live runs vs full runs.** A run a visitor starts on the site uses the memory-light "live" profile. It reads your area at 10 m, but the controls at 40 m and from a separate satellite-image search. The showcase and validation runs use "full" mode: everything at 10 m, from the same scenes. Live verdicts are labelled "quick check" for this reason (METHOD.md §9).

### The air (ULEZ) method, step by step

Source: `docs/AIR_METHOD.md` and `src/app/air/`. **It is on main but switched off. It has been reviewed (DECISIONS.md) but not validated.**

1. **Pick a registered case, not a drawn area** (`src/app/air/cases.py`). There are three:
   - Central ULEZ, 8 Apr 2019 (analysis from 8 Mar 2018).
   - Inner-London expansion, 25 Oct 2021. Always forced to CAN'T TELL, because too little clean data exists between COVID and the expansion.
   - London-wide expansion, 29 Aug 2023. Analysis from 19 Jul 2021, covering only the newly added outer area.
2. **Fetch hourly NO₂.** London monitors come from LAQN (Imperial) and control monitors in other UK cities from DEFRA AURN. Weather comes from ERA5 (via Open-Meteo), and the official zone boundaries from the GLA (`src/app/air/providers.py`).
3. **Quality control, hourly → daily → weekly.** A station must have at least 80% coverage both before and after the policy date. Every rejection gets a receipt.
4. **Keep roadside and background monitors separate throughout.** If the two groups disagree, the verdict is CAN'T TELL.
5. **Adjust for weather** (`weather.py`). A ridge regression for each station is fitted **only on data from before the policy**.
6. **Fix the London group of monitors.** Their levels are lined up on their pre-policy average. A week is used only if at least 80% of that fixed group reported.
7. **Pick controls of the same type from outside London.** Drop control cities that had their own clean-air zone during the window. This check is described in the code as incomplete.
8. **Estimate with the same synthetic-control method as land**, plus a conformal interval with a wider search suited to NO₂'s units (µg/m³).
9. **Run placebos.** Each placebo is a group of non-London stations the same size as the London group. It re-selects its own controls and tuning from scratch. At least 19 valid placebo groups are needed.
10. **Run further checks:** a pre-trend test (13 weeks leading into the date), fake earlier policy dates, leave-one-station-out, and removing the most influential controls.
11. **Apply the verdict rules** (`analysis.py`).
    - **REAL** needs all of: ≥12 controls, ≥52 weeks before, ≥8 weeks after, ≥19 placebos, an interval entirely below zero, a fall of at least 1.0 µg/m³, and placebo p ≤ 0.10.
    - **NOT REAL** if the interval rules out a fall of 1.0 µg/m³ or more.
    - Otherwise **CAN'T TELL**.
12. **Only then attach the published ULEZ studies** for comparison. The estimator code never reads them.

---

## 2. Repo map

### Top-level documents

| File | What it is |
|---|---|
| `CLAUDE.md` | Rules for AI agents. Read `SPEC.md` first, never touch `DONOTREAD/`, no invented numbers, log decisions. |
| `SPEC.md` | The original brief: a land-change verdict app, with its audience, the idea of "sick" quality, scope and the definition of done. |
| `SPEC-v2.md` | Expansion to several signal types: a plugin refactor, then air, then later signals. Codex added a "status" paragraph at the top on the branch. |
| `WORKFLOW.md` | How Claude (architect/reviewer), Codex (implementer) and grunt (routine code) split the work, plus non-negotiable rules. |
| `ULEZ-DESIGN.md` | Your proposal for a better ULEZ design (roadside-minus-background, ramp instead of step, COVID-free windows). **Not implemented.** |
| `DECISIONS.md` | The project's memory: every significant decision, the CRITIQUE triage table, and HANDOFF sections. |
| `HANDOFF-CODEX.md` | Codex's handoff for the air branch. |
| `CRITIQUE.md` | An independent critical review: 23 issues, triaged in DECISIONS.md. |
| `PLAN.md` | The original milestone plan. |
| `SITES.md` | The known-answer candidate sites, with sources. |
| `REFERENCES.md` | Citations. The air citations were added on the branch and **have not been checked against the papers**. |
| `README.md` | The public face. On the branch, Codex rewrote the intro to present air as a live second signal. |
| `DEPLOY.md` | A beginner's deploy guide (Render free tier, and why Hugging Face is no longer free). |
| `Dockerfile`, `render.yaml` | Container and Render blueprint. `main` auto-deploys. |
| `.github/workflows/tests.yml` | Runs the test suite on GitHub. |
| `.github/workflows/hf-sync.yml` | Mirrors to a Hugging Face Space if a token is set. Hugging Face now needs a paid plan for that. |
| `Makefile`, `requirements*.txt` | Build and dependencies. `requirements-validation.txt` (branch) pins the versions Codex tested with. |

### `src/app/`: the land app (main)

| File | Responsibility |
|---|---|
| `server.py` | FastAPI backend. Live runs as background jobs (1 at a time), permalinks, showcase, track record, batch, share previews. On the branch it also has air routes and an air worker. |
| `run.py` | One verdict end to end: fetch → bin → donors → estimate → placebo → verdict. Handles ring/wide/auto modes and the live/full profiles. |
| `fetch.py`, `providers.py`, `extract.py` | Satellite image search and pixel reads, memory budgets, per-area statistics. |
| `s2.py`, `s1.py` | Cleaning for optical and radar data, including the receipts. |
| `geometry.py` | Polygon checks, area limits, the grid of candidate control cells. |
| `covariates.py`, `donors.py` | Land cover and elevation, and control selection. |
| `prep.py`, `series.py` | Binning into the matrix the estimator uses. |
| `estimator.py` | Augmented synthetic control, conformal interval, placebos in space and time. **The shared core; air uses it too.** |
| `verdict.py` | Fixed thresholds that turn the numbers into REAL / NOT REAL / CAN'T TELL. |
| `evidence.py` | Weighs optical against radar evidence. |
| `imagery.py`, `pixels.py`, `breakdate.py` | Before/after thumbnails, a pixel-level change test, and a "when did it change?" mode. |
| `report.py` | The Markdown report for a run. |

### `src/app/air/`: added by Codex (on main, switched off)

| File | Responsibility |
|---|---|
| `cases.py` | Registered ULEZ cases (dates, geometries, horizons) and the published answer keys, kept away from the estimator. |
| `models.py` | Station identity, type, and the dates each station was active. |
| `providers.py` | LAQN, DEFRA AURN, ERA5/Open-Meteo, GLA boundaries, an HTTP cache, daily and weekly aggregation. |
| `weather.py` | Weather adjustment fitted before the policy only. |
| `analysis.py` | Fixed monitor groups, control matching, the estimator, placebos, pre-trend and sensitivity checks, verdict rules. |
| `run.py` | Runs a case end to end, writes receipts and IDs that never change, then compares with the studies afterwards. |

### `src/` (top level): the original CarbonTwin

Most of this is **not used by the app**. `scm.py`, `inference.py`, `audit.py`, `spectral.py`, `contract.py`, `adapter.py` and `monitor.py` are the older hackathon engine. `carbon.py`, `actuary.py` and `portfolio.py` are the carbon-credit pricing layer, which the SPEC keeps out of the product. `radar.py`'s tillage channel is **simulated**. `synth_data.py` makes synthetic test data.

### `scripts/`

| Group | Scripts |
|---|---|
| Land validation | `run_sites.py` (showcase and known-answer runs), `power.py` (detection power), `redteam.py`, `track_record.py`, `method_tables.py` (generates the table in METHOD.md; a test fails if the table drifts), `refresh_verdicts.py`, `calibration.py`, `validate_app.py`, `compare_profiles.py` (live vs full; results on another branch) |
| Blind validation | `blind_sample.py` (seeded draw), `blind_validation.py` (runner; resumable, per-item processes), `blind_review_prep.py`. Results: `showcase/blind_v3/`, report `docs/BLIND_VALIDATION.md`. |
| Ops | `memtest.py`, `desktop_screenshots.py`, `fetch_area.py` |
| Air (branch) | `run_air_case.py`, `air_known_answers.py`, `air_redteam.py`, `air_power.py` |
| Legacy CarbonTwin | `render.py`, `run_on_the_day.py`, `run_real_s2.py`, `validate.py`, `breakdate_demo.py`, `pixel_change.py` |

### `web/`: the frontend (plain HTML/JS, no build step)

- `index.html` + `landing.js/.css`: the map and draw screen, and the showcase list. On the branch it gains a Land / Air pollution tab.
- `verdict.html/.js` + `chart.js`: the verdict page.
- `track.html/.js`: the track-record page.
- `batch.*`: several areas at once.
- `mobile.css/.js`: the bottom-sheet layout for phones.
- Codex added `desktop.css`, `evidence.css`, `favicon.svg` and `air_render_test.mjs`.

### Other folders

- `showcase/`: 11 committed full-mode land runs plus thumbnails, `index.json` (the landing list) and `track_record.json`. On the branch, also `air_power_synthetic.json` and `air_redteam.json`, both copied over from the older v2.2 archive.
- `docs/`:
  - `METHOD.md` (land) and `AIR_METHOD.md` (air, still titled v2.2).
  - `REDTEAM.md`: the land self-attack, with numbers.
  - `LIVE_RUNS_DESIGN.md`: the hosting analysis.
  - `AIR_REDTEAM_REPORT.md` and `AIR_V2_2_RELEASE.md`: inherited history.
  - `validation/air-ulez-2026-09-25/`: Codex's ULEZ run files and logs.
  - `screenshots/`.
- `tests/`: 47 test files. `test_air_*.py` are from Codex. `test_redteam.py` deliberately encodes known weaknesses as "expected failures", so fixing one makes its test flip.
- `assets/`: demo PNGs from the CarbonTwin era.
- `DONOTREAD/`: licensed data and private notes. It is **not in this checkout**, and must never be read or committed.

---

## 3. Current state (updated 1 Oct 2026)

### Branches

| Branch | State |
|---|---|
| `main` | Deployed. Land app under **method v2** (merged 1 Oct), with air switched off (`APP_AIR_ENABLED=0`). |
| `codex/air-ulez` | The working branch. Everything on main plus work in progress; merged to main after each published step. |
| Older `track/*`, `wip-*`, `claude/*` branches | Merged or superseded. Don't merge them; they conflict in the UI files. |

### What's deployed

- **Live site: https://otherwise-r1vd.onrender.com.** Render free tier (512 MB RAM, 0.1 CPU). Every push to `main` redeploys it.
- Every showcase run, the power table and the blind validation use method v2 (`DECISIONS.md`, 30 Sep 2026).
- **Live runs now finish on the free host for small areas.** On 30 Sep a 29 ha live run took 18 minutes against the 40-minute limit, after the control-area reads moved to Planetary Computer's data API. This is one measurement on one small area. Large areas and wide mode on the live host are untested.
- Land only: the air tab is hidden and `/api/air/*` returns 404.

### What's tested

| Check | Result |
|---|---|
| Full test suite (with browser tests) | 545 passed, 1 expected failure |
| Known-answer sites (METHOD.md §10) | 8 documented events: **5 REAL, 0 missed, 3 CAN'T TELL**. 2 no-change sites: **0 false alarms, 2 CAN'T TELL**. **None confirmed by you yet.** |
| Detection power (METHOD.md §10, the product's real verdict rules) | NDVI: 0/20 false alarms; −0.05 detected 3/20, −0.10 10/20, −0.20 15/20. Radar VH: 0/20 false alarms; −1 dB 6/20, −2 dB 18/20. One test area (Midlands). |
| **Blind validation v3** (`docs/BLIND_VALIDATION.md`) | 247 items drawn by script (seed 20260918), all run. Events: **69/130 REAL (53%, 95% CI 45–61%)**, 6 missed, 55 CAN'T TELL. Controls: **1/117 false alarm (0.9%, CI 0.2–4.7%)**, 78 correct, 38 CAN'T TELL. Tropical forest 5/23 detected. Forest loss and US wildfire only. |
| Speed-ups | S2 read 13x faster with bit-identical outputs; live control reads moved to the PC data API (CPU per scene ~10 s to ~0.03–0.07 s; values match the local read to ~1e-4 NDVI / 0.001 dB in almost all cells). |
| Air | Switched off. No completed ULEZ result; no false-alarm or power test for the current version. |

### Half-finished

1. **Air** (switched off): LAQN download timeouts, its own known-answer set and false-alarm test, and a decision on `ULEZ-DESIGN.md`.
2. **Live vs full comparison** was measured before method v2 and before the remote reads (9 of 10 agreed). It should be re-run.
3. **REDTEAM.md numbers** were measured before the fixes and not re-run; its status note says so.
4. **Human blind review**: the review page exists, but nobody has reviewed any cases.
5. **The SPEC-v2 "plugin" refactor**: not done.

## 4. Known weaknesses and open decisions

### Method weaknesses in the land product as shipped

1. **Many runs end in CAN'T TELL.** 42% of blind events and 33% of blind controls. That is the method refusing to guess, not a wrong answer, but it limits usefulness, above all in the tropics (5 of 23 tropical events detected), where cloud leaves too few clear observations.
2. **The 4x rule** (CRITIQUE #1). It skips the pre-fit check when the effect is at least 4x the pre-event error. It was added after it blocked Grünheide. Grünheide and Rhodes still pass only through it, and their pages say so. It can also be reached on null cells (REDTEAM E6, open).
3. **The one blind false alarm** had the minimum 20 pre-event periods, so no fake-date test could run. A candidate rule (require a fake-date test before REAL) is logged in DECISIONS and must be tested on fresh data, not applied to this run.
4. **Nearby cells aren't independent** (CRITIQUE #5). Rhodes' controls sit in a few clusters.
5. **Wide mode and live mode lose co-observation** (CRITIQUE #6). Controls come from different scenes and, in live mode, at 40 m.
6. **The Rhodes and Sindh wide-mode radii were set by hand.** A user can't reach that configuration.
7. **Coverage.** Validated on forest loss and US wildfire only. Floods, construction, regrowth and UK sites have no blind validation; flooding is marked experimental in the UI.

Fixed in method v2 (no longer weaknesses): the placebo fairness bug (CRITIQUE #4), pre-trends called REAL (E5), short floods deleted as haze (E7), the in-time placebo leak, the centroid-measured spillover buffer (#16), the evidence sentence outrunning the verdict (E9), and a power table that didn't use the real rules (#9).

### Air weaknesses

- **No completed ULEZ result exists.**
- **Method reviewed, but not red-teamed.** The architect triage is in DECISIONS.md ("Codex air changes: triage"): 11 items, 7 valid, 4 partly valid, 0 wrong. The adversarial pass WORKFLOW.md requires has not been done.
- **One confounder can't be identified from this data.** A London-only shock starting on exactly the policy date would look like a policy effect.
- **Your `ULEZ-DESIGN.md` proposes a different design.** It would change the method, so it needs a decision.

### Hosting / CPU

- **Small live runs now fit the free tier.** Measured: one 29 ha run in 18 minutes on Render; locally, parent plus job process peaked at about 382 MB under a 512 MiB cap.
- **Untested on the live host:** large areas, wide mode, and several visitors at once (there is one job slot).
- **Long offline runs** (validation, showcase) only progress while this cloud session is awake. A machine that stays on, such as a GitHub Actions workflow for owner-triggered batch work or your laptop, would make them reliable.

### Open decisions (yours)

1. Confirm, or reject, the 10 known-answer sites.
2. Where long offline runs should live (GitHub Actions, your laptop, or paid compute).
3. Whether to adopt the `ULEZ-DESIGN.md` approach for air, and when air is switched on (bar: its own known-answer set and false-alarm test).
4. Codex's V6 UI pass: it isn't on the remote.

---

## 5. What you can and can't claim today

### Claims you can make

- "Otherwise builds a matched counterfactual for a drawn area from Sentinel-1 and Sentinel-2 data (augmented synthetic control, conformal intervals) and runs placebo tests on untouched places and on fake earlier dates for every verdict."
- "In a blind test of 247 cases drawn by script before any were run, it called 69 of 130 real forest-loss and wildfire events REAL (53%), and raised 1 false alarm on 117 untouched controls (under 1%). It answered CAN'T TELL rather than guess in 42% of events." Say what it covers (forest loss and US wildfire), and that tropical forest is its weak spot.
- "On 10 candidate known-answer sites: 5 of 8 documented events detected, 0 false alarms on 2 no-change sites, the rest CAN'T TELL." Say they are **candidates**.
- "Its own red team found two ways to break it; both are fixed and every published result was re-run under the fix." Then point to REDTEAM.md, and say its numbers predate the fix.
- "A stranger can draw a small area on the live site and get a verdict in about 18 minutes on a free server." This is one measurement on a 29 ha area; don't promise it for large areas.
- "Every discarded observation is logged with a reason, every verdict has a permanent link and a report, and every rate is shown with its interval and count."
- Engineering stories that are true and documented: a 13x read speed-up with bit-identical outputs, found by profiling; moving image decoding to the data provider so live runs fit a 0.1-CPU server; pre-registered fixes and a pre-registered blind sample.

### Claims you can't make yet

- ✗ Accuracy on **floods, construction, regrowth or UK sites**. None of those were in the blind sample.
- ✗ That it **works well in the tropics**. 5 of 23 tropical events were detected.
- ✗ That the **known-answer sites are confirmed**. You haven't confirmed them.
- ✗ That **live runs equal published runs**. They are a quick check at coarser resolution, and the live-vs-full comparison predates method v2.
- ✗ That **live runs are fast for any area**. Only a 29 ha run has been timed on the live host.
- ✗ **Anything about ULEZ or air pollution** as a working feature.
- ✗ "No public tool does this." Say "I didn't find a public tool that…".
- ✗ Any number not traceable to a committed file (`docs/METHOD.md` §10, `showcase/track_record.json`, `showcase/blind_v3/summary.json`).

**Before posting anything,** check that the claim appears in the first list, that its number is in `docs/METHOD.md` §10, `showcase/track_record.json` or `docs/BLIND_VALIDATION.md`, and that the link you're sending opens a full-mode showcase run, not a live one.
