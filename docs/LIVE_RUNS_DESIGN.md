# Live runs: where the compute goes

A decision document. Written 2026-09-19. Every external number below is quoted
from an official page, with the URL and the date I read it, in
[Sources](#sources). Where I could not verify a number I have written
**unverified** rather than guessing.

---

## Recommendation in one box

> **Do not build visitor-triggered GitHub Actions runs.** It is technically
> workable — a 25-minute run fits a job's 6-hour ceiling with room to spare, and
> public repositories get free minutes on a 4-vCPU/16 GB runner, which is better
> hardware than any free container host. But GitHub's own Additional Product
> Terms say Actions must not be used for *"any activity that places a burden on
> our servers, where that burden is disproportionate to the benefits provided to
> users (for example, don't use Actions as a content delivery network **or as
> part of a serverless application**)"* or, on hosted runners, *"any other
> activity unrelated to the production, testing, deployment, or publication of
> the software project associated with the repository"*. A public web page that
> queues satellite analysis for anonymous strangers is exactly that. The stated
> penalty is *"suspension or termination of your GitHub account"*. The asset at
> risk is the GitHub account the whole portfolio lives on. That is a worse
> downside than any hosting bill this project could generate. [S10]
>
> **Instead:** keep live runs off the public critical path. Ship the precomputed
> library plus a "request an area" form; run requests offline in batch, which is
> what already happens. If and when visitor-triggered live runs earn their
> place, put the compute on **Modal** (per-second billing, $30/month of included
> compute on the Starter plan — roughly 4 cents of compute per typical run by my
> arithmetic below) with the existing Render free service as the thin request
> broker. A **$25/month Render `1c-2g`** instance is the boring fallback.

The rest of this document is the working: the mechanism if you did build it, the
limits with citations, and the fair comparison.

---

## 0. What we are designing against

### Measured inputs (from this repo, not from me)

| Quantity | Value | Source |
|---|---|---|
| Live-profile peak RSS, cold 27 ha run | **339 MB** | `DECISIONS.md`, Track A (2026-09-19) |
| Same run, cgroup-accounted under an enforced 512 MiB limit | **467 MB**, no OOM kill | `DECISIONS.md`, Track A |
| Cold live run, 27 ha Grünheide, box with ~2 usable cores | **25 min wall / 43 min CPU** | `DECISIONS.md`, Track A |
| Committed Rhodes wide-control run, recorded `timing.total_s` | **3226 s = 53.8 min** | `showcase/0c2af4baa8c24486.json` |
| Committed Grünheide full-profile run, recorded `timing.total_s` | **380 s = 6.3 min** | `showcase/5a5f8d14423c28f0.json` |
| Render free tier | 0.1 CPU / 512 MB, spins down after 15 idle min | [S8][S9] |

**Flag.** The brief gives the wide-control Rhodes worst case as **2.8 hours**. I
could not find that figure anywhere in the repo. The committed Rhodes wide run
records `timing.total_s = 3226.0` (53.8 min) with 44 donor cells in 6 groups.
Either the 2.8 h run is a later, uncommitted measurement, or the figure has
drifted. **I have carried 2.8 h through as the worst case anyway**, because it is
the conservative choice and because none of the conclusions below flip between
54 min and 2.8 h. But it should be pinned down before anyone quotes it.

### Assumptions, flagged

- **A1.** The repo is, or will be, **public**. Every "free minutes" claim below
  depends on that. If it goes private the arithmetic changes completely (§3).
- **A2.** Run time scales roughly with available cores. The 25 min figure was
  43 min of CPU on ~2 cores; a 4-vCPU runner should be no slower. I have **not**
  measured this and the work is I/O-bound on `/vsicurl` reads as much as
  CPU-bound, so treat "faster on 4 cores" as plausible, not proven.
- **A3.** Nothing in the pipeline needs secrets. Confirmed: Planetary Computer,
  WorldCover and Copernicus DEM are all anonymous (`DEPLOY.md`).
- **A4.** On a 16 GB runner the memory-bounded `live` profile is unnecessary;
  runs could use `profile="full"`. This matters methodologically and I return to
  it in §6.

---

## 1. The mechanism: how a click becomes a workflow run

### 1.1 The options, honestly compared

| Option | How it works | Verdict |
|---|---|---|
| **`workflow_dispatch` via REST** `POST /repos/{o}/{r}/actions/workflows/{id}/dispatches` | Caller passes `ref` + `inputs` (≤25 top-level properties, ≤65,535 chars). Needs a token: classic PAT `repo` scope, or a fine-grained token with **Actions: write**. [S6][S7][S11] | **Recommended.** Typed inputs, shows up in the Actions UI with the inputs visible, re-runnable by hand. |
| **`repository_dispatch`** `POST /repos/{o}/{r}/dispatches` | Caller passes `event_type` + `client_payload` (≤10 top-level properties, ≤65,535 chars). Needs classic `repo` scope, or fine-grained **Contents: write** — a *broader* permission than Actions:write. [S7][S11] | Workable, and the payload shape is nicer for freeform JSON (a GeoJSON polygon). But Contents:write means the token can rewrite the repository. Rejected on least-privilege. |
| **Commit a request file** | Relay commits `requests/<id>.json`; `on: push` picks it up. | Rejected. Turns every visitor click into a commit in history, forever (§2). Also serialises badly and races on concurrent pushes. |
| **Issue / issue-comment trigger** | Relay opens an issue; `on: issues` runs the job. | Rejected. Makes every request a public artefact under Mohib's name, invites spam on a public repo, and the issue tracker becomes a queue you cannot prune quietly. |

Both dispatch events have a constraint that shapes the design: *"This event will
only trigger a workflow run if the workflow file exists on the default branch."*
[S11] So the live-run workflow must live on `main`, even while everything else is
staged on a branch — which is at odds with the current, deliberate decision in
`DECISIONS.md` not to merge to `main` until the memory work is proven live.

### 1.2 The token, and why the browser never sees it

The awkward part is not awkward once stated plainly: **a static page cannot hold
a write-scoped token, and there is no version of this design where it can.**
Anything shipped to the browser is public. A token in `landing.js`, in a
query string, or fetched from an unauthenticated endpoint is a token that grants
strangers write access to the repository.

So the request must pass through something that holds the secret server-side.
Render already runs that something.

```
 browser (public, no secret)
    │  POST /api/run   { geojson, event_date, change_type, post_months }
    ▼
 Render free web service  ── the relay ──────────────────────────────────┐
    • validates the polygon (validate_polygon, already exists)           │
    • computes run_id (run.run_id, already exists — deterministic hash)  │
    • checks "already computed?" → if yes, returns the permalink now     │
    • rate-limits / caps (see §4)                                        │
    • holds GH_DISPATCH_TOKEN as a Render environment variable           │
    │                                                                    │
    │  POST /repos/<o>/<r>/actions/workflows/live-run.yml/dispatches     │
    │  Authorization: Bearer <fine-grained token, Actions: write>        │
    ▼                                                                    │
 GitHub Actions runner (4 vCPU / 16 GB / 14 GB SSD)                      │
    • checkout, pip install, python -m scripts.run_one --inputs …        │
    • uploads run JSON + PNGs to a Release (see §2)                      │
    ▼                                                                    │
 Render serves /v/<run_id> by fetching the blob from GitHub ─────────────┘
```

The token lives in **exactly one place: a Render environment variable** (Render
dashboard → the service → Environment). It is never in the repo, never in the
bundle, never in a response body. Scope: a **fine-grained personal access token,
scoped to this one repository, with `Actions: write` and nothing else** [S7].
Not a classic PAT — classic needs the whole `repo` scope [S6], which is
read/write over code, issues and settings, and cannot be narrowed.

**This is a legitimate answer and worth saying out loud:** Render does not
disappear from the architecture. It becomes a request broker — a job it can do
on 0.1 CPU and 512 MB without breaking a sweat, because brokering is a few
milliseconds of JSON validation, and the thing it cannot do (25 minutes of
`/vsicurl` reads and NNLS fitting) is what moves away.

Two consequences of Render's free tier that the relay design must swallow:
- It **spins down after 15 idle minutes** and cold start *"takes about one
  minute"* [S8]. So the first visitor after a quiet spell waits ~1 min for the
  *dispatch*, on top of the run. Acceptable for a 25-minute job, faintly absurd
  as a user experience.
- Free instance hours are **750 per calendar month per workspace** [S8]. One
  always-reachable service cannot exceed that (a 30-day month is 720 hours), but
  a second free service would.

### 1.3 Idempotency, for free

`run.run_id()` is already a deterministic hash of (geometry, event date, change
type, post months). Two people drawing the same polygon get the same `run_id`.
The relay should therefore: look the id up first, dispatch only on a miss, and
pass the id in as a workflow input so the runner writes to a predictable name.
This is the cheapest abuse control in the document and it already exists in the
code — `submit()` in `server.py` does the lookup today.

---

## 2. Getting the result back

A finished run is not one file. Measured from `showcase/`:

| Per-run artefact | Size |
|---|---|
| Run JSON | 184–374 KB (11 committed runs; largest `9028a5c4c87fc301.json` = 373,670 B) |
| `_before.png`, `_after.png` | ~336–340 KB each |
| 8 × `_t<i>.png` time-lapse frames | ~340 KB each |
| **Total for a run with frames** | **≈ 3.5 MB** (measured: `0423e078c5f38593*` = 3.5 MB) |
| A run without frames | ≈ 888 KB (measured: `9028a5c4c87fc301*`) |

`showcase/` as a whole is **36 MB**; `showcase/blind/runs/` is **7.5 MB for 34
runs** (the brief says 8.2 MB for the whole `blind/` directory, which matches
`du -sh showcase/blind` = 8.2 MB).

So the unit of storage is ~3.5 MB, not 300 KB. That single number decides this
section.

| Store | Retention | Size / cost | Verdict |
|---|---|---|---|
| **Commit to the repo** | Forever | 3.5 MB × N, **in git history forever**, and PNGs do not delta-compress. 100 runs ≈ 350 MB of permanent history; every clone and every Render build pays for it. GitHub Pages source repos have a *recommended* limit of 1 GB [S13]. | **Rejected for live runs.** Fine for the ~11 curated showcase runs, which is what it is used for today. Catastrophic as a growing store of visitor requests. |
| **Actions artifacts** | Default **90 days**, configurable **1–90 days** for public repos [S4][S5] | Free plan includes 500 MB artifact storage (that figure is stated for the Free plan; whether artifact storage in *public* repos is exempt is **unverified**) | **Rejected as the permanent store.** A permalink that dies at 90 days is not a permalink, and `SPEC.md` says *"Permalinks matter a lot."* Useful only as a debugging side-channel. |
| **GitHub Releases as a blob store** | Indefinite | *"Each file included in a release must be under 2 GiB"*, *"Up to 1000 release assets may be associated with a single release"*, *"There is no limit on the total size of a release, nor bandwidth usage"* [S12] | **Recommended.** Assets live outside git history, so the repo stays small. 1000 assets/release ≈ 90 runs per release at 11 files each; roll to `results-2026-q4`, `results-2027-q1`, … and the cap never bites. |
| **GitHub Pages** | Indefinite | Site ≤ **1 GB**, bandwidth soft limit **100 GB/month**, **10 builds/hour** soft limit [S13] | Rejected. The 10-builds/hour ceiling is a hard throughput cap on result publication, and Pages content still comes from a repo, so it inherits the history problem. |
| **External free object store** (Cloudflare R2, Backblaze B2, Supabase Storage) | Indefinite | Not researched for this document — **unverified** | The honest alternative if Releases-as-blob-store feels like a misuse. It also removes the §4 dependency on GitHub's goodwill entirely. |

### What happens to a permalink in six months

With the Releases design: **it still works**, provided (a) the release and its
assets are not deleted, and (b) something is still serving `/v/<run_id>` — i.e.
the Render service still exists. The result itself is a static blob at a stable
`objects.githubusercontent.com` URL.

Two failure modes to be honest about:
1. **Releases are not a product promise.** Nothing in GitHub's terms blesses
   using releases as an app's data store, and the Acceptable Use Policies
   reserve the right to *"suspend your Account, throttle your file hosting, or
   otherwise limit your activity"* if bandwidth is *"significantly excessive in
   relation to other users of similar features"* [S14]. At this project's traffic
   that is not a realistic trigger, but it is a dependency on judgement, not on a
   contract.
2. **Render disappearing takes the permalinks with it**, because `/v/<id>` is a
   Render route. If that matters, the mitigation is to make the verdict page a
   pure static page that reads its run JSON from a URL, so it can be re-hosted
   anywhere. Worth doing regardless — it is a small change to `web/verdict.js`
   and it decouples permalink survival from hosting choice.

---

## 3. The limits, each with a citation

All read **2026-09-19**. Full URLs in [Sources](#sources).

| Limit | Value | Source |
|---|---|---|
| Max job duration, GitHub-hosted runner | *"Each job in a workflow can run for up to 6 hours of execution time."* | [S1] |
| Max job duration, self-hosted | *"up to 5 days"* | [S1] |
| Max workflow run duration | 35 days, then *"the workflow run is cancelled"* | [S1] |
| `timeout-minutes` default | **360** (= 6 h); *"If the timeout exceeds the job execution time limit for the runner, the job will be canceled when the execution time limit is met instead."* | [S15] |
| Concurrent jobs, **Free** plan | **20** total (Pro 40, Team 60, Enterprise 500) | [S1] |
| Workflow trigger events | 1,500 events / 10 s / repository | [S1] |
| Queued workflow runs | max 500 workflow runs / 10 s | [S1] |
| Per concurrency group | *"Up to 100 jobs or workflow runs can be queued per concurrency group."* | [S1] |
| Runner spec, **public** repo, `ubuntu-latest` | **4 vCPU, 16 GB RAM, 14 GB SSD** | [S2] |
| Runner spec, **private** repo, `ubuntu-latest` | **2 vCPU, 8 GB RAM, 14 GB SSD** | [S2] |
| Minutes cost, public repo | *"GitHub Actions usage is free for self-hosted runners and for public repositories that use standard GitHub-hosted runners."* | [S3] |
| Free plan allowance, private repos | **2,000 minutes/month**, **500 MB** artifact storage, **10 GB** cache per repo | [S3] |
| Artifact + log retention | default **90 days**; public repos configurable **1–90 days** | [S4][S5] |
| Max individual artifact size | **unverified** — I did not find a documented per-artifact size cap on the pages I read |  |
| Release asset limits | file **< 2 GiB**; **1000 assets** per release; *"no limit on the total size of a release, nor bandwidth usage"* | [S12] |
| REST rate limit, fine-grained/classic PAT | **5,000 requests/hour** per user | [S7] |
| REST rate limit, `GITHUB_TOKEN` inside a job | **1,000 requests/hour per repository** | [S1][S7] |
| Unauthenticated REST | **60 requests/hour** | [S7] |
| Secondary limit, content creation | *"no more than 80 content-generating requests per minute and no more than 500 content-generating requests per hour"* | [S7] |
| Secondary limit, concurrency | *"No more than 100 concurrent requests are allowed."* | [S7] |
| `workflow_dispatch` inputs | ≤ **25** top-level properties, ≤ **65,535** characters | [S11] |
| `repository_dispatch` payload | ≤ **10** top-level properties, ≤ **65,535** characters | [S11] |
| Dispatch events and branches | *"This event will only trigger a workflow run if the workflow file exists on the default branch."* (both dispatch events) | [S11] |
| Queue time before auto-cancel | documented as 24 h for **self-hosted** only | [S1] |
| **Typical** queue delay on hosted runners | **unverified** — GitHub publishes no typical or guaranteed queue latency |  |

### Behaviour on cancel / timeout

Documented: a job that hits 6 hours, or its `timeout-minutes`, is **cancelled**
[S1][S15]. What follows is engineering consequence rather than a documented
promise, and should be treated as such:

- A cancelled job's later steps do not run, so **nothing is uploaded** unless the
  upload step is guarded with `if: always()`. Even then the upload has no result
  to upload.
- Partial state on the runner's 14 GB SSD is destroyed with the runner. There is
  no resume.
- The relay therefore cannot distinguish "still running" from "died silently"
  without polling the Actions API for run conclusion, which means the relay needs
  **read** access to the run status as well — the same fine-grained token with
  `Actions: write` covers reads.

### The question that matters: does it fit?

**Yes, with margin — duration is not the binding constraint.**

| Case | Wall time | Fraction of the 6 h job ceiling |
|---|---|---|
| Typical (27 ha, live profile, ~2 cores) | 25 min | 7% |
| Committed Rhodes wide run (`total_s`) | 54 min | 15% |
| Brief's stated worst case | 2.8 h | 47% |

All three fit. And per A2, the runner has 4 vCPU against the ~2 the measurement
used, so the real figures should be lower, not higher. I would still set
`timeout-minutes: 300` rather than accept the 360 default, so a wedged run dies
with a diagnosable "timed out" instead of an opaque platform cancel.

**Realistic throughput** (arithmetic, from the cited limits and the measured
25 min — flagged as derived, not measured):

- The Free plan's **20 concurrent jobs** are shared across everything in the
  account, including the `tests.yml` CI that runs on every push. Spending all 20
  on satellite runs means a push cannot get CI.
- With a self-imposed cap of **3** concurrent runs: 3 jobs / 25 min ≈ **7 runs
  per hour, ~170 per day**, if the runner behaves like the measured box.
- Minutes are free on a public repo [S3], so the ceiling is concurrency, not
  budget.
- **On a private repo it collapses**: 2,000 minutes/month [S3] ÷ 25 min =
  **80 typical runs per month**, and a single 2.8 h run consumes 168 minutes —
  8.4% of the monthly allowance. (Whether Linux standard runners consume minutes
  at a 1× multiplier is **unverified** on the page I read, so 80 is an upper
  bound.) Private-repo hosting of this design is not viable.

---

## 4. Abuse, and whether it can cost money

The trigger is a public page with no login. Assume it will be found.

### What a stranger can do with the design as drawn

1. **Queue runs in bulk.** Each POST costs them nothing and costs the project
   25 minutes of a runner. With no controls, a trivial script saturates the
   account's 20 concurrent jobs and every subsequent visitor — and every CI run
   on every push — sits behind them.
2. **Force expensive runs.** A large polygon with `post_months=18` and a change
   type that escalates to wide mode is the 2.8 h case. Nothing in the current
   `RunRequest` model bounds this beyond `validate_polygon` and the 1–18 month
   clamp.
3. **Fill the store.** Each run is ~3.5 MB of release assets. 1,000 runs ≈ 3.5 GB
   of assets on the account.

### Controls, cheapest first

| Control | Where | Effect | Effort |
|---|---|---|---|
| **Deterministic `run_id` dedupe** | relay (exists today) | Repeat requests for the same area are free and instant | zero — already written |
| **Global daily cap** (e.g. 20 dispatches/day) | relay, counter with a date key | Hard ceiling on total damage, independent of how clever the attacker is | tiny |
| **Queue-depth cap** (e.g. ≤ 3 in flight) | relay, query Actions API for in-progress runs of this workflow | Protects CI and other visitors; also the throughput knob from §3 | small |
| **Per-IP rate limit** (e.g. 3/hour, sliding window) | relay | Stops casual abuse; trivially defeated by rotating IPs | small |
| **Bound the work, not just the request** | `RunRequest` validation | Cap area hectares, cap `post_months`, require `event_date ≥ 2018` (already enforced in `run_verdict`), refuse wide-mode escalation on the public path | small, and this is the highest-value one |
| **Turnstile / hCaptcha** | landing page + relay verify | Removes scripted abuse almost entirely; Cloudflare Turnstile is free but needs an account — **Mohib's decision** (account creation) | medium |
| **Allowlist / invite code in the emailed link** | relay | Since the audience *is* a cold-email list, a per-recipient code in the permalink is a near-perfect fit and costs nothing | small |

### What a determined abuser can still do

Rotate IPs behind the per-IP limit and burn the global daily cap every day, so
that no genuine visitor ever gets a live run. **The global cap converts an
availability attack into a guaranteed-denial attack** — that is a real trade, not
a fix, and it is worth stating plainly. Turnstile or the invite-code allowlist
are the only controls in the table that actually change that.

### Can it cost money?

| Vector | Cost exposure |
|---|---|
| Actions minutes, public repo | **$0** — free for public repos on standard runners [S3] |
| Actions minutes, private repo | Beyond 2,000 min/month, billed. Mitigate with a spending limit of $0 in billing settings |
| Release asset storage / bandwidth | *"no limit on the total size of a release, nor bandwidth usage"* [S12] — no metered cost |
| Render free tier | 750 instance hours/month included [S8]; outbound bandwidth *"count[s] against your monthly included amounts"* with overage charges if exceeded [S8], so a bandwidth-heavy abuse *could* in principle generate a bill. I did not verify the free plan's included bandwidth figure — **unverified** |
| **The real exposure** | **Account suspension, not a bill.** [S10] |

That last row is the whole point. Read the clause again: Actions must not be used
for *"any activity that places a burden on our servers, where that burden is
disproportionate to the benefits provided to users (for example, don't use
Actions as a content delivery network or as part of a serverless application…)"*
and, on hosted runners, *"any other activity unrelated to the production,
testing, deployment, or publication of the software project associated with the
repository"*. Consequences: *"termination of jobs, restrictions in your ability
to use GitHub Actions, disabling of repositories created to run Actions in a way
that violates these Terms, or in some cases, suspension or termination of your
GitHub account."* [S10]

A visitor-triggered analysis service is a serverless application built on
Actions. I do not think that is a stretch of the wording; I think it is the
wording. And an abuser who queues 500 runs makes it look exactly like the thing
the clause is written to stop.

There is an important distinction here, and it is what makes my recommendation in
§7 workable: **Mohib running the analysis himself, on his own repository, to
produce that repository's published results — showcase sites, the track record,
blind validation — is "publication of the software project associated with the
repository."** A `workflow_dispatch` that *he* triggers from the Actions tab is
on the right side of the line. The same workflow triggered by anonymous
strangers through a relay is on the wrong side. Same code, different clause.

---

## 5. Honest UX for a run that takes 25 minutes to hours

### What exists today

- **`web/landing.js` `pollJob(jobId, fallbackRunId)`**: polls
  `/api/jobs/<job_id>` every **1500 ms**, forever, until `status` is `done` or
  `error`; on done it does `location.href = /v/<run_id>`. Network errors are
  swallowed and retried on the next tick. There is no timeout, no persistence,
  and no way to leave and come back.
- **Progress copy** in `rebuildProgressBlock()`: *"Live runs read every Sentinel
  scene over the area for the last three years and usually take three to eight
  minutes."* Against the measured 25 minutes this is **wrong copy and has to
  change** — it is the kind of number `CLAUDE.md` forbids.
- **`_jobs` in `server.py`** is an in-memory `OrderedDict`, trimmed at 200
  entries, wiped on restart. On Render free that restart happens **every 15 idle
  minutes** [S8]. A 25-minute job whose browser tab closes loses its job record
  before it finishes.
- `job_status` 404s on an unknown `job_id`, so `pollJob` on a restarted server
  gets a 404, swallows it, and polls a dead id forever.

### What has to change

1. **The permalink becomes the waiting room.** `run_id` is deterministic and
   known *before* the run starts. So the relay should redirect straight to
   `/v/<run_id>` and let that page render one of three states: **pending**,
   **ready**, **failed**. No job ids in the UI at all. This makes the wait link
   shareable, bookmarkable and survivable across restarts — and it deletes the
   `_jobs` problem rather than solving it.
2. **State goes where the result goes.** The pending marker must outlive the
   relay process: a tiny `status.json` written beside the result, or derived live
   by asking the Actions API "is there an in-progress run with this `run_id`
   input?". Either way, not a Python dict.
3. **Polling gets slower and gives up.** 1.5 s is right for a 5-second wait and
   absurd for a 40-minute one. Suggested: 3 s for the first minute, then 15 s,
   then 60 s, with a visible *"still going"* state after 10 minutes and a
   *"we'll leave this page here for you"* state after 30. Stop polling when the
   tab is hidden (`visibilitychange`) and catch up on focus.
4. **Say the true number.** Something like: *"This reads every Sentinel-1 and
   Sentinel-2 scene over your area for three years. It usually takes about half
   an hour. You can close this page — the link above will hold the result."*
   Half an hour is defensible from the 25 min measurement; "three to eight
   minutes" is not.
5. **Notification without email infrastructure.** Ranked:
   - **The link itself.** Copy-to-clipboard, *"bookmark this"*. Costs nothing,
     works for the actual audience (someone who clicked a link in an email
     already has somewhere to paste it).
   - **Browser tab title + favicon flip** on completion, so a background tab
     announces itself. A handful of lines.
   - **Web Push / Notification API.** Free, no backend email, but needs a
     service worker and a permission prompt — a permission prompt on first visit
     is exactly the kind of thing `SPEC.md`'s 15-second first impression cannot
     afford. Not worth it.
   - **Email.** Explicitly out — no infrastructure, and collecting an address on
     a cold-email landing page changes what the page *is*.
6. **Failure has to read like the rest of the app.** `MemoryBudgetError` and
   `JobTimeout` already produce explained refusals in `_worker`; a dispatched
   run needs the equivalent — the workflow must write a failure marker, not just
   die, or the page hangs on "pending" forever.

---

## 6. Alternatives, compared fairly

Prices and specs read 2026-09-19.

| Option | Specs | Price | Fits a 25 min run? | Honest read |
|---|---|---|---|---|
| **GitHub Actions**, public repo | 4 vCPU / 16 GB / 14 GB SSD [S2] | Free [S3] | Yes — 7% of the 6 h ceiling [S1] | Best hardware per pound in this table, and **the terms forbid the use case** [S10]. Fine for runs Mohib triggers himself. |
| **Render, paid `1c-2g`** | 1 CPU / 2 GB [S9] | **$25/month** [S9] | Yes, and no spin-down | The boring answer. 10× the free tier's CPU, 4× its RAM, one dashboard, zero new concepts, deploy config already written. Still only 1 core, so expect slower than the 2-core measurement. |
| **Render, paid `0.5c-512mb`** | 0.5 CPU / 512 MB [S9] | **$7/month** [S9] | Memory: same 512 MB ceiling as the free tier, so still 467 MB against it — between **45 and 70 MB of headroom** depending on whether that 467 figure is MB or MiB, which is not headroom either way | 5× the free CPU for $7, and no more memory at all. Tempting on price; I would not trust 512 MB on a 500 ha polygon. |
| **Render one-off jobs** | Any compute plan, *"billed at the per-second rate for its specified compute plan"*, terminated after 30 days [S16] | `1c-2g` cron rate is **$0.00058/minute** [S9]; 25 min ⇒ **$0.0145** (my arithmetic) | Yes | **The most interesting thing I found.** Per-second compute, triggered from the relay by API, on the platform that is already there. Caveat: whether a *free* base service can create one-off jobs is **unverified** — the docs do not say, and it probably requires a paid base service. |
| **Hugging Face Spaces** | CPU Basic: 2 vCPU / 16 GB / 50 GB non-persistent [S17] | **Docker Spaces now require a paid plan — PRO is $9/month** for personal accounts [S17][S18] | Yes | **`DEPLOY.md` Route A is out of date and this is a finding, not a footnote.** The docs now read: *"Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts."* Route A is presented in `DEPLOY.md` as free. It is $9/month. The existing `.github/workflows/hf-sync.yml` does exactly one thing — `git push --force` of `main` to `https://user:$HF_TOKEN@huggingface.co/spaces/$HF_SPACE` so the Space rebuilds from the `Dockerfile` — so the plumbing is 22 lines and still correct; only the price changed. At $9 for 2 vCPU / 16 GB it is the cheapest *adequate* always-on box in this table, but free Spaces *"go to sleep"* when unused [S17] and the disk is not persistent, so results must still go somewhere else. |
| **Fly.io** | `shared-cpu-1x` 1 GB: **$5.92/month** or **$0.00000228/s**; 256 MB: **$2.02/month** [S19] | No free allowance on the pricing page [S19] | Yes | Machines *"don't automatically scale to zero"* but can be stopped, and a stopped machine is billed only for rootfs (*"$0.15"* per GB per 30 days) [S19]. A start-on-request architecture is possible but is real engineering. Cheap; not simple. |
| **Cloud Run** | ≤ 8 vCPU, ≤ 32 GiB per instance [S20] | Free tier figures **unverified** — the pricing page did not render for me | Services time out at **60 minutes per request** [S20] — a 2.8 h run does **not** fit a service. Cloud Run **jobs** allow *"168 hours (7 days)"* [S20], which does | Scale-to-zero is genuinely free-ish at this traffic, but it needs a GCP project, billing card, IAM and two different Cloud Run primitives (service for the relay, job for the run). Heaviest first-timer tax in the table, and the brief's audience has never deployed anything. |
| **Modal** | Per-second serverless containers | **$30/month included compute** on Starter, **$0.0000131/core/s** CPU, **$0.00000222/GiB/s** memory, no platform fee [S21] | Yes | **My pick if live runs happen.** My arithmetic for 25 min at 2 cores + 1 GiB: 1500 s × (2 × 0.0000131 + 0.00000222) = **$0.043/run**; the 2.8 h case = **$0.29**. The $30 included credit is therefore ~700 typical runs/month. Purpose-built for exactly this shape (triggered, minutes-long, scale-to-zero), no terms problem, and a Python-native API. Cost is a new account and a new SDK to learn. |
| **No live runs at all** | — | $0 | n/a | See below. |

### Are live runs even on the critical path?

I don't think they are, and I think this is the most important paragraph in the
document.

`SPEC.md` says the primary audience is people at UK EO companies who *"click a
link in my email and need to get it in about 15 seconds"*, and that *"before each
email I run the tool on something relevant to that person and send them a
permalink to the verdict page. Permalinks matter a lot."* That workflow is
**already batch, already offline, and already the thing Mohib does by hand.**
The 15-second reader is never going to start a 25-minute run; they are going to
look at a verdict page Mohib prepared for them.

`SPEC.md` also lists under "Done =" that *"a stranger can … draw their own area
and get an honest verdict"*. So live runs are in the spec. But the spec equally
says *"If free tiers can't handle live runs, say so and propose the cheapest
honest option (a job queue, cached results, or limiting live runs)."* It
anticipated this exact conversation and pre-authorised the answer.

There is also a methodological argument against making live runs prominent, and
it is already in `DECISIONS.md` in Mohib's own words: live mode *"measures the
treated area at 10 m and its controls at 40 m, from separate STAC searches with
their own dates"*, giving up co-observation, and *"live verdicts must not be
presented as equivalent to full-mode verdicts"* until the comparison sweep
finishes — a sweep that was at **0 of 10 runs recorded** at the last handoff. So
today the honest live-run button ships a verdict that the project's own decision
log says must carry a caveat. A "request an area, I'll run it properly" form
ships a `profile="full"` verdict with no caveat at all. **The worse product
feature produces the better science.**

Note the flip side, which is real: a 4-vCPU/16 GB runner (or a Modal container)
has enough memory to run `profile="full"`, which would dissolve the caveat
entirely. That is the strongest *technical* argument for moving compute off
Render, and it applies to Modal exactly as much as to Actions — without the
terms problem.

---

## 7. Recommendation

### The call

1. **Do not build the visitor-triggered Actions path.** §4 is why: the terms
   [S10] read against this use case, and the downside is the GitHub account the
   portfolio lives on. Technically it would work; that is not the same as it
   being a good idea.
2. **This week: take live runs off the public critical path.** Fix the copy that
   claims three to eight minutes, ship a "request an area" form that records the
   request, and run requests offline in batch with `profile="full"`. The public
   site becomes: instant showcase, honest track record, a form. That matches
   `SPEC.md`'s primary audience exactly and costs nothing.
3. **Keep using Actions for what it is for.** A `workflow_dispatch` workflow that
   *Mohib* triggers, to produce the repo's own published results — new showcase
   sites, the unfinished Sindh wide rerun, the blind validation sweep, the
   stalled `compare_profiles` sweep — is publication of the software project and
   is on the right side of the clause. On a public repo it is free, on 4 vCPU /
   16 GB, with a 6-hour ceiling that even the 2.8 h case fits inside. **This is a
   genuinely good use of Actions and it solves a problem the repo actually has
   today**: several long sweeps are parked because the sandbox ran out of budget.
4. **If, later, live runs prove they are wanted: Modal for the compute, Render
   free as the relay.** ~$0.04/run by my arithmetic against $30/month of included
   compute [S21], no terms problem, and enough memory for `profile="full"`. If
   that feels like one platform too many, **$25/month Render `1c-2g`** [S9] is
   the answer that requires no new concepts at all.
5. **Results in GitHub Releases, whichever compute wins** (§2): assets stay out
   of git history, retention is indefinite, and *"no limit on the total size of a
   release, nor bandwidth usage"* [S12]. Never commit visitor results to the
   repo.

### Migration path, for a first-time deployer

Steps 1–4 are this week and involve no accounts, no money and no new platforms.

1. **Fix the lie in the progress copy.** `web/landing.js`
   `rebuildProgressBlock()` — replace "three to eight minutes". One string.
2. **Make the permalink the waiting room.** Relay returns `/v/<run_id>`
   immediately; the verdict page renders pending / ready / failed. Deletes the
   `_jobs`-lost-on-restart problem instead of patching it (§5).
3. **Set `APP_LIVE_RUNS=0` on the Render free service** — the switch already
   exists in `server.py` and `DEPLOY.md` step B4 already documents it. The site
   keeps working and tells visitors live runs are off. This is a dashboard
   setting, not a deploy.
4. **Add the "request an area" form.** Draw, date, change type, optional email
   *only if the requester volunteers it*; POST writes a request record. Mohib
   runs the batch when he likes — `/batch` and its Markdown/JSON report export
   already exist.
5. **Correct `DEPLOY.md` Route A.** It presents Hugging Face Spaces as free. As
   of 2026-09-19 a Docker Space needs a paid plan, PRO is $9/month [S17][S18].
   Leaving that wrong in a first-timer's deploy guide will waste an afternoon.
6. **Add an owner-triggered `workflow_dispatch` batch workflow** (inputs: site
   key or GeoJSON, event date, change type, months, mode, profile).
   `timeout-minutes: 300`. Upload results as release assets. Trigger it from the
   Actions tab. No token, no relay, nothing public — this is the Actions tab
   button, not an API.
7. **Only if live runs are wanted:** create the Modal account (**money and
   accounts — Mohib's call**), port `run_verdict` to a Modal function, and have
   the relay call it. Keep the daily cap, the queue-depth cap and the
   bound-the-work validation from §4 from day one, not after the first abuse.

### What I am unsure about

- **The 2.8 h worst case.** Not reproducible from anything in the repo; the
  committed Rhodes wide run records 53.8 min. Needs pinning down (§0).
- **Whether A2 holds.** Whether 4 vCPU actually halves the wall clock, or whether
  the run is I/O-bound on `/vsicurl` and barely moves. Unmeasured, and it changes
  the throughput arithmetic by 2×.
- **Whether a free Render service can create one-off jobs** [S16]. If it can,
  that is the cheapest good answer in the whole document and it needs no new
  platform. The docs don't say. Worth ten minutes with the API.
- **Cloud Run's free tier numbers.** The pricing page did not render for me;
  everything I have for Cloud Run is limits, not prices.
- **Whether artifact storage in public repos is free.** The 500 MB figure is
  stated for the Free plan [S3]; I could not confirm how it applies to public
  repos. Does not affect the recommendation, since artifacts are not the store.
- **Turnstile.** I did not research it. If step 7 happens it should be looked at
  properly, because it is the only control in §4 that survives a determined
  abuser.
- **My reading of the Actions terms.** I have quoted the clause rather than
  paraphrased it [S10] precisely because this is a judgement call and Mohib
  should make it on the text, not on my summary. If he reads
  *"as part of a serverless application"* as narrower than I do, the Actions
  design in §1–§3 is ready to build and the limits all check out.

### This week vs later

| This week | Later |
|---|---|
| Fix the "three to eight minutes" copy | Modal (or paid Render) live runs |
| Permalink-as-waiting-room; retire `_jobs` | Turnstile / invite codes |
| `APP_LIVE_RUNS=0` and ship the showcase site | Static, re-hostable verdict page |
| "Request an area" form | Releases-as-blob-store plumbing |
| Correct `DEPLOY.md` Route A's pricing | Finish `compare_profiles`, then decide whether live verdicts need a caveat label |
| Owner-triggered `workflow_dispatch` batch workflow (unblocks Sindh, blind validation, the profile sweep) | |

---

## Sources

All read **2026-09-19**.

- **[S1]** GitHub Actions limits — https://docs.github.com/en/actions/reference/limits
- **[S2]** GitHub-hosted runners reference (specs) — https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- **[S3]** Billing for GitHub Actions — https://docs.github.com/en/billing/concepts/product-billing/github-actions
- **[S4]** Removing workflow artifacts — https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts
- **[S5]** Configuring the retention period for a repository — https://docs.github.com/en/organizations/managing-organization-settings/configuring-the-retention-period-for-github-actions-artifacts-and-logs-in-your-organization
- **[S6]** REST: Create a workflow dispatch event (classic scopes, inputs) — https://docs.github.com/en/rest/actions/workflows
- **[S7]** Rate limits for the REST API — https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- **[S8]** Render free tier — https://render.com/docs/free
- **[S9]** Render pricing (compute plan prices, cron per-minute rates) — https://render.com/pricing ; plan IDs and CPU/RAM — https://render.com/docs/compute-plans
- **[S10]** GitHub Terms for Additional Products and Features — GitHub Actions restrictions — https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features
- **[S11]** Events that trigger workflows (`workflow_dispatch`, `repository_dispatch`) — https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- **[S12]** About releases (asset size limits) — https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- **[S13]** GitHub Pages limits — https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- **[S14]** GitHub Acceptable Use Policies (bandwidth) — https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies
- **[S15]** Workflow syntax — `timeout-minutes` — https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- **[S16]** Render one-off jobs — https://render.com/docs/one-off-jobs ; cron jobs — https://render.com/docs/cronjobs
- **[S17]** Hugging Face Spaces overview (hardware, paid-plan requirement, sleep) — https://huggingface.co/docs/hub/spaces-overview
- **[S18]** Hugging Face pricing (PRO $9/month) — https://huggingface.co/pricing
- **[S19]** Fly.io pricing — https://fly.io/docs/about/pricing/
- **[S20]** Cloud Run quotas and limits — https://docs.cloud.google.com/run/quotas
- **[S21]** Modal pricing — https://modal.com/pricing

Repo sources: `SPEC.md`, `DECISIONS.md` (2026-09-19 entry and HANDOFF),
`DEPLOY.md`, `render.yaml`, `Dockerfile`, `.github/workflows/hf-sync.yml`,
`.github/workflows/tests.yml`, `src/app/server.py`, `src/app/run.py`,
`src/app/fetch.py`, `web/landing.js`, and measurements taken with `du`/`ls` over
`showcase/`.
