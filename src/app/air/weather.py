"""Pre-event-only meteorological normalisation for daily NO2.

The model is deliberately transparent: ridge regression with nonlinear weather
terms and calendar harmonics.  Hyperparameters and coefficients are selected
using PRE-policy observations only.

Normalisation is counterfactual-weather adjustment, not detrending::

    y_norm(t) = y(t) - [f(actual weather_t, calendar_t)
                        - f(reference weather_t, calendar_t)]

The reference weather for each date is the median PRE-policy weather observed
within ±14 days of that day-of-year (circular distance), with the overall
pre-policy median as a fallback.  This preserves seasonally plausible weather
rather than replacing July with January-like conditions or one global median.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

WEATHER_COLS = ["temperature_2m", "precipitation", "wind_u", "wind_v", "boundary_layer_height"]
REFERENCE_DOY_RADIUS = 14


@dataclass
class WeatherAdjustment:
    series: pd.Series
    applicable: bool
    alpha: float | None
    pre_rmse: float | None
    n_pre: int
    features: list[str]
    reference_weather: dict[str, float]
    note: str
    reference_strategy: str = "pre-policy seasonal median ±14 day-of-year"
    coverage: dict = field(default_factory=dict)

    def metadata(self) -> dict:
        return {
            "applicable": self.applicable,
            "model": "pre-period ridge weather normalisation",
            "alpha": self.alpha,
            "pre_rmse": self.pre_rmse,
            "n_pre_days": self.n_pre,
            "features": self.features,
            "reference_weather": {k: round(float(v), 4) for k, v in self.reference_weather.items()},
            "reference_strategy": self.reference_strategy,
            "trained_pre_event_only": True,
            "note": self.note,
            "coverage": self.coverage,
        }


def _prepare_weather(index: pd.DatetimeIndex, weather: pd.DataFrame) -> pd.DataFrame:
    w = weather.reindex(index).copy()
    for c in WEATHER_COLS:
        if c not in w:
            w[c] = np.nan
        w[c] = pd.to_numeric(w[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return w


def _repair_weather_gaps(s: pd.Series) -> pd.Series:
    """Fill only complete internal runs of at most three missing days."""
    missing = s.isna()
    runs = missing.ne(missing.shift()).cumsum()
    lengths = missing.groupby(runs).transform("sum")
    interpolated = s.interpolate(limit_area="inside")
    return s.where(~(missing & (lengths <= 3)), interpolated)


def _circular_doy_distance(a: np.ndarray, b: int) -> np.ndarray:
    d = np.abs(a - int(b))
    return np.minimum(d, 366 - d)


def _seasonal_reference(index: pd.DatetimeIndex, weather: pd.DataFrame,
                        pre_mask: np.ndarray, radius: int = REFERENCE_DOY_RADIUS) -> tuple[pd.DataFrame, dict[str, float]]:
    """Build a date-specific reference weather frame from pre-policy days only."""
    ref = pd.DataFrame(index=index, columns=WEATHER_COLS, dtype=float)
    pre_mask = np.asarray(pre_mask, dtype=bool)
    pre_doy = index.dayofyear.to_numpy(int)[pre_mask]
    all_doy = index.dayofyear.to_numpy(int)
    fallback: dict[str, float] = {}
    for c in WEATHER_COLS:
        pre_vals = weather[c].to_numpy(float)[pre_mask]
        finite = np.isfinite(pre_vals)
        fallback[c] = float(np.nanmedian(pre_vals)) if finite.any() else 0.0
        for doy in np.unique(all_doy):
            near = finite & (_circular_doy_distance(pre_doy, int(doy)) <= radius)
            value = float(np.nanmedian(pre_vals[near])) if near.any() else fallback[c]
            ref.loc[all_doy == doy, c] = value
    return ref, fallback


def _design(index: pd.DatetimeIndex, weather: pd.DataFrame,
            weather_center: dict[str, float], weather_scale: dict[str, float]) -> tuple[np.ndarray, list[str]]:
    n = len(index)
    day = index.dayofyear.to_numpy(float)
    dow = index.dayofweek.to_numpy(float)
    days = (index - index.min()).days.to_numpy(float)
    trend = (days - days.mean()) / max(days.std(), 1.0)

    cols = [np.ones(n)]
    names = ["intercept"]
    # Calendar terms are intentionally retained in both actual/reference
    # predictions.  Only the weather component is normalised away.
    for harmonic in (1, 2):
        angle = 2 * np.pi * harmonic * day / 365.25
        cols += [np.sin(angle), np.cos(angle)]
        names += [f"annual_sin_{harmonic}", f"annual_cos_{harmonic}"]
    angle_d = 2 * np.pi * dow / 7.0
    cols += [np.sin(angle_d), np.cos(angle_d), trend]
    names += ["dow_sin", "dow_cos", "trend"]

    vals: dict[str, np.ndarray] = {}
    for c in WEATHER_COLS:
        raw = weather[c].to_numpy(float)
        raw = np.where(np.isfinite(raw), raw, weather_center[c])
        z = (raw - weather_center[c]) / weather_scale[c]
        vals[c] = z
        cols.append(z); names.append(c)
    cols += [vals["temperature_2m"] ** 2,
             vals["wind_u"] ** 2 + vals["wind_v"] ** 2,
             vals["precipitation"] ** 2,
             vals["boundary_layer_height"] ** 2,
             vals["wind_u"] * vals["boundary_layer_height"],
             vals["wind_v"] * vals["boundary_layer_height"]]
    names += ["temperature_sq", "wind_speed_sq", "precip_sq", "pbl_sq", "wind_u_x_pbl", "wind_v_x_pbl"]
    return np.column_stack(cols), names


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    p = X.shape[1]
    penalty = np.eye(p) * float(alpha)
    penalty[0, 0] = 0.0
    try:
        return np.linalg.solve(X.T @ X + penalty, X.T @ y)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(X.T @ X + penalty) @ X.T @ y


def _choose_alpha(X: np.ndarray, y: np.ndarray, alphas=(0.0, 0.1, 1.0, 10.0, 100.0)) -> float:
    """Blocked pre-period holdout; never inspects policy-period outcomes."""
    n = len(y)
    if n < 90:
        return 10.0
    cut = max(int(n * 0.8), 60)
    cut = min(cut, n - 14)
    if cut <= 30:
        return 10.0
    best, best_err = 10.0, np.inf
    for a in alphas:
        beta = _ridge_fit(X[:cut], y[:cut], a)
        pred = X[cut:] @ beta
        err = float(np.sqrt(np.mean((y[cut:] - pred) ** 2)))
        if np.isfinite(err) and err < best_err - 1e-12:
            best, best_err = float(a), err
    return best


def weather_normalise(no2_daily: pd.Series, weather_daily: pd.DataFrame,
                      event_date: str | pd.Timestamp, min_pre_days: int = 180) -> WeatherAdjustment:
    s = no2_daily.copy().sort_index()
    if s.empty:
        return WeatherAdjustment(s, False, None, None, 0, [], {}, "no NO2 data")
    s.index = pd.DatetimeIndex(pd.to_datetime(s.index)).normalize()
    w = _prepare_weather(s.index, weather_daily)
    event = pd.Timestamp(event_date)
    pre = ((s.index < event) & s.notna()).to_numpy(bool)
    n_pre = int(pre.sum())
    # Never borrow post-event weather to repair a pre-event training row.
    # Boundary-layer height is optional at the provider; all four core fields
    # must be available. Unrepaired weather cannot masquerade as normalised NO2.
    pre_dates = np.asarray(s.index < event)
    coverage = {"missing_days": {}, "interpolated_days": {}, "unavailable_optional_features": []}
    for c in WEATHER_COLS:
        before = w[c].isna()
        coverage["missing_days"][c] = int(before.sum())
        if c == "boundary_layer_height" and before.all():
            coverage["unavailable_optional_features"].append(c)
            w[c] = 0.0
            coverage["interpolated_days"][c] = 0
            continue
        for mask in (pre_dates, ~pre_dates):
            w.loc[mask, c] = _repair_weather_gaps(w.loc[mask, c])
        coverage["interpolated_days"][c] = int((before & w[c].notna()).sum())
    valid_weather = w.notna().all(axis=1)
    coverage["valid_days_after_repair"] = int(valid_weather.sum())
    coverage["total_days"] = len(w)
    if not valid_weather.all():
        return WeatherAdjustment(s, False, None, None, n_pre, [], {},
                                 "meteorological data unavailable or contain gaps longer than three days or at a period boundary",
                                 coverage=coverage)

    centers, scales = {}, {}
    for c in WEATHER_COLS:
        arr = w[c].to_numpy(float)[pre]
        med = float(np.nanmedian(arr)) if np.isfinite(arr).any() else 0.0
        sd = float(np.nanstd(arr)) if np.isfinite(arr).any() else 1.0
        centers[c], scales[c] = med, max(sd, 1e-6)
    if n_pre < min_pre_days:
        return WeatherAdjustment(s, False, None, None, n_pre, [], centers,
                                 f"only {n_pre} pre-event NO2 days; need {min_pre_days} for weather normalisation", coverage=coverage)

    ref_weather, ref_summary = _seasonal_reference(s.index, w, pre)
    X, names = _design(s.index, w, centers, scales)
    Xref, _ = _design(s.index, ref_weather, centers, scales)
    ok_pre = pre & np.all(np.isfinite(X), axis=1)
    ypre = s.to_numpy(float)[ok_pre]
    Xpre = X[ok_pre]
    if len(ypre) < min_pre_days:
        return WeatherAdjustment(s, False, None, None, int(len(ypre)), names, ref_summary,
                                 "too many missing meteorological rows for a pre-event-only model", coverage=coverage)

    alpha = _choose_alpha(Xpre, ypre)
    beta = _ridge_fit(Xpre, ypre, alpha)
    pred_actual = X @ beta
    pred_reference = Xref @ beta
    adjusted = s.to_numpy(float) - (pred_actual - pred_reference)
    adjusted[~s.notna().to_numpy()] = np.nan
    out = pd.Series(adjusted, index=s.index, name=s.name)
    rmse = float(np.sqrt(np.mean((ypre - Xpre @ beta) ** 2)))
    return WeatherAdjustment(
        out, True, alpha, rmse, int(len(ypre)), names, ref_summary,
        "weather model fit and selected using pre-event observations only; reference weather uses pre-policy seasonal medians",
        coverage=coverage,
    )
