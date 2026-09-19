# CRITIQUE — independent senior review of "Otherwise" / carbon-twin

Read-only review of `claude/elegant-franklin-en2noi` at commit `6d8776d`. Every
claim below points at code, committed data, docs or a command I ran in this
worktree. Where I estimated rather than measured, I say so. I did not open
`DONOTREAD/`.

---

## Bottom line

**No — this would not survive a professional Earth-observation review today, and
the reason is not the memory bug.** The engineering instincts are unusually good
for a portfolio project: the counterfactual framing is the right one, the
receipts panel is a genuinely original trust feature, `docs/REDTEAM.md` is a
better adversarial self-review than most commercial teams ever write, and the
tool refuses to over-claim far more often than it over-claims.

What sinks it is that the published evidence does not describe the shipped
product. The one clean REAL on the track record (Rhodes) passes only through a
gate bypass that the repo's own red team flags as exploitable (`verdict.py:69`),
using controls 105–149 km away in a code path the red team explicitly lists as
untested, with a placebo p sitting exactly on its own arithmetic floor. The
control radii for that site and for Sindh are hand-set per site in
`scripts/run_sites.py:23,31` — a user drawing an area can never reach the Sindh
configuration. The two rules that turn a borderline case into REAL were both
committed *after* the known-answer runs they rescue (`a3cbc4b`, `f729168`), and
the held-out validation designed to fix exactly this (`scripts/blind_sample.py`)
was never run. The published power table is computed with a *different decision
rule* from the app's (`scripts/power.py:55` omits the pre-fit gate, the
controls-shifted gate and the in-time placebos). `docs/METHOD.md` §9–10
contradicts the committed showcase JSON on two of six rows. And the committed
test suite does not pass: `python -m pytest -q` aborts at collection, and with
the two uncollectable files skipped, `tests/test_known_answer.py` fails on the
committed data.

A skeptical reviewer from Sylvera or UNEP will not need to run anything. They
will read `docs/REDTEAM.md` — which is in the repo, and to the author's credit —
see "E5 … **breaks** … This is the most serious finding", check
`src/app/verdict.py:146-149`, find the fix unapplied, then check
`docs/METHOD.md` §9 "Known limits" and find that the two failures the author's
own red team calls "breaks" are not listed there. That sequence is the interview
that goes badly. Everything else on this list is fixable in days; that one is a
credibility problem, and the fix is to publish the limits and run the blind
validation, not to write more code.

---

## Ranked issues

| ID | Severity | Area | Title |
|---|---|---|---|
| 1 | BLOCKER | Credibility / method | Verdict rules and control geometry were changed after seeing the answers; no held-out validation exists |
| 2 | BLOCKER | Docs / honesty | The repo's own red team says the method "breaks" in two ways; neither is fixed and neither is in the public limits |
| 3 | BLOCKER | Deployment / memory | One scene's working set is ~half the 512 MB box, times 8 threads, inside the web process |
| 4 | MAJOR | Statistics | Donors are picked to fit the treated unit, then used as the placebo distribution — the placebo test is anti-conservative |
| 5 | MAJOR | Statistics | Spatially clustered placebo cells are treated as independent; the flagship p sits on its own floor |
| 6 | MAJOR | Method | Wide mode — the path that produced the headline REAL — breaks co-observation and mixes 10 m and 40 m support with no intercept |
| 7 | MAJOR | Statistics / copy | The "how sure" sentence reports the wrong placebo statistic |
| 8 | MAJOR | Credibility | Track-record arithmetic makes "0 misses, 0 false alarms" unfalsifiable |
| 9 | MAJOR | Statistics | The published power table does not use the app's verdict rules |
| 10 | MAJOR | Docs | Three validation tables in the repo disagree with each other and with the shipped runs |
| 11 | MAJOR | Correctness | The "control areas" map shows the wrong cells |
| 12 | MAJOR | UI / deployment | A dead live run hangs the UI forever by design |
| 13 | MAJOR | Copy / honesty | The verdict page asserts causation and over-states the placebo result |
| 14 | MAJOR | Statistics / UI | The hero number is an undocumented ratio with no interval |
| 15 | MAJOR | Code quality | The test suite is red and CI cannot have been green |
| 16 | MINOR | Method | Spillover buffer is measured centroid-to-polygon; at ≥200 ha controls touch the area |
| 17 | MINOR | Pipeline | No usable cloud pre-filter; SCL is read at 10 m despite docs saying 20 m |
| 18 | MINOR | Deployment | No rate limit, no job timeout, in-memory job state, ephemeral run storage |
| 19 | MINOR | Statistics | Interval width cap guesses its units from the pre-RMSE magnitude |
| 20 | MINOR | Reproducibility | Unpinned dependencies and a gitignored cache the validation depends on |
| 21 | MINOR | UI / mobile | The landing bottom sheet covers the map and cannot be collapsed |
| 22 | MINOR | UI | Permalinks have no share preview and every page has the same `<title>` |
| 23 | NIT | Code quality | Dead import, duplicated Docker layers, degenerate intervals rendered as precision |

---

## 1. BLOCKER — Verdict rules and control geometry were changed after seeing the answers

**What's wrong.** Three things compound.

*The pre-fit gate has a bypass added to rescue a named validation site.*
`src/app/verdict.py:61-69`:

```python
loose = self.pre_rmse <= max(1.5 * self.placebo_pre_rmse_median, PRE_RMSE_FLOOR[self.signal])
return loose or abs(self.point) >= 4.0 * self.pre_rmse
```

`DECISIONS.md` (milestone 3) and `docs/METHOD.md` §8 both state plainly that the
`4×` clause was added after it blocked Grünheide. `git log` confirms the order:
`593c8b3` "Showcase set: six known-answer runs" → `35a6953` "Known-answer tests
over the showcase runs" → `a3cbc4b` "Relax the pre-fit gate when the effect
dwarfs the fit error". The same pattern repeats one commit later with `f729168`
"Never let a radar NOT REAL override a large, under-sampled optical effect",
which is `verdict.combine` (`src/app/verdict.py:168-183`) and exists because of
Saddleworth Moor.

