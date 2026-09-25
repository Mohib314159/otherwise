"""What the verdict page is allowed to say.

These are copy tests, not layout tests. They pin the four honesty fixes:

1. The "how sure" sentence describes `placebo_p` -- the post/pre fit-error rank
   -- and the effect-size count (`placebo_p_effect`) is a separate, labelled
   line. The page used to describe the second and compute the first.
2. The claim (the user's dropdown) and the finding (what the data show) are
   separate sentences. The method cannot tell a burn from a harvest, so the
   dropdown word never appears in the finding.
3. The hero percentage carries an interval through the same divisor as the
   point estimate, and falls back to index units when that divisor is near zero.
4. A live ("quick check") run is labelled; a full run, and a run with no profile
   field at all (every run made before the field existed), is not.

The source-level checks always run. The browser checks drive the real page in
Chromium with the API stubbed, and skip cleanly where Playwright or a Chromium
build is unavailable.
"""
from __future__ import annotations

import copy
import glob
import http.server
import json
import os
import re
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
SHOWCASE = os.path.join(ROOT, "showcase")


def read_web(name: str) -> str:
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


# ---- source-level checks (no browser) ---------------------------------------

BANNED_IN_VERDICT_JS = [
    # the user's dropdown stated as a finding
    "This area burned",
    "This area flooded",
    "This area was built over",
    "This area lost its vegetation",
    "This area grew back",
    # stronger than the REAL rule allows
    "Similar areas nearby did not",
    # the effect-size sentence that was computed from the fit-ratio statistic
    "showed a change this big",
    "That is why we call it real",
    "That is why we call it not real",
]


@pytest.mark.parametrize("phrase", BANNED_IN_VERDICT_JS)
def test_verdict_js_no_longer_contains_the_phrase(phrase):
    assert phrase not in read_web("verdict.js")


def test_the_landing_page_states_no_live_run_duration():
    """No minute count anywhere in the progress copy: none has been measured
    on the deployment hardware, so any range would be invented."""
    for name in ("index.html", "landing.js"):
        src = read_web(name)
        assert "three to eight minutes" not in src
        # any "N ... minutes" promise about how long a run takes
        assert not re.search(r"take[sn]?\s+[a-z0-9]+\s+to\s+[a-z0-9]+\s+minutes", src)
    assert "tens of minutes" in read_web("index.html")


def test_both_ends_of_the_interval_go_through_the_same_divisor():
    """A regression guard on the arithmetic the browser test measures."""
    src = read_web("verdict.js")
    assert "(sig.lo / base) * 100" in src and "(sig.hi / base) * 100" in src
    assert "DIVISOR_FLOOR" in src


# ---- browser fixtures --------------------------------------------------------

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


@pytest.fixture(scope="module")
def web_url():
    """Serve web/ the way the app does, with /v/<id> mapped to verdict.html."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            name = path.split("?")[0].lstrip("/")
            if name.startswith("static/"):
                name = name[len("static/"):]
            if name.startswith("v/") or name == "v":
                name = "verdict.html"
            if not name:
                name = "index.html"
            return os.path.join(WEB_DIR, os.path.basename(name))

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def showcase_run(status: str) -> dict:
    """A committed run with this verdict status, or skip."""
    index_path = os.path.join(SHOWCASE, "index.json")
    if not os.path.exists(index_path):
        pytest.skip("no showcase/index.json in this checkout")
    with open(index_path) as f:
        index = json.load(f)
    for entry in index:
        p = os.path.join(SHOWCASE, f"{entry['id']}.json")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            run = json.load(f)
        if run["verdict"]["status"] == status:
            return run
    pytest.skip(f"no committed {status} run in this checkout")


@pytest.fixture
def load(browser, web_url):
    """open(run_dict) -> a Playwright page showing that run's verdict page."""
    pages = []

    def open_run(run: dict, width: int = 1280, height: int = 900):
        pg = browser.new_page(viewport={"width": width, "height": height})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.errors = errors

        def route(r, req):
            url = req.url
            if url.startswith(web_url):
                path = url[len(web_url) - 1:]
                if re.match(r"^/api/runs/[^/]+$", path.split("?")[0]):
                    r.fulfill(status=200, content_type="application/json", body=json.dumps(run))
                    return
                if path.startswith("/api/"):
                    r.fulfill(status=404, content_type="application/json", body='{"detail":"none"}')
                    return
                r.continue_()
                return
            r.fulfill(status=200, content_type="text/plain", body=b"")   # CDN, fonts, tiles

        pg.route("**/*", route)
        pg.goto(f"{web_url}v/{run['id']}", wait_until="load")
        pg.wait_for_selector("#verdict-top", timeout=15_000)
        pages.append(pg)
        return pg

    yield open_run
    for pg in pages:
        pg.close()


