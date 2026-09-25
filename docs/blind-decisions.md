# Blind validation and blind review — decisions

Decisions taken on the blind-validation track (Track D), with the reasoning, for
folding into `DECISIONS.md`. Nothing in this file is a projection: where a number
appears, it is a count of something that exists on disk at the commit named.

## Why this track exists

The known-answer track record is 9 counted sites with 4 clear REALs, all chosen
by us. That is enough to show the method works at all and nothing more. A
reviewer who does this professionally will ask two questions it cannot answer:
how does the tool behave on events *nobody picked*, and how much of the
"can't tell" pile is actually obvious to a human looking at the pictures? The
second question cannot be answered by the owner looking at sites whose answers
he already knows — that is why the review mode is blind.

## Sampling

- **Seeded and scripted, never hand-picked.** `scripts/blind_sample.py` draws
  from fixed dataset releases with `numpy.random.default_rng([seed, stage])`,
  one independent substream per stage (Hansen events 1, Hansen controls 2, MTBS
  3). Seed **20260918**. Because the stages are independent substreams, the
  datasets can be drawn in separate invocations and merged
  (`scripts/blind_merge.py`) and the result is what one combined run would have
  produced. The merge refuses draws with different seeds or duplicate ids.
- **Controls by the same mechanical rule as events**, never chosen for being
  easy: same tiles, same band design, box size drawn from the accepted events'
  sizes, placed uniformly where `treecover2000 >= 50` over the whole box and no
  mapped Hansen loss 2001–2023 in the box or a 300 m buffer. MTBS controls are
  boxes of the same sizes 10–120 km from a sampled fire, at least 5 km from
  *every* MTBS perimeter of any year.
- **Stratification** is by construction rather than by quota: tile (nine tiles
  spanning eastern Amazonia, the Congo basin, Borneo/Java, Central America,
  central Europe, the Pacific North-West, Siberia, the Río de la Plata region
  and New South Wales), loss year 2018–2023 drawn uniformly, and size bucket
  (<50 ha, 50–150 ha, >150 ha) as a reported cross-tab. Climate class is a fixed
  per-tile mapping, stated in the sample file, not a per-item judgement.
- **Polygon sizes stay inside the app's limits** (`MIN_AREA_HA = 0.5`,
  `MAX_AREA_HA = 500` in `src/app/geometry.py`, unchanged): components are kept
  between 20 and 400 ha and the box is capped at 400 ha.
- **Hansen dates are years, not days.** The event date given to the tool is
  `<year>-01-01` with `post_months = 18`, which is a real handicap: a clearing
  in November contributes two months of post-event signal to an 18-month
  average. It is reported as a property of the label, and MTBS (day-precision
  ignition dates) is in the sample partly as a control for exactly this.
- **Sources used:** Hansen Global Forest Change GFC-2023 v1.11 (clearing) and
  MTBS burned-area perimeters (burn). **Considered and not used:** Copernicus
  EMS rapid mapping (per-activation archives, no programmatic index to sample
  from), EFFIS/GWIS (download endpoint redirects to an interactive form, WFS
  endpoint timed out from this environment on 2026-09-18), JRC Global Surface
  Water (bucket reachable, but the change and transitions layers carry no event
  year; the yearly-classification product would and is the obvious next
  addition). **Consequence: no water or flood events are in the blind sample**,
  so the blind numbers say nothing about floods.
- `scripts/blind_sample.py` needs `pyshp` for the MTBS shapefile, which is not
  in `requirements.txt` (it is a sampling-time dependency, not an app one).
  Worth adding to a dev requirements file.

## Running the sample

- **Locally, never against the deployed server.** Runs go through
  `src.app.run.run_verdict` in a worker process per item, with an on-disk cache
  (`APP_CACHE_DIR`), because the free Render tier has 512 MB and another track
  was fixing exactly that.
- **Checkpoint after every single item**, and resume from what is on disk:
  one JSON line per item in `showcase/blind/results.jsonl`, plus the run JSON
  under `showcase/blind/runs/`. On restart the runner adopts any cached run
  whose row is missing or an error, so work is never redone or lost. This
  mattered: the session was cut off mid-batch and 29 finished runs were
  recovered from their run JSONs afterwards, with no refetching.
- **Seeded random run order** (`--shuffle-seed`, recorded as `run_order_seed`
  in `summary.json`). A run of 247 items at roughly eight minutes each will
  always be stopped part-way, so the order decides what the finished subset
  *is*. A seeded shuffle makes it a random subsample of the draw; file order
  would have meant "all events, no controls" — which is exactly the bias the
  first batch has, because it was launched before this option existed.
