"""The cleaned result of a fetch: dense per-observation series for the treated
area and every donor cell, plus receipts. Serialisable to a cache directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict

import numpy as np
from shapely.geometry import mapping, shape


@dataclass
class SensorSeries:
    """dates: (T,) 'YYYY-MM-DD'; values[name]: (T, 1+n_donors) column 0 = treated."""
    sensor: str
    dates: np.ndarray
    values: dict[str, np.ndarray]
    scene_ids: list[str]
    meta: dict = field(default_factory=dict)

    @property
    def n_obs(self) -> int:
        return len(self.dates)

    def treated(self, name: str) -> np.ndarray:
        return self.values[name][:, 0]

    def donors(self, name: str) -> np.ndarray:
        return self.values[name][:, 1:]


@dataclass
class AreaData:
    area_geojson: dict
    area_ha: float
    epsg: int
    cells_geojson: list[dict]          # donor cells in WGS84
    cell_distance_m: list[float]
    start: str
    end: str
    s2: SensorSeries | None
    s1: SensorSeries | None
    receipts: list[dict]
    summary: dict
    timing: dict = field(default_factory=dict)
    mode: str = "ring"
    groups: list = field(default_factory=list)     # wide mode: [{"cells_geojson", "distance_m", "landcover", "elevation", "s2", "s1"}]

    # ---- persistence ----------------------------------------------------
    @staticmethod
    def _dump_series(ss, d, name):
        if ss is None:
            return None
        np.savez_compressed(os.path.join(d, f"{name}.npz"), **ss.values)
        return {"sensor": ss.sensor, "dates": ss.dates.tolist(), "scene_ids": ss.scene_ids,
                "meta": ss.meta, "keys": list(ss.values)}

    @staticmethod
    def _load_series(m, d, name):
        if m is None:
            return None
        z = np.load(os.path.join(d, f"{name}.npz"))
        return SensorSeries(m["sensor"], np.asarray(m["dates"]), {k: z[k] for k in m["keys"]},
                            m["scene_ids"], m["meta"])

    def save(self, d: str) -> None:
        os.makedirs(d, exist_ok=True)
        meta = {k: v for k, v in self.__dict__.items() if k not in ("s2", "s1", "groups")}
        meta["s2"] = self._dump_series(self.s2, d, "s2")
        meta["s1"] = self._dump_series(self.s1, d, "s1")
        meta["groups"] = []
        for gi, g in enumerate(self.groups):
            gm = {k: v for k, v in g.items() if k not in ("s2", "s1")}
            gm["s2"] = self._dump_series(g.get("s2"), d, f"g{gi}_s2")
            gm["s1"] = self._dump_series(g.get("s1"), d, f"g{gi}_s1")
            meta["groups"].append(gm)
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(meta, f)

    @classmethod
    def load(cls, d: str) -> "AreaData":
        with open(os.path.join(d, "meta.json")) as f:
            meta = json.load(f)
        meta["s2"] = cls._load_series(meta.get("s2"), d, "s2")
        meta["s1"] = cls._load_series(meta.get("s1"), d, "s1")
        groups = []
        for gi, gm in enumerate(meta.get("groups", [])):
            gm["s2"] = cls._load_series(gm.get("s2"), d, f"g{gi}_s2")
            gm["s1"] = cls._load_series(gm.get("s1"), d, f"g{gi}_s1")
            groups.append(gm)
        meta["groups"] = groups
        meta.setdefault("mode", "ring")
        return cls(**meta)


def cache_key(area_geojson: dict, start: str, end: str, grid_sig: str, version: str = "v1") -> str:
    g = shape(area_geojson)
    coords = np.round(np.asarray(g.exterior.coords), 6).tolist()
    s = json.dumps({"c": coords, "s": start, "e": end, "g": grid_sig, "v": version})
    return hashlib.sha1(s.encode()).hexdigest()[:16]
