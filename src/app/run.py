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

from .ids import RUNS_DIR, run_id  # noqa: F401  (re-exported; defined light for the web process)
PRE_YEARS = 3
MAX_POST_MONTHS = 18
BIN_DAYS = 10
DONOR_K = 80
LIVE_DONOR_K = 40          # live runs read fewer, coarser control cells; see DECISIONS.md


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
    pool = b.matrix[:, 1:].T                             # (n, B) every covered candidate
    D = pool[sel.index]                                  # (m, B) the treated unit's donors
    if D.shape[0] < 3:
        return None
    progress(f"{signal}: fitting", 0, 1)
    # Placebo units are drawn from the whole candidate pool, and each one re-runs
    # the treated unit's donor selection on itself. See DECISIONS.md, CRITIQUE #4.
    cell_of_col = np.where(b.donor_cov >= 0.70)[0]
    res, f, ci, sp, tp = signal_result(
        y, D, b.pre, signal, sensor, expected_sign, pool=pool,
        select_for=_placebo_selector(pool, b.pre, cell_of_col, cov, donor_k),
        select_at=_time_selector(b.matrix, b.donor_cov, cov, donor_k),
        progress=lambda: progress(f"{signal}: placebo", 0, 1))
    tp_reselected = all(t.reselected for t in tp)
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
        "time_placebo_reselected": tp_reselected,
    }
    # sel.index counts coverage-filtered columns; sel.cell_index maps back to the
    # grid. Using sel.index here drew the wrong cells on the control-areas map
    # whenever any cell was dropped for coverage (i.e. on most runs).
    donors = {"grid_index": (donor_all_idx[sel.cell_index]).tolist(),
              "weights": np.round(f.weights, 4).tolist(), "pre_rmse": np.round(sel.pre_rmse, 4).tolist(),
              "notes": sel.notes, "counts": sel.counts}
    return res, chart, donors


def signal_result(y, D, pre, signal, sensor, expected_sign, pool=None, select_for=None,
                  select_at=None, progress=lambda: None):
    """Estimator outputs -> the SignalResult `verdict.decide` judges.

    The one place a SignalResult is built from a fit, its conformal interval, the
    in-space placebo and the in-time placebos, with the product's settings
    (ALPHA, 60 placebo units, 3 fake dates). `scripts/power.py` calls this too,
    so the power table measures the rule the app ships (CRITIQUE #9).
    Returns (SignalResult, Fit, Conformal, SpacePlacebo, [TimePlacebo]).
    """
    f = fit_ascm(y, D, pre)
    point = float(np.mean(f.effect[~pre]))
    ci = conformal_interval(y, D, pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA)
    progress()
    sp = space_placebo(y, D, pre, f.lam, point, max_units=60, pool=pool, select_for=select_for)
    # With `select_at`, each fake date re-selects the treated unit's donors, and
    # re-tunes lambda, on data before that fake date only (DECISIONS.md,
    # CRITIQUE #4 follow-up); without it, the older fixed-donor procedure.
    tp = time_placebos(y, D, pre, None if select_at is not None else f.lam, n=3,
                       min_effect=MIN_EFFECT[signal], alpha=ALPHA,
                       pool=pool if select_at is not None else None, select_at=select_at)
    res = SignalResult(signal=signal, sensor=sensor, expected_sign=expected_sign,
                       point=point, lo=ci.lo, hi=ci.hi, p_zero=ci.p_zero, pre_rmse=f.pre_rmse,
                       placebo_pre_rmse_median=float(np.median(sp.pre_rmses)),
                       n_pre=int(pre.sum()), n_post=int((~pre).sum()), n_donors=int(D.shape[0]),
                       placebo_p=sp.p_value, placebo_p_effect=sp.p_effect, placebo_n=int(len(sp.ratios)),
                       time_placebo_flags=[t.flagged for t in tp],
                       placebo_effect_median=float(np.median(sp.effects)),
                       placebo_symmetric=bool(sp.symmetric))
    return res, f, ci, sp, tp


def _time_selector(matrix: np.ndarray, donor_cov: np.ndarray, cov: Covariates | None, k: int):
    """The treated unit's own donor selection, restricted to a sub-window.

    Returns select_at(mask) -> row indices into the candidate pool
    (`matrix[:, 1:].T`): exactly `select_donors` as run for the real analysis
    (same land-cover / elevation filters, same k, same relaxation), except that
    the pre-event similarity ranking sees only the periods where `mask` is True.
    `time_placebos` passes the window before each fake date, so no fake-date
    test is run on donors chosen partly on the window it is scoring.

    The coverage filter is unchanged: it is a data-availability rule over the
    whole window, not an outcome comparison, and it defines the candidate set
    itself (the same pool the space placebo draws from).
    """
    def select_at(mask: np.ndarray):
        return select_donors(matrix, mask, donor_cov, cov, k=k).index

    return select_at


def _placebo_selector(pool: np.ndarray, pre: np.ndarray, cell_of_col: np.ndarray,
                      cov: Covariates | None, k: int):
    """Give every placebo unit the same donor selection the treated unit got.

    `pool` is (n, T): every covered candidate cell. `cell_of_col[i]` is the grid
    cell behind pool row i, which is how a unit's own covariates are found
    (Covariates arrays are indexed 0 = treated area, c + 1 = cell c).

    Returns select_for(j) -> row indices into `pool`, being the donors unit j
    gets when `select_donors` is applied with j in the treated slot: ranked by
    j's own pre-event similarity, filtered by j's own land cover and elevation,
    same k, same relaxation rules. See DECISIONS.md, CRITIQUE #4.
    """
    n = pool.shape[0]
    all_rows = np.arange(n)

    def select_for(j: int):
        others = all_rows[all_rows != j]
        if len(others) < 3:
            return None
        # unit j in the treated slot, every other candidate as a donor
        matrix_j = np.column_stack([pool[j], pool[others].T])
        cov_j = None
        if cov is not None:
            cj, co = cell_of_col[j], cell_of_col[others]

            def take(arr):
                return np.concatenate([[arr[cj + 1]], arr[co + 1]])

            cov_j = Covariates(take(cov.landcover).astype(int), take(cov.landcover_frac),
                               take(cov.elevation), take(cov.slope), cov.year)
        # every column of matrix_j is a real candidate, so coverage is all ones and
        # select_donors' internal good_idx becomes the identity -- its assertion
        # that the two line up is what keeps this honest
        sel_j = select_donors(matrix_j, pre, np.ones(len(others)), cov_j, k=k)
        return others[sel_j.index]

    return select_for


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
        "signals": {k: {**v.__dict__, "min_effect": v.min_effect, "pre_fit_ok": v.pre_fit_ok, "pre_fit_loose": v.pre_fit_loose,
                        # missing on runs that predate the leak-free in-time placebo
                        "time_placebo_reselected": bool((charts.get(k) or {}).get("time_placebo_reselected", False))}
                    for k, v in results.items()},
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
