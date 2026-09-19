"""One verdict, end to end: fetch -> bin -> donors -> estimate -> placebo -> verdict."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, datetime, timezone

import numpy as np
from dateutil.relativedelta import relativedelta

from .covariates import Covariates, fetch_covariates
from .donors import select_donors
from .estimator import conformal_interval, fit_ascm, space_placebo, time_placebos
from .evidence import assess
from .fetch import fetch_area
from .geometry import validate_polygon, donor_grid
from .prep import binned, binned_groups
from .verdict import ALPHA, SIGNALS, SignalResult, Verdict, combine, MIN_EFFECT

RUNS_DIR = os.environ.get("APP_RUNS_DIR", "data/runs")
PRE_YEARS = 3
MAX_POST_MONTHS = 18
BIN_DAYS = 10
DONOR_K = 80
LIVE_DONOR_K = 40          # live runs read fewer, coarser control cells; see DECISIONS.md


def run_id(area_geojson, event_date, change_type, post_months) -> str:
    from .series import cache_key
    return cache_key(area_geojson, str(event_date), str(post_months), change_type, version="run1")


def _window(event: date, post_months: int) -> tuple[str, str]:
    start = event - relativedelta(years=PRE_YEARS)
    end = event + relativedelta(months=post_months)
    today = date.today()
    return start.isoformat(), min(end, today).isoformat()


def _analyse(dates, values, event_np, donor_all_idx, cov, signal, sensor, expected_sign, progress,
             groups=None, donor_k=DONOR_K):
    """values: (T, 1+n) per-observation. Returns (SignalResult, chart dict, donors dict) or None.
    In wide mode `groups` is a list of (dates, values) donor blocks with their own date axes."""
    if groups is not None:
        b = binned_groups(dates, values, groups, event_np, bin_days=BIN_DAYS)
    else:
        b = binned(dates, values, event_np, bin_days=BIN_DAYS)
    if b.matrix.shape[1] < 2 or b.pre.sum() < 5 or (~b.pre).sum() < 1:
        return None
    sel = select_donors(b.matrix, b.pre, b.donor_cov, cov, k=donor_k)
    y = b.matrix[:, 0]
    D = b.matrix[:, 1:][:, sel.index].T                  # (m, B)
    if D.shape[0] < 3:
        return None
    progress(f"{signal}: fitting", 0, 1)
    f = fit_ascm(y, D, b.pre)
    point = float(np.mean(f.effect[~b.pre]))
    ci = conformal_interval(y, D, b.pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA)
    progress(f"{signal}: placebo", 0, 1)
    sp = space_placebo(y, D, b.pre, f.lam, point, max_units=60)
    tp = time_placebos(y, D, b.pre, f.lam, n=3, min_effect=MIN_EFFECT[signal], alpha=ALPHA)
    res = SignalResult(signal=signal, sensor=sensor, expected_sign=expected_sign,
                       point=point, lo=ci.lo, hi=ci.hi, p_zero=ci.p_zero, pre_rmse=f.pre_rmse,
                       placebo_pre_rmse_median=float(np.median(sp.pre_rmses)),
                       n_pre=int(b.pre.sum()), n_post=int((~b.pre).sum()), n_donors=int(D.shape[0]),
                       placebo_p=sp.p_value, placebo_p_effect=sp.p_effect, placebo_n=int(len(sp.ratios)),
                       time_placebo_flags=[t.flagged for t in tp],
                       placebo_effect_median=float(np.median(sp.effects)))
    band_lo = np.percentile(sp.effect_series, 5, axis=0)
    band_hi = np.percentile(sp.effect_series, 95, axis=0)
    chart = {
        "dates": [str(d) for d in b.dates], "pre": b.pre.tolist(), "n_obs": b.n_obs.tolist(),
        "treated": np.round(y, 4).tolist(), "counterfactual": np.round(f.synthetic, 4).tolist(),
        "counterfactual_scm": np.round(f.synthetic_scm, 4).tolist(),
        "effect": np.round(f.effect, 4).tolist(),
        "placebo_band": [np.round(band_lo, 4).tolist(), np.round(band_hi, 4).tolist()],
        "placebo_effects": np.round(sp.effects, 4).tolist(),
        "time_placebos": [{"date": str(b.dates[t.fake_index]), "effect": round(t.effect, 4),
                           "lo": round(t.lo, 4), "hi": round(t.hi, 4), "flagged": t.flagged} for t in tp],
        "ci_grid": np.round(ci.grid, 4).tolist(), "ci_pvals": np.round(ci.pvals, 3).tolist(),
        "lambda": f.lam,
    }
    donors = {"grid_index": (donor_all_idx[sel.index]).tolist(),
              "weights": np.round(f.weights, 4).tolist(), "pre_rmse": np.round(sel.pre_rmse, 4).tolist(),
              "notes": sel.notes, "counts": sel.counts}
    return res, chart, donors


WIDE_INNER_M = 20_000.0
WIDE_OUTER_M = 150_000.0


def _controls_shifted(res: SignalResult | None) -> bool:
    """The ring's placebo cells moved with the area: the event is probably larger than the ring."""
    if res is None:
        return False
    return abs(res.placebo_effect_median) >= res.min_effect and np.sign(res.placebo_effect_median) == np.sign(res.point)


