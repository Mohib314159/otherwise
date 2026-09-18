# SPEC — "Did it really change?" (working name, rename freely)

## What we're building
A public web app. You draw an area on a map, pick a date and say what supposedly happened ("forest cleared here in March 2024", "this field flooded", "restoration started"). The app pulls free Sentinel-1 (radar) and Sentinel-2 (optical) time series for that area, cleans them, compares the area with matched control areas that *didn't* get the event, and returns a clear verdict: **real / not real / can't tell**, with the evidence behind it.

It grows out of my existing project, CarbonTwin (this repo): satellite optical + radar time series, fixing calibration changes, filtering contaminated observations, and testing whether an apparent effect survives against matched controls. Reuse its logic wherever it helps. Improve it if you see a better way, but tell me what you changed and why.

### What's already in this repo (read before planning)
- **Reusable core:**
  - `scm.py`: synthetic control with convex weights.
  - `inference.py`: Abadie placebo permutation test plus Benjamini-Hochberg false-discovery control. This is the placebo check, already built.
  - `audit.py`: five verdicts (VERIFIED / PARTIAL / INCONCLUSIVE / REJECTED / BASELINE).
  - `spectral.py`: Sentinel-2 index stack, with the Baseline-04.00 harmonisation fix.
  - `contract.py`: `Dataset` / `FieldSeries`, and a latitude-aware off-season mask.
  - `adapter.py`: loaders from Sentinel-2 zarr, CSV and GeoTIFF into a `Dataset`.
  - `monitor.py`: detects onset and reversal of an effect.
- **Caveats:**
  - `radar.py`'s tillage channel is **simulated**, not real Sentinel-1. The app needs a real Sentinel-1 path.
  - The demo so far ran on synthetic data (`synth_data.py`) and a hackathon-provided cube. The app must use only open data.
- **Out of scope for the app:** `carbon.py`, `actuary.py` and `portfolio.py` (tonnage bands and pricing). Leave them in the repo, but keep them off the product.
- **Adapt to a draw-any-area app:** the engine is currently built around fields and parcels. Treated area = the drawn polygon; donor pool = comparable nearby areas the app selects automatically.

**One-line pitch:** existing tools tell you *something changed*. This tells you whether it changed *more than it would have anyway*.

## Who it's for
- **Primary:** people at UK space and Earth-observation companies I'm cold-emailing (Sylvera, Satellite Vu, Open Cosmos, Earth Blox, ESA Harwell, etc.). They click a link in my email and need to get it in about 15 seconds.
- **Real-world users it should credibly serve:** carbon-credit checkers, journalists and researchers who want to know whether a claimed land change actually happened.
- **Key workflow:** before each email I run the tool on something relevant to that person and send them a permalink to the verdict page. Permalinks matter a lot.

## What "sick" means here
- **Product first.** You land on a map and can use it immediately. No essay. The method explanation sits behind a toggle or "how this works" drawer.
- **The verdict page is the hero:** a big verdict plus a confidence statement, a chart of the area's actual trajectory vs the no-event (control) trajectory with the event date marked, before/after imagery, and a "receipts" panel listing which observations were thrown out and why (cloud, calibration change, orbit mismatch, and so on).
- **Placebo check on every verdict:** rerun the same test on fake event dates and/or nearby untouched areas, and show how often the method "finds" an effect that isn't there. This is the trust feature. No public tool I've found shows it.
- **Fast first impression:** 3–4 precomputed showcase examples load instantly from the landing page. Live runs on new areas can take longer, but need honest progress feedback.
- **Visible care in every detail.** No generic AI-dashboard look, no filler copy, no fake numbers. It should feel designed by someone who cares about the user.

## Scope
- **Change types:** vegetation and land-surface change (clearing, regrowth, flooding, burn scars, construction). Not "any event imaginable".
- **Data:** open Sentinel-1 and Sentinel-2. Microsoft Planetary Computer STAC (its Sentinel-1 RTC product saves a lot of radar preprocessing) or Copernicus Data Space. You choose.
- **Limits:** a sensible maximum polygon size and date range so runs stay feasible. You pick the numbers.
- **Method:** you design the details (control selection, matching variables, estimator, uncertainty, verdict thresholds). Constraints:
  - It must be defensible to someone who does this professionally. If "can't tell" is the honest answer, say "can't tell".
  - Validate it on known-answer cases: at least one documented real clearing or disturbance, one documented flood, and one site where nothing happened. Propose the specific sites with sources, and I'll confirm.
  - Automated tests for the known-answer cases and the placebo check.

