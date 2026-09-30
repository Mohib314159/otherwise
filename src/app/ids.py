"""Run ids and the runs directory, importable without the analysis pipeline.

The web process needs these to answer requests (find a saved run, compute the id
a submitted area would get) but must not pay for rasterio/scipy/pandas at start-up
on a 512 MB host: the pipeline itself only ever runs in the spawned job child
(see jobrunner.py). `run.py` re-exports both names, so existing imports keep working.
"""
from __future__ import annotations

import os

RUNS_DIR = os.environ.get("APP_RUNS_DIR", "data/runs")


def run_id(area_geojson, event_date, change_type, post_months) -> str:
    from .series import cache_key        # numpy + shapely: loaded on first submit only
    return cache_key(area_geojson, str(event_date), str(post_months), change_type, version="run1")
