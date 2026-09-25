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
| Blind validation | `blind_sample.py` (on main). The runner and review-prep scripts are on another branch. |
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

## 3. Current state

### Branches

| Branch | State |
|---|---|
| `main` | The land app, plus (merged 25 Sep, in this order):<br>• `claude/elegant-franklin-en2noi`: the CRITIQUE #4 symmetric-placebo fix, blind validation (`/review`) and the live-vs-full comparison<br>• `codex/air-ulez`: the air/ULEZ pipeline **switched off** (`APP_AIR_ENABLED=0`), Codex's desktop UI, the `p=1.000` fix, and the README/DECISIONS honesty fixes |
| `codex/air-ulez` | Same content as `main` after the merge. Keep developing air here. |
| `claude/elegant-franklin-en2noi` | Fully merged. |
| `track/ui-honesty`, `track/live-runs-design`, `track/blind`, `wip-blind`, `wip-design` | Older work branches. Their useful content reached main through `elegant-franklin`. Don't merge them now: they conflict in the UI files. |
| `track/hectare`, `track/mobile`, `design`, and other `claude/*` | Already merged. |

### What's deployed

- **Live site: https://otherwise-r1vd.onrender.com.** Render free tier (512 MB RAM, 0.1 CPU, sleeps after 15 idle minutes). Every push to `main` redeploys it.
- Land only: the air tab is hidden and `/api/air/*` returns 404.
- New runs use the symmetric placebo. The committed showcase runs predate that fix, so their pages and reports carry an "older placebo procedure" caveat until they are re-run.
- The GitHub → Hugging Face sync workflow fails on every push because its secrets are empty. It deploys nothing, and is harmless but noisy.

### What's tested

| Check | Result |
|---|---|
| Full suite on this branch, with browser tests (**re-run today**) | 328 passed, 8 expected failures, 0 skipped |
| Full suite on `main`, same setup (**re-run today**) | 280 passed, 8 expected failures |
| Air rendering test and JS syntax checks (**re-run today**) | Pass |
| Known-answer table in METHOD.md vs committed runs (**re-run today**) | In sync |
| The branch's change to the shared estimator (**checked today**) | Same results as main's version on 120 random cases, so land's numbers don't move |
| Land detection power (METHOD.md §10) | NDVI: 0/20 false alarms; −0.05 effect detected 6/20, −0.10 17/20, −0.20 19/20. Radar VH: 0/20 false alarms, −2 dB detected 20/20. **But see §4, weaknesses 1 and 4.** |
| Land known-answer sites (METHOD.md §10) | 10 sites: 4 correct REAL, 0 missed, 0 false alarms, 6 CAN'T TELL. **None confirmed by you yet** (all 10 have `"confirmed": false` in `showcase/index.json`). |
| Live vs full (on `elegant-franklin`) | 9 of 10 verdicts agree. The one disagreement (Saddleworth) goes CAN'T TELL → REAL in live mode, on noisier evidence. |
| Blind validation (on `elegant-franklin`) | 247 items drawn. 34 runs done, **all of them real events, zero control areas**. So there is a detection figure (18/34 REAL) but **no false-alarm rate**. No human review has been done. |
| Air: Codex's reported tests | 308 passed, 20 skipped, 8 expected failures on Windows; adversarial checks 6/6. |
| Air: live ULEZ runs | Both **CAN'T TELL, and neither is a completed analysis**:<br>• 2019: 0 London monitors survived, because of LAQN download timeouts. No estimate.<br>• 2023: an estimate exists, but with too few controls and **0 placebo groups**. |
| Air: false-alarm/power test for the current version (v2.3.1) | **Not run.** |

### Half-finished