def _wide_cov(data) -> Covariates:
    lc = [data.summary.get("treated_landcover", 0)] + [c for g in data.groups for c in g["landcover"]]
    el = [np.nan] + [e if e is not None else np.nan for g in data.groups for e in g["elevation"]]
    n = len(lc)
    return Covariates(np.asarray(lc, dtype=int), np.ones(n), np.asarray(el, dtype=float),
                      np.full(n, np.nan), 2021)


def _analyse_all(data, event_np, primary_sig, sign, radar, cov, progress, donor_k=DONOR_K):
    """Run the per-signal analysis for a fetched AreaData (ring or wide).

    A fetch that split the treated and control reads into separate passes (wide
    mode, and the live profile's ring) returns `groups`, each with its own date
    axis; those are joined on event-anchored bins by `prep.binned_groups`."""
    results, charts, donors = {}, {}, {}
    wide = bool(data.groups)
    n_cells = len(data.cells_geojson)
    idx = np.arange(n_cells)
    if data.s2 is not None:
        groups = ([(g["s2"].dates, g["s2"].values[primary_sig]) for g in data.groups if g.get("s2") is not None]
                  if wide else None)
        r = _analyse(data.s2.dates, data.s2.values[primary_sig], event_np, idx, cov, primary_sig, "S2", sign,
                     progress, groups=groups, donor_k=donor_k)
        if r:
            results[primary_sig], charts[primary_sig], donors[primary_sig] = r
    if data.s1 is not None:
        for rsig, rsign in radar:
            groups = ([(g["s1"].dates, g["s1"].values[rsig]) for g in data.groups if g.get("s1") is not None]
                      if wide else None)
            r = _analyse(data.s1.dates, data.s1.values[rsig], event_np, idx, cov, rsig, "S1", rsign,
                         progress, groups=groups, donor_k=donor_k)
            if r:
                results[rsig], charts[rsig], donors[rsig] = r
    return results, charts, donors