*The bypass is load-bearing for the headline result.* From
`showcase/0c2af4baa8c24486.json` (Rhodes): `pre_rmse` 0.02280,
`placebo_pre_rmse_median` 0.01410, `PRE_RMSE_FLOOR["NBR"]` 0.02. The loose gate
threshold is `max(1.5 × 0.01410, 0.02) = 0.02114`, and 0.02280 > 0.02114, so the
loose gate **fails**. The run reaches REAL only because
`|−0.4680| ≥ 4 × 0.02280 = 0.0912`. The single unambiguous REAL on the track
record is a bypassed pre-fit gate. `docs/REDTEAM.md` E6 measures that the same
bypass is reached by chance on ~1.7% of null fits on real autocorrelated series.

*Control geometry is hand-set per validation site.* `scripts/run_sites.py:23`
gives Rhodes `mode="wide", inner_km=20, outer_km=150`; line 31 gives Sindh
`mode="wide", inner_km=150, outer_km=400`. A user gets `mode="auto"` with the
fixed `WIDE_INNER_M = 20_000.0 / WIDE_OUTER_M = 150_000.0`
(`src/app/run.py:90-91`), because `server._worker` calls `run_verdict` with no
`mode`, `inner_m` or `outer_m` (`src/app/server.py:92-93`). Sindh's 150–400 km
configuration is unreachable through the product. Rhodes also shows
`"escalation": null` in its JSON, so it was not auto-escalated — the wide mode
was chosen for it by hand.

*The fix for all of this was built and never run.* `scripts/blind_sample.py`
(700 lines) and `scripts/blind_validation.py` (427 lines) exist with tests;
`showcase/blind/` contains `sample.json` and `sample.log` and **no results**.
`DECISIONS.md` HANDOFF item 3 confirms: "No verdict results yet."

**Why it matters.** The target reader's first question about any counterfactual
tool is "what did you tune, and on what?" Here the honest answer is: two decision
rules and, for two of ten sites, the control geometry, all on the ten sites that
are then published as the track record. There is no held-out set. That is the
difference between a validated method and a fitted one, and the audience for
this tool exists precisely because they have been burned by the difference.

**Fix.** Run the blind validation that is already written, on the seeded Hansen
sample, before sending a single link. Publish its hit and false-alarm rates as
*the* track record and demote `showcase/` to "worked examples". Then either (a)
delete the per-site `mode`/`inner_km`/`outer_km` overrides from
`scripts/run_sites.py` so every showcase run uses the user's defaults, or (b)
expose the same controls in the UI and say on each showcase page which settings
were used. In `docs/METHOD.md` §8, state that the 4× rule was added after
Grünheide and that E6 measures it firing on ~1.7% of null fits — the paragraph
currently argues the case for the rule without giving the reader that number.

---

## 2. BLOCKER — The red team says the method breaks; the fixes are unapplied and the limits are unpublished

**What's wrong.** `docs/REDTEAM.md` grades two attacks as **breaks**:

- **E5, pre-trends.** A decline that began 12 months *before* the claimed date is
  called REAL in 9/15 (Midlands) and 14/15 (Austin) fits at −0.20/yr. The in-time
  placebo detects it — and `src/app/verdict.py:146-149` appends a sentence and
  **returns REAL anyway**:
  ```python
  if any(r.time_placebo_flags):
      reasons.append("a fake event date in the pre-period also produced a 'significant' effect; ...")
  return Verdict("REAL", "Real change", core + " " + placebo, reasons, r.signal)
  ```
  The recommended two-line fix (return CAN'T TELL; disable the 4× bypass when a
  placebo is flagged) is not applied. `estimator.time_placebos:244` still skips
  the check entirely below 24 pre-event bins, while `MIN_PRE_BINS` is 20 — so a
  run with 20–23 pre bins can be REAL with no pre-trend check at all.
- **E7, short floods.** `s2.despike` is NDVI-only and one-sided, so standing
  water is deleted as haze: 100% of the observations of a ≤20-day flood, and on
  the real Sindh cache the three peak-flood observations (10, 15, 23 Sep 2022).
  The flood verdict is decided on NDWI, computed on a series with the flood
  surgically removed. Unfixed at `src/app/s2.py:176-199` and its three call sites
  (`fetch.py:244`, `fetch.py:256`, `fetch.py:315`).
- **E8/E9, partial.** `evidence.status_of` (`src/app/evidence.py:37-44`) applies
  weaker rules than `verdict.decide`: it can print "Optical and radar agree" on a
  page whose verdict is CAN'T TELL. Unfixed.

`tests/test_redteam.py` encodes these as strict xfail (8 xfailed in my run), which
is an honest engineering choice — but it also means the known-broken behaviour is
shipped, green, and invisible.

Now the honesty gap: `docs/METHOD.md` §9 "Known limits" lists four limits —
events larger than the ring, thin pre-2018 archives, 0.05 being below power, and
the constant-shift interval. **Neither E5 nor E7 appears.** `README.md` links
METHOD.md and never mentions `docs/REDTEAM.md`. The in-app "How this works"
drawer (`web/common.js:128-151`) has no limits section at all.

**Why it matters.** A carbon-credit checker's single most common adversarial
scenario is a project claiming credit for a decline that was already under way —
that is E5, and the tool says REAL. A journalist's most common query is a flash
flood — that is E7, and the tool deletes the evidence. The author has already
found and quantified both. Publishing the method write-up without them, while the
private write-up that has them sits unlinked two directories away, is the kind of
asymmetry a reviewer reads as spin even when it was just an oversight.

