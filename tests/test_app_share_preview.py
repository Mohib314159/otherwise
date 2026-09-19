"""Share-preview tags on a permalink (`GET /v/{rid}`).

The verdict page is static HTML filled in by JavaScript, so a crawler sees only
what the server sends. These tests check that the server renders the run's own
title, description and thumbnail into the page, that an unknown id and a missing
thumbnail degrade instead of failing, and — the part that matters for safety —
that a user-supplied label cannot escape the attribute it lands in.

Tags are parsed out of the response with html.parser rather than matched as
substrings, so a label that broke out of its quotes would change the parsed
attribute and fail the assertion instead of slipping through a `in body` check.
"""
from __future__ import annotations

import json
import os
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from src.app import server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOWCASE = os.path.join(ROOT, "showcase")


class Head(HTMLParser):
    """The <title> text plus every <meta> tag, as the crawler would read them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self.metas: dict[str, str] = {}
        self.scripts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "title":
            self._in_title = True
            self.title = ""
        elif tag == "meta":
            key = d.get("property") or d.get("name")
            if key:
                self.metas[key] = d.get("content", "")
        elif tag == "script":
            self.scripts.append(d.get("src") or "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data


def head_of(body: str) -> Head:
    h = Head()
    h.feed(body)
    h.close()
    return h


def showcase_run() -> dict:
    """A committed showcase run, or skip: these are real, full-mode runs."""
    index_path = os.path.join(SHOWCASE, "index.json")
    if not os.path.exists(index_path):
        pytest.skip("no showcase/index.json in this checkout")
    with open(index_path) as f:
        index = json.load(f)
    for entry in index:
        p = os.path.join(SHOWCASE, f"{entry['id']}.json")
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    pytest.skip("no showcase run JSON in this checkout")


@pytest.fixture
def real_client():
    """The app over the repo's own showcase directory."""
    return TestClient(server.app)


def test_a_real_run_gets_its_own_title_description_and_image(real_client):
    run = showcase_run()
    rid = run["id"]
    r = real_client.get(f"/v/{rid}")
    assert r.status_code == 200
    h = head_of(r.text)

    label = run["label"]
    headline = run["verdict"]["headline"]
    # title and og:title carry the run's own label and verdict, not "Otherwise"
    assert h.title != "Otherwise"
    assert label in h.title and headline in h.title
    assert h.metas["og:title"] == h.title
    assert h.metas["twitter:title"] == h.title

    # the description quotes the stored effect for the lead signal
    lead = run["verdict"]["lead_signal"]
    sig = run["signals"][lead]
    desc = h.metas["og:description"]
    assert headline in desc
    assert f"{sig['point']:.3f}" in desc or f"{sig['point']:.2f}" in desc
    assert h.metas["description"] == desc
    assert h.metas["twitter:description"] == desc

    assert h.metas["og:type"] == "article"
    assert h.metas["og:site_name"] == "Otherwise"
    assert h.metas["og:url"].endswith(f"/v/{rid}")
    assert h.metas["og:url"].startswith("http")

    # the existing after-thumbnail serves as the preview image
    if os.path.exists(os.path.join(SHOWCASE, f"{rid}_after.png")):
        assert h.metas["og:image"].endswith(f"/api/runs/{rid}/after.png")
        assert h.metas["og:image"].startswith("http")
        assert h.metas["twitter:image"] == h.metas["og:image"]
        assert h.metas["twitter:card"] == "summary_large_image"
        # and it is actually served
        assert real_client.get(f"/api/runs/{rid}/after.png").status_code == 200
    else:
        assert "og:image" not in h.metas
        assert h.metas["twitter:card"] == "summary"

    # the page itself is still the app: the module that fills it in is loaded
    assert any(s.endswith("/static/verdict.js") for s in h.scripts)