- **The numbers are tied to a commit.** The fetch and estimator path was being
  changed in parallel, so `summary.json` and the doc record both the commit the
  sample was drawn at and the commit the runs were scored at.

## Blind review

- **Blinding is enforced in the payload, not in the page.** `blind_payload` in
  `src/app/review.py` builds the reviewer's JSON from an explicit whitelist, so
  a new field added to the pipeline later cannot leak by accident. Hidden: the
  ground truth, the tool's verdict and every number behind it (effect,
  interval, placebo p, placebo band), the label, the site, the change type, the
  signal name, the polygon and its coordinates, the absolute dates, the run id
  and the item id. Shown: the two thumbnails, the time-lapse frames, and the
  observed/control trajectories and their gap on a **relative day axis** with
  day 0 as the claimed date, under a neutral axis label ("Surface index
  (unitless)" or "Radar backscatter (dB)").
- **Opaque case ids.** A case is addressed as `sha256("otherwise-blind:<seed>:<item id>")[:12]`,
  including its images (`/api/review/case/<case id>/before.png`), so nothing in
  a URL, a filename or a page title carries the answer.
- **Blinding is procedural, not cryptographic**, and the docs say so: the
  sample and the results are public in this repo, so a reviewer who wanted to
  cheat could recompute the mapping. The instrument stops the answer arriving by
  accident; the protocol asks the reviewer not to go looking. This is the
  standing assumption of visual-interpretation reference data generally.
- **The human sees the tool's charts**, not only the imagery. That is a
  deliberate choice — it matches the workflow the app is for — and it means
  "human alone" is *human with the tool's charts and no verdict*, not a pure
  photo-interpretation baseline. Stated as such wherever the number appears.
- **Per-session order and no repeats.** Each reviewer gets a session id and a
  shuffle seeded by it, stored with the session; an answered case is never shown
  again in that session; several people can review independently and
  `by_session` keeps them separate.
- **Answers live in SQLite** at `APP_REVIEW_DB`, defaulting inside the runs
  directory (which is git-ignored), not in the repo: reviews are collected
  data, and publishing them is a separate, deliberate act.
- **A test proves the payload is blind.** `tests/test_app_review.py` asserts
  that neither `blind_payload` nor `GET /api/review/next` contains any of a list
  of giveaway keys and values (`expected`, `REAL`, `CANT_TELL`, `verdict`,
  `status`, `placebo`, `change_type`, `event_date`, the label, the coordinates,
  the signal name, the run id, the item id). The payload key `axis` is
  deliberately not called `axis_label`, so that the word "label" can be
  forbidden outright.

## The three numbers

- **Reported separately, each over its own denominator**, with a **95% Wilson
  score** interval (small denominators, rates near 0 and 1, where the normal
  approximation leaves the unit interval).
- **"Tool + human" = the tool decides; the human adjudicates its CAN'T TELLs.**
  Where the tool returns REAL or NOT REAL its call stands, because it carries a
  placebo test and an interval that an eye does not; where it declines, the
  human's call is used; if the human is unsure too, the pair stays CAN'T TELL.
  Chosen over an agreement rule because it is the workflow the product is
  actually for (an analyst triaging what the tool could not settle) and because
  it cannot change the tool's answer on the cases it did decide, so any
  difference between "tool" and "tool + human" is attributable to the
  adjudication alone. The rule is printed on the page next to the numbers.
- **An empty column says it is empty.** With no reviews recorded, the human and
  tool + human cards read "No blind reviews recorded yet" and the false-alarm
  row reads "not measured"; no placeholder rate is ever rendered. The same
  holds in `docs/BLIND_VALIDATION.md`.

## State at the end of this track's session (commit `6d8776d`, runs recorded at `fc65e7d`)

- Drawn: **130 events** (115 Hansen clearing, 15 MTBS burn) and **117 controls**
  (115 Hansen no-loss, 2 MTBS) — the MTBS control draw was cut off after 2 of an
  intended 15, so the draw is not balanced.
- Finished verdict runs: **34**, all of them event items; **18** REAL, **1** NOT
  REAL, **15** CAN'T TELL. Six further event items were attempted and produced
  no verdict (killed mid-run, recorded as timeouts). **No control item has been
  run**, so the false-alarm rate is not measured.
- Blind reviews recorded: **0**. No case has imagery rendered yet
  (`scripts/blind_review_prep.py` exists and was not run), so the review pool is
  empty and the page says so.
- Not yet defensible, and known: 34 event runs and no controls is not a blind
  test, it is the first third of one; the can't-tell share (15 of 34) is large
  and its causes are per-run in the JSONs but not yet tabulated; floods are
  absent from the sample; and the human numbers do not exist at all.
