#!/usr/bin/env python3
"""Desktop screenshot capture + pixel-diff harness for the mobile-redesign track.

Proves that the desktop layout is untouched by the mobile CSS/JS added in
web/mobile.css and web/mobile.js.

Usage
-----
Capture a "before" baseline against a clean checkout, running its own server:

    uvicorn src.app.server:app --port 8012          # in the before checkout
    python scripts/desktop_screenshots.py before /tmp/shots/before

Then, against the changed checkout (its own server, same or different port):

    uvicorn src.app.server:app --port 8012          # in the changed checkout
    python scripts/desktop_screenshots.py after /tmp/shots/after \
        --before-dir /tmp/shots/before

"after" mode compares every shot against the matching "before" shot pixel by
pixel and prints, per page and viewport: identical yes/no, the number of
differing pixels, and the path to a diff image when they differ (written
under <outdir>/diffs/).

Pages captured: /, /v/<showcase id>, /track-record, /batch
Viewports: 1280x800 and 1920x1080 (desktop only — this is the "did nothing
move" proof; see the separate mobile screenshots for the phone layouts).

Determinism
-----------
- Map tile requests (OSM's tile.openstreetmap.org and Esri's
  server.arcgisonline.com) are intercepted and aborted, so screenshots never
  depend on tile-server availability, network speed, or which tiles happen
  to be cached. Leaflet still renders its container, controls, and any
  drawn/GeoJSON overlays (showcase polygons, dots, the verdict page's
  control-cells map) on top of a blank tile background — those overlays are
  what a pixel diff needs to catch anyway.
- Every capture waits for Playwright's "networkidle" and for
  `document.fonts.ready`, then scrolls the page to the bottom and back to
  the top before the shot. The verdict page reveals its sections
  (`.reveal`) and animates its chart via scroll-triggered
  IntersectionObservers; without this the shots would depend on exactly
  when in its lifecycle the full-page screenshot happened to sample each
  section. Scrolling once, fully, settles every section at its resting
  state (and returns the sticky verdict pill to its own resting state)
  before the shot is taken.
- The browser context is forced to `prefers-reduced-motion: reduce`
  (`reduced_motion="reduce"` + `page.emulate_media`). verdict.js reads that
  media feature once at load (`REDUCED`) and, when set, skips chart.js's
  ~1.1s stroke-dashoffset draw-in animation for the trajectory chart
  entirely (drawing it fully revealed on the first frame) instead of
  racing the screenshot against an in-flight animation; app.css's own
  `@media (prefers-reduced-motion: reduce)` block does the same for the
  `.reveal` fade/slide-in transitions. This was the actual source of the
  small (tens-to-low-hundreds-pixel) verdict-page diffs seen before this
  flag was added — confirmed by diffing two screenshots of the *same*
  unmodified checkout, taken moments apart, which showed the same kind of
  diff in the same chart region purely from run-to-run animation timing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from PIL import Image, ImageChops
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VIEWPORTS = [(1280, 800), (1920, 1080)]

BLOCKED_HOST_FRAGMENTS = (
    "tile.openstreetmap.org",
    "server.arcgisonline.com",
    "nominatim.openstreetmap.org",
)


def default_showcase_id() -> str | None:
    idx_path = os.path.join(ROOT, "showcase", "index.json")
    if not os.path.exists(idx_path):
        return None
    with open(idx_path) as f:
        entries = json.load(f)
    return entries[0]["id"] if entries else None


def pages_for(showcase_id: str) -> list[tuple[str, str]]:
    return [
        ("home", "/"),
        ("verdict", f"/v/{showcase_id}"),
        ("track-record", "/track-record"),
        ("batch", "/batch"),
    ]


def _chromium_executable() -> str | None:
    """The preinstalled Chromium build's own binary, if the environment's
    playwright *browsers* were provisioned for a different playwright
    *package* version than the one `pip install`ed (its default headless
    shell path then won't exist). Falls back to Playwright's own default
    resolution otherwise."""
    browsers_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not browsers_root or not os.path.isdir(browsers_root):
        return None
    for name in sorted(os.listdir(browsers_root)):
        if name.startswith("chromium-"):
            candidate = os.path.join(browsers_root, name, "chrome-linux", "chrome")
            if os.path.exists(candidate):
                return candidate
    return None


def block_tiles(route, request):
    url = request.url
    if any(frag in url for frag in BLOCKED_HOST_FRAGMENTS):
        route.abort()
    else:
        route.continue_()


def settle_and_shoot(page, out_path: str) -> None:
    page.wait_for_load_state("networkidle", timeout=30_000)
    try:
        page.evaluate("document.fonts && document.fonts.ready ? document.fonts.ready : null")
    except Exception:
        pass
    # Reveal every scroll-triggered section, then return to the resting
    # (top) scroll position, so the shot always shows the same, fully
    # settled state regardless of how full_page screenshotting samples the
    # page.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(250)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    page.screenshot(path=out_path, full_page=True)


def capture(base_url: str, showcase_id: str, outdir: str) -> list[str]:
    from playwright.sync_api import sync_playwright

    os.makedirs(outdir, exist_ok=True)
    shots = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=_chromium_executable())
        try:
            for slug, path in pages_for(showcase_id):
                for w, h in VIEWPORTS:
                    ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
                    page = ctx.new_page()
                    page.emulate_media(reduced_motion="reduce")
                    page.route("**/*", block_tiles)
                    page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=30_000)
                    out_path = os.path.join(outdir, f"{slug}_{w}x{h}.png")
                    settle_and_shoot(page, out_path)
                    shots.append(out_path)
                    print(f"captured {slug} @ {w}x{h} -> {out_path}")
                    ctx.close()
        finally:
            browser.close()
    return shots


def compare(outdir: str, before_dir: str, showcase_id: str) -> bool:
    diffs_dir = os.path.join(outdir, "diffs")
    all_identical = True
    print(f"\n{'page':<14} {'viewport':<10} {'identical':<10} {'diff px':<10} diff image")
    for slug, _path in pages_for(showcase_id):
        for w, h in VIEWPORTS:
            vp = f"{w}x{h}"
            name = f"{slug}_{vp}.png"
            before_path = os.path.join(before_dir, name)
            after_path = os.path.join(outdir, name)
            if not os.path.exists(before_path) or not os.path.exists(after_path):
                print(f"{slug:<14} {vp:<10} MISSING FILE ({before_path if not os.path.exists(before_path) else after_path})")
                all_identical = False
                continue
            im_before = Image.open(before_path).convert("RGB")
            im_after = Image.open(after_path).convert("RGB")
            if im_before.size != im_after.size:
                print(f"{slug:<14} {vp:<10} {'no':<10} size differs: {im_before.size} vs {im_after.size}")
                all_identical = False
                continue
            diff = ImageChops.difference(im_before, im_after)
            arr = np.array(diff)
            diff_mask = arr.any(axis=-1)
            n_diff = int(diff_mask.sum())
            identical = n_diff == 0
            all_identical = all_identical and identical
            diff_img_path = ""
            if not identical:
                os.makedirs(diffs_dir, exist_ok=True)
                diff_img_path = os.path.join(diffs_dir, name)
                # amplify the diff so small differences are visible
                amplified = Image.eval(diff, lambda px: min(255, px * 8))
                amplified.save(diff_img_path)
            print(f"{slug:<14} {vp:<10} {'yes' if identical else 'no':<10} {n_diff:<10} {diff_img_path}")
    print()
    print("ALL DESKTOP SHOTS IDENTICAL" if all_identical else "DESKTOP SHOTS DIFFER — see above")
    return all_identical


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["before", "after"])
    ap.add_argument("outdir", help="directory to write this run's screenshots into")
    ap.add_argument("--base-url", default="http://127.0.0.1:8012")
    ap.add_argument("--showcase-id", default=None, help="defaults to the first entry in showcase/index.json")
    ap.add_argument("--before-dir", default=None, help="required for 'after' mode: directory holding the 'before' shots")
    args = ap.parse_args()

    showcase_id = args.showcase_id or default_showcase_id()
    if not showcase_id:
        print("No showcase id given and none found in showcase/index.json", file=sys.stderr)
        return 2

    print(f"showcase id: {showcase_id}")
    t0 = time.time()
    capture(args.base_url, showcase_id, args.outdir)
    print(f"captured {len(pages_for(showcase_id)) * len(VIEWPORTS)} shots in {time.time() - t0:.1f}s")

    if args.mode == "after":
        before_dir = args.before_dir
        if not before_dir:
            print("--before-dir is required for 'after' mode", file=sys.stderr)
            return 2
        ok = compare(args.outdir, before_dir, showcase_id)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