1. **Placebo fix (CRITIQUE #4).** Now on main, and new runs use it. Still owed: re-running `power.py` and every showcase site under it, and publishing the results even if verdicts weaken. It takes hours per site, because the caches are gone. The in-time placebo's similar leak is not yet fixed.
2. **Blind validation.** Now on main. The runs on control areas haven't started, so there is no false-alarm rate, and nobody has reviewed anything.
3. **Air (switched off).** The LAQN downloads need to cope with timeouts, and the AURN station list includes stations that don't measure NO₂ for the years needed.
   Still to do: the known-answer set (Ratcliffe, COVID, null cities), a v2.3.1 false-alarm/power test, a decision on `ULEZ-DESIGN.md`, and justifying or removing the 3× pre-fit bypass (DECISIONS.md triage #9).
4. **The SPEC-v2 "plugin" refactor (Part A).** Not done. Air was built beside land, not through a shared plugin interface.
5. **Small UI items:**
   - The mobile sheet uses `vh` (should use `dvh`).
   - The draw hint doesn't explain how to close a polygon.
   - On a phone the landing map opens framed on the Arctic. This was already the case before the merge (`docs/screenshots/2026-09-25/`).

---

## 4. Known weaknesses and open decisions

### Method weaknesses in the land product as shipped

1. **CRITIQUE #4: the placebo test flatters the result.**
   - Controls are picked because they best match *your* area before the event. Then each of those same controls is used as a placebo, but fitted on a group chosen for your area, not for itself. It even reuses your area's tuning setting.
   - So your area gets a better-than-fair fit before the event, which makes its post/pre ratio look more unusual. **Every published land p-value is therefore too optimistic.**
   - The fix is on `elegant-franklin`: each placebo unit re-selects its own controls and tuning. The fix was written down in advance, before any results were seen.
   - On synthetic data it makes the test stricter: the median placebo ratio went from 1.259 to 1.373, and 0 of 12 no-effect panels reached p ≤ 0.05.
   - **It is not on main.** It hasn't been published, because every showcase site and the power table have to be re-run first. Each site takes hours, because the image caches are gone.
   - The in-time placebo has the same kind of leak, and is deliberately left for a separate fix.
2. **A decline that started before the claimed date still gets called REAL** (REDTEAM E5). On synthetic data with a pre-existing downward trend, the verdict came back REAL in 9 of 15 fits (−0.10/yr) and 14 of 15 (−0.20/yr). The in-time placebo notices, but it only adds a caveat.
3. **Short floods get deleted as "haze"** (REDTEAM E7). The despike filter removes 100% of the observations of a flood lasting under 20 days. On the real Sindh 2022 data it removed the three peak-flood observations.
4. **The published power table doesn't use the real verdict rules** (CRITIQUE #9). `power.py` leaves out the pre-fit, controls-shifted and in-time checks that the product applies.
5. **The 4× rule looks tuned after the fact** (CRITIQUE #1). A rule that skips the pre-fit check when the effect is at least 4× the pre-event error was added after it blocked Grünheide. The Rhodes and Sindh wide-mode radii were set by hand and a user can't reach them.
6. **Nearby cells aren't independent** (CRITIQUE #5). Rhodes' 42 controls sit in 6 clusters, so they are not 42 independent draws.
7. **Wide mode and live mode lose co-observation** (CRITIQUE #6). The controls come from different scenes and a coarser resolution than your area.
8. **The spillover buffer is measured from the centre** (CRITIQUE #16). At 200 ha and above, a control cell can share an edge with your area.
9. **Most runs end in CAN'T TELL.** 6 of the 10 known-answer sites are CAN'T TELL, and a −0.05 NDVI effect is detected only 30% of the time on the cloudiest test area.

### Air weaknesses

- **No completed ULEZ result exists.**
- **Method reviewed, but not red-teamed.** The architect triage is in DECISIONS.md ("Codex air changes: triage"): 11 items, 7 valid, 4 partly valid, 0 wrong. The adversarial pass WORKFLOW.md requires has not been done.
- **One confounder can't be identified from this data.** A London-only shock starting on exactly the policy date would look like a policy effect.
- **Your `ULEZ-DESIGN.md` proposes a different design.** It would change the method, so it needs a decision.

### Hosting / CPU problem

- **Memory is solved; CPU is not.**
  - A live land run peaked at 339 MB resident memory, and 467–471 MB counted by the container, under a 512 MiB limit.
  - It took **26 minutes for a 27 ha area** on a machine with about two cores. A wide run took **2.81 hours**.
  - Render free has **0.1 CPU**, and the job timeout is 2400 s (40 min). A live run there may never finish.
- **Live mode isn't faster.** For wide runs it was about twice as slow as full mode (10,123 s against 3,226 s, one run each). Its only advantage is memory.
- **GitHub Actions is ruled out for visitor-triggered runs.** GitHub's terms forbid using it as a serverless backend, and the penalty is account suspension. It is fine for owner-triggered batch work.
- **The options are all your call, because some cost money:**
  - (a) Set `APP_LIVE_RUNS=0` and offer "request an area"; precomputed permalinks only.
  - (b) A paid Render instance.
  - (c) Per-second compute such as Modal, with Render as a thin relay.
  - (d) A Hugging Face Space, now PRO at $9/month, which gives 16 GB RAM and could run full mode.
- The SPEC says your audience needs a verdict in about 15 seconds from an email link. That argues for precomputed permalinks over live runs.

### Open decisions (yours)

1. Hosting option (a)–(d) above.
2. Confirm, or reject, the 10 land known-answer sites.
3. When to spend the hours re-running the showcase sites under the fixed placebo.
4. Whether to adopt the `ULEZ-DESIGN.md` approach for air. This is a method call. Claude should decide it and log it, but you set the priority.
5. When air is switched on. The bar you set: its own known-answer set and false-alarm test first.

---

## 5. What you can and can't claim today

### Claims you can make

- "Otherwise builds a matched counterfactual for a drawn area from Sentinel-1 and Sentinel-2 data, using augmented synthetic control with conformal intervals, and runs a placebo check on every verdict."
- "It has three possible answers, including CAN'T TELL, and uses it often. On 10 candidate known-answer sites: 4 correct REAL, 0 false alarms, 0 misses, 6 can't tell." Say the can't-tell count in the same sentence, and say the sites are **candidates**.
- "In a detection-power test on real, untouched cells, it raised 0 false alarms in 20 no-effect cases for NDVI and 0 in 20 for radar." Add that this test used a simplified version of the verdict rules.
- "Every discarded observation is logged with a reason, and every verdict has a permanent link and a downloadable report."
- "It publishes its own weaknesses: an adversarial red-team report, an independent critique with a public triage table, and known limits in the method doc." This is true and unusual; use it.
- "The repo has a test suite of more than 280 passing tests, run on every change."
- Engineering stories that are true and documented: the live-run memory fix, found by measuring rather than guessing, and the pre-registered placebo fix written down before seeing the results.

### Claims you can't make yet

- ✗ Any claim about **how often it's right on unseen cases.** There is no false-alarm rate from blind validation (0 control runs), and the known-answer sites are unconfirmed and were partly used to shape the rules.
- ✗ That the **published placebo p-values are exact or conservative.** Every committed showcase and known-answer p-value comes from the old procedure, which is too optimistic (CRITIQUE #4). Only runs made after the 25 Sep merge use the fixed one.
- ✗ That it **detects floods reliably** (REDTEAM E7), or that REAL on a gradually declining area is trustworthy (E5).
- ✗ That **live runs match the published runs.** They are a "quick check": 9 of 10 agree, and the one that doesn't errs towards REAL.
- ✗ That a **stranger can draw an area and get a verdict** on the free host in reasonable time. CPU makes that unproven.
- ✗ **Anything about ULEZ or air pollution** as a working feature: "air is the second signal", "it reproduces the published ULEZ studies", or any ULEZ effect size. No ULEZ run has completed, the air method hasn't been reviewed, and the air citations haven't been checked. The branch README currently says more than this. Fix it before merging.
- ✗ "Multi-signal", "any signal", "any place", or "in minutes". Only land exists on main, and runs take tens of minutes to hours.
- ✗ "No public tool does this." SPEC.md says only that you didn't find one. Say "I didn't find a public tool that…".
- ✗ Any number not traceable to a committed run file. Published tables must be generated by `scripts/method_tables.py` and `scripts/track_record.py`, never typed by hand.

**Before posting anything,** check that the claim appears in the first list, that its number is in `docs/METHOD.md` §10 or `showcase/track_record.json`, and that the link you're sending opens a full-mode showcase run, not a live one.