**Fix.** Apply red-team fixes (a)–(c) exactly as `docs/REDTEAM.md` specifies —
they are about ten lines total and the document gives the recomputed cost (0–7%
extra CAN'T TELL on nulls). Until then, add E5 and E7 to `docs/METHOD.md` §9 and
to the drawer, and have the flood path print a warning on the page. Link
`docs/REDTEAM.md` from `README.md` and from the drawer; it is an asset, not a
liability, once the limits it names are also in the public doc.

---

## 3. BLOCKER — The memory blow-up: one scene is half the box, and it runs inside the web process

**What's wrong.** Three independent decisions multiply.

*The read window is set by the control ring, not by the drawn area.*
`geometry.donor_grid` defaults to `outer_m = 12000.0` (`src/app/geometry.py:91`),
so `Zones.build` snaps a bounding box that spans ~24 × 24 km
(`src/app/extract.py:36-49`) for **every** run, whether the user drew 0.5 ha or
500 ha.

*Everything in that window is read at 10 m, including the 20 m mask.*
`fetch._run` calls `process_scene` without `res` for ring mode
(`src/app/fetch.py:238`), so `s2.process_scene` uses its default `res: float = 10.0`
(`src/app/s2.py:87`) and `read_window` resamples the 20 m SCL **up** to 10 m
(`src/app/extract.py:81-87`). `PLAN.md` says "SCL read first at 20 m"; the code
reads it at 10 m, quadrupling the mask array.

Arithmetic from those shapes (my estimate from array sizes, not a profiled
measurement): 24 km ÷ 10 m = 2400 px, so 5.76 M px per array. Per in-flight
scene: SCL uint8 5.8 MB; the `int32` label image from `labels_for` 23 MB; four
`float32` reflectance bands 92 MB; three `float32` index arrays 69 MB; a
`np.nan_to_num(arr)` copy per index (`s2.py:129`) 23 MB; and
`zone_means`' `values.ravel()[v].astype(float)` float64 promotion
(`extract.py:103`) up to 46 MB. That is roughly **250 MB peak for one scene**.

*And it is multiplied by the worker count, in the web process.* `render.yaml`
sets `APP_FETCH_WORKERS: 8`; `fetch._run` submits every scene to a
`ThreadPoolExecutor(max_workers=WORKERS)` at once (`src/app/fetch.py:73-78`).
Eight concurrent ~250 MB scenes on a 512 MB instance cannot work; one cannot
comfortably either. `server._worker` runs the job as a `threading.Thread` in the
same process that serves the pages (`src/app/server.py:131`), so the OOM takes
the showcase down with it. `render.yaml` does **not** set `APP_LIVE_RUNS=0`,
even though `DEPLOY.md` Route B step 4 already anticipates needing it.

**Why it matters.** The link in the cold email goes to a site where the one
interactive feature kills the server. A reviewer who tries their own area and
then finds the showcase pages have gone dark has learned something about the
engineering, not the method.

**Fix, in order of leverage.** (1) Set `APP_LIVE_RUNS=0` in `render.yaml` today
and say so on the page — a fast, honest showcase beats a broken live run. (2)
Read SCL at its native 20 m and only upsample the clear mask, not the array; that
alone is 4× on the mask path. (3) Decouple the read window from the ring: read
the treated area's window and the donor cells' windows separately (the wide path
already reads donors in compact groups at `donor_res=40.0` — apply the same idea
to ring mode), or cap `outer_m` by area size. (4) Compute indices band-pair by
band-pair and free each band; keep `zone_means` in float32 with `np.bincount`
weights rather than promoting to float64. (5) Cache the label image per
`(epsg, transform)` instead of rasterising 23 MB per scene. (6) Move live runs to
a separate process with a hard RSS cap, so an OOM kills the job and not the site.

---

## 4. MAJOR — The placebo test is anti-conservative because donors are selected to fit the treated unit

**What's wrong.** `donors.select_donors` ranks candidate cells by pre-event RMSE
*to the treated series* and keeps the best 80 (`src/app/donors.py:63-67`):

```python
cand = np.where(mask)[0]
order = cand[np.argsort(rmse[cand])]
keep = order[:k]
```

`estimator.space_placebo` then fits each of those 80 as if it were the treated
unit, against the other 79 (`src/app/estimator.py:206-225`), and ranks the
treated unit's post/pre RMSPE ratio among them.

The two are not symmetric. The treated unit got the best-80-of-400 pool *chosen
for it*; each placebo unit gets a pool chosen for someone else. Selection on
pre-fit lowers the treated unit's pre-period RMSE, which is the **denominator**
of Abadie's ratio, so the treated ratio is inflated relative to the placebo
ratios by construction. The reported p is biased downward. Abadie's test is
valid only when the treated and placebo units are handled identically.

**Why it matters.** The placebo check is, by the author's own framing in
`SPEC.md`, "the trust feature. No public tool I've found shows it." Anyone who
has implemented synthetic control will look at the donor ranking and the placebo
loop within thirty seconds of each other and see the asymmetry. It undermines the
one number the product asks readers to trust.

**Fix.** Re-select donors per placebo unit: for donor *j*, rank the remaining
cells by pre-event RMSE to *j* and keep the best 80 from the full covered pool.
That is the like-for-like comparison and it costs one extra `argsort` per placebo
unit, not another fit. If that is too slow, the fallback is to drop the fit-based
ranking from donor selection entirely (keep coverage, land cover and elevation,
then take all of them or a distance-stratified sample), which restores symmetry
by removing the selection. Whichever route, say in `docs/METHOD.md` §7 that the
placebo units are selected the same way the treated unit is.

---

## 5. MAJOR — Spatially clustered placebo cells are counted as independent

**What's wrong.** The in-space placebo p is `(#{ratio ≥ treated} + 1) / (n + 1)`
(`src/app/estimator.py:222`), with `n` up to 60 cells. In ring mode those cells
are a contiguous grid 1–12 km around the area; adjacent cells share weather,
phenology, soil and often the same field. In wide mode it is worse: Rhodes'
42 control cells sit in **6 spatial buckets** of 11/8/7/7/6/5 cells
(`showcase/0c2af4baa8c24486.json`, `donors.groups`), because
`fetch._wide_groups` deliberately buckets candidates into compact 30 km groups so
each group is one read window (`src/app/fetch.py:179-186`). The effective number
of independent placebo units is closer to 6 than 42.

The same file reports `placebo_p = 0.023256`, which is exactly `1/43` — the
arithmetic floor. The page then renders "Of 42 untouched cells given the same
test, 0 showed a divergence this large (placebo p = 0.02)". Nothing in the
verdict, the page or `docs/METHOD.md` tells the reader that the p is at its floor
and cannot go lower, or that the 42 cells are 6 neighbourhoods.

**Why it matters.** Spatial autocorrelation is the first thing an EO statistician
checks in a matched-control design. "p = 0.02 from 42 cells" reads as strong; "p
is at its floor, and the 42 cells are 6 clusters" reads as weak-to-moderate. The
tool currently shows the first.

**Fix.** Report the placebo p with its floor: "p ≤ 0.023 (the smallest value
42 cells can produce)". Better, cluster the placebo units — compute the ratio per
spatial group (median or max within group) and rank over groups — and show the
group count on the page. In wide mode, increase the number of buckets and shrink
them rather than taking the six largest (`fetch._wide_groups:185` sorts buckets by
size and truncates, which maximises within-bucket correlation).

