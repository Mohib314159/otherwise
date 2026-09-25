"""Counterfactual analysis for weather-normalised ground-monitor NO2.

This module is intentionally more conservative than a dashboard demo.  A
positive ULEZ verdict must survive several *different* failure checks:

* stable treated-monitor composition and ≥80% station coverage on both sides;
* same-type control monitors with no long post-policy outcome imputation;
* augmented synthetic control selected using the pre period only;
* a NO₂-scale conformal interval whose numerical search is not truncated;
* exact-size, fully symmetric in-space placebo cohorts;
* fake-date / anticipation checks inside the pre period;
* leave-one-treated-monitor-out and high-weight-donor sensitivity.

The goal is not to make ULEZ come out significant.  The goal is to make a REAL
result difficult to obtain for the wrong reason.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np
import pandas as pd

from ..estimator import Conformal, conformal_interval, fit_ascm

AIR_MIN_EFFECT = 1.0          # µg/m³; design threshold, not a regulatory limit
AIR_ALPHA = 0.10
AIR_PLACEBO_P_MAX = 0.10
AIR_MIN_DONORS = 12
AIR_MIN_PLACEBOS = 19         # p-value resolution <= 0.05 under +1 correction
AIR_MIN_PRE_WEEKS = 52
AIR_MIN_POST_WEEKS = 8
AIR_DONOR_K = 24
AIR_STATION_COVERAGE = 0.80
AIR_WEEKLY_COHORT_FRACTION = 0.80
AIR_LEAD_WEEKS = 13
AIR_PROTOCOL = "air-ground-no2-v2.3.1"


@dataclass
class AirVerdict:
    status: str
    headline: str
    statement: str
    reasons: list[str]
    lead_signal: str


@dataclass
class _PlaceboResult:
    p_ratio: float | None      # None when no placebo cohort could be formed
    p_effect: float | None
    ratios: np.ndarray
    effects: np.ndarray
    pre_rmses: np.ndarray
    paths: np.ndarray
    cohort_size: int
    exact_size: bool
    possible_groups: int


def _ratio(effect: np.ndarray, pre: np.ndarray) -> float:
    a = np.sqrt(np.mean(effect[pre] ** 2)) + 1e-9
    b = np.sqrt(np.mean(effect[~pre] ** 2))
    return float(b / a)


def _repair_one_week_gap(s: pd.Series) -> tuple[pd.Series, float]:
    """Repair at most one *internal* weekly hole; never seasonal-fill outcomes.

    The first air prototype filled longer donor gaps from the donor's pre-policy
    seasonal pattern.  That can manufacture a smooth post-policy counterfactual.
    v2.2 permits only a one-week interpolation bounded by real observations; a
    donor with any remaining used-week gap is discarded.
    """
    x = s.astype(float).copy()
    missing = np.flatnonzero(x.isna().to_numpy())
    # A limit on consecutive interpolation does not limit the total holes.
    # Refuse multiple holes rather than choosing one based on outcome values.
    if len(missing) != 1:
        return x, 0.0
    i = int(missing[0])
    if i == 0 or i == len(x) - 1:
        return x, 0.0
    if isinstance(x.index, pd.DatetimeIndex):
        week = pd.Timedelta(days=7)
        if x.index[i] - x.index[i - 1] != week or x.index[i + 1] - x.index[i] != week:
            return x, 0.0
    x.iloc[i] = (x.iloc[i - 1] + x.iloc[i + 1]) / 2.0
    return x, 1.0 / len(x)


def _select_donors(y: np.ndarray, D: np.ndarray, pre: np.ndarray,
                   k: int = AIR_DONOR_K) -> tuple[np.ndarray, np.ndarray]:
    """Rank candidate monitors using PRE-policy trajectory, level and trend only."""
    scores = []
    x = np.arange(int(pre.sum()), dtype=float)
    ypre = y[pre]
    ytrend = float(np.polyfit(x, ypre, 1)[0]) if len(x) >= 3 else 0.0
    ysd = float(np.std(ypre))
    for j in range(D.shape[0]):
        dpre = D[j, pre]
        rmse = float(np.sqrt(np.mean((dpre - ypre) ** 2)))
        level = abs(float(np.mean(dpre) - np.mean(ypre)))
        dtrend = float(np.polyfit(x, dpre, 1)[0]) if len(x) >= 3 else 0.0
        trend = abs(dtrend - ytrend) * max(len(x), 1)
        variability = abs(float(np.std(dpre)) - ysd)
        # Trajectory fit dominates.  Trend/variability penalties are modest and
        # use no post-policy values.
        scores.append(rmse + 0.20 * level + 0.15 * trend + 0.10 * variability)
    order = np.argsort(scores)
    take = order[:min(int(k), len(order))]
    return take, np.asarray(scores, dtype=float)[take]


def _cohort_aggregate(tdf: pd.DataFrame, pre_mask: pd.Series) -> tuple[pd.Series, list[str], list[str], int, dict[str, float]]:
    """Fixed-composition, baseline-aligned treated aggregation.

    Stations must have ≥80% weekly coverage in *both* periods.  Baseline
    alignment prevents a high-NO₂ station disappearing for a few weeks from
    mechanically lowering the cohort mean.  A week is used only when ≥80% of
    the fixed eligible cohort is observed.
    """
    eligible, dropped = [], []
    coverage: dict[str, float] = {}
    post_mask = ~pre_mask
    for code in tdf.columns:
        pre_cov = float(tdf.loc[pre_mask, code].notna().mean()) if pre_mask.any() else 0.0
        post_cov = float(tdf.loc[post_mask, code].notna().mean()) if post_mask.any() else 0.0
        coverage[code] = min(pre_cov, post_cov)
        if pre_cov >= AIR_STATION_COVERAGE and post_cov >= AIR_STATION_COVERAGE:
            eligible.append(code)
        else:
            dropped.append(code)
    if not eligible:
        return pd.Series(np.nan, index=tdf.index), [], dropped, 0, coverage

    x = tdf[eligible].copy()
    pre_means = x.loc[pre_mask].mean(axis=0, skipna=True)
    anchor = float(pre_means.mean())
    aligned = x.subtract(pre_means, axis=1).add(anchor)
    need = max(1, int(math.ceil(len(eligible) * AIR_WEEKLY_COHORT_FRACTION)))
    agg = aligned.mean(axis=1, skipna=True)
    agg[aligned.notna().sum(axis=1) < need] = np.nan
    return agg, eligible, dropped, need, coverage


def _sample_exact_groups(m: int, n: int, target_n: int, seed_key: str) -> list[tuple[int, ...]]:
    if n <= 0 or m < n:
        return []
    possible = math.comb(m, n)
    target_n = min(int(target_n), possible)
    digest = hashlib.sha256(seed_key.encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
    if possible <= 5000:
        import itertools
        groups = list(itertools.combinations(range(m), n))
        if len(groups) <= target_n:
            return groups
        pick = rng.choice(len(groups), size=target_n, replace=False)
        return [groups[int(i)] for i in pick]
    groups: list[tuple[int, ...]] = []
    seen = set()
    attempts = 0
    while len(groups) < target_n and attempts < target_n * 100:
        g = tuple(sorted(rng.choice(m, size=n, replace=False).tolist()))
        attempts += 1
        if g not in seen:
            seen.add(g); groups.append(g)
    return groups


def _symmetric_placebos(y: np.ndarray, candidates: np.ndarray, pre: np.ndarray,
                        treated_effect: float, treated_n: int, seed_key: str,
                        max_units: int = 40) -> _PlaceboResult:
    """Exact cohort-size-matched, fully re-selected in-space placebos."""
    m = candidates.shape[0]
    group_n = int(treated_n)
    possible = math.comb(m, group_n) if 0 < group_n <= m else 0
    # A fake treated cohort must be exactly the same size as London *and* leave
    # enough monitors behind to satisfy the same donor minimum as the real run.
    if group_n <= 0 or m - group_n < AIR_MIN_DONORS:
        # No placebo cohort means no test, not p = 1. The (0+1)/(0+1) sentinel used
        # to reach the CLI and reports as "p=1.000"; the verdict already refuses
        # REAL below AIR_MIN_PLACEBOS, so None changes no verdict.
        return _PlaceboResult(None, None, np.array([]), np.array([]), np.array([]),
                              np.empty((0, len(y))), max(group_n, 0), False, possible)
    groups = _sample_exact_groups(m, group_n, max_units, seed_key)
    ratios, effects, pres, paths = [], [], [], []
    for group in groups:
        mask = np.ones(m, dtype=bool); mask[list(group)] = False
        pool = candidates[mask]
        yy = np.mean(candidates[list(group)], axis=0)
        sel, _ = _select_donors(yy, pool, pre, k=AIR_DONOR_K)
        DD = pool[sel]
        if DD.shape[0] < AIR_MIN_DONORS:
            continue
        f = fit_ascm(yy, DD, pre, lam=None)  # lambda re-selected for every placebo
        ratios.append(_ratio(f.effect, pre))
        effects.append(float(np.mean(f.effect[~pre])))
        pres.append(f.pre_rmse)
        paths.append(f.effect)
    if not ratios:
        return _PlaceboResult(None, None, np.array([]), np.array([]), np.array([]),
                              np.empty((0, len(y))), group_n, True, possible)
    ratios = np.asarray(ratios); effects = np.asarray(effects); pres = np.asarray(pres)
    real_fit_sel, _ = _select_donors(y, candidates, pre, k=AIR_DONOR_K)
    real_fit = fit_ascm(y, candidates[real_fit_sel], pre, lam=None)
    real_ratio = _ratio(real_fit.effect, pre)
    p_ratio = (np.sum(ratios >= real_ratio) + 1) / (len(ratios) + 1)
    sign = -1.0 if treated_effect < 0 else 1.0
    p_effect = (np.sum(sign * effects >= sign * treated_effect) + 1) / (len(effects) + 1)
    return _PlaceboResult(float(p_ratio), float(p_effect), ratios, effects, pres,
                          np.vstack(paths), group_n, True, possible)


def _air_conformal(y: np.ndarray, D: np.ndarray, pre: np.ndarray, lam: float,
                   point: float, scale: float, n_grid: int = 61) -> Conformal:
    # NO₂ effects can comfortably exceed the legacy ±10 land/radar search cap.
    # Search at least ±30 µg/m³, span zero, and expose boundary truncation.
    max_half = max(30.0, abs(float(point)) + 10.0 * max(float(scale), 0.25))
    return conformal_interval(
        y, D, pre, lam, point, max(float(scale), 0.25), alpha=AIR_ALPHA,
        n_grid=n_grid, max_half=max_half, ensure_zero=True, max_widen=6,
    )


def _time_placebos(y: np.ndarray, candidates: np.ndarray, pre: np.ndarray,
                    dates: pd.DatetimeIndex, n: int = 3) -> list[dict]:
    idx = np.where(pre)[0]
    if len(idx) < 78:
        return []
    yy_all = y[idx]
    DD_all = candidates[:, idx]
    out = []
    for k in range(1, n + 1):
        cut = int(len(idx) * k / (n + 1))
        if cut < 26 or len(idx) - cut < 13:
            continue
        fake_pre = np.zeros(len(idx), dtype=bool); fake_pre[:cut] = True
        sel, _ = _select_donors(yy_all, DD_all, fake_pre, k=AIR_DONOR_K)
        DD = DD_all[sel]
        if DD.shape[0] < AIR_MIN_DONORS:
            continue
        f = fit_ascm(yy_all, DD, fake_pre, lam=None)
        point = float(np.mean(f.effect[~fake_pre]))
        ci = _air_conformal(yy_all, DD, fake_pre, f.lam, point, f.pre_rmse, n_grid=31)
        flagged = bool((not ci.boundary_hit) and (not ci.accepted_empty) and
                       ci.hi < 0 and point <= -AIR_MIN_EFFECT)
        out.append({"date": str(dates[idx[cut]].date()), "effect": round(point, 3),
                    "lo": round(ci.lo, 3), "hi": round(ci.hi, 3),
                    "boundary_hit": bool(ci.boundary_hit), "flagged": flagged})
    return out


def _lead_diagnostic(y: np.ndarray, candidates: np.ndarray, pre: np.ndarray,
                     dates: pd.DatetimeIndex, lead_weeks: int = AIR_LEAD_WEEKS) -> dict:
    """Test whether London was already diverging before the implementation date."""
    idx = np.where(pre)[0]
    if len(idx) < AIR_MIN_PRE_WEEKS or len(idx) <= lead_weeks + 26:
        return {"applicable": False, "flagged": False}
    lead_idx = idx[-lead_weeks:]
    train = pre.copy(); train[lead_idx] = False
    sel, _ = _select_donors(y, candidates, train, k=AIR_DONOR_K)
    DD = candidates[sel]
    if DD.shape[0] < AIR_MIN_DONORS:
        return {"applicable": False, "flagged": False}
    f = fit_ascm(y, DD, train, lam=None)
    lead_effect = float(np.mean(f.effect[lead_idx]))
    threshold = max(AIR_MIN_EFFECT, 2.0 * max(f.pre_rmse, 0.25))
    flagged = bool(lead_effect <= -threshold)
    return {
        "applicable": True,
        "weeks": int(lead_weeks),
        "start": str(dates[lead_idx[0]].date()),
        "end": str(dates[lead_idx[-1]].date()),
        "effect": lead_effect,
        "threshold": -threshold,
        "flagged": flagged,
    }


def _fit_effect(y: np.ndarray, candidates: np.ndarray, pre: np.ndarray) -> tuple[float, object, np.ndarray]:
    sel, _ = _select_donors(y, candidates, pre, k=AIR_DONOR_K)
    DD = candidates[sel]
    if DD.shape[0] < AIR_MIN_DONORS:
        return np.nan, None, sel
    f = fit_ascm(y, DD, pre, lam=None)
    return float(np.mean(f.effect[~pre])), f, sel


def _treated_jackknife(aligned_tdf: pd.DataFrame, eligible_codes: list[str], dates: pd.DatetimeIndex,
                       candidates: np.ndarray, pre: np.ndarray, point: float) -> dict:
    if len(eligible_codes) < 2:
        return {"applicable": False, "robust": False, "effects": {},
                "reason": "fewer than two eligible treated monitors"}
    out: dict[str, float] = {}
    for leave in eligible_codes:
        keep = [c for c in eligible_codes if c != leave]
        sub = aligned_tdf.loc[dates, keep]
        need = max(1, int(math.ceil(len(keep) * AIR_WEEKLY_COHORT_FRACTION)))
        yy = sub.mean(axis=1, skipna=True)
        yy[sub.notna().sum(axis=1) < need] = np.nan
        if yy.isna().any():
            continue
        eff, _, _ = _fit_effect(yy.to_numpy(float), candidates, pre)
        if np.isfinite(eff):
            out[leave] = float(eff)
    if len(out) != len(eligible_codes):
        return {"applicable": True, "robust": False, "effects": out,
                "reason": "at least one leave-one-monitor-out refit was not estimable"}
    vals = np.asarray(list(out.values()), dtype=float)
    if point < 0:
        threshold = -max(0.5, 0.25 * abs(point))
        robust = bool(np.all(vals <= threshold))
    else:
        threshold = max(0.5, 0.25 * abs(point))
        robust = bool(np.all(vals >= threshold))
    return {
        "applicable": True, "robust": robust, "effects": out,
        "least_supportive_effect": float(vals.max() if point < 0 else vals.min()),
        "max_abs_shift": float(np.max(np.abs(vals - point))),
        "threshold": float(threshold),
    }


def _donor_sensitivity(y: np.ndarray, candidates: np.ndarray, pre: np.ndarray,
                       all_codes: list[str], selected_idx: np.ndarray,
                       weights: np.ndarray, point: float) -> dict:
    if len(selected_idx) == 0:
        return {"applicable": False, "robust": False, "effects": {}}
    # Only donors that materially contribute to the convex component are tested;
    # at most three keeps the diagnostic cheap enough for an interactive run.
    order = np.argsort(weights)[::-1]
    influential = [int(selected_idx[int(i)]) for i in order[:3] if weights[int(i)] >= 0.05]
    out: dict[str, float] = {}
    for global_idx in influential:
        keep = np.ones(candidates.shape[0], dtype=bool); keep[global_idx] = False
        if keep.sum() < AIR_MIN_DONORS:
            continue
        eff, _, _ = _fit_effect(y, candidates[keep], pre)
        if np.isfinite(eff):
            out[all_codes[global_idx]] = float(eff)
    if not influential:
        return {"applicable": False, "robust": True, "effects": {}}
    if len(out) != len(influential):
        return {"applicable": True, "robust": False, "effects": out,
                "reason": "an influential-donor removal was not estimable"}
    vals = np.asarray(list(out.values()), dtype=float)
    if point < 0:
        threshold = -max(0.5, 0.25 * abs(point))
        robust = bool(np.all(vals <= threshold))
    else:
        threshold = max(0.5, 0.25 * abs(point))
        robust = bool(np.all(vals >= threshold))
    return {
        "applicable": True, "robust": robust, "effects": out,
        "least_supportive_effect": float(vals.max() if point < 0 else vals.min()),
        "max_abs_shift": float(np.max(np.abs(vals - point))),
        "threshold": float(threshold),
    }


def _decide(signal: str, result: dict, post_label: str) -> AirVerdict:
    point, lo, hi = result["point"], result["lo"], result["hi"]
    reasons: list[str] = []
    core = (f"Weather-normalised NO₂ was {abs(point):.1f} µg/m³ {'lower' if point < 0 else 'higher'} than the "
            f"matched no-policy trajectory {post_label} (90% interval {lo:+.1f} to {hi:+.1f} µg/m³; "
            f"{result['relative_pct']:+.1f}%).")
    if result["n_donors"] < AIR_MIN_DONORS:
        reasons.append(f"only {result['n_donors']} usable same-type control monitors (need {AIR_MIN_DONORS})")
    if result["n_pre"] < AIR_MIN_PRE_WEEKS:
        reasons.append(f"only {result['n_pre']} pre-event weekly observations (need {AIR_MIN_PRE_WEEKS})")
    if result["n_post"] < AIR_MIN_POST_WEEKS:
        reasons.append(f"only {result['n_post']} post-event weekly observations (need {AIR_MIN_POST_WEEKS})")
    if result.get("treated_station_count", 0) < 2:
        reasons.append("fewer than two treated monitors survived the fixed-cohort coverage rules")
    fit_gate = max(1.5 * result["placebo_pre_rmse_median"], 5.0)
    if result["pre_rmse"] > fit_gate and abs(point) < 3.0 * result["pre_rmse"]:
        reasons.append("the no-policy trajectory does not reproduce pre-policy NO₂ closely enough")
    if result.get("time_placebo_flags") and any(result["time_placebo_flags"]):
        reasons.append("a fake pre-policy start date also produced a meaningful NO₂ drop")
    if result.get("pretrend", {}).get("flagged"):
        reasons.append("London was already diverging downward during the lead window before implementation")
    if result.get("conformal_boundary_hit") or result.get("conformal_empty"):
        reasons.append("the conformal interval is numerically unresolved at the searched NO₂ scale")
    if not result.get("placebo_exact_cohort", False):
        reasons.append("the control pool cannot support placebo cohorts as large as the treated London cohort")
    if result.get("placebo_n", 0) < AIR_MIN_PLACEBOS:
        reasons.append(f"only {result.get('placebo_n', 0)} valid exact-size placebo cohorts (need {AIR_MIN_PLACEBOS})")
    if result.get("treated_jackknife", {}).get("applicable") and not result["treated_jackknife"].get("robust"):
        reasons.append("the estimated improvement is not robust to leaving out one treated monitor")
    if result.get("donor_sensitivity", {}).get("applicable") and not result["donor_sensitivity"].get("robust"):
        reasons.append("the estimated improvement is not robust to removing an influential control monitor")
    if reasons:
        return AirVerdict("CANT_TELL", "Can't tell", core + " But: " + "; ".join(reasons) + ".", reasons, signal)

    if lo > 0 and point > 0:
        reason = "NO₂ moved in the opposite direction to an air-cleaning effect"
        return AirVerdict("NOT_REAL", "NO₂ did not improve", core + " " + reason + ".", [reason], signal)
    if hi < 0 and point <= -AIR_MIN_EFFECT:
        if (result["placebo_p"] <= AIR_PLACEBO_P_MAX and
                result["placebo_p_effect"] <= AIR_PLACEBO_P_MAX):
            return AirVerdict("REAL", "Air got cleaner beyond controls", core, [], signal)
        reason = ("the effect was not simultaneously rare enough in both the placebo fit-ratio and signed-effect tests "
                  f"(p-ratio={result['placebo_p']:.2f}, p-effect={result['placebo_p_effect']:.2f})")
        return AirVerdict("CANT_TELL", "Can't tell", core + " " + reason.capitalize() + ".", [reason], signal)
    if lo > -AIR_MIN_EFFECT:
        reason = f"the interval rules out an additional NO₂ drop of {AIR_MIN_EFFECT:.1f} µg/m³ or more"
        return AirVerdict("NOT_REAL", "No additional NO₂ drop detected", core + " " + reason.capitalize() + ".",
                          [reason], signal)
    reason = "the interval is too wide to rule a meaningful additional NO₂ drop in or out"
    return AirVerdict("CANT_TELL", "Can't tell", core + " " + reason.capitalize() + ".", [reason], signal)


def analyse_stratum(treated_weekly: dict[str, pd.Series], donor_weekly: dict[str, pd.Series],
                     event_date: str, post_months: int, stratum: str,
                     donor_meta: dict[str, dict], treated_meta: dict[str, dict],
                     analysis_start: str | None = None) -> tuple[dict, dict, dict, AirVerdict] | None:
    """Analyse traffic or background monitors; never pool the two strata."""
    if not treated_weekly or not donor_weekly:
        return None
    event = pd.Timestamp(event_date)
    end = event + pd.DateOffset(months=int(post_months))
    all_series = list(treated_weekly.values()) + list(donor_weekly.values())
    observed_start = min(s.index.min() for s in all_series if not s.empty)
    registered_start = pd.Timestamp(analysis_start) if analysis_start else event - pd.DateOffset(years=3)
    start = max(observed_start, registered_start)
    full_index = pd.date_range(start=start, end=end, freq="W-SUN")
    # W-SUN bins cover Monday through Sunday. A mid-week policy launch
    # creates a mixed-exposure bin, not an outcome gap eligible for repair.
    crossing = (full_index >= event) & (full_index - pd.Timedelta(days=6) < event)
    full_index = full_index[~crossing]
    pre_series = pd.Series(full_index < event, index=full_index)

    raw_tdf = pd.DataFrame({k: s.reindex(full_index) for k, s in treated_weekly.items()}, index=full_index)
    treated, eligible_treated, dropped_treated, need_t, treated_coverage = _cohort_aggregate(raw_tdf, pre_series)
    if not eligible_treated:
        return None
    # Retain the aligned fixed-cohort frame for leave-one-out sensitivity.
    eligible_frame = raw_tdf[eligible_treated].copy()
    pre_means = eligible_frame.loc[pre_series].mean(axis=0, skipna=True)
    anchor = float(pre_means.mean())
    aligned_tdf = eligible_frame.subtract(pre_means, axis=1).add(anchor)

    raw_donor = pd.DataFrame({k: s.reindex(full_index) for k, s in donor_weekly.items()}, index=full_index)
    filled: dict[str, pd.Series] = {}
    donor_coverage: dict[str, float] = {}
    for code in raw_donor:
        s = raw_donor[code]
        pre_cov = float(s[pre_series].notna().mean()) if pre_series.any() else 0.0
        post_cov = float(s[~pre_series].notna().mean()) if (~pre_series).any() else 0.0
        donor_coverage[code] = min(pre_cov, post_cov)
        if pre_cov < AIR_STATION_COVERAGE or post_cov < AIR_STATION_COVERAGE:
            continue
        x, _ = _repair_one_week_gap(s)
        filled[code] = x
    if len(filled) < 3:
        return None

    ddf = pd.DataFrame(filled, index=full_index)
    ok = treated.notna()
    dates = full_index[ok]
    y = treated[ok].to_numpy(float)
    # A donor is eligible only when it is actually observed (or one-week repaired)
    # on every week used by the treated cohort. No long outcome imputation.
    all_codes = [c for c in ddf.columns if ddf.loc[ok, c].notna().all()]
    if len(all_codes) < 3:
        return None
    candidates = ddf.loc[ok, all_codes].to_numpy(float).T
    pre = np.asarray(dates < event)
    if pre.sum() < 10 or (~pre).sum() < 1:
        return None

    sel, scores = _select_donors(y, candidates, pre, k=AIR_DONOR_K)
    D = candidates[sel]
    selected_codes = [all_codes[i] for i in sel]
    f = fit_ascm(y, D, pre, lam=None)
    point = float(np.mean(f.effect[~pre]))
    ci = _air_conformal(y, D, pre, f.lam, point, f.pre_rmse, n_grid=61)
    sp = _symmetric_placebos(y, candidates, pre, point, treated_n=len(eligible_treated),
                             seed_key=f"{event_date}:{stratum}:{len(all_codes)}:{AIR_PROTOCOL}")
    tps = _time_placebos(y, candidates, pre, dates, n=3)
    pretrend = _lead_diagnostic(y, candidates, pre, dates)
    tj = _treated_jackknife(aligned_tdf, eligible_treated, dates, candidates, pre, point)
    dsens = _donor_sensitivity(y, candidates, pre, all_codes, sel, f.weights, point)

    cf_mean = float(np.mean(f.synthetic[~pre]))
    denom = cf_mean if abs(cf_mean) > 1e-6 else np.nan
    pct = float(100 * point / denom) if np.isfinite(denom) else np.nan
    lo_pct = float(100 * ci.lo / denom) if np.isfinite(denom) else np.nan
    hi_pct = float(100 * ci.hi / denom) if np.isfinite(denom) else np.nan
    signal = "NO2_TRAFFIC" if stratum == "traffic" else "NO2_BACKGROUND"
    placebo_med = float(np.median(sp.effects)) if sp.effects.size else 0.0
    median_pre = float(np.median(sp.pre_rmses)) if sp.pre_rmses.size else f.pre_rmse
    result = {
        "signal": signal, "sensor": "ground monitors", "source": "LAQN + DEFRA AURN",
        "expected_sign": -1, "unit": "µg/m³", "site_type": stratum,
        "estimand": "incremental average NO₂ change after the registered implementation date versus a matched no-policy trajectory",
        "point": point, "lo": ci.lo, "hi": ci.hi, "p_zero": ci.p_zero,
        "conformal_boundary_hit": bool(ci.boundary_hit), "conformal_empty": bool(ci.accepted_empty),
        "relative_pct": pct, "relative_lo_pct": lo_pct, "relative_hi_pct": hi_pct,
        "counterfactual_post_mean": cf_mean, "pre_rmse": f.pre_rmse,
        "placebo_pre_rmse_median": median_pre,
        "n_pre": int(pre.sum()), "n_post": int((~pre).sum()), "n_donors": int(D.shape[0]),
        "treated_station_count": int(len(eligible_treated)),
        "treated_station_requested": int(raw_tdf.shape[1]),
        "treated_station_codes": eligible_treated,
        "treated_station_dropped": dropped_treated,
        "treated_station_min_per_week": need_t,
        "treated_station_coverage": {k: round(v, 4) for k, v in treated_coverage.items()},
        "placebo_p": sp.p_ratio, "placebo_p_effect": sp.p_effect, "placebo_n": int(len(sp.ratios)),
        "placebo_symmetric": True, "placebo_exact_cohort": bool(sp.exact_size),
        "placebo_cohort_size": int(sp.cohort_size), "placebo_possible_groups": int(sp.possible_groups),
        "time_placebo_flags": [bool(x["flagged"]) for x in tps],
        "pretrend": pretrend,
        "treated_jackknife": tj,
        "donor_sensitivity": dsens,
        "placebo_effect_median": placebo_med, "min_effect": AIR_MIN_EFFECT,
        "pre_fit_ok": bool(f.pre_rmse <= max(1.5 * median_pre, 5.0) or abs(point) >= 3 * f.pre_rmse),
    }
    if sp.paths.size:
        band_lo = np.percentile(sp.paths, 5, axis=0)
        band_hi = np.percentile(sp.paths, 95, axis=0)
    else:
        band_lo = band_hi = np.full(len(y), np.nan)
    chart = {
        "dates": [str(d.date()) for d in dates], "pre": pre.tolist(),
        "treated": np.round(y, 3).tolist(), "counterfactual": np.round(f.synthetic, 3).tolist(),
        "counterfactual_scm": np.round(f.synthetic_scm, 3).tolist(), "effect": np.round(f.effect, 3).tolist(),
        "placebo_band": [np.round(band_lo, 3).tolist(), np.round(band_hi, 3).tolist()],
        "placebo_effects": np.round(sp.effects, 3).tolist(), "time_placebos": tps,
        "ci_grid": np.round(ci.grid, 3).tolist(), "ci_pvals": np.round(ci.pvals, 3).tolist(),
        "lambda": f.lam,
    }
    donors = {
        "station_codes": selected_codes,
        "weights": np.round(f.weights, 5).tolist(),
        "pre_match_score": np.round(scores, 3).tolist(),
        "stations": [donor_meta[c] for c in selected_codes if c in donor_meta],
        "candidate_station_count": len(all_codes),
        "coverage": {c: round(donor_coverage.get(c, 0.0), 4) for c in selected_codes},
        "imputed_fraction": {
            c: round(float((raw_donor.loc[ok, c].isna() & ddf.loc[ok, c].notna()).mean()), 4)
            for c in selected_codes
        },
        "notes": ["same monitoring-site stratum", "non-London AURN controls",
                  "ranked using pre-policy NO₂ trajectory, baseline level, trend and variability",
                  "only one internal weekly donor gap may be interpolated; longer used-week gaps exclude the donor"],
    }
    post_label = f"over the {post_months} months after {event.day} {event.strftime('%b %Y')}"
    verdict = _decide(signal, result, post_label)
    return result, chart, donors, verdict


def combine_air_verdict(verdicts: dict[str, AirVerdict]) -> AirVerdict:
    """Combine traffic/background without hiding disagreement between strata."""
    if not verdicts:
        return AirVerdict("CANT_TELL", "Can't tell", "No monitor stratum had enough data to run.",
                          ["no usable traffic or background monitor panel"], "NO2_TRAFFIC")
    ordered = [verdicts[k] for k in ("traffic", "background") if k in verdicts]
    statuses = [v.status for v in ordered]
    lead = ordered[0].lead_signal
    if len(set(statuses)) > 1:
        statement = "Traffic and background monitors do not give the same level of evidence. " + " ".join(v.statement for v in ordered)
        return AirVerdict("CANT_TELL", "Mixed evidence by monitor type", statement,
                          [f"{k}: {v.status}" for k, v in verdicts.items()], lead)
    st = statuses[0]
    if st == "REAL":
        headline = "NO₂ fell beyond comparable cities"
    elif st == "NOT_REAL":
        headline = "No additional NO₂ drop detected"
    else:
        headline = "Can't tell"
    return AirVerdict(st, headline, " ".join(v.statement for v in ordered),
                      [r for v in ordered for r in v.reasons], lead)