def run_verdict(area_geojson: dict, event_date: str, change_type: str = "other",
                post_months: int = 12, label: str = "", progress=lambda s, d, t: None,
                save: bool = True, runs_dir: str = RUNS_DIR, mode: str = "auto",
                inner_m: float | None = None, outer_m: float | None = None,
                profile: str = "full") -> dict:
    """mode: "ring" (controls 1-12 km away), "wide" (similarity-matched controls
    inner_m..outer_m away, for events larger than the ring) or "auto" (ring first,
    escalate to wide when the ring's controls moved with the area).

    profile: "full" reads every control cell at 10 m from one window (offline,
    showcase and validation runs). "live" reads the treated area alone at 10 m
    and the controls coarsely in a second pass, with the scene list pre-filtered,
    so a user-drawn run fits the deployment's memory. `scripts/compare_profiles.py`
    measures what the difference costs.
    """
    t0 = time.time()
    change_type = change_type if change_type in SIGNALS else "other"
    post_months = int(min(max(post_months, 1), MAX_POST_MONTHS))
    event = date.fromisoformat(event_date)
    if event < date(2018, 1, 1):
        raise ValueError("Event date must be 2018 or later (three years of Sentinel history are needed).")
    start, end = _window(event, post_months)
    rid = run_id(area_geojson, event_date, change_type, post_months)
    area = validate_polygon(area_geojson)
    cov_year = 2020 if event < date(2022, 1, 1) else 2021
    event_np = np.datetime64(event_date)
    primary_sig, sign, radar = SIGNALS[change_type]
    used_mode = "ring"
    escalation = None
    donor_k = LIVE_DONOR_K if profile == "live" else DONOR_K

    cov = None
    if mode in ("ring", "auto"):
        progress("fetch", 0, 1)
        data = fetch_area(area_geojson, start, end, progress=progress, profile=profile,
                          event_date=event_date)
        if data.groups:
            # the live profile already read covariates for its control cells
            cov = _wide_cov(data)
        else:
            grid = donor_grid(area)
            progress("covariates", 0, 1)
            try:
                cov = fetch_covariates([area.utm] + grid.cells, area.epsg, cov_year)
            except Exception:
                cov = None
        results, charts, donors = _analyse_all(data, event_np, primary_sig, sign, radar, cov, progress,
                                               donor_k=donor_k)
        lead0 = results.get(primary_sig) or next((results[r] for r, _ in radar if r in results), None)
        if mode == "auto" and _controls_shifted(lead0):
            escalation = {"reason": "ring controls shifted with the area",
                          "ring_placebo_median": round(float(lead0.placebo_effect_median), 4),
                          "ring_point": round(float(lead0.point), 4)}
            mode = "wide"
    if mode == "wide":
        used_mode = "wide"
        progress("fetch wide", 0, 1)
        data = fetch_area(area_geojson, start, end, progress=progress, mode="wide", cov_year=cov_year,
                          inner_m=inner_m or WIDE_INNER_M, outer_m=outer_m or WIDE_OUTER_M,
                          max_cells=90 if profile == "live" else 150,
                          n_groups=4 if profile == "live" else 6,
                          profile=profile, event_date=event_date)
        cov = _wide_cov(data)
        results, charts, donors = _analyse_all(data, event_np, primary_sig, sign, radar, cov, progress,
                                               donor_k=donor_k)

    # lead signal: optical unless it has too few post-event observations and radar has enough
    lead = primary_sig if primary_sig in results else None
    if lead is None or results[lead].n_post < 3:
        for rsig, _ in radar:
            if rsig in results and results[rsig].n_post >= 3:
                lead = rsig
                break
    post_label = f"in the {post_months} months after {event.strftime('%-d %b %Y')}"
    if lead is None:
        verdict = Verdict("CANT_TELL", "Can't tell",
                          "Not enough clear observations to build a control trajectory for this area and window.",
                          ["no usable series"], primary_sig)
    else:
        verdict = combine(results[lead], results.get(primary_sig), change_type, post_label)
    ev = assess(results, change_type)

    out = {
        "id": rid, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label, "change_type": change_type, "event_date": event_date,
        "post_months": post_months, "window": [start, end],
        "area": {"geojson": area.geojson, "ha": round(area.area_ha, 2), "lon": round(area.lon, 5),
                 "lat": round(area.lat, 5),
                 "landcover": (cov.label(0) if cov and cov.landcover[0] else None),
                 "elevation_m": (round(float(cov.elevation[0])) if cov and np.isfinite(cov.elevation[0]) else None)},
        "verdict": {"status": verdict.status, "headline": verdict.headline,
                    "statement": verdict.statement, "reasons": verdict.reasons, "lead_signal": verdict.lead_signal},
        "evidence": {"agreement": ev.agreement, "optical": ev.optical_status, "radar": ev.radar_status,
                     "p_combined": ev.p_combined, "sentence": ev.sentence},
        "mode": used_mode, "profile": profile, "escalation": escalation,
        "controls": {"mode": used_mode, "inner_m": data.summary.get("inner_m", 1000.0),
                     "outer_m": data.summary.get("outer_m", 12000.0), "n_groups": data.summary.get("n_groups", 1)},
        "signals": {k: {**v.__dict__, "min_effect": v.min_effect, "pre_fit_ok": v.pre_fit_ok} for k, v in results.items()},
        "charts": charts,
        "donors": {**{k: v for k, v in donors.items()},
                   "cells": data.cells_geojson, "distance_m": [round(d) for d in data.cell_distance_m],
                   "landcover": (cov.landcover.tolist() if cov else None),
                   "groups": [{"n": len(g["cells_geojson"]), "distance_m": [round(d) for d in g["distance_m"]],
                               "seconds": g.get("seconds")} for g in data.groups]},
        "receipts": data.receipts,
        "data_summary": data.summary,
        "timing": {**data.timing, "run_s": round(time.time() - t0, 1)},
        "method": {"estimator": "augmented synthetic control (ridge-corrected convex weights)",
                   "interval": f"conformal, moving-block permutation, {int((1 - ALPHA) * 100)}%",
                   "bin_days": BIN_DAYS, "pre_years": PRE_YEARS, "donor_k": donor_k,
                   "profile": profile,
                   "donor_res_m": data.summary.get("donor_res_m"),
                   "scenes_read": data.summary.get("s2_scenes_read")},
    }
    if save:
        os.makedirs(runs_dir, exist_ok=True)
        with open(os.path.join(runs_dir, f"{rid}.json"), "w") as f:
            json.dump(out, f)
    return out