---

## 6. MAJOR — Wide mode breaks co-observation, mixes 10 m and 40 m support, and has no intercept

**What's wrong.** In ring mode the treated area and every donor are measured from
*the same pixels of the same scene*, which cancels most atmosphere, sun-angle,
BRDF and processing-baseline effects. That is the quiet strength of the design.

Wide mode gives it up. `fetch._fetch_wide` reads the treated area alone at full
resolution (`src/app/fetch.py:312-313`) and then reads each donor group with its
own STAC search, its own scenes and its own dates, at
`donor_res = 40.0` from the COG overviews (`fetch.py:341-342`, `fetch.py:194`).
`prep.binned_groups` joins them on event-anchored 10-day bins
(`src/app/prep.py:73-113`). So the treated and control observations come from
different acquisitions, different tiles, different sun angles and different
spatial support, and are compared as if co-observed.

Two consequences. First, an index is a nonlinear function of reflectance, so the
NBR of a 40 m overview pixel is not the mean NBR of its sixteen 10 m pixels —
there is a systematic level offset between treated and donors that varies with
scene brightness. Second, `fit_ascm` has **no intercept**: the convex weights sum
to one (`estimator.solve_weights:39-40`) and `_ridge_eta` centres across donors,
not across time (`estimator.py:62-67`). A level offset between the treated series
and any weighted donor average cannot be absorbed; it has to be matched by the
weights themselves.

`docs/REDTEAM.md` "What was not tested" states it directly: "wide mode end to end
(no cached wide-mode run had donor groups)". The Rhodes REAL — the tool's best
result, at the top of the track record — is wide mode.

**Why it matters.** "Your best case is the one path your own red team did not
test, with controls on a different island read at a different resolution from
different scenes" is a complete and fatal question in an interview. It is also
probably answerable — the effect is −0.47 NBR, far larger than any plausible
cross-scene bias — but the answer has to be measured, not asserted.

**Fix.** Read donor groups at the same resolution as the treated area, or read
the treated area a second time at 40 m and use *that* series in wide mode so
support matches. Add a demeaned / intercept-corrected variant of `fit_ascm`
(fit on the pre-period deviations from each unit's own pre-mean) and report both;
it is standard in the ASCM literature and costs a few lines. Run at least one
wide-mode null: pick an untouched area, run wide, confirm it is not REAL, and put
the result in `docs/REDTEAM.md`.

---

## 7. MAJOR — "How sure" reports the wrong placebo statistic

**What's wrong.** `estimator.SpacePlacebo` computes two different quantities
(`src/app/estimator.py:191-225`): `p_value`, the rank of the treated unit's
**post/pre RMSPE ratio**, and `p_effect`, the share of donors whose **signed
post-event gap** is at least as large in the same direction.

The plain-English copy describes the second and uses the first.
`verdict.decide:118-120`:

```python
k = max(int(round(r.placebo_p * (r.placebo_n + 1))) - 1, 0)
placebo = (f"Of {r.placebo_n} untouched cells given the same test, "
           f"{k} showed a divergence this large (placebo p = {r.placebo_p:.2f}).")
```

and `web/verdict.js` `renderSure` repeats it as the page's one confidence
sentence: "`k` of `N` similar areas nearby showed a change this big." `k` is
back-derived from the **ratio** rank. A cell with a tiny effect and a tiny
pre-period error has a large ratio and is counted; a cell with a large effect and
a large pre-period error is not. `placebo_p_effect` is carried all the way into
`SignalResult` (`verdict.py:51`) and into the run JSON, and is displayed nowhere.

**Why it matters.** This is the headline trust number on the hero page, stated in
plain English to non-specialists, and it means something other than what it says.
An expert who opens `run.json` and recomputes will find the mismatch in a minute.

**Fix.** Use `placebo_p_effect` for the sentence about how many areas "showed a
change this big", keep `placebo_p` (the ratio rank) as the formal test in the
numbers table, and label each for what it is. Two lines in `verdict.py:118-120`
and one in `verdict.js` `renderSure`.

---

## 8. MAJOR — The track record's arithmetic makes a clean record unfalsifiable

**What's wrong.** `scripts/track_record.py:28-38`:

```python
if st == "CANT_TELL":
    cant += 1
elif st == e["expected"]:
    hits += 1
elif e["expected"] == "NOT_REAL":
    false_alarms += 1
else:
    misses += 1
```

A documented real event that comes back CAN'T TELL is neither a hit nor a miss.
Since the method almost never returns NOT_REAL on a real event, `misses` is
structurally near-impossible, and `false_alarms` can only be produced by a REAL
on a null site. `showcase/track_record.json` summary: `n: 10, hits: 4, misses: 0,
false_alarms: 0, cant_tell: 6`. Four of the eight documented events (Saddleworth,
Lützerath, Hasankeyf, Sindh) were not detected and are recorded as neither.

The page makes it worse. `web/track.js:60` promises "Every known-answer site the
tool has been run on, **misses included**", and `summaryLine`
(`web/track.js:14-21`) then prints sites / correct / false alarms / can't tell and
**omits misses entirely**.

Separately, every row of `showcase/index.json` carries `"confirmed": false`, and
`SITES.md` states these are "labelled 'candidate' in the app". They are not:
`grep -rn "candidate\|confirmed" web/` returns nothing but an unrelated variable
in `chart.js`. The public page presents unconfirmed ground truth as ground truth.
Two of the ten "expected" answers rest on a Wikipedia article (Table Mountain,
Austin) when Copernicus EMS and EFFIS perimeters exist for the burns.

And the specificity claim rests on two null sites, both run with
`type="clearing"` (`scripts/run_sites.py:50,53`), i.e. a one-sided test, both
returning CAN'T TELL. A CAN'T TELL on a null is not evidence of specificity.

**Why it matters.** "0 misses, 0 false alarms" is the single line a reviewer will
quote back. It is not earned by the data; it is produced by the counting rule.
This is also the one place where the project's own standard — `CLAUDE.md`: "No
invented numbers or claims in the app, its copy or the README" — is arguably
breached, not by inventing a number but by choosing a denominator that cannot
produce a bad one.

**Fix.** Report "4 of 8 documented events detected; 4 not detected (can't tell);
0 wrong-direction calls; 0 false alarms on 2 null sites" and put `misses` back
into `summaryLine`. Render the `confirmed` flag as a visible "candidate" badge on
every row and on the showcase cards. Swap the Wikipedia sources for EMS/EFFIS
perimeters. Then get the blind validation numbers (issue 1) and lead with those.

---

## 9. MAJOR — The published power table does not use the app's verdict rules

**What's wrong.** `docs/METHOD.md` §10 says the power table applies the "full
estimator and verdict rules"; `DECISIONS.md` says "the full estimator + verdict
rules were applied"; `README.md` points readers at it. The actual test,
`scripts/power.py:55`:

```python
found = (ci.hi < 0 if eff < 0 else (ci.lo > 0 or ci.hi < 0)) and abs(point) >= MIN_EFFECT[signal] and sp.p_value <= PLACEBO_P_MAX
```

Three conditions. `verdict.decide` applies, in addition: `MIN_DONORS`, the
pre-fit gate including the 4× bypass, the controls-shifted rule, the degenerate
interval rule, and the in-time placebo path. The pre-fit gate is the **most
common** reason for CAN'T TELL on the real sites (Richmond, Jaú and Lützerath all
fail it), and it is absent here.

