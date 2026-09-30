"""Server-side S1 RTC donor reads (src/app/remote_s1.py) and their wiring. No network.

The titiler expression is numexpr, which parses with Python's grammar, so it is
evaluated here with numpy bound to the same names and checked against the
local path in s1.py (mean in linear power, then dB; RATIO = VH_dB - VV_dB;
validity = finite, > 0, not nodata in both polarisations).
"""
import types
from datetime import datetime, timezone

import numpy as np
import pytest
from shapely.geometry import box

from src.app import fetch, remote_s1 as R1, remote_s2
from src.app.extract import Zones, labels_for, zone_means
from src.app.providers import Scene
from src.app.s1 import VALID_MIN, to_db


def _eval(expr, bands):
    env = {f"{k}_b1": v for k, v in bands.items()}
    env.update(where=np.where, floor=np.floor, log10=np.log10)
    with np.errstate(invalid="ignore", divide="ignore"):
        return [np.asarray(eval(p, {"__builtins__": {}}, env), dtype="float64") for p in expr.split(";")]


def _server(bands):
    """What the server returns: codes as uint8 hi/lo, with its nodata mask (0 in all bands)."""
    parts = _eval(R1.build_expression(), bands)
    masked = (bands["vv"] == -32768) | (bands["vh"] == -32768)
    return [np.where(masked, 0, p).astype("uint8") for p in parts]


def _gamma0(seed=0, shape=(20, 20)):
    rng = np.random.default_rng(seed)
    vv = (10 ** rng.uniform(-3, 0.5, shape)).astype("float32")      # -30 .. +5 dB
    vh = (10 ** rng.uniform(-4, -0.5, shape)).astype("float32")
    vv[0, :5] = -32768; vh[1, :3] = 0.0; vv[2, :2] = np.nan; vh[3, :4] = -1e-3
    return vv, vh


def test_codes_round_trip_linear_power_within_quantisation():
    db = np.array([-79.9, -35.0, -12.3456, 0.0, 7.5, 49.9])
    lin, ok = R1.decode_codes(*(np.divmod(R1.encode_db(db), 256)))
    assert ok.all()
    assert np.max(np.abs(to_db(lin) - db)) <= 0.5 / R1.SCALE + 1e-9      # ~0.001 dB


def test_expression_matches_local_validity_and_values():
    vv, vh = _gamma0()
    hv, lv, hh, lh = _server({"vv": vv, "vh": vh})
    lin_vv, ok_vv = R1.decode_codes(hv, lv)
    lin_vh, ok_vh = R1.decode_codes(hh, lh)
    local_valid = (np.isfinite(vv) & (vv > 0) & (vv != -32768)) & (np.isfinite(vh) & (vh > 0) & (vh != -32768))
    assert np.array_equal(ok_vv & ok_vh, local_valid)
    m = local_valid
    assert np.max(np.abs(to_db(lin_vv[m]) - to_db(vv[m].astype(float)))) <= 0.5 / R1.SCALE + 1e-4


def test_out_of_range_db_is_clipped_not_dropped():
    bands = {"vv": np.array([1e-12, 1e7], dtype="float64"), "vh": np.array([1.0, 1.0])}
    hv, lv, _, _ = _eval(R1.build_expression(), bands)
    lin, ok = R1.decode_codes(hv.astype("uint8"), lv.astype("uint8"))
    assert ok.all()
    assert to_db(lin)[0] == pytest.approx(R1.DB_MIN) and to_db(lin)[1] == pytest.approx(R1.DB_MAX)


def test_reduce_linear_means_in_linear_then_db_like_s1():
    vv, vh = _gamma0(1)
    zones = Zones([box(0, 0, 400, 800), box(400, 0, 800, 800)], 32630, (0.0, 0.0, 800.0, 800.0))
    labels = labels_for(zones, remote_s2.label_transform(zones.bounds, 40.0), vv.shape)
    hv, lv, hh, lh = _server({"vv": vv, "vh": vh})
    lin_vv, ok_vv = R1.decode_codes(hv, lv)
    lin_vh, ok_vh = R1.decode_codes(hh, lh)
    out, vf, n_px = R1.reduce_linear({"VV": lin_vv, "VH": lin_vh}, ok_vv & ok_vh, labels, 2)
    valid = np.isfinite(vv) & (vv > 0) & (vv != -32768) & np.isfinite(vh) & (vh > 0)
    for pol, arr in (("VV", vv), ("VH", vh)):
        m, n_valid, n_total = zone_means(np.where(valid, arr, 0).astype("float32"), valid, labels, 2)
        assert np.allclose(out[pol], to_db(m), atol=2e-3)
    assert np.allclose(vf, n_valid / n_total)
    assert np.allclose(out["RATIO"], out["VH"] - out["VV"])
    assert n_px.tolist() == [200, 200]