## Prior art (cite it in the "how this works" section; know how we differ)
- **PWTT, Ballinger:** Sentinel-1 pixel-wise t-test for building damage; draw-an-area web app. Compares each pixel only with its own history, with no matched controls. https://github.com/oballinger/PWTT
- **Cambridge 4C PACT / tmf-implementation:** pixel-matching counterfactuals for tropical forest carbon. Command-line only, runs on the JRC forest-cover map rather than raw imagery. https://github.com/quantifyearth/tmf-implementation
- **Placebo evaluation of counterfactual methods (4C, 2025):** the idea behind our placebo check. https://github.com/epingchris/placebo_evaluation
- **Pachama dynamic baselines (commercial), Global Forest Watch (stats for your own area, no counterfactual), CTrees LUCA (radar alerts), Earth Blox (paid no-code platform).**

## Ideas to consider (your call whether and how)
- **Control selection is the hardest problem.** My starting hypothesis is a three-stage approach:
  1. **Shortlist** candidate controls by landscape similarity. One option: the AlphaEarth Foundations Satellite Embeddings (Google/DeepMind; 64-dim, 10 m, annual 2017–2025; CC-BY 4.0; COGs on Source Cooperative, AWS Open Data and GCS, so no Earth Engine needed). Use **pre-event years only**, because post-event embeddings already contain the change. Other shortlist options are land cover, terrain and distance-to-features covariates, as in 4C PACT. The two can also be combined.
  2. **Weight** the shortlisted controls with the existing synthetic control on the pre-event outcome series.
  3. **Exclude** controls too close to the treated area, since nearby land can be affected too (`pipeline.run_audit` already has a `buffer_m` for this).
  
  Test the alternatives against each other with the placebo check and the known-answer cases (the 4C placebo paper does this kind of comparison), and keep whichever holds up best. If you find a better approach, use it. Attribution for AlphaEarth, if used: "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind." The embedding-retrieval idea mirrors my JeansFinder project (CLIP similarity search), which is a nice story, but only if it actually performs.
- **Public track-record page:** run the tool on roughly 15–20 events with known answers (real disturbances, floods, and areas where nothing happened) and publish its hit rate and false-alarm rate, misses included.

## Deployment (important: I've never deployed anything)
- Pick the simplest setup that works on free or near-free tiers, and explain each step to me as a first-timer.
- Ideally: push to GitHub → it deploys automatically. One public URL.
- Heavy processing belongs on a backend, not in the browser. If free tiers can't handle live runs, say so and propose the cheapest honest option (a job queue, cached results, or limiting live runs).
- Include a short DEPLOY.md I can follow alone, plus how to add a new showcase example.
- Keep secrets out of the repo.

## How I want to work with you
- **You have broad autonomy.** You're the lead engineer and methodologist. Make the architecture, method, library, data-source, design and hosting decisions yourself, and change your mind when the evidence says so. This spec states goals and constraints, not instructions. Where it conflicts with a clearly better approach, take the better one and tell me why.
- Start with a short plan: architecture, method outline, data and hosting choices, and the biggest risks. Then keep going. Don't wait for my approval between milestones.
- Build in milestones, each ending in something that runs, committed to git with a clear message:
  1. Data in and cleaned for one area
  2. Verdict and placebo computed, known-answer tests passing
  3. Verdict page and map UI
  4. Showcase examples, permalinks and the track-record page
  5. Deployed at a public URL
- Keep a running `DECISIONS.md`: one or two lines per significant decision and why, so I can understand and defend the project in interviews.
- **Only stop and ask me** for things that need me personally: creating accounts, anything that costs money, putting something public under my name, or confirming the known-answer sites.
- Hard rules: no invented numbers or claims anywhere in the app, README or copy; if a result is weak, say so; never touch `DONOTREAD/`.

## Done =
A public URL where a stranger can open a showcase verdict in under 5 seconds, draw their own area and get an honest verdict with receipts and a placebo check, and share the result as a permalink. The code is in my GitHub with a README a recruiter can skim in 30 seconds.