Three further departures from production: the donor pool is "the 60 best pre-fit
donors" (`power.py:49-50`) rather than the app's land-cover- and
elevation-filtered 80; `space_placebo` runs with `max_units=30`
(`power.py:54`) instead of 60, so the p floor is 1/31 not 1/61; and the donor
columns come straight from the cached grid with **no spillover buffer**, so a
null cell's controls include its immediate neighbours — far better controls than
a real run's 1 km-buffered ring.

Finally, the injected effect is a constant step (`power.py:43`), which is exactly
the alternative the absolute-mean conformal statistic is built to detect
(`estimator._stat:116-125`). Real events are not step functions — the method doc
says so itself in §6.

**Why it matters.** "0/20 false alarms, 19/20 detection at −0.10 NDVI" is the
quantitative backbone of the whole validation story, and it characterises a
decision rule the product does not use, on a donor pool the product does not
build, against an alternative the estimator is optimal for. The true false-alarm
rate could be higher or lower; the point is that this table cannot tell you.

**Fix.** Import `verdict.decide` in `power.py` and count `status == "REAL"`, so
the table measures the shipped rule. Build the donor pool through
`donors.select_donors` with the real buffer. Add a second row block with a
time-varying effect (ramp, or step-then-partial-recovery). Then correct the
sentences in `docs/METHOD.md` §10 and `DECISIONS.md`, or mark the existing table
as "estimator-only, not the full verdict rule".

---

## 10. MAJOR — Three validation tables in the repo disagree

**What's wrong.** Checked against the committed `showcase/*.json`:

| Claim | `docs/METHOD.md` §9–10 | `showcase/track_record.json` | `showcase/validation.md` |
|---|---|---|---|
| Rhodes | CAN'T TELL, "controls burnt too", placebo p 0.61 | **REAL**, NBR −0.468, p 0.023 | CAN'T TELL, NBR −0.06 (−0.06 to −0.06), p 0.61 |
| Grünheide interval | −0.61 (−0.57 to −0.45) | −0.606 (−0.706 to −0.550) | −0.61 (−0.57 to −0.45) |
| Sites counted / correct | 6 / 1 | 10 / 4 | 6 / 1 |

`showcase/validation.md` states its own provenance: "Generated 2026-09-18 20:32
UTC at commit `1865e81`" — five commits before HEAD. `docs/METHOD.md` §9 uses the
old Grünheide interval as its worked example of the "point estimate outside its
own interval" limit; on the committed run, −0.606 sits *inside* [−0.706, −0.550],
so the example no longer demonstrates the limit it is cited for. METHOD.md §9
also lists Rhodes as the canonical "event larger than the ring → CAN'T TELL"
limit while the shipped Rhodes run is REAL.

**Why it matters.** `README.md` sends the serious reader to `docs/METHOD.md`, and
the site sends them to `/track-record`. Those two say different things about the
same site. Whichever one they read second, they stop trusting both.

**Fix.** Make `docs/METHOD.md` §10 read its numbers from `track_record.json` at
build time, or regenerate it with `scripts/refresh_verdicts.py` +
`scripts/track_record.py` + `scripts/validate_app.py` and commit all three
together — the DEPLOY.md workflow already describes the sequence. Add a CI check
that fails when a number in METHOD.md disagrees with the committed showcase, or
delete the duplicated tables and link instead. Find a new worked example for the
"point outside its interval" limit; `showcase/40bc25d4d731d8d7.json` still has one
(Saddleworth NBR −0.396 with interval [−0.234, −0.002]).

---

## 11. MAJOR — The "control areas" map shows the wrong cells

