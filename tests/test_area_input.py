"""Regression tests for the drawn-area (hectare) input on the landing page.

`web/landing.js` shows the hectares of the polygon the user draws and decides
whether to enable "Check it". `src/app/geometry.py::validate_polygon` measures
the same polygon again server-side and answers 400 outside 0.5-500 ha. The two
have to agree, and the polygon the page posts has to be the one it measured.

Before the fix, neither held. Both failures below were reproduced in Chromium:

1. The client measured the area with a local equirectangular projection while
   the server reprojects to the polygon's UTM zone. The two numbers differed by
   up to ~0.75%, so near the limits the page showed "498.8 ha" and enabled
   "Check it" for a polygon the server rejected with
   400 "Area is 502 ha; the maximum is 500 ha."

2. Leaflet pans across world copies, so a polygon drawn after panning past the
   antimeridian carried longitudes like 358.5. `layer.toGeoJSON()` was posted
   unchanged; the hectare line looked perfectly normal and "Check it" was
   enabled, and the server answered
   400 "The polygon is outside the usable latitude range."

The browser tests drive the real page. They skip cleanly when Playwright, a
Chromium build or the CDN copies of Leaflet are unavailable, so the suite still
runs on a bare machine. `test_server_area_limits_are_the_contract` needs none of
that and always runs.
"""
from __future__ import annotations

import glob
import http.server
import json
import math
import os
import threading
import urllib.request

import pytest

from src.app.geometry import MAX_AREA_HA, MIN_AREA_HA, PolygonError, validate_polygon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

# Exactly what web/index.html loads. Fetched by the test process (not the
# browser) and replayed from memory, so the run is offline and deterministic.
CDN_ASSETS = {
    "leaflet/1.9.4/leaflet.min.js": (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js",
        "application/javascript"),
    "leaflet.draw/1.0.4/leaflet.draw.js": (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js",
        "application/javascript"),
    "leaflet/1.9.4/leaflet.min.css": (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
        "text/css"),
    "leaflet.draw/1.0.4/leaflet.draw.css": (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css",
        "text/css"),
}


# ---- fixtures ----------------------------------------------------------------

@pytest.fixture(scope="module")
def cdn():
    """CDN bytes, or skip. Downloaded once by the test process."""
    out = {}
    for key, (url, ctype) in CDN_ASSETS.items():
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                out[key] = (r.read(), ctype)
        except Exception as e:  # no network, proxy, DNS...
            pytest.skip(f"cannot reach {url}: {e}")
    return out