def text_of(pg, selector: str) -> str:
    el = pg.query_selector(selector)
    return el.inner_text().strip() if el else ""


def dom_text(pg, selector: str) -> str:
    """Text present in the DOM, including inside a collapsed <details>."""
    el = pg.query_selector(selector)
    return (el.text_content() or "").strip() if el else ""


# ---- 2. the claim is not the finding -----------------------------------------

def test_the_claim_is_stated_as_a_claim_and_the_finding_names_no_mechanism(load):
    run = showcase_run("REAL")
    pg = load(run)
    kicker = text_of(pg, ".verdict-kicker")
    finding = text_of(pg, ".verdict-plain")

    assert kicker.lower().startswith("you reported")
    assert finding and finding != kicker

    # the dropdown word appears in the claim, never in the finding
    word = {"burn": "burn", "flood": "flood", "clearing": "clearing",
            "construction": "construction", "regrowth": "regrowth"}.get(run["change_type"])
    if word:
        assert word in kicker.lower()
    for mechanism in ("burned", "flooded", "built over", "lost its vegetation", "grew back"):
        assert mechanism not in finding.lower()

    # the finding is about the measured gap against the controls
    lead = run["verdict"]["lead_signal"]
    assert lead in finding
    assert "control" in finding.lower()
    assert f"{abs(run['signals'][lead]['point']):.2f}" in finding
    assert not pg.errors


# ---- 3. the hero number ------------------------------------------------------

def _post_counterfactual_mean(run: dict) -> float:
    chart = run["charts"][run["verdict"]["lead_signal"]]
    post = [abs(v) for v, pre in zip(chart["counterfactual"], chart["pre"]) if not pre]
    return sum(post) / len(post)


def test_the_hero_percentage_carries_its_interval_through_the_same_divisor(load):
    run = showcase_run("REAL")
    lead = run["verdict"]["lead_signal"]
    if lead in ("VV", "VH", "RATIO"):
        pytest.skip("radar runs are shown in dB, not as a percentage")
    pg = load(run)

    base = _post_counterfactual_mean(run)
    sig = run["signals"][lead]
    expect = {k: round(sig[k] / base * 100) for k in ("point", "lo", "hi")}

    hero = text_of(pg, "#big-number")
    assert hero.replace("−", "-") == f"{expect['point']:+d}%".replace("+", "+")

    interval = text_of(pg, "#big-interval").replace("−", "-")
    assert "90% interval" in interval
    got = [int(t) for t in re.findall(r"[-+]?\d+", interval.replace("90% interval", ""))]
    assert got == [expect["lo"], expect["hi"]]

    # the index-unit effect is still on the page, and the definition is one tap away
    assert f"{sig['point']:.2f}".replace("-", "−") in text_of(pg, "#big-index")
    definition = dom_text(pg, "#what-num")
    assert "average level the control trajectory predicted" in definition
    assert not pg.errors


def test_the_hero_falls_back_to_index_units_when_the_divisor_is_near_zero(load):
    run = copy.deepcopy(showcase_run("REAL"))
    lead = run["verdict"]["lead_signal"]
    if lead in ("VV", "VH", "RATIO"):
        pytest.skip("radar runs are shown in dB, not as a percentage")
    chart = run["charts"][lead]
    # flatten the control trajectory onto (near) zero over the post-event window
    chart["counterfactual"] = [v if pre else 0.001 for v, pre in
                               zip(chart["counterfactual"], chart["pre"])]
    pg = load(run)

    hero = text_of(pg, "#big-number")
    assert "%" not in hero, "a near-zero divisor must not produce a percentage"
    assert f"{abs(run['signals'][lead]['point']):.2f}" in hero
    assert lead in hero or lead in text_of(pg, ".big-sub")
    assert "too close to zero" in dom_text(pg, "#what-num")
    assert not pg.errors


# ---- 1. the two placebo figures ----------------------------------------------

def _k(p: float, n: int) -> int:
    return max(0, round(p * (n + 1)) - 1)


def test_the_placebo_sentence_describes_the_statistic_it_is_computed_from(load):
    run = showcase_run("REAL")
    lead = run["verdict"]["lead_signal"]
    sig = run["signals"][lead]
    pg = load(run)

    lines = [el.inner_text().strip() for el in pg.query_selector_all(".sure-line")]
    assert len(lines) == 2, "the two placebo figures are never merged into one line"
    fit, gap = lines

    # line 1: the fit-ratio test, described as a fit that breaks down, and its
    # count back-derived from placebo_p (not from the effect-size share)
    n = sig["placebo_n"]
    assert f"{_k(sig['placebo_p'], n)} of them" in fit or f"In {_k(sig['placebo_p'], n)} of them" in fit
    assert str(n) in fit
    assert "matched before" in fit or "fitted before" in fit
    assert f"{sig['placebo_p']:.2f}" in fit

    # line 2: the effect-size count, labelled as such and carrying p_effect
    assert "gap size" in gap.lower()
    assert f"{_k(sig['placebo_p_effect'], n)} of those {n}" in gap
    assert f"{sig['placebo_p_effect']:.2f}" in gap
    assert not pg.errors