**What's wrong.** `select_donors` returns indices into the **coverage-filtered**
donor columns (`src/app/donors.py:34,63-68`: `good_idx` is computed, then `keep`
indexes the surviving columns). `run._analyse` maps them through an index over
**all** grid cells (`src/app/run.py:84`):

```python
donors = {"grid_index": (donor_all_idx[sel.index]).tolist(), ...}
```

with `donor_all_idx = np.arange(n_cells)` (`run.py:113`). Whenever any cell is
dropped for coverage, the mapping is wrong, and `web/verdict.js` `renderDetails`
uses `donors.grid_index` against `donors.cells` to draw the control map.

This is not theoretical. In every committed showcase run except one, `covered <
grid`. Jaú (`showcase/917915c7bc6e2fb9.json`): 77 of 400 cells covered, 77 kept,
and `grid_index` is exactly `[0, 1, 2, …, 76]` — the first 77 cells of the grid,
all 1.66–5.02 km out, when the ring spans 1.66–11.97 km. Richmond: 189 covered,
44 kept, max `grid_index` 187. The map draws a lopsided cluster on one side of
the area and calls it the control set.

The estimate itself is fine — `D = b.matrix[:, 1:][:, sel.index]`
(`run.py:53`) indexes the same column space, correctly. Only the display is
wrong. The `landcover` array and `distance_m` list in the same dict are indexed
the same way and are therefore also wrong.

**Why it matters.** "Show me your controls" is the second question anyone asks
about a synthetic control. The panel that answers it is wrong on nine of ten
published runs, and it is wrong in a visually suspicious direction — clustered on
one side, all close in.

**Fix.** Carry the good-column → grid mapping through: in `run._analyse`, compute
`good_idx = np.where(b.donor_cov >= 0.70)[0]` and index
`donor_all_idx[good_idx][sel.index]`. Better, return `good_idx` from
`select_donors` so the mapping lives in one place. Add a test asserting that every
returned `grid_index` cell's `distance_m` is within the requested ring and that
the selected set is not a prefix of the grid.

---

## 12. MAJOR — A dead live run hangs the UI forever, by design

**What's wrong.** `web/landing.js` `pollJob`:

```js
try {
  job = await apiGet(`/api/jobs/${jobId}`);
} catch (err) {
  return; // transient network hiccup; try again next tick
}
```

Every failure is swallowed, including the permanent 404 that follows a server
restart. Job state lives only in the in-process `_jobs` OrderedDict
(`src/app/server.py:34`), so when the OOM kills the worker (issue 3) the job
vanishes and `/api/jobs/{id}` returns 404 forever. There is no poll timeout and
no attempt counter, so the page sits on "Reading Sentinel-2 scene 0 of 767" —
exactly the reported symptom — until the tab is closed. `stageProgressFraction`
also pins the bar at 8–63% for the whole read stage, so the user has no signal
that nothing is advancing.

The progress copy is a second problem: "Live runs read every Sentinel scene over
the area for the last three years and usually take three to eight minutes"
(`web/index.html:151` and `landing.js` `rebuildProgressBlock`). `DECISIONS.md`
records 191 s for 3 years / 100 cells through the sandbox proxy; the deployed
configuration is 400 cells on a shared free-tier CPU, and it currently never
finishes. Under `CLAUDE.md`'s no-invented-numbers rule that sentence needs either
a measurement from the deployed box or removal.

**Why it matters.** The recipient of the cold email draws a box, waits eight
minutes on a frozen counter, and leaves. A clean "this run failed, here's why,
here's a showcase example" costs nothing and reads as competence.

**Fix.** Count consecutive poll failures; after ~3, or on an explicit 404, stop
the interval and show the error state that `pollJob` already renders for
`status === "error"`. Add an overall wall-clock cap with an honest message.
Persist job state to disk (`RUNS_DIR/jobs/<id>.json`) so a restart is
recoverable, and have the server mark orphaned "running" jobs as failed on
startup. Replace the timing sentence with a measurement or with "this can take
several minutes; you'll get a permalink when it's done".

---

## 13. MAJOR — The verdict copy asserts causation and over-states the placebo

**What's wrong.** `web/verdict.js`:

- `plainWhat` returns "This area burned" / "This area flooded" / "This area was
  built over" purely from `d.change_type`, which is **what the user typed into
  the dropdown**. The method tests whether an index moved more than matched
  controls; it cannot distinguish a burn from a harvest, or a flood from
  irrigation or a new reservoir. The page states the user's claim as a finding.
- `plainVerdict` for REAL: "Similar areas nearby did not." The REAL rule allows
  in-space placebo p up to 0.10 (`verdict.PLACEBO_P_MAX`), i.e. up to one in ten
  untouched cells moving as far. "Did not" is stronger than the rule.
- `renderSure` appends "That is why we call it real." to a sentence built on the
  mis-described placebo statistic (issue 7).

Meanwhile `docs/METHOD.md` is scrupulous about exactly these distinctions. The
careful framing exists; it just does not reach the page.

**Why it matters.** The audience is people who spend their working lives on
attribution. "This area burned" from a tool that has not tested for fire is the
sentence they will screenshot. It also undercuts the project's real
differentiator, which is epistemic honesty.

**Fix.** Split the claim from the finding: "You said: burn, 18 Jul 2023. We
found: the burn ratio fell 0.47 more than matched controls." For REAL, use
"Similar areas nearby mostly did not — `k` of `n` moved this far." Keep the
change-type word out of the finding sentence entirely.

---

## 14. MAJOR — The hero number is an undocumented ratio with no interval

**What's wrong.** `web/verdict.js` `relativeChange` renders the biggest number on
the page as

```js
base = mean(|counterfactual| over post-event bins)
pct  = round(point / base * 100)
```

