# WORKFLOW.md — how Otherwise gets built (two AIs, one repo)

Both Claude and Codex must read this before working. It exists to keep the discipline that produced the trustworthy parts of this project.

## Roles
- **Opus 5.5 (Claude) — architect and reviewer.** Owns: method and statistics, architecture, what gets merged, specs, and the final call on trade-offs. Writes CRITIQUE/triage, runs validation, merges to `main`.
- **Codex (GPT) — implementer.** Owns: well-specified implementation work — UI, refactors, adapters, wiring, tests to a given spec. Does not change statistical method or verdict rules without a decision from the architect, logged in DECISIONS.md.
- **grunt (Sonnet subagent)** — routine code: CSS, boilerplate, test scaffolding.
- **Mohib** — decides scope, priorities, hosting/spend, and anything user-facing or public.

## Non-negotiable rules (kept from the Fable build)
1. **Tests gate everything.** Full suite green before any merge to `main`. New behaviour ships with tests.
2. **Known-answer + null power test after every method change.** Report detection rate, false-alarm rate and can't-tell rate. Never loosen false-alarm protection to get more REAL verdicts.
3. **Adversarial pass every round.** One agent (read-only) attacks the work: method validity, leakage, confounders, UI honesty. Output ranked issues; the architect **triages** them (valid / partly valid / wrong + reason). Triage tables go in DECISIONS.md. A critique is evidence, not orders.
4. **Verify before believing.** Measure the cause before fixing (the memory bug was found by measurement, not guesswork). Disprove your own hypothesis when the evidence says so, and say you did.
5. **No invented numbers or claims**, anywhere: app, docs, README, commit messages. Published tables are generated from committed run files, never hand-edited.
6. **DECISIONS.md is the memory.** Every significant decision: what, why, what was rejected. HANDOFF section at the end kept current.
7. **Branch discipline.** `codex/*` and `claude/*` branches; never two agents on one branch; `main` only via reviewed merge with green tests. `main` auto-deploys, so a bad merge is a live outage.
8. **Checkpoint before limits.** When usage/credit is low: stop new work, merge what's green, push unfinished work to `wip-*` branches, update HANDOFF.

## Handover between Claude and Codex
- **The repo is the only source of truth.** Not chat transcripts, not zips.
- Whoever finishes a session writes/updates **HANDOFF** in DECISIONS.md: state of each track, branch names, what's tested, exact next steps.
- Codex's work reaches GitHub as a branch (GitHub Desktop is fine). Claude reviews the diff, requests changes, and merges.
- Conflicts are resolved by the architect, not by whoever pushed last.

## Definition of done (any change)
- Tests green, including known-answer and null power tests where the method is touched.
- Docs and generated tables updated; DECISIONS.md entry written.
- Screenshots checked (desktop **and** 390px) for anything visual; desktop must not regress unintentionally.
- Merged to `main`, pushed, live site checked.
