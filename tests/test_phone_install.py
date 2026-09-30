"""Phone landing: the PWA Install button is a ghost, not the lime primary fill."""
from __future__ import annotations

from tests.test_web_copy import browser, web_url  # noqa: F401  (fixtures)

TRANSPARENT = ("rgba(0, 0, 0, 0)", "transparent")


def _bg(browser, web_url, width):  # noqa: F811
    pg = browser.new_page(viewport={"width": width, "height": 800})
    pg.route("**/*", lambda r, req: r.continue_() if req.url.startswith(web_url)
             else r.fulfill(status=200, content_type="text/plain", body=b""))
    pg.goto(web_url, wait_until="load")
    el = pg.wait_for_selector(".nav-install", state="attached")
    out = el.evaluate("e => getComputedStyle(e).backgroundColor")
    pg.close()
    return out


def test_phone_install_is_ghost(browser, web_url):  # noqa: F811
    assert _bg(browser, web_url, 390) in TRANSPARENT


def test_desktop_install_keeps_its_fill(browser, web_url):  # noqa: F811
    assert _bg(browser, web_url, 1280) not in TRANSPARENT
