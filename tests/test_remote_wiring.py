"""Live donor reads go through the PC data API, and fall back to the local read."""
from __future__ import annotations

import types

from src.app import fetch, remote_s2


PC = types.SimpleNamespace(name="planetary-computer")
ES = types.SimpleNamespace(name="earth-search")


def test_remote_only_for_live_donor_groups_on_pc(monkeypatch):
    monkeypatch.setattr(fetch, "REMOTE_S2", True)
    live, full = fetch.PROFILES["live"], fetch.PROFILES["full"]
    assert fetch._use_remote(live, PC, require_zone0=False)
    assert not fetch._use_remote(live, PC, require_zone0=True)     # treated area stays local
    assert not fetch._use_remote(full, PC, require_zone0=False)    # full profile stays local
    assert not fetch._use_remote(live, ES, require_zone0=False)    # data API is PC-only
    monkeypatch.setattr(fetch, "REMOTE_S2", False)
    assert not fetch._use_remote(live, PC, require_zone0=False)


def test_api_failure_falls_back_to_local_read(monkeypatch):
    def boom(*a, **k):
        raise remote_s2.RemoteError("503")
    calls = []
    monkeypatch.setattr(remote_s2, "process_scene_remote", boom)
    monkeypatch.setattr(fetch.s2mod, "process_scene",
                        lambda sc, zones, sign, res=None, require_zone0=False: calls.append(res) or ("obs", None))
    assert fetch._s2_remote_or_local("scene", "zones", None, res=40.0) == ("obs", None)
    assert calls == [40.0]


def test_remote_fills_nbr_from_a_second_request(monkeypatch):
    obs = types.SimpleNamespace(values={"NDVI": [0.5], "NDWI": [-0.4], "NBR": [float("nan")]})
    monkeypatch.setattr(remote_s2, "process_scene_remote", lambda *a, **k: (obs, None))
    monkeypatch.setattr(remote_s2, "fetch_scene_cells",
                        lambda *a, **k: types.SimpleNamespace(values={"NBR": [0.3]}))
    zones = types.SimpleNamespace(epsg=32630, polygons=[None])
    o, r = fetch._s2_remote_or_local("scene", zones, None, res=40.0)
    assert o.values["NBR"] == [0.3] and r is None
