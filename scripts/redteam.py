"""Red-team experiments for the Otherwise method (see docs/REDTEAM.md).

Every experiment runs offline on cached real data (data/cache/<key>) or on
synthetic series, and reuses the app's own pipeline: prep.binned ->
donors.select_donors -> estimator (ASCM + conformal + placebo) -> verdict.decide.
Nothing here touches the network or edits any app file.

    python3 -m scripts.redteam            # all experiments
    python3 -m scripts.redteam e1 e7      # a subset

Each experiment takes well under two minutes on the cached data.
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings

import numpy as np
from shapely.geometry import box

from src.app import s2 as s2mod
from src.app.donors import select_donors
from src.app.estimator import conformal_interval, fit_ascm, space_placebo, time_placebos
from src.app.geometry import Area, donor_grid, wide_candidates
from src.app.prep import binned
from src.app.series import AreaData
from src.app.verdict import ALPHA, MIN_EFFECT, SIGNALS, SignalResult, decide

warnings.filterwarnings("ignore", category=RuntimeWarning)

CACHES = {
    "midlands": "data/cache/5f0bbacbdf08fe51",   # 36 ha arable, 2020-2024, 79 clear S2 obs (cloudiest)
    "austin": "data/cache/52694d610e86d9fe",     # 53 ha, 2017-2021, 213 clear S2 obs (sunny)
    "richmond": "data/cache/2fdf10a60e49000a",   # 46 ha, 2019-2023, 110 obs
    "sindh": "data/cache/5fbfbf9d6b6f9eaa",      # flood site, 2019-2022, 240 obs
}
N_UNITS = 15
SEED = 0


# ---------------------------------------------------------------------------
# shared helper: exactly what run._analyse + verdict.decide do, on one column
# ---------------------------------------------------------------------------
def analyse(dates, V, u, event, signal="NDVI", change_type="other", k=80, n_grid=11,
            max_units=60, time_pl=False, sign=None):
    """Treat column `u` of V (T, 1+n) as the area; the other donor columns are the pool."""
    cols = [u] + [c for c in range(1, V.shape[1]) if c != u]
    M = V[:, cols]
    b = binned(dates, M, event, bin_days=10)
    if b.matrix.shape[1] < 2 or b.pre.sum() < 5 or (~b.pre).sum() < 1:
        return None
    sel = select_donors(b.matrix, b.pre, b.donor_cov, None, k=k)
    y = b.matrix[:, 0]
    D = b.matrix[:, 1:][:, sel.index].T
    if D.shape[0] < 3:
        return None
    f = fit_ascm(y, D, b.pre)
    point = float(np.mean(f.effect[~b.pre]))
    ci = conformal_interval(y, D, b.pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA, n_grid=n_grid)
    sp = space_placebo(y, D, b.pre, f.lam, point, max_units=max_units)
    flags = []
    if time_pl:
        flags = [t.flagged for t in time_placebos(y, D, b.pre, f.lam, n=3, min_effect=MIN_EFFECT[signal], alpha=ALPHA)]
    exp_sign = SIGNALS[change_type][1] if sign is None else sign
    r = SignalResult(signal=signal, sensor="S2", expected_sign=exp_sign, point=point, lo=ci.lo, hi=ci.hi,
                     p_zero=ci.p_zero, pre_rmse=f.pre_rmse, placebo_pre_rmse_median=float(np.median(sp.pre_rmses)),
                     n_pre=int(b.pre.sum()), n_post=int((~b.pre).sum()), n_donors=int(D.shape[0]),
                     placebo_p=sp.p_value, placebo_p_effect=sp.p_effect, placebo_n=int(len(sp.ratios)),
                     time_placebo_flags=flags, placebo_effect_median=float(np.median(sp.effects)))
    v = decide(r, change_type, "")
    loose = r.pre_rmse <= max(1.5 * r.placebo_pre_rmse_median, 0.02)
    return {"status": v.status, "reasons": v.reasons, "point": point, "lo": ci.lo, "hi": ci.hi,
            "pre_rmse": f.pre_rmse, "placebo_med": float(np.median(sp.pre_rmses)), "placebo_p": sp.p_value,
            "placebo_eff_med": float(np.median(sp.effects)), "n_pre": r.n_pre, "n_post": r.n_post,
            "n_donors": r.n_donors, "ratio": abs(point) / max(f.pre_rmse, 1e-9), "loose_ok": loose,
            "pre_fit_ok": r.pre_fit_ok, "time_flags": flags, "lam": f.lam, "b": b}


def load(name, signal="NDVI"):
    d = AreaData.load(CACHES[name])
    ss = d.s2 if signal in ("NDVI", "NDWI", "NBR") else d.s1
    V = ss.values[signal].astype(float)
    dates = ss.dates.astype("datetime64[D]")
    return d, V, dates


def null_units(V, n=N_UNITS, seed=SEED, min_cov=0.75):
    cov = np.mean(np.isfinite(V[:, 1:]), axis=0)
    good = np.where(cov >= min_cov)[0] + 1
    rng = np.random.default_rng(seed)
    return rng.choice(good, size=min(n, len(good)), replace=False)


def base_event(dates, frac=0.65):
    return np.datetime64(dates[int(len(dates) * frac)])


def _count(rows, key="status"):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


# ---------------------------------------------------------------------------
# E1: date selection (the user tries several event dates on a null area)
# ---------------------------------------------------------------------------
def e1_date_selection(sites=("midlands", "austin"), offsets=(0, 20, 40, 60, 80), change_types=("other", "clearing")):
    """Under the null, how often does at least one of five candidate dates come back REAL?"""
    out = {}
    for site in sites:
        d, V, dates = load(site)
        units = null_units(V)
        base = base_event(dates)
        for ct in change_types:
            per_date = {o: 0 for o in offsets}
            any_real, any_not_real, n_cells = 0, 0, 0
            time_flag_rate = []
            ratios, loose_fail, rescued, rescued_real = [], 0, 0, 0
            t0 = time.time()
            for u in units:
                statuses = []
                for o in offsets:
                    ev = base + np.timedelta64(o, "D")
                    r = analyse(dates, V, u, ev, change_type=ct, time_pl=(o == 0))
                    if r is None:
                        continue
                    statuses.append(r["status"])
                    per_date[o] += r["status"] == "REAL"
                    ratios.append(r["ratio"])
                    if not r["loose_ok"]:
                        loose_fail += 1
                        if r["pre_fit_ok"]:
                            rescued += 1
                            rescued_real += r["status"] == "REAL"
                    if o == 0 and r["time_flags"]:
                        time_flag_rate.append(any(r["time_flags"]))
                n_cells += 1
                any_real += "REAL" in statuses
                any_not_real += "NOT_REAL" in statuses
            out[f"{site}/{ct}"] = {
                "cells": n_cells, "dates_per_cell": len(offsets),
                "REAL_per_date": per_date, "cells_with_any_REAL": any_real,
                "cells_with_any_NOT_REAL": any_not_real,
                "single_date_REAL_rate": round(sum(per_date.values()) / max(n_cells * len(offsets), 1), 3),
                "any_of_5_REAL_rate": round(any_real / max(n_cells, 1), 3),
                "in_time_placebo_flag_rate": (round(float(np.mean(time_flag_rate)), 2) if time_flag_rate else None),
                "ratio_max": round(float(np.max(ratios)), 2), "ratio_ge_4": int(np.sum(np.asarray(ratios) >= 4)),
                "loose_gate_failed": loose_fail, "rescued_by_4x_rule": rescued, "rescued_and_REAL": rescued_real,
                "seconds": round(time.time() - t0, 1)}
            print("E1", f"{site}/{ct}", json.dumps(out[f"{site}/{ct}"]), flush=True)
    return out


# ---------------------------------------------------------------------------
# E2: leakage (geometry + despike bias on donors)
# ---------------------------------------------------------------------------
def _square_area(ha: float, lon=-1.286, lat=52.908) -> Area:
    from src.app.geometry import reproject, utm_epsg
    epsg = utm_epsg(lon, lat)
    from shapely.geometry import Point
    c = reproject(Point(lon, lat), 4326, epsg)
    side = math.sqrt(ha * 10_000)
    utm = box(c.x - side / 2, c.y - side / 2, c.x + side / 2, c.y + side / 2)
    return Area(wgs84=reproject(utm, epsg, 4326), utm=utm, epsg=epsg, area_ha=ha, lon=lon, lat=lat)


def _strip_area(ha: float, aspect: float, lon=-1.286, lat=52.908) -> Area:
    from src.app.geometry import reproject, utm_epsg
    from shapely.geometry import Point
    epsg = utm_epsg(lon, lat)
    c = reproject(Point(lon, lat), 4326, epsg)
    w = math.sqrt(ha * 10_000 / aspect); h = w * aspect
    utm = box(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)
    return Area(wgs84=reproject(utm, epsg, 4326), utm=utm, epsg=epsg, area_ha=ha, lon=lon, lat=lat)


def e2_leakage():
    out = {}
    # (a) the "1 km exclusion" is measured centroid-to-polygon, not edge-to-edge
    for ha in (1, 10, 50, 100, 250, 500):
        a = _square_area(ha)
        g = donor_grid(a)
        edge = np.asarray([c.distance(a.utm) for c in g.cells])          # edge-to-edge gap, metres
        out[f"square_{ha}ha"] = {"cell_m": round(g.cell_m), "n_cells": len(g.cells),
                                 "min_centroid_gap_m": round(float(g.distances_m.min())),
                                 "min_edge_gap_m": round(float(edge.min())),
                                 "cells_edge_gap_lt_500m": int((edge < 500).sum()),
                                 "cells_edge_gap_lt_250m": int((edge < 250).sum())}
    a = _strip_area(50, aspect=25)      # 141 m x 3540 m strip (a road / pipeline / river bank)
    g = donor_grid(a)
    edge = np.asarray([c.distance(a.utm) for c in g.cells])
    out["strip_50ha_1x25"] = {"cell_m": round(g.cell_m), "min_edge_gap_m": round(float(edge.min())),
                              "cells_edge_gap_lt_500m": int((edge < 500).sum())}
    # (b) wide_candidates: random placement, cells can overlap each other (duplicate donors)
    for inner, outer, n in ((20_000, 150_000, 600), (1_000, 12_000, 600)):
        a = _square_area(50)
        wc = wide_candidates(a, inner, outer, n=n)
        cells = wc.cells
        overl = 0
        for i in range(len(cells)):
            bi = cells[i].bounds
            for j in range(i + 1, len(cells)):
                bj = cells[j].bounds
                if bi[0] < bj[2] and bj[0] < bi[2] and bi[1] < bj[3] and bj[1] < bi[3]:
                    overl += 1
        touches_area = sum(c.intersects(a.utm) for c in cells)
        out[f"wide_{inner // 1000}-{outer // 1000}km_n{n}"] = {"overlapping_pairs": overl, "cells_touching_area": touches_area}
    # (c) despike after a real, permanent drop: how many of the first post-drop observations are deleted?
    rng = np.random.default_rng(0)
    res = {}
    for drop in (0.2, 0.3, 0.5):
        deleted_first8 = []
        for s in range(200):
            rng = np.random.default_rng(s)
            days = np.arange(0, 400, 5)
            keep = rng.random(len(days)) < 0.5
            days = days[keep]
            ndvi = 0.7 + rng.normal(0, 0.03, len(days))
            ndvi[days >= 200] -= drop
            sus = s2mod.despike(days.astype("datetime64[D]"), ndvi)
            post = np.where(days >= 200)[0][:8]
            deleted_first8.append(int(sus[post].sum()))
        res[f"step_-{drop}"] = {"mean_deleted_of_first_8_post_obs": round(float(np.mean(deleted_first8)), 2),
                                "runs_with_any_deleted": int(np.sum(np.asarray(deleted_first8) > 0)), "of": 200}
    out["despike_after_permanent_drop"] = res
    for k, v in out.items():
        print("E2", k, json.dumps(v), flush=True)
    return out


# ---------------------------------------------------------------------------
# E3: common regional shock and a local (spatially correlated) shock
# ---------------------------------------------------------------------------
def e3_regional_shock(sites=("midlands", "austin"), shock=-0.10, local_km=3.0):
    out = {}
    for site in sites:
        d, V, dates = load(site)
        dist = np.asarray(d.cell_distance_m)
        units = null_units(V)
        ev = base_event(dates)
        post = dates >= ev
        for kind in ("regional", "local", "graded"):
            rows = []
            for u in units:
                M = V.copy()
                if kind == "regional":
                    M[post, :] += shock
                elif kind == "local":
                    cols = [0] + [j for j in range(1, V.shape[1]) if dist[j - 1] <= local_km * 1000]
                    M[np.ix_(post, cols)] += shock
                    M[post, u] += shock if u not in cols else 0.0
                else:
                    # exponential decay from the treated cell: neighbours share part of the shock
                    dtreat = np.asarray([0.0] + [abs(dist[j - 1] - dist[u - 1]) for j in range(1, V.shape[1])])
                    w = np.exp(-dtreat / 3000.0)
                    M[post, :] += shock * w[None, :]
                    M[post, u] = V[post, u] + shock
                r = analyse(dates, M, u, ev, change_type="clearing")
                if r:
                    rows.append(r)
            out[f"{site}/{kind}"] = {"n": len(rows), "status": _count(rows),
                                     "median_point": round(float(np.median([r["point"] for r in rows])), 3),
                                     "median_placebo_p": round(float(np.median([r["placebo_p"] for r in rows])), 3),
                                     "median_placebo_eff": round(float(np.median([r["placebo_eff_med"] for r in rows])), 3),
                                     "controls_shifted_fired": int(sum("control cells themselves shifted" in " ".join(r["reasons"]) for r in rows))}
            print("E3", f"{site}/{kind}", json.dumps(out[f"{site}/{kind}"]), flush=True)
    return out


# ---------------------------------------------------------------------------
# E4: seasonal (phenology) misalignment
# ---------------------------------------------------------------------------
def synth_seasonal(seed, n_donors=60, years=4, event_year=3, shift_days=0.0, amp=0.25, noise=0.03,
                   phase_sd=4.0, dropout=0.45, cadence=5, rho=0.5):
    rng = np.random.default_rng(seed)
    days = np.arange(0, int(365.25 * years), cadence)
    keep = rng.random(len(days)) < (1 - dropout)
    days = days[keep]
    t = days.astype(float)
    dates = (np.datetime64("2019-01-01") + days.astype("timedelta64[D]"))
    phases = rng.normal(0, phase_sd, n_donors + 1)
    phases[0] = shift_days
    V = np.empty((len(t), n_donors + 1))
    for j in range(n_donors + 1):
        e = np.empty(len(t)); e[0] = rng.normal(0, noise)
        for i in range(1, len(t)):
            e[i] = rho * e[i - 1] + rng.normal(0, noise * math.sqrt(1 - rho ** 2))
        V[:, j] = 0.45 + amp * np.sin(2 * math.pi * (t - phases[j] - 100) / 365.25) + e
    event = np.datetime64("2019-01-01") + np.timedelta64(int(365.25 * event_year), "D")
    return dates, V, event


def e4_seasonal(shifts=(0, 10, 20, 30), seeds=range(N_UNITS)):
    out = {}
    for shift in shifts:
        for ct in ("other", "clearing"):
            rows = []
            for s in seeds:
                dates, V, ev = synth_seasonal(s, shift_days=shift)
                r = analyse(dates, V, 0, ev, change_type=ct)
                if r:
                    rows.append(r)
            out[f"shift{shift}d/{ct}"] = {"n": len(rows), "status": _count(rows),
                                          "median_point": round(float(np.median([r["point"] for r in rows])), 3),
                                          "median_pre_rmse": round(float(np.median([r["pre_rmse"] for r in rows])), 3),
                                          "median_placebo_med": round(float(np.median([r["placebo_med"] for r in rows])), 3),
                                          "pre_fit_ok": int(sum(r["pre_fit_ok"] for r in rows))}
            print("E4", f"shift{shift}d/{ct}", json.dumps(out[f"shift{shift}d/{ct}"]), flush=True)
    # real data: the cell's own series re-sampled 20 days earlier (interpolated from its own observations)
    d, V, dates = load("austin")
    units = null_units(V)
    ev = base_event(dates)
    tnum = dates.astype(int).astype(float)
    for shift in (0, 20):
        rows = []
        for u in units:
            M = V.copy()
            col = V[:, u]; ok = np.isfinite(col)
            M[:, u] = np.interp(tnum - shift, tnum[ok], col[ok])
            r = analyse(dates, M, u, ev, change_type="other")
            if r:
                rows.append(r)
        out[f"austin_resampled_shift{shift}d/other"] = {"n": len(rows), "status": _count(rows),
                                                        "pre_fit_ok": int(sum(r["pre_fit_ok"] for r in rows))}
        print("E4", f"austin_resampled_shift{shift}d/other", json.dumps(out[f"austin_resampled_shift{shift}d/other"]), flush=True)
    return out


# ---------------------------------------------------------------------------
# E5: pre-trend (drift that starts before the event)
# ---------------------------------------------------------------------------
def e5_pretrend(sites=("midlands", "austin"), slopes_per_year=(-0.05, -0.10, -0.20), lead_days=365):
    out = {}
    for site in sites:
        d, V, dates = load(site)
        units = null_units(V)
        ev = base_event(dates)
        tnum = (dates - ev).astype(int).astype(float)      # days relative to the event
        for slope in slopes_per_year:
            rows = []
            for u in units:
                M = V.copy()
                drift = np.clip(tnum + lead_days, 0, None) * slope / 365.0
                M[:, u] = V[:, u] + drift
                r = analyse(dates, M, u, ev, change_type="clearing", time_pl=True)
                if r:
                    rows.append(r)
            out[f"{site}/slope{slope}/yr"] = {
                "n": len(rows), "status": _count(rows),
                "pre_fit_gate_blocked": int(sum(not r["pre_fit_ok"] for r in rows)),
                "loose_gate_failed": int(sum(not r["loose_ok"] for r in rows)),
                "rescued_by_4x": int(sum((not r["loose_ok"]) and r["pre_fit_ok"] for r in rows)),
                "time_placebo_flagged": int(sum(any(r["time_flags"]) for r in rows)),
                "REAL_with_time_flag": int(sum(r["status"] == "REAL" and any(r["time_flags"]) for r in rows)),
                "median_point": round(float(np.median([r["point"] for r in rows])), 3),
                "median_ratio": round(float(np.median([r["ratio"] for r in rows])), 2)}
            print("E5", f"{site}/slope{slope}/yr", json.dumps(out[f"{site}/slope{slope}/yr"]), flush=True)
    return out


# ---------------------------------------------------------------------------
# E6: the 4x pre-fit relaxation on null cells
# ---------------------------------------------------------------------------
def e6_relaxation(sites=("midlands", "austin", "richmond"), n_units=20, fracs=(0.55, 0.65, 0.75)):
    """Distribution of |point| / pre_rmse on null cells, and how the 4x rule interacts with the loose gate."""
    out = {}
    for site in sites:
        d, V, dates = load(site)
        units = null_units(V, n=n_units)
        ratios, loose_fail, rescued, rescued_real, any_real = [], 0, 0, 0, 0
        for frac in fracs:
            ev = base_event(dates, frac)
            for u in units:
                r = analyse(dates, V, u, ev, change_type="other")
                if r is None:
                    continue
                ratios.append(r["ratio"])
                any_real += r["status"] == "REAL"
                if not r["loose_ok"]:
                    loose_fail += 1
                    if r["pre_fit_ok"]:
                        rescued += 1; rescued_real += r["status"] == "REAL"
        ratios = np.asarray(ratios)
        out[site] = {"fits": int(len(ratios)), "ratio_p50": round(float(np.median(ratios)), 2),
                     "ratio_p95": round(float(np.percentile(ratios, 95)), 2), "ratio_max": round(float(ratios.max()), 2),
                     "ratio_ge_4": int((ratios >= 4).sum()), "ratio_ge_2": int((ratios >= 2).sum()),
                     "loose_gate_failed": loose_fail, "rescued_by_4x": rescued, "rescued_and_REAL": rescued_real,
                     "REAL_total": any_real}
        print("E6", site, json.dumps(out[site]), flush=True)
    # what would it take? a null cell whose post-period noise is larger than its pre-period noise
    rng = np.random.default_rng(1)
    hits = 0; N = 2000; q = 12; Tpre = 36
    for _ in range(N):
        pre = rng.normal(0, 0.02, Tpre); post = rng.normal(0, 0.02, q)
        hits += abs(post.mean()) >= 4 * np.sqrt(np.mean(pre ** 2))
    out["iid_gaussian_q12"] = {"P(ratio>=4)": hits / N}
    print("E6", "iid_gaussian_q12", json.dumps(out["iid_gaussian_q12"]), flush=True)
    return out


# ---------------------------------------------------------------------------
# E7: the one-sided NDVI despike versus floods (NDWI)
# ---------------------------------------------------------------------------
def e7_despike_flood():
    out = {}
    # (a) real data: what the Sindh cache threw away right after the flood
    d = AreaData.load(CACHES["sindh"])
    ev = "2022-08-25"
    haze = [r for r in d.receipts if r["reason"] == "haze"]
    after = [r for r in haze if ev <= r["date"] <= "2022-10-25"]
    out["sindh_haze_receipts_after_event"] = [(r["date"], r["detail"][:22]) for r in after]
    dts = d.s2.dates
    sel = (dts >= "2022-08-01") & (dts <= "2022-10-25")
    out["sindh_kept_treated_NDVI_NDWI"] = [(str(x), round(float(a), 2), round(float(b), 2)) for x, a, b in
                                            zip(dts[sel], d.s2.values["NDVI"][sel, 0], d.s2.values["NDWI"][sel, 0])]
    # (b) synthetic: share of flooded observations deleted, by flood duration
    res = {}
    for dur in (10, 20, 30, 45, 60, 90):
        deleted, total = 0, 0
        for s in range(200):
            rng = np.random.default_rng(s)
            days = np.arange(0, 400, 5)
            days = days[rng.random(len(days)) < 0.5]
            ndvi = 0.6 + rng.normal(0, 0.03, len(days))
            fl = (days >= 200) & (days < 200 + dur)
            ndvi[fl] = -0.1 + rng.normal(0, 0.03, fl.sum())    # standing water
            sus = s2mod.despike(days.astype("datetime64[D]"), ndvi)
            deleted += int(sus[fl].sum()); total += int(fl.sum())
        res[f"flood_{dur}d"] = {"flooded_obs": total, "deleted_as_haze": deleted, "share": round(deleted / max(total, 1), 2)}
    out["synthetic_despike_on_floods"] = res
    # (c) end to end on synthetic NDWI: 25-day flood, post window of 1 month, with and without the despike
    rows = {"with_despike": [], "without_despike": []}
    for s in range(N_UNITS):
        rng = np.random.default_rng(100 + s)
        days = np.arange(0, 365 * 3 + 40, 5)
        days = days[rng.random(len(days)) < 0.6]
        n = 60
        base_ndwi = -0.45 + 0.05 * np.sin(2 * math.pi * days / 365.25)
        NDWI = base_ndwi[:, None] + rng.normal(0, 0.03, (len(days), n + 1))
        NDVI = 0.55 - 0.15 * np.sin(2 * math.pi * days / 365.25)
        NDVI = NDVI[:, None] + rng.normal(0, 0.03, (len(days), n + 1))
        ev_day = 365 * 3
        fl = (days >= ev_day) & (days < ev_day + 25)
        NDWI[fl, 0] = 0.3 + rng.normal(0, 0.03, fl.sum())
        NDVI[fl, 0] = -0.1 + rng.normal(0, 0.03, fl.sum())
        dates = np.datetime64("2019-01-01") + days.astype("timedelta64[D]")
        ev = np.datetime64("2019-01-01") + np.timedelta64(ev_day, "D")
        end = ev + np.timedelta64(31, "D")
        win = dates <= end
        for mode in rows:
            keep = win.copy()
            if mode == "with_despike":
                sus = s2mod.despike(dates, NDVI[:, 0])
                keep &= ~sus
            r = analyse(dates[keep], NDWI[keep], 0, ev, signal="NDWI", change_type="flood")
            rows[mode].append(r["status"] if r else "no-fit")
    out["synthetic_flood_25d_post1mo"] = {m: _count([{"status": s} for s in v]) for m, v in rows.items()}
    for k, v in out.items():
        print("E7", k, json.dumps(v), flush=True)
    return out


# ---------------------------------------------------------------------------
# E8: gates and NaN paths (mostly encoded as tests; here a quick probe)
# ---------------------------------------------------------------------------
def e8_gates():
    out = {}
    good = dict(signal="NDVI", sensor="S2", expected_sign=-1, point=-0.30, lo=-0.35, hi=-0.25, p_zero=0.0,
                pre_rmse=0.02, placebo_pre_rmse_median=0.02, n_pre=40, n_post=12, n_donors=60,
                placebo_p=0.02, placebo_p_effect=0.02, placebo_n=60)
    out["baseline"] = decide(SignalResult(**good), "clearing", "").status
    for k, v in (("n_donors", 19), ("n_post", 2), ("n_pre", 19)):
        out[f"{k}={v}"] = decide(SignalResult(**{**good, k: v}), "clearing", "").status
    out["point=nan"] = decide(SignalResult(**{**good, "point": float("nan")}), "clearing", "").status
    out["lo=hi=nan"] = decide(SignalResult(**{**good, "lo": float("nan"), "hi": float("nan")}), "clearing", "").status
    out["time_placebo_flagged_all"] = decide(SignalResult(**{**good, "time_placebo_flags": [True, True, True]}), "clearing", "").status
    # NaN into the estimator: silently handled?
    rng = np.random.default_rng(0)
    T = 60; D = rng.normal(0, 0.05, (30, T)) + 0.5; y = D[:5].mean(axis=0) + rng.normal(0, 0.01, T)
    pre = np.arange(T) < 45
    D2 = D.copy(); D2[3, 10] = np.nan
    f = fit_ascm(y, D2, pre)
    out["fit_with_one_nan_donor"] = {"effect_all_nan": bool(np.all(np.isnan(f.effect))),
                                     "weights_equal": bool(np.allclose(f.weights, 1 / 30)), "pre_rmse": f.pre_rmse}
    for k, v in out.items():
        print("E8", k, json.dumps(v), flush=True)
    return out


# ---------------------------------------------------------------------------
# E9: every code path from numbers to a verdict, probed for REAL with < 20
#     donors or < 3 post bins (verdict.decide, verdict.combine, run.py's lead
#     switch, evidence.assess, prep/donors NaN paths)
# ---------------------------------------------------------------------------
def e9_real_paths():
    from src.app.evidence import assess, status_of
    from src.app.verdict import combine
    out = {}
    strong = dict(signal="NDVI", sensor="S2", expected_sign=-1, point=-0.30, lo=-0.35, hi=-0.25, p_zero=0.0,
                  pre_rmse=0.02, placebo_pre_rmse_median=0.02, n_pre=40, n_post=12, n_donors=60,
                  placebo_p=0.02, placebo_p_effect=0.02, placebo_n=60)
    radar_ok = dict(strong, signal="VH", sensor="S1", point=-2.0, lo=-2.5, hi=-1.5, pre_rmse=0.3,
                    placebo_pre_rmse_median=0.3)
    # (a) decide: sweep the two gates one unit either side of the threshold
    for nd in (19, 20):
        for npost in (2, 3):
            r = SignalResult(**{**strong, "n_donors": nd, "n_post": npost})
            out[f"decide/donors={nd}/post={npost}"] = decide(r, "clearing", "").status
    # (b) combine: optical lead with 2 post bins; radar lead REAL while optical has 2 post bins
    opt2 = SignalResult(**{**strong, "n_post": 2})
    out["combine/optical_lead_2post"] = combine(opt2, opt2, "clearing", "").status
    out["combine/radar_lead_REAL_optical_2post"] = combine(SignalResult(**radar_ok), opt2, "clearing", "").status
    out["combine/radar_lead_REAL_optical_19donors"] = combine(
        SignalResult(**radar_ok), SignalResult(**{**strong, "n_donors": 19}), "clearing", "").status
    # (c) evidence.status_of: is a signal with 19 donors or a bad pre-fit still 'supportive'?
    out["evidence/19_donors_supportive"] = status_of(SignalResult(**{**strong, "n_donors": 19}))
    out["evidence/pre_fit_bad_supportive"] = status_of(SignalResult(**{**strong, "pre_rmse": 0.2}))
    out["evidence/controls_shifted_supportive"] = status_of(SignalResult(**{**strong, "placebo_effect_median": -0.3}))
    out["evidence/2_post_bins"] = status_of(SignalResult(**{**strong, "n_post": 2}))
    ev = assess({"NDVI": SignalResult(**{**strong, "n_donors": 19}), "VH": SignalResult(**{**radar_ok, "n_donors": 19})}, "clearing")
    out["evidence/assess_19_donors_both"] = {"agreement": ev.agreement, "sentence": ev.sentence[:60]}
    # (d) run.py lead switch: optical with < 3 post bins hands the lead to radar; the optical
    #     'too large to dismiss' guard only fires on a radar NOT_REAL, never on a radar REAL
    out["run/lead_switch_rule"] = "lead = radar if optical.n_post < 3 and radar.n_post >= 3 (run.py:182-186)"
    # (e) NaN inside the pipeline: a donor column that binned_groups could not interpolate
    rng = np.random.default_rng(0)
    T = 60; D = rng.normal(0, 0.05, (30, T)) + 0.5; y = D[:5].mean(axis=0) + rng.normal(0, 0.01, T)
    pre = np.arange(T) < 45
    D2 = D.copy(); D2[3, 10] = np.nan
    f = fit_ascm(y, D2, pre)
    point = float(np.mean(f.effect[~pre]))
    r = SignalResult(**{**strong, "point": point, "lo": point, "hi": point, "pre_rmse": f.pre_rmse})
    out["nan_donor/point"] = point
    out["nan_donor/decide"] = decide(r, "clearing", "").status
    # (f) donors: fewer than 20 columns pass coverage -> n_donors as reported by run._analyse
    T = 50
    dates = np.datetime64("2021-01-01") + (np.arange(T) * 7).astype("timedelta64[D]")
    V = 0.5 + rng.normal(0, 0.03, (T, 1 + 25))
    V[:, 1:19] = V[:, 1:19]; V[::3, 19:] = np.nan; V[1::3, 19:] = np.nan     # 7 donors at 33% coverage
    ev_np = dates[35]
    b = binned(dates, V, ev_np, bin_days=10)
    sel = select_donors(b.matrix, b.pre, b.donor_cov, None, k=80)
    out["donors/columns_after_coverage"] = int(b.matrix.shape[1] - 1)
    out["donors/n_kept"] = int(len(sel.index))
    for k, v in out.items():
        print("E9", k, json.dumps(v), flush=True)
    return out


# ---------------------------------------------------------------------------
# E10: pure synthetic common shock (deterministic; mirrored in tests/test_redteam.py)
# ---------------------------------------------------------------------------
def synth_panel(seed=0, n_donors=60, T=110, n_pre=75, noise=0.03, shock=0.0, treated_extra=0.0):
    """Every unit shares a seasonal curve and drops by `shock` after the event;
    the treated unit drops by `shock + treated_extra`."""
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    season = 0.2 * np.sin(2 * math.pi * t / 36.5)
    amp = rng.uniform(0.8, 1.2, n_donors + 1); off = rng.normal(0, 0.05, n_donors + 1)
    V = 0.5 + season[:, None] * amp[None, :] + off[None, :] + rng.normal(0, noise, (T, n_donors + 1))
    post = t >= n_pre
    V[post, :] += shock
    V[post, 0] += treated_extra
    dates = np.datetime64("2020-01-01") + (t * 10).astype("timedelta64[D]")
    return dates, V, dates[n_pre]


def e10_synthetic_shock(seeds=range(N_UNITS), shock=-0.10):
    out = {}
    for label, extra in (("common_only", 0.0), ("common_plus_treated-0.10", -0.10)):
        rows = []
        for s in seeds:
            dates, V, ev = synth_panel(seed=s, shock=shock, treated_extra=extra)
            r = analyse(dates, V, 0, ev, change_type="clearing")
            if r:
                rows.append(r)
        out[label] = {"n": len(rows), "status": _count(rows),
                      "median_point": round(float(np.median([r["point"] for r in rows])), 3),
                      "median_placebo_eff": round(float(np.median([r["placebo_eff_med"] for r in rows])), 3),
                      "controls_shifted_fired": int(sum("control cells themselves shifted" in " ".join(r["reasons"]) for r in rows))}
        print("E10", label, json.dumps(out[label]), flush=True)
    return out


EXPERIMENTS = {"e1": e1_date_selection, "e2": e2_leakage, "e3": e3_regional_shock, "e4": e4_seasonal,
               "e5": e5_pretrend, "e6": e6_relaxation, "e7": e7_despike_flood, "e8": e8_gates,
               "e9": e9_real_paths, "e10": e10_synthetic_shock}


if __name__ == "__main__":
    names = sys.argv[1:] or list(EXPERIMENTS)
    results = {}
    for n in names:
        t0 = time.time()
        results[n] = EXPERIMENTS[n]()
        print(f"== {n} done in {time.time() - t0:.0f}s", flush=True)
    import os
    out_path = os.environ.get("REDTEAM_OUT", "")
    if out_path:
        with open(out_path, "w") as f:
            json.dump(results, f, default=str, indent=1)