def test_valid_min_masks_cells():
    labels = np.array([[1, 1, 2, 2]])
    lin = np.array([[1.0, 1.0, 1.0, np.nan]])
    ok = np.isfinite(lin)
    out, vf, _ = R1.reduce_linear({"VV": lin, "VH": lin}, ok, labels, 2)
    assert vf.tolist() == [1.0, 0.5] and 0.5 < VALID_MIN
    assert out["VV"][0] == 0.0 and np.isnan(out["VV"][1]) and np.isnan(out["RATIO"][1])


def test_expression_uses_both_assets_and_four_bands():
    e = R1.build_expression()
    assert e.count(";") == 3 and "vv_b1" in e and "vh_b1" in e
    p = R1.request_params("S1X_rtc", 32630, e, 4)
    assert ("collection", "sentinel-1-rtc") in p and [v for k, v in p if k == "rescale"] == ["0,255"] * 4


def test_item_fields():
    it = {"id": "S1X", "properties": {"proj:epsg": 32630, "proj:bbox": [1, 2, 3, 4]}, "assets": {"vv": {}}}
    assert R1.item_fields(it) == ("S1X", 32630, (1, 2, 3, 4))
    sc = Scene("S1Y", "S1", datetime(2022, 5, 1, tzinfo=timezone.utc), {}, {"grid_bounds": [5, 6, 7, 8]}, epsg=32631)
    assert R1.item_fields(sc) == ("S1Y", 32631, (5, 6, 7, 8))


def _scene():
    return Scene("S1Z", "S1", datetime(2022, 5, 1, 17, 49, tzinfo=timezone.utc), {},
                 {"orbit_state": "ascending", "relative_orbit": 132}, epsg=32630)


def test_process_scene_remote_keeps_the_s1_contract(monkeypatch):
    zones = Zones([box(0, 0, 400, 400), box(400, 0, 800, 400)], 32630, (0.0, 0.0, 800.0, 400.0))
    vals = {"VV": np.array([-10.0, np.nan]), "VH": np.array([-17.0, np.nan]), "RATIO": np.array([-7.0, np.nan])}
    monkeypatch.setattr(R1, "fetch_scene_cells",
                        lambda *a, **k: remote_s2.SceneCells("S1Z", vals, np.array([0.95, 0.3]), np.array([100, 100])))
    o, r = R1.process_scene_remote(_scene(), zones)
    assert r is None and o.values["RATIO"][0] == -7.0 and o.orbit == "ascending-132"
    assert o.valid_frac.tolist() == [0.95, 0.3]
    monkeypatch.setattr(R1, "fetch_scene_cells",
                        lambda *a, **k: remote_s2.SceneCells("S1Z", vals, np.array([0.5, 0.3]), np.array([100, 100])))
    o, r = R1.process_scene_remote(_scene(), zones)
    assert o is None and r.reason == "outside"
    with pytest.raises(ValueError):
        R1.process_scene_remote(_scene(), zones, require_zone0=True)


# --- wiring -------------------------------------------------------------------

PC = types.SimpleNamespace(name="planetary-computer")


def test_s1_gate_has_its_own_flag(monkeypatch):
    live = fetch.PROFILES["live"]
    monkeypatch.setattr(fetch, "REMOTE_S1", True)
    monkeypatch.setattr(fetch, "REMOTE_S2", False)
    assert fetch._use_remote(live, PC, False, sensor="S1")
    assert not fetch._use_remote(live, PC, False, sensor="S2")
    assert not fetch._use_remote(live, PC, True, sensor="S1")            # treated area stays local
    assert not fetch._use_remote(fetch.PROFILES["full"], PC, False, sensor="S1")
    monkeypatch.setattr(fetch, "REMOTE_S1", False)
    assert not fetch._use_remote(live, PC, False, sensor="S1")


def test_s1_api_failure_falls_back_to_local_read(monkeypatch):
    def boom(*a, **k):
        raise remote_s2.RemoteError("503")
    calls = []
    monkeypatch.setattr(R1, "process_scene_remote", boom)
    monkeypatch.setattr(fetch.s1mod, "process_scene",
                        lambda sc, zones, sign, res=None, require_zone0=False: calls.append(res) or ("obs", None))
    assert fetch._s1_remote_or_local("scene", "zones", None, res=40.0) == ("obs", None)
    assert calls == [40.0]
