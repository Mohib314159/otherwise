# Screenshots, 25 Sep 2026: air-hidden merge

Captured locally before merging `codex/air-ulez` to `main`, at 1280×800
(full page) and 390×844 (phone), with map tiles loaded and the page scrolled
through so scroll-reveal sections render.

- `off-*`: the build as deployed, `APP_AIR_ENABLED=0`. The Land/Air tab is
  hidden (`#domain-picker` computed `display: none`), the track record has no air
  section, and no page logged a JavaScript error.
- `on-*`: the same build with `APP_AIR_ENABLED=1`, for review only. It shows the
  air tab and Codex's 2023 London-wide result page (run `34d89f77f1989209`, copied
  from `docs/validation/`). With zero placebo cohorts, that page shows "—" for both
  p-values and says no placebo test could be run.

Known and not caused by this merge: on a phone the landing map opens framed on
the Arctic, with the showcase dots under the bottom sheet. The live site
(`main` before this merge) shows the same framing.
