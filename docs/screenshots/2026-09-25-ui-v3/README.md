# Screenshots, 25 Sep 2026: Hero V3 UI reconciled onto main

Captured locally before merging, at 1280×800 (`-desktop`) and 390×844 (`-390`). The
landing shots cover the viewport; every other page is full length and scrolled
through, so the scroll-reveal sections render.

- `off-*`: as deployed, `APP_AIR_ENABLED=0`. The air tab stays hidden even with the
  workbench open. On every page except `/review`, the service worker registers with
  scope `/`. No page logged a JavaScript error.
- `on-*`: `APP_AIR_ENABLED=1`, for review only. The air tab and case picker work
  inside the new workbench, but the air panel's typography is not yet restyled for it.

Known and not caused by this merge: on a phone the landing map opens framed
on the Arctic (see `../2026-09-25/README.md`).
