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

    # ---- persistence ----------------------------------------------------
    def save(self, d: str) -> None:
        os.makedirs(d, exist_ok=True)
        meta = {k: v for k, v in asdict(self).items() if k not in ("s2", "s1")}
        for name in ("s2", "s1"):
            ss = getattr(self, name)
            if ss is None:
                meta[name] = None
                continue
            meta[name] = {"sensor": ss.sensor, "dates": ss.dates.tolist(),
                          "scene_ids": ss.scene_ids, "meta": ss.meta, "keys": list(ss.values)}
            np.savez_compressed(os.path.join(d, f"{name}.npz"), **ss.values)
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(meta, f)

    @classmethod
    def load(cls, d: str) -> "AreaData":
        with open(os.path.join(d, "meta.json")) as f:
            meta = json.load(f)
        out = {}
        for name in ("s2", "s1"):
            m = meta.pop(name)
            if m is None:
                out[name] = None
                continue
            z = np.load(os.path.join(d, f"{name}.npz"))
            out[name] = SensorSeries(m["sensor"], np.asarray(m["dates"]),
                                     {k: z[k] for k in m["keys"]}, m["scene_ids"], m["meta"])
        return cls(**meta, **out)


def cache_key(area_geojson: dict, start: str, end: str, grid_sig: str, version: str = "v1") -> str:
    g = shape(area_geojson)
    coords = np.round(np.asarray(g.exterior.coords), 6).tolist()
    s = json.dumps({"c": coords, "s": start, "e": end, "g": grid_sig, "v": version})
    return hashlib.sha1(s.encode()).hexdigest()[:16]
