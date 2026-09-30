"""Red-team regression tests for the change-verdict method (see docs/REDTEAM.md).

Everything here is offline, seeded and fast (< 10 s in total). Two kinds of test:

* HOLDS: behaviour the review confirmed and that must not regress (a common
  regional shock is never REAL; the donor / post-bin gates in `decide`).
* BREAKS: deterministic failures the review found. These are written as the
  behaviour the method SHOULD have and marked `xfail(strict=True)`, so they
  fail today, document the bug, and turn into a hard failure (XPASS) the moment
  the fix lands, which forces the marker to be removed. Nothing under src/ was
  edited for this review.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.app import s2 as s2mod
from src.app.donors import select_donors
from src.app.estimator import conformal_interval, fit_ascm, space_placebo, time_placebos
from src.app.evidence import status_of
from src.app.prep import binned
from src.app.verdict import ALPHA, MIN_DONORS, MIN_EFFECT, MIN_POST_BINS, SIGNALS, SignalResult, combine, decide


# ---------------------------------------------------------------------------
# helpers: a seeded synthetic panel and the exact numbers run._analyse produces
# ---------------------------------------------------------------------------
def synth_panel(seed=0, n_donors=60, T=110, n_pre=75, noise=0.03, shock=0.0, treated_extra=0.0):
    """Every unit shares one seasonal curve (own amplitude and offset) and drops
    by `shock` after the event; the treated unit (column 0) drops by
    `shock + treated_extra` on top. Dates are one observation per 10 days."""
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    season = 0.2 * np.sin(2 * math.pi * t / 36.5)
    amp = rng.uniform(0.8, 1.2, n_donors + 1)
    off = rng.normal(0, 0.05, n_donors + 1)
    V = 0.5 + season[:, None] * amp[None, :] + off[None, :] + rng.normal(0, noise, (T, n_donors + 1))
    post = t >= n_pre
    V[post, :] += shock
    V[post, 0] += treated_extra
    dates = np.datetime64("2020-01-01") + (t * 10).astype("timedelta64[D]")
    return dates, V, dates[n_pre]


def pipeline(dates, V, event, signal="NDVI", change_type="clearing", n_grid=11, time_pl=False):
    """prep.binned -> donors.select_donors -> fit_ascm -> conformal -> placebo -> SignalResult.
    Mirrors run._analyse line for line, minus covariates."""
    b = binned(dates, V, event, bin_days=10)
    sel = select_donors(b.matrix, b.pre, b.donor_cov, None, k=80)
    y = b.matrix[:, 0]
    D = b.matrix[:, 1:][:, sel.index].T
    f = fit_ascm(y, D, b.pre)
    point = float(np.mean(f.effect[~b.pre]))
    ci = conformal_interval(y, D, b.pre, f.lam, point, max(f.pre_rmse, 1e-3), alpha=ALPHA, n_grid=n_grid)
    sp = space_placebo(y, D, b.pre, f.lam, point, max_units=60)
    flags = []
    if time_pl:
        flags = [t.flagged for t in time_placebos(y, D, b.pre, f.lam, n=3, min_effect=MIN_EFFECT[signal], alpha=ALPHA)]
    return SignalResult(signal=signal, sensor="S2", expected_sign=SIGNALS[change_type][1], point=point,
                        lo=ci.lo, hi=ci.hi, p_zero=ci.p_zero, pre_rmse=f.pre_rmse,
                        placebo_pre_rmse_median=float(np.median(sp.pre_rmses)),
                        n_pre=int(b.pre.sum()), n_post=int((~b.pre).sum()), n_donors=int(D.shape[0]),
                        placebo_p=sp.p_value, placebo_p_effect=sp.p_effect, placebo_n=int(len(sp.ratios)),
                        time_placebo_flags=flags, placebo_effect_median=float(np.median(sp.effects)))


STRONG = dict(signal="NDVI", sensor="S2", expected_sign=-1, point=-0.30, lo=-0.35, hi=-0.25, p_zero=0.0,
              pre_rmse=0.02, placebo_pre_rmse_median=0.02, n_pre=40, n_post=12, n_donors=60,
              placebo_p=0.02, placebo_p_effect=0.02, placebo_n=60)


def make(**over) -> SignalResult:
    return SignalResult(**{**STRONG, **over})


# ---------------------------------------------------------------------------
# HOLDS
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_common_regional_shock_is_never_real(seed):
    """All cells drop 0.10 after the date (a regional drought, a sensor
    recalibration). The synthetic control drops with them, the gap is ~0 and
    `decide` must not say REAL."""
    dates, V, ev = synth_panel(seed=seed, shock=-0.10)
    r = pipeline(dates, V, ev)
    v = decide(r, "clearing", "")
    assert abs(r.point) < 0.03, r.point
    assert r.n_donors >= MIN_DONORS and r.n_post >= MIN_POST_BINS
    assert v.status != "REAL", (v.status, v.reasons)


def test_treated_effect_on_top_of_regional_shock_is_still_found():
    """Control for the test above: the same shock plus a real -0.10 on the
    treated cell is recovered as REAL, so the non-REAL above is not just
    the method being blind."""
    dates, V, ev = synth_panel(seed=0, shock=-0.10, treated_extra=-0.10)
    r = pipeline(dates, V, ev)
    assert decide(r, "clearing", "").status == "REAL"
    assert -0.13 < r.point < -0.07


def test_null_panel_is_not_real():
    dates, V, ev = synth_panel(seed=3)
    r = pipeline(dates, V, ev)
    assert decide(r, "clearing", "").status != "REAL"


@pytest.mark.parametrize("n_donors,n_post", [(19, 12), (60, 2), (19, 2)])
def test_decide_gates_below_thresholds_are_cant_tell(n_donors, n_post):
    """No route through `decide` reaches REAL with < 20 donors or < 3 post bins."""
    assert decide(make(n_donors=n_donors, n_post=n_post), "clearing", "").status == "CANT_TELL"


def test_combine_optical_lead_with_two_post_bins_is_cant_tell():
    r = make(n_post=2)
    assert combine(r, r, "clearing", "").status == "CANT_TELL"


def test_nan_point_or_interval_is_never_real():
    assert decide(make(point=float("nan")), "clearing", "").status != "REAL"
    assert decide(make(lo=float("nan"), hi=float("nan")), "clearing", "").status != "REAL"


def test_seasonal_shift_20_days_is_not_real():
    """Treated phenology 20 days out of phase with every donor: the fit gets
    worse, never a false REAL (E4)."""
    rng = np.random.default_rng(7)
    days = np.arange(0, 4 * 365, 5)
    days = days[rng.random(len(days)) < 0.55]
    t = days.astype(float)
    n = 60
    phases = rng.normal(0, 4.0, n + 1); phases[0] = 20.0
    V = np.empty((len(t), n + 1))
    for j in range(n + 1):
        V[:, j] = 0.45 + 0.25 * np.sin(2 * math.pi * (t - phases[j] - 100) / 365.25) + rng.normal(0, 0.03, len(t))
    dates = np.datetime64("2019-01-01") + days.astype("timedelta64[D]")
    ev = np.datetime64("2022-01-01")
    r = pipeline(dates, V, ev, change_type="clearing")
    assert decide(r, "clearing", "").status != "REAL"


# ---------------------------------------------------------------------------
# BREAKS (desired behaviour, xfail strict). E5, E7 and E8 are fixed (METHOD.md
# section 9) and their markers removed; the rest still fail today.
# ---------------------------------------------------------------------------
def test_pretrend_with_flagged_time_placebos_is_not_real():
    dates, V, ev = synth_panel(seed=0)
    t = np.arange(len(dates)); n_pre = int(np.sum(dates < ev))
    V[:, 0] += np.clip((t - n_pre) * 10 + 365, 0, None) * (-0.2) / 365.0      # -0.2 NDVI/yr from 1 yr before
    r = pipeline(dates, V, ev, time_pl=True)
    assert any(r.time_placebo_flags), "the in-time placebo does see the pre-trend"
    assert decide(r, "clearing", "").status != "REAL"


def test_pretrend_4x_rescue_is_disabled_when_time_placebos_flag():
    """Pins the mechanism of the E5 fix on the same panel. Before the fix the
    loose pre-fit gate failed, the 4x rule rescued it, two of three in-time
    placebos were flagged and the verdict was still REAL. Now the flags switch
    the 4x rescue off (pre_fit_ok is False) and the verdict is CAN'T TELL."""
    dates, V, ev = synth_panel(seed=0)
    t = np.arange(len(dates)); n_pre = int(np.sum(dates < ev))
    V[:, 0] += np.clip((t - n_pre) * 10 + 365, 0, None) * (-0.2) / 365.0
    r = pipeline(dates, V, ev, time_pl=True)
    loose = r.pre_rmse <= max(1.5 * r.placebo_pre_rmse_median, 0.02)
    assert not loose and abs(r.point) >= 4 * r.pre_rmse
    assert sum(r.time_placebo_flags) >= 2
    assert not r.pre_fit_ok
    assert decide(r, "clearing", "").status == "CANT_TELL"