def test_the_description_never_states_a_number_of_its_own(real_client):
    """Every figure in the preview comes from the run file, formatted only."""
    run = showcase_run()
    lead = run["verdict"]["lead_signal"]
    sig = run["signals"][lead]
    h = head_of(real_client.get(f"/v/{run['id']}").text)
    desc = h.metas["og:description"]
    stored = {f"{sig[k]:.3f}" for k in ("point", "lo", "hi") if isinstance(sig.get(k), float)}
    stored |= {f"{sig['placebo_p']:.3f}", str(run["post_months"]), run["event_date"]}
    # pull every number-looking token out of the description; each must be stored
    import re
    for token in re.findall(r"-?\d+\.\d+", desc):
        assert token.lstrip("−-") in {s.lstrip("−-") for s in stored}, token


def test_an_unknown_id_still_serves_the_page_with_generic_tags(real_client):
    r = real_client.get("/v/nosuchrun0000")
    assert r.status_code == 200
    h = head_of(r.text)
    assert h.title == "Otherwise"
    assert h.metas["description"] == server.SHARE_DEFAULT_DESC
    assert "og:image" not in h.metas
    assert h.metas["twitter:card"] == "summary"
    assert h.metas["og:url"].endswith("/v/nosuchrun0000")


@pytest.fixture
def hostile_client(tmp_path, monkeypatch):
    """A run whose label tries to break out of the attribute it is written into."""
    runs = tmp_path / "runs"
    runs.mkdir()
    show = tmp_path / "showcase"
    show.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(show))
    run = {
        "id": "abc123",
        "label": 'Bad "quoted" <script>alert(1)</script> & \'sneaky\'',
        "change_type": "clearing",
        "event_date": "2023-01-01",
        "post_months": 12,
        "verdict": {"status": "CANT_TELL", "headline": "Can't tell",
                    "statement": "s", "reasons": [], "lead_signal": "NDVI"},
        "signals": {"NDVI": {"point": -0.1, "lo": -0.2, "hi": 0.0, "placebo_p": 0.5,
                             "placebo_n": 40, "sensor": "S2"}},
        "charts": {}, "donors": {"cells": []}, "receipts": [], "data_summary": {},
        "timing": {}, "method": {}, "area": {"ha": 10},
    }
    with open(runs / "abc123.json", "w") as f:
        json.dump(run, f)
    return TestClient(server.app), run


def test_a_hostile_label_is_escaped_not_executed(hostile_client):
    client, run = hostile_client
    body = client.get("/v/abc123").text
    h = head_of(body)

    # nothing executable and no stray tag reached the document
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "&quot;" in body

    # the parsed attribute is exactly the label the run carried: quotes intact,
    # markup inert, so the value never escaped its attribute
    assert run["label"] in h.metas["og:title"]
    assert run["label"] in h.title
    assert h.metas["og:title"].startswith('Bad "quoted" <script>')

    # the only scripts on the page are the page's own
    assert all(s.startswith("/static/") or s.startswith("https://") for s in h.scripts)
    assert "alert(1)" not in "".join(h.scripts)


def test_a_missing_thumbnail_drops_the_image_tags_only(hostile_client):
    client, _ = hostile_client            # tmp runs dir has no *_after.png
    h = head_of(client.get("/v/abc123").text)
    assert "og:image" not in h.metas and "twitter:image" not in h.metas
    assert h.metas["twitter:card"] == "summary"
    assert h.metas["og:title"] and h.metas["og:description"]


def test_a_malformed_run_file_falls_back_to_generic_tags(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(server, "RUNS_DIR", str(runs))
    monkeypatch.setattr(server, "SHOWCASE_DIR", str(tmp_path / "nothing"))
    with open(runs / "broken1.json", "w") as f:
        f.write("{not json")
    h = head_of(TestClient(server.app).get("/v/broken1").text)
    assert h.title == "Otherwise"
    assert h.metas["description"] == server.SHARE_DEFAULT_DESC


def test_the_page_is_served_unchanged_when_the_markers_are_gone(tmp_path, monkeypatch):
    """The injection is opt-in: no markers in verdict.html, no rewriting."""
    web = tmp_path / "web"
    web.mkdir()
    (web / "verdict.html").write_text("<!doctype html><title>Otherwise</title>", encoding="utf-8")
    monkeypatch.setattr(server, "WEB_DIR", str(web))
    r = TestClient(server.app).get("/v/abc123")
    assert r.status_code == 200
    assert r.text == "<!doctype html><title>Otherwise</title>"