shown as e.g. "−76%" with the caption "greenness compared with what was
expected". Three problems. The denominator is the mean **absolute** counterfactual
index, so the same absolute effect reads as a wildly different percentage
depending on the control level — a −0.2 NDVI drop is "−25%" against dense forest
at 0.8 and "−100%" against sparse scrub at 0.2. NDVI is a normalised difference
ratio, not a quantity for which percent change is defined. And no uncertainty is
attached: the 90% interval is computed, stored, and not propagated into the one
number a 15-second visitor actually reads.

This quantity appears nowhere in `docs/METHOD.md`. It is mentioned once in the
final `DECISIONS.md` design entry, so it is logged — but the public method write-up
does not define the number on the hero.

**Why it matters.** The first number an expert sees is one the method doc never
defines, with no interval, computed in a way that is not a percentage of anything
physical. That is the "invented number" objection even though nothing was
invented.

**Fix.** Show the effect in index units, which is what the method estimates and
what the interval covers, with the interval underneath: "NDVI −0.61 (90%:
−0.71 to −0.55)". If a relative figure is wanted for lay readers, define it
against the counterfactual **level** (not its absolute mean), show its interval
by transforming both endpoints, and add it to `docs/METHOD.md` §5.

---

## 15. MAJOR — The test suite is red and CI cannot have been green

**What's wrong.** `python -m pytest -q` in this worktree:

```
ERROR tests/test_app_batch.py - RuntimeError: The starlette.testclient module requires the httpx2 package
ERROR tests/test_app_server.py - RuntimeError: ...
!!!!! Interrupted: 2 errors during collection !!!!!
3 skipped, 2 errors in 1.55s
```

Zero tests execute. `httpx` appears in neither `requirements.txt` nor
`requirements-app.txt` (`grep -rn httpx requirements*.txt` → nothing), yet
`README.md` documents `pip install -r requirements.txt` then
`python -m pytest -q`.

