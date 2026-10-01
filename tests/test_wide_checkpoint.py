"""A wide fetch killed part-way resumes from its checkpoints and gives the same data."""
from __future__ import annotations

import numpy as np
import pytest

from src.app import covariates as covmod
from src.app import fetch
from src.app.series import SensorSeries


def _area():
    d = 0.009
    return {"type": "Polygon", "coordinates": [[[27.9, 36.08], [27.9 + d, 36.08], [27.9 + d, 36.08 + d],
                                               [27.9, 36.08 + d], [27.9, 36.08]]]}


def _series(sensor, ncols, seed):
    rng = np.random.default_rng(seed)
    dates = np.array([f"2022-{m:02d}-{d:02d}" for m in range(1, 13) for d in (5, 20)])
    keys = ("NDVI", "NDWI", "NBR") if sensor == "S2" else ("VV", "VH", "RATIO")
    vals = {k: rng.normal(0.5, 0.05, (len(dates), ncols)).astype("float32") for k in keys}
    return SensorSeries(sensor, dates, vals, [f"{sensor}-{i}" for i in range(len(dates))], {})


class _Cov:
    def __init__(self, n):
        self.landcover = np.full(n, 10); self.landcover_frac = np.ones(n)
        self.elevation = np.zeros(n); self.slope = np.zeros(n); self.year = 2021


@pytest.fixture
def stubs(monkeypatch):
    calls = []
    crash = {"at": None}

    def fake_group(polys, epsg, g_wgs, start, end, prov, s1_prov, sensors, progress, receipts,
                   res, require_zone0, tag, cfg=None, bin_anchor=None, bin_days=10):
        calls.append(tag)
        if crash["at"] is not None and tag == crash["at"]:
            raise RuntimeError("killed")
        seed = len(polys) * 1000 + sum(ord(c) for c in tag)
        receipts.append({"date": "2022-03-01", "reason": "cloud", "scene": tag})
        counts = {"s2_found": 1, "s2_covering": 1, "s1_found": 1, "s1_covering": 1, "orbit": "x"}
        return _series("S2", len(polys), seed), _series("S1", len(polys), seed + 1), counts

    monkeypatch.setattr(fetch, "_fetch_group", fake_group)
    monkeypatch.setattr(fetch, "PlanetaryComputer", lambda: object())
    monkeypatch.setattr(covmod, "fetch_covariates", lambda polys, *a, **k: _Cov(len(polys)))
    monkeypatch.setattr(fetch, "_wide_groups", lambda area, cands, cov, *a: [[0, 1, 2], [3, 4], [5, 6, 7]])
    return calls, crash


def _run(tmp_path, **kw):
    return fetch._fetch_wide(_area(), "2022-01-01", "2022-12-31", providers="pc", inner_m=20_000.0,
                             outer_m=150_000.0, max_cells=8, use_cache=True, cache_dir=str(tmp_path),
                             progress=lambda *a: None, sensors=("S2", "S1"), cov_year=2021, n_groups=3,
                             group_km=30.0, donor_res=None, **kw)


def _same(a, b):
    assert a.receipts == b.receipts and a.cells_geojson == b.cells_geojson
    for ga, gb in zip(a.groups, b.groups):
        for s in ("s2", "s1"):
            for k in ga[s].values:
                np.testing.assert_array_equal(ga[s].values[k], gb[s].values[k])
    for s in ("s2", "s1"):
        for k in getattr(a, s).values:
            np.testing.assert_array_equal(getattr(a, s).values[k], getattr(b, s).values[k])


def test_resumed_wide_fetch_equals_uninterrupted(stubs, tmp_path):
    calls, crash = stubs
    clean = _run(tmp_path / "clean")

    crash["at"] = " group 3/3"
    with pytest.raises(RuntimeError):
        _run(tmp_path / "resume")
    calls.clear(); crash["at"] = None
    resumed = _run(tmp_path / "resume")
    assert calls == [" group 3/3"]           # treated and groups 1-2 came from checkpoints
    _same(clean, resumed)


def test_checkpoints_removed_once_the_fetch_is_cached(stubs, tmp_path):
    _run(tmp_path)
    assert not list(tmp_path.glob("*/partial/*.pkl"))