def test_all_time_placebos_flagged_blocks_real():
    assert decide(make(time_placebo_flags=[True, True, True]), "clearing", "").status != "REAL"


@pytest.mark.xfail(strict=True, reason="E9: evidence.status_of applies neither MIN_DONORS, the pre-fit gate nor "
                                       "the controls-shifted rule, so the page can say 'optical and radar agree' "
                                       "under a CAN'T TELL verdict (evidence.status_of)")
@pytest.mark.parametrize("over", [dict(n_donors=19), dict(pre_rmse=0.2), dict(placebo_effect_median=-0.3)])
def test_evidence_status_respects_verdict_gates(over):
    r = make(**over)
    assert decide(r, "clearing", "").status == "CANT_TELL"      # the verdict gate fires ...
    assert status_of(r) != "supportive"                          # ... so the evidence must not contradict it


def test_donor_cells_keep_one_km_edge_gap_for_large_areas():
    """E2 (fixed, CRITIQUE #16): the 1 km buffer is now edge-to-edge."""
    from shapely.geometry import Point, box
    from src.app.geometry import Area, donor_grid, reproject, utm_epsg
    lon, lat, ha = -1.286, 52.908, 500.0
    epsg = utm_epsg(lon, lat)
    c = reproject(Point(lon, lat), 4326, epsg)
    side = math.sqrt(ha * 10_000)
    utm = box(c.x - side / 2, c.y - side / 2, c.x + side / 2, c.y + side / 2)
    area = Area(wgs84=reproject(utm, epsg, 4326), utm=utm, epsg=epsg, area_ha=ha, lon=lon, lat=lat)
    g = donor_grid(area)
    edge = np.asarray([cell.distance(area.utm) for cell in g.cells])
    assert edge.min() >= 1000.0 - 1e-6, f"nearest donor cell edge is {edge.min():.0f} m from the area"


