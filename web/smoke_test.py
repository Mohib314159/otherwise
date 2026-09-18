"""Smoke test for the static frontend. Starts no server; just checks that each
HTML file parses and only pulls assets from /static/ or an allowed CDN /
Google Fonts host. Run with: python3 web/smoke_test.py
"""
from __future__ import annotations

import os
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILES = ["index.html", "verdict.html", "track.html"]

ALLOWED_CDN_PREFIXES = (
    "https://cdnjs.cloudflare.com/",
    "https://cdn.jsdelivr.net/npm/",
)
ALLOWED_FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
ASSET_TAGS = {"script": "src", "img": "src"}


class AssetCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.assets = []  # (tag, url)
        self.errors = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ASSET_TAGS:
            url = d.get(ASSET_TAGS[tag])
            if url:
                self.assets.append((tag, url))
        if tag == "link":
            rel = (d.get("rel") or "").split()
            url = d.get("href")
            if url and ({"stylesheet", "preconnect"} & set(rel)):
                self.assets.append(("link", url))


def check_url(url: str) -> str | None:
    """Returns an error string if the url is not from an allowed origin."""
    if url.startswith("/static/"):
        return None
    if url.startswith(ALLOWED_CDN_PREFIXES):
        return None
    parsed = urlparse(url)
    if not parsed.scheme:
        return None  # relative path (e.g. within /static already, or a fragment)
    if parsed.netloc in ALLOWED_FONT_HOSTS:
        return None
    return f"asset from disallowed origin: {url}"


def check_file(path: str) -> list[str]:
    errors = []
    with open(path, encoding="utf-8") as f:
        html = f.read()
    parser = AssetCollector()
    try:
        parser.feed(html)
        parser.close()
    except Exception as e:  # pragma: no cover - html.parser is lenient
        errors.append(f"parse error: {e}")
        return errors
    for tag, url in parser.assets:
        err = check_url(url)
        if err:
            errors.append(f"<{tag}>: {err}")
    return errors


def main() -> int:
    ok = True
    for name in HTML_FILES:
        path = os.path.join(WEB_DIR, name)
        if not os.path.exists(path):
            print(f"FAIL {name}: file not found")
            ok = False
            continue
        errors = check_file(path)
        if errors:
            ok = False
            print(f"FAIL {name}:")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"PASS {name}")

    required_js = ["common.js", "landing.js", "verdict.js", "track.js", "chart.js"]
    for name in required_js:
        path = os.path.join(WEB_DIR, name)
        if os.path.exists(path):
            print(f"PASS {name} present")
        else:
            print(f"FAIL {name} missing")
            ok = False

    if os.path.exists(os.path.join(WEB_DIR, "app.css")):
        print("PASS app.css present")
    else:
        print("FAIL app.css missing")
        ok = False

        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