def test_the_two_placebo_figures_stay_apart_when_they_disagree(load):
    """A run where the fit rank and the effect rank differ is the case the old
    sentence got wrong; both numbers must survive to the page unmixed."""
    run = copy.deepcopy(showcase_run("CANT_TELL"))
    lead = run["verdict"]["lead_signal"]
    sig = run["signals"][lead]
    sig["placebo_n"] = 59
    sig["placebo_p"] = 0.75        # k = 44 by the fit ratio
    sig["placebo_p_effect"] = 0.10  # k = 5 by gap size
    pg = load(run)

    fit, gap = [el.inner_text().strip() for el in pg.query_selector_all(".sure-line")]
    assert "44" in fit and "0.75" in fit
    assert "5 of those 59" in gap and "0.10" in gap
    assert "44" not in gap
    assert not pg.errors


# ---- 5. the quick-check label ------------------------------------------------

def test_a_live_run_is_labelled_a_quick_check(load):
    run = copy.deepcopy(showcase_run("REAL"))
    run["profile"] = "live"
    pg = load(run)
    mark = text_of(pg, "#quick-mark")
    note = text_of(pg, "#quick-note")
    assert mark.lower() == "quick check"
    assert pg.query_selector("#quick-mark").is_visible()
    # the note says what is weaker and that a full run exists
    assert "40 m" in note and "10 m" in note
    assert "full run" in note.lower()
    # it sits with the verdict, not inside a details toggle
    assert pg.query_selector("#quick-note").evaluate("el => !el.closest('details')")
    assert not pg.errors


def test_the_label_follows_method_profile_too(load):
    run = copy.deepcopy(showcase_run("REAL"))
    run.setdefault("method", {})["profile"] = "live"
    pg = load(run)
    assert pg.query_selector("#quick-mark") is not None


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda r: r, id="no-profile-field-at-all"),
    pytest.param(lambda r: r.update(profile="full") or r, id="profile-full"),
    pytest.param(lambda r: r.setdefault("method", {}).update(profile="full") or r, id="method-profile-full"),
])
def test_a_full_or_older_run_carries_no_label(load, mutate):
    run = mutate(copy.deepcopy(showcase_run("REAL")))
    pg = load(run)
    assert pg.query_selector("#quick-mark") is None
    assert pg.query_selector("#quick-note") is None
    assert "quick check" not in text_of(pg, "#verdict-top").lower()


# ---- no sideways scroll on the pages this change touches ---------------------

@pytest.mark.parametrize("path", ["/", "/v/{id}", "/track-record"])
def test_no_horizontal_scroll_at_360(browser, web_url, path):
    run = showcase_run("REAL")
    name = {"/": "index.html", "/track-record": "track.html"}.get(path, f"v/{run['id']}")
    pg = browser.new_page(viewport={"width": 360, "height": 780}, is_mobile=True, has_touch=True)

    def route(r, req):
        url = req.url
        if url.startswith(web_url):
            p = url[len(web_url) - 1:]
            if re.match(r"^/api/runs/[^/]+$", p.split("?")[0]):
                r.fulfill(status=200, content_type="application/json", body=json.dumps(run))
                return
            if p.startswith("/api/"):
                r.fulfill(status=200, content_type="application/json", body="[]")
                return
            r.continue_()
            return
        r.fulfill(status=200, content_type="text/plain", body=b"")

    pg.route("**/*", route)
    pg.goto(web_url + name.lstrip("/"), wait_until="load")
    pg.wait_for_timeout(800)
    widths = pg.evaluate("() => [document.scrollingElement.scrollWidth, window.innerWidth]")
    pg.close()
    assert widths[0] <= widths[1], f"{path} scrolls sideways at 360px: {widths}"


def test_runs_from_before_the_placebo_fix_say_so(load):
    """Committed showcase runs predate CRITIQUE #4 and carry no placebo_symmetric
    flag; their page must say the p-value came from the older, flattering procedure.
    A run made with the symmetric procedure must not carry that caveat."""
    run = copy.deepcopy(showcase_run("REAL"))
    sig = run["signals"][run["verdict"]["lead_signal"]]
    sig.pop("placebo_symmetric", None)
    caveat = [el.inner_text() for el in load(run).query_selector_all(".sure-caveat")]
    assert len(caveat) == 1 and "predates a fix to the placebo test" in caveat[0]

    sig["placebo_symmetric"] = True
    assert load(run).query_selector_all(".sure-caveat") == []