@pytest.fixture(scope="module")
def web_url():
    """Serve web/ over HTTP, mapping /static/<f> to web/<f> as the app does."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            name = path.split("?")[0].lstrip("/")
            if name.startswith("static/"):
                name = name[len("static/"):]
            if not name:
                name = "index.html"
            return os.path.join(WEB_DIR, os.path.basename(name))

        def log_message(self, *a):  # keep pytest output clean
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")
    pw = sync_playwright().start()
    b = None
    try:
        b = pw.chromium.launch()
    except Exception:
        # Fall back to a browser build already on the machine, which may not be
        # the revision this playwright release expects.
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
        for exe in sorted(glob.glob(os.path.join(root, "chromium-*/chrome-linux/chrome"))):
            try:
                b = pw.chromium.launch(executable_path=exe)
                break
            except Exception:
                continue
    if b is None:
        pw.stop()
        pytest.skip("no usable Chromium build (PLAYWRIGHT_BROWSERS_PATH)")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser, cdn, web_url):
    """The landing page, with Leaflet replayed from memory, every other external
    request stubbed out, and POST /api/run captured instead of sent."""
    pg = browser.new_page(viewport={"width": 1400, "height": 1200})
    pg.errors = []
    pg.posted = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))

    def route(r, req):
        if req.url.startswith(web_url):
            path = req.url[len(web_url) - 1:]
            if path.startswith("/api/run"):
                pg.posted.append(json.loads(req.post_data))
                r.fulfill(status=200, content_type="application/json",
                          body='{"job_id":"t","run_id":"t","done":false}')
                return
            if path.startswith("/api/"):
                r.fulfill(status=200, content_type="application/json", body="[]")
                return
            r.continue_()
            return
        for key, (body, ctype) in cdn.items():
            if key in req.url:
                r.fulfill(status=200, content_type=ctype, body=body)
                return
        r.fulfill(status=200, content_type="text/plain", body=b"")     # tiles, fonts

    pg.route("**/*", route)
    pg.goto(web_url, wait_until="load")
    pg.wait_for_timeout(1500)
    if pg.evaluate("typeof window.__DEBUG_MAP") != "object":
        pytest.skip("Leaflet did not initialise in this browser")
    yield pg
    pg.close()


# ---- helpers -----------------------------------------------------------------

def _square(lat, lon, side_m):
    """A [lat, lng] ring roughly side_m on a side, as Leaflet hands them over."""
    dlat = (side_m / 2) / 111320.0
    dlon = (side_m / 2) / (111320.0 * math.cos(math.radians(lat)))
    return [[lat - dlat, lon - dlon], [lat - dlat, lon + dlon],
            [lat + dlat, lon + dlon], [lat + dlat, lon - dlon]]


def _draw(pg, ring):
    """Hand the page a finished polygon the way leaflet-draw does."""
    pg.evaluate(
        "(ring) => window.__DEBUG_MAP.fire(L.Draw.Event.CREATED,"
        " { layer: L.polygon(ring), layerType: 'polygon' })", ring)
    pg.wait_for_timeout(300)


def _ha_line(pg):
    return pg.evaluate("document.getElementById('area-ha-line').textContent")


def _submit_disabled(pg):
    return pg.evaluate("document.getElementById('submit-btn').disabled")


def _submit(pg):
    """Fill in the date and press "Check it". A no-op if the page has disabled it."""
    if _submit_disabled(pg):
        return
    pg.fill("#f-date", "2023-06-01")
    pg.evaluate("document.getElementById('submit-btn').scrollIntoView()")
    pg.click("#submit-btn")
    pg.wait_for_timeout(700)


# ---- the contract, with no browser -------------------------------------------

def test_server_area_limits_are_the_contract():
    """The numbers web/landing.js has to agree with."""
    assert (MIN_AREA_HA, MAX_AREA_HA) == (0.5, 500.0)
    # ~502 ha by UTM at lat 68: the polygon that used to slip past the client.
    ring = _square(68.0, 0.0, 2236.0)
    gj = {"type": "Polygon",
          "coordinates": [[[round(p[1], 6), round(p[0], 6)] for p in ring]
                          + [[round(ring[0][1], 6), round(ring[0][0], 6)]]]}
    with pytest.raises(PolygonError):
        validate_polygon(gj)


# ---- the browser regressions --------------------------------------------------

@pytest.mark.parametrize("lat,lon,side_m", [
    (52.4, -1.5, 500.0),      # ordinary ~25 ha area
    (68.0, 0.0, 2236.0),      # ~502 ha: over the limit, was shown as 498.8 ha
    (0.0, 3.0, 70.8),         # ~0.5 ha: at the other limit
    (-33.95, 18.46, 1000.0),  # southern hemisphere
    (36.1, 27.92, 1500.0),    # away from the zone's central meridian
])
def test_hectares_shown_match_the_hectares_the_server_measures(page, lat, lon, side_m):
    """The number on screen is the number validate_polygon will compute.

    Before the fix the client used an equirectangular projection and the server
    UTM, so these differed by up to ~0.75% and disagreed about the limits.
    """
    _draw(page, _square(lat, lon, side_m))
    shown = float(_ha_line(page).split(" ha")[0])
    offered = not _submit_disabled(page)      # read before submitting re-disables it
    _submit(page)

    if page.posted:
        geojson = page.posted[0]["geojson"]
    else:
        # Over/under the limit, so "Check it" is disabled and nothing is posted:
        # rebuild the same ring the page would have sent.
        ring = _square(lat, lon, side_m)
        geojson = {"type": "Polygon",
                   "coordinates": [[[round(p[1], 6), round(p[0], 6)] for p in ring]
                                   + [[round(ring[0][1], 6), round(ring[0][0], 6)]]]}

    try:
        server_ha = validate_polygon(geojson).area_ha
        rejected = False
    except PolygonError:
        server_ha = None
        rejected = True

    if rejected:
        # If the server would refuse it, the page must not offer to run it.
        assert not offered, f"server rejects it but the page offered to run {shown} ha"
        assert not page.posted, "posted a polygon the server rejects"
    else:
        assert abs(shown - server_ha) <= 0.06, f"page says {shown} ha, server says {server_ha} ha"
        assert offered, f"server accepts {server_ha} ha but the page would not run it"
    assert page.errors == []


def test_polygon_drawn_on_a_world_copy_is_posted_wrapped(page):
    """Leaflet pans across world copies; the posted longitudes must still be real.

    Before the fix the page posted lng ~358.5 and the server answered
    400 "The polygon is outside the usable latitude range."
    """
    page.evaluate("window.__DEBUG_MAP.setView([52.4, 358.5], 15)")
    page.wait_for_timeout(300)
    _draw(page, _square(52.4, 358.5, 500.0))

    assert _submit_disabled(page) is False, f"area line said {_ha_line(page)!r}"
    _submit(page)
    assert page.posted, "nothing was posted"

    geojson = page.posted[0]["geojson"]
    lons = [c[0] for c in geojson["coordinates"][0]]
    assert all(-180.0 <= x <= 180.0 for x in lons), f"unwrapped longitudes posted: {lons}"

    area = validate_polygon(geojson)          # must not raise
    assert abs(area.lon - (-1.5)) < 0.01      # 358.5 is really -1.5
    assert abs(float(_ha_line(page).split(" ha")[0]) - area.area_ha) <= 0.06
    assert page.errors == []


def test_drawing_with_the_mouse_produces_a_polygon_the_server_accepts(page):
    """The real leaflet-draw path: click vertices, close on the first one."""
    page.evaluate("window.__DEBUG_MAP.setView([52.4, -1.5], 15)")
    page.wait_for_timeout(300)
    page.click("#draw-btn")
    page.wait_for_timeout(300)
    pts = [(700, 400), (880, 400), (880, 540), (700, 540)]
    for x, y in pts:
        page.mouse.move(x, y)
        page.wait_for_timeout(60)
        page.mouse.click(x, y)
        page.wait_for_timeout(200)
    page.mouse.click(*pts[0])
    page.wait_for_timeout(800)

    shown_text = _ha_line(page)
    assert shown_text.endswith(" ha"), f"no hectare figure after drawing: {shown_text!r}"
    shown = float(shown_text.split(" ha")[0])
    assert 0.5 <= shown <= 500

    # The form the user now has to fill in must be on screen, not below the fold.
    assert page.evaluate(
        "() => { const r = document.getElementById('submit-btn').getBoundingClientRect();"
        "        return r.top >= 0 && r.bottom <= innerHeight; }"), "\"Check it\" is off screen"

    _submit(page)
    assert page.posted, "nothing was posted"
    area = validate_polygon(page.posted[0]["geojson"])     # must not raise
    assert abs(shown - area.area_ha) <= 0.06, f"page says {shown} ha, server says {area.area_ha} ha"
    assert page.errors == []