def test_despike_keeps_short_flood_observations():
    """E7 fix: given the NDWI series, the despike sees the water and keeps the
    flood. (Dry vegetation NDWI about -0.45, standing water about +0.3.)"""
    rng = np.random.default_rng(0)
    days = np.arange(0, 400, 5)
    days = days[rng.random(len(days)) < 0.5]
    ndvi = 0.6 + rng.normal(0, 0.03, len(days))
    flooded = (days >= 200) & (days < 220)
    ndvi[flooded] = -0.1 + rng.normal(0, 0.03, flooded.sum())       # standing water, not cloud
    ndwi = -0.45 + rng.normal(0, 0.03, len(days))
    ndwi[flooded] = 0.3 + rng.normal(0, 0.03, flooded.sum())
    sus = s2mod.despike(days.astype("datetime64[D]"), ndvi, ndwi=ndwi)
    assert flooded.sum() >= 2
    assert sus[flooded].mean() < 0.5, f"{sus[flooded].sum()} of {flooded.sum()} flooded observations flagged as haze"


def test_despike_without_ndwi_still_deletes_the_whole_short_flood():
    """NDVI alone cannot tell water from haze: without the NDWI series the
    despike behaves exactly as before the E7 fix. Every caller in fetch.py now
    passes NDWI."""
    rng = np.random.default_rng(0)
    days = np.arange(0, 400, 5)
    days = days[rng.random(len(days)) < 0.5]
    ndvi = 0.6 + rng.normal(0, 0.03, len(days))
    flooded = (days >= 200) & (days < 220)
    ndvi[flooded] = -0.1 + rng.normal(0, 0.03, flooded.sum())
    sus = s2mod.despike(days.astype("datetime64[D]"), ndvi)
    assert sus[flooded].all()
