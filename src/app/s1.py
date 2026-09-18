"""Sentinel-1 RTC: gamma0 VV/VH area means, orbit consistency, receipts.

Backscatter from different relative orbits sees the ground at different
incidence angles, so mixing them puts a saw-tooth into the series. We keep the
relative orbit with the most coverage and log the rest as receipts.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .extract import Zones, labels_for, read_window, zone_means
from .providers import Scene
from .s2 import Receipt

VALID_MIN = 0.80
POLS = ("VV", "VH")


@dataclass
class S1Observation:
    scene_id: str
    date: str
    minute_key: str
    values: dict[str, np.ndarray]      # "VV","VH" in dB, "RATIO" = VH-VV dB
    valid_frac: np.ndarray
    n_pixels: np.ndarray
    props: dict = field(default_factory=dict)

    @property
    def orbit(self) -> str:
        return f"{self.props.get('orbit_state', '?')}-{self.props.get('relative_orbit', '?')}"


def to_db(x: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(x > 0, 10.0 * np.log10(x), np.nan)


def process_scene(scene: Scene, zones: Zones, sign) -> tuple[S1Observation | None, Receipt | None]:
    n = len(zones.polygons)
    lin = {}
    valid_all = None
    labels = None
    for pol in POLS:
        r = read_window(sign(scene.hrefs[pol]), zones)
        if r is None:
            return None, Receipt("S1", scene.date, scene.id, "outside",
                                 "Scene footprint does not cover the area.")
        arr, tr, nodata = r
        if labels is None:
            labels = labels_for(zones, tr, arr.shape)
        if labels.shape != arr.shape:
            return None, Receipt("S1", scene.date, scene.id, "read-error",
                                 f"{pol} window shape mismatch.")
        v = np.isfinite(arr) & (arr > 0)
        if nodata is not None:
            v &= arr != nodata
        valid_all = v if valid_all is None else (valid_all & v)
        lin[pol] = arr
    values, vf = {}, None
    for pol in POLS:
        m, n_valid, n_total = zone_means(lin[pol], valid_all, labels, n)
        if vf is None:
            with np.errstate(invalid="ignore", divide="ignore"):
                vf = np.where(n_total > 0, n_valid / np.maximum(n_total, 1), 0.0)
        m[vf < VALID_MIN] = np.nan
        values[pol] = to_db(m)          # mean in linear power, then dB
    if n_total[0] == 0:
        return None, Receipt("S1", scene.date, scene.id, "outside",
                             "Scene footprint does not cover the area.")
    if vf[0] == 0:
        return None, Receipt("S1", scene.date, scene.id, "outside",
                             "Scene footprint does not cover the area.")
    if vf[0] < VALID_MIN:
        return None, Receipt("S1", scene.date, scene.id, "edge",
                             f"Only {vf[0]:.0%} of the area has valid radar pixels (swath edge or layover); dropped.",
                             value=float(vf[0]))
    values["RATIO"] = values["VH"] - values["VV"]
    return S1Observation(scene.id, scene.date, scene.minute_key, values, vf, n_total,
                         props=dict(scene.props)), None


def select_orbit(obs: list[S1Observation]) -> tuple[list[S1Observation], list[Receipt], str]:
    """Keep the relative orbit with the most observations of the treated area."""
    if not obs:
        return [], [], ""
    counts = Counter(o.orbit for o in obs)
    best = counts.most_common(1)[0][0]
    keep, receipts = [], []
    for o in obs:
        if o.orbit == best:
            keep.append(o)
        else:
            receipts.append(Receipt("S1", o.date, o.scene_id, "orbit",
                                    f"Relative orbit {o.orbit} differs from the main orbit {best} "
                                    f"(different look angle); kept out of the series."))
    return keep, receipts, best


def dedupe_by_minute(obs: list[S1Observation]) -> tuple[list[S1Observation], list[Receipt]]:
    from .s2 import merge_duplicates
    return merge_duplicates(obs)


def select_orbit_scenes(scenes: list[Scene], area_wgs84) -> tuple[list[Scene], list[Receipt], str]:
    """Pick the relative orbit with the most passes over the area BEFORE reading
    anything; other orbits are logged, not read."""
    covering = [s for s in scenes if s.geometry is None or s.geometry.intersects(area_wgs84)]
    if not covering:
        return [], [], ""
    key = lambda s: f"{s.props.get('orbit_state', '?')}-{s.props.get('relative_orbit', '?')}"
    counts = Counter(key(s) for s in covering)
    best = counts.most_common(1)[0][0]
    keep, receipts = [], []
    for s in covering:
        if key(s) == best:
            keep.append(s)
        else:
            receipts.append(Receipt("S1", s.date, s.id, "orbit",
                                    f"Relative orbit {key(s)} differs from the main orbit {best} "
                                    f"(different look angle); kept out of the series."))
    return keep, receipts, best
