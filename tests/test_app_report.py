"""render_report(): markdown formatting over a run JSON. No stats, just text."""
import json
import os

from src.app.report import render_report

SHOWCASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "showcase")


def test_render_report_on_real_showcase_run():
    with open(os.path.join(SHOWCASE, "5a5f8d14423c28f0.json")) as f:
        run = json.load(f)
    md = render_report(run)
    assert isinstance(md, str) and md
    assert run["verdict"]["status"] in md
    assert run["id"] in md
    assert "Reproduce" in md
    assert ("Contains modified Copernicus Sentinel data. Land cover © ESA WorldCover. "
           "Terrain © Copernicus DEM. Data via Microsoft Planetary Computer.") in md


def test_render_report_on_minimal_dict_does_not_crash():
    md = render_report({})
    assert isinstance(md, str) and md
    assert "n/a" in md
    assert "Drawn area" in md


def test_render_report_missing_fields_are_na_not_invented():
    run = {"id": "x1", "label": "", "change_type": "clearing", "event_date": "2023-01-01",
          "post_months": 12, "area": {}, "verdict": {"status": "REAL", "lead_signal": "NDVI"},
          "signals": {}, "charts": {}, "data_summary": {}, "receipts": [], "method": {}}
    md = render_report(run)
    assert "n/a" in md
    assert "REAL" in md


def test_report_flags_placebo_p_from_before_the_symmetric_fix():
    from src.app.report import _placebo_lines
    base = {"placebo_n": 40, "placebo_p": 0.02}
    note = "anti-conservative"
    assert any(note in l for l in _placebo_lines(dict(base)))                       # flag missing: old run
    assert any(note in l for l in _placebo_lines({**base, "placebo_symmetric": False}))
    assert not any(note in l for l in _placebo_lines({**base, "placebo_symmetric": True}))