With those two files ignored: **1 failed**, 194 passed, 3 skipped, 8 xfailed.
The failure is `tests/test_known_answer.py::test_events_larger_than_ring_are_not_called_real`
— Rhodes is now REAL, and the test asserting it must not be was never updated
when the wide-mode rerun landed. `DECISIONS.md` HANDOFF claims "`python -m
pytest -q` is green (xfails are deliberate)".

CI is worse: `.github/workflows/tests.yml` runs `pip install -r requirements.txt
zarr`, and `requirements.txt` contains no `fastapi`, `uvicorn`, `httpx` or
`pillow`. The API tests cannot collect there either, so the Tests workflow has
been failing on every push.

Separately, several tests are tautological. `tests/test_known_answer.py:39-53`
re-checks on the stored JSON exactly the conditions `verdict.decide` used to emit
REAL (interval excludes zero, `|point| ≥ min_effect`, `placebo_p ≤ 0.10`). It
cannot fail unless the JSON is corrupted, but it reads like a validation test.

**Why it matters.** A recruiter or engineer who clones the repo runs `make test`
first. Red on the first command, with a README that says it should be green, is
the cheapest possible own goal.

**Fix.** Add `httpx` to `requirements.txt` (and the app requirements if the smoke
tests run in the container); make CI install both requirements files. Update or
delete `test_events_larger_than_ring_are_not_called_real` — with wide mode the
assertion is obsolete, and the replacement should assert that *ring* mode on
Rhodes is not REAL. Rename the tautological checks to
`test_stored_runs_are_internally_consistent` so nobody mistakes them for
validation. Re-run the suite before the next commit to `showcase/`.

---

## 16. MINOR — The spillover buffer is measured from the cell centroid

`geometry.donor_grid:109` uses `d = cell.centroid.distance(area.utm)`, so
`inner_m = 1000` is a centroid gap, not an edge gap. `docs/REDTEAM.md` E2
measures the consequence: the edge-to-edge gap of the nearest kept cell is 0 m at
200, 350, 400 and 500 ha. For a 500 ha clearing, controls can share an edge with
the treated polygon, which is exactly where smoke, silt, access roads and
drainage land. It biases the gap toward zero, so it costs power rather than
causing false alarms — but it contradicts `docs/METHOD.md` §3 ("the inner gap is
a spillover buffer"). One-line fix, already specified in REDTEAM: use
`cell.distance(area.utm)` and keep `distances_m` as the edge gap.

---

## 17. MINOR — No usable cloud pre-filter, and SCL is read at the wrong resolution

`providers.PlanetaryComputer.search_s2` filters on `eo:cloud_cover < 95.0`
(`src/app/providers.py:101`), which excludes almost nothing. The reported live run
read 767 scenes; in a cloudy region most of those are dropped after a full SCL
read. Tile-level `eo:cloud_cover` is a crude proxy for a small polygon, but the
treated area needs ≥80% clear (`s2.CLEAR_MIN`), so a threshold around 80 would
cut the read count substantially at small cost, and the dropped scenes can still
be listed as receipts. Combined with reading SCL at 10 m instead of its native
20 m (issue 3), the pipeline is doing roughly four times the mask work on roughly
twice the scenes it needs.

---

## 18. MINOR — Deployment hardening

- No rate limiting or authentication on `POST /api/run` or `POST /api/batch`
  (`src/app/server.py:109,283`). One visitor can queue 25 full pipeline runs
  (`MAX_BATCH_FEATURES = 25`) behind a semaphore of 1.
- No timeout on a running job. `_worker` holds `_sem` for the life of the run
  (`server.py:85`); one wedged job blocks every future live run until restart.
- `_jobs` and `_batches` are in-memory only; Render's free tier spins down after
  15 idle minutes, so both are lost silently (see issue 12).
- `APP_RUNS_DIR=/data/runs` (Dockerfile) is ephemeral — `render.yaml` declares no
  disk, and `DEPLOY.md` notes the HF Space disk is not persistent either. Live-run
  permalinks die on every deploy. `SPEC.md` says "Permalinks matter a lot".
- `render.yaml` has no `healthCheckPath` even though `/api/health` exists.
- The Dockerfile runs `apt-get update` in two consecutive layers and `COPY`s
  `requirements.txt` without installing it.

---

## 19. MINOR — The interval width cap guesses its units

`estimator.conformal_interval:167`:

```python
max_half = 1.0 if scale < 0.3 else 10.0   # index units, or dB
```

The function infers whether it is working in index units or decibels from the
magnitude of the pre-period RMSE. A noisy optical signal with `pre_rmse ≥ 0.3`
silently gets the radar cap of ±10 index units, on a scale that only spans
[−2, 2]. The caller knows the signal name; pass it. Related: when the widening
loop exits with an empty acceptance set, the function returns `lo = hi = point`
(`estimator.py:177-178`) — a zero-width "90% interval". `verdict.decide:136-138`
catches this for the lead signal and returns CAN'T TELL, which is the right call
and good defensive work. But the secondary-signal rows in `verdict.js`
`renderNumbers` filter only the all-zero case, so `showcase/5a5f8d14423c28f0.json`
publishes "radar VH −0.68, interval −0.68 to −0.68" — a collapsed interval
rendered as extreme precision.

---

## 20. MINOR — Reproducibility

No dependency is pinned beyond `numpy<3`; there is no lock file. `rasterio`,
`scipy` and `fastapi` are all floating, and the numbers in `showcase/` depend on
`scipy.optimize.nnls` behaviour. `scripts/validate_app.py:20-44` selects "the
cached area under `data/cache/` with the most donors and the longest window", and
`data/cache/` is gitignored — so `showcase/validation.md` and its "regenerated on
demand" claim in `docs/METHOD.md` §10 cannot be reproduced by anyone but the
author on his own machine. For an audience that reviews methods for a living,
pinning the runtime and committing (or publicly hosting) the small cached series
behind the validation would matter more than any UI work.

---

## 21. MINOR — Mobile

`web/index.html:63-73` turns the side panel into a fixed bottom sheet with
`max-height: 65vh` over a `position: fixed; inset: 0` map. There is no collapse
handle, no drag, and no way to dismiss it, so on a phone up to two thirds of the
map is permanently covered by the panel you need the map to use. `100vh` is also
the wrong unit on mobile browsers (dynamic URL bar) — `100dvh` or `svh` is
needed. The verdict page has 640/800 px breakpoints and fares better;
`DECISIONS.md` is candid that mobile was "only checked for nothing broken". Given
that a cold-email link is very often opened on a phone, the landing page is the
one to fix.

---

## 22. MINOR — Permalinks have no share preview

`web/verdict.html` has `<title>Otherwise</title>` and a generic
`meta[name=description]` — identical for every verdict. There are no
`og:title` / `og:description` / `og:image` / `twitter:card` tags. A permalink
pasted into an email, Slack or LinkedIn renders as a bare URL. `DECISIONS.md`
HANDOFF lists "share-preview images" as specified but not started; given that the
entire distribution strategy in `SPEC.md` is "send them a permalink", this is
higher leverage than its severity suggests. The `*_after.png` thumbnails already
exist and would serve as `og:image`; the title can be set client-side or by
templating `verdict.html` server-side in the `/v/{rid}` route.

---

## 23. NIT — Assorted

- `src/app/fetch.py:109` imports `box as _box` inside `_fetch_group`; it is used
  only in `_fetch_wide`, which has its own import at line 294. Dead.
- `prep.complete` returns `Binned(..., 0)` and the caller then patches
  `b.bin_days` (`prep.py:63,69`); pass it through instead.
- `.github/workflows/hf-sync.yml` embeds `HF_TOKEN` in the push URL. Actions masks
  secrets in logs, but a credential helper or `git remote set-url` with a masked
  env var is the safer habit.
- `PLAN.md` says "SCL read first at 20 m"; the code reads it at 10 m.
- `README.md` presents `/batch` with a caveat ("treat them as in-progress"), which
  is honest, but the landing page footer links to `/batch` unconditionally.
- `_load_run` swallows a malformed `*_change.json` with a bare
  `except Exception: pass` (`server.py:69`). I did **not** verify whether a
  crafted `rid` can traverse paths in `_find_run` / `get_thumb` — uvicorn decodes
  `%2F` before routing, so a path parameter probably cannot contain a slash, but
  a `re.fullmatch(r"[0-9a-f]{8,32}", rid)` guard at the top of `_find_run` costs
  one line and removes the question.
- The "How this works" drawer (`web/common.js:154-175`) has no `role="dialog"`,
  no `aria-modal`, no focus trap and no `aria-expanded` on its triggers, though it
  does handle Escape. The verdict page's slider and time-lapse scrubber, by
  contrast, have proper `role="slider"`, ARIA values and keyboard handlers —
  better accessibility than most hand-built comparison widgets.

---

## What's genuinely good

- **The question is the right one, and it is carried through the whole product.**
  "Did it change more than it would have anyway" is not marketing here; it is the
  estimator, the placebo panel and the verdict wording. Most tools in this space
  do not have a counterfactual at all.
- **`docs/REDTEAM.md` is the best artefact in the repo.** Attacks specified,
  executed, counted, and graded holds/partial/breaks — including "breaks" on the
  author's own method, with the recomputed cost of each fix. Very few people
  write this about their own work. It should be linked from the README, not
  hidden.
- **The receipts idea.** Listing every dropped observation with a human-readable
  reason is original, cheap, and precisely what a verification audience wants.
- **Real methodological judgement in several places.** Keying the Baseline-04.00
  offset on `s2:processing_baseline` rather than acquisition date; averaging radar
  in linear power before converting to dB; pinning one relative orbit; never
  interpolating the treated column; reading SCL before the 10 m bands; replacing
  SLSQP with NNLS after measuring the placebo cost. These are the decisions of
  someone who has thought about the data, not just the library API.
- **The failures are recorded rather than hidden.** Rhodes and Sindh outgrowing
  the control ring, the point estimate falling outside its own interval, CAN'T
  TELL dominating the null sites — all written down in `DECISIONS.md` with the
  reasoning. The instinct is right; the gap is that the public-facing documents
  do not yet inherit it.
- **`DECISIONS.md` itself.** A reader can reconstruct why every significant choice
  was made. That is worth more in an interview than most of the code.
