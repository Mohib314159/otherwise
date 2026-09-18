"""Shared matplotlib styling + the counterfactual figure (dashboard & renderer)."""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from .contract import offseason_mask

BG = "#0f1115"; PANEL = "#161a20"; INK = "#e8eaed"; MUTE = "#9aa0a6"
GREEN = "#34a853"; BLUE = "#6aa3ff"; GRID = "#2a2f3a"

STYLE = {
    "figure.facecolor": BG, "axes.facecolor": PANEL, "savefig.facecolor": BG,
    "text.color": INK, "axes.labelcolor": INK, "xtick.color": MUTE,
    "ytick.color": MUTE, "axes.edgecolor": GRID, "font.size": 11,
    "font.family": "DejaVu Sans", "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
}


def counterfactual_figure(rep, title: str):
    """Build the actual-vs-synthetic NDVI figure for one audit report."""
    plt.rcParams.update(STYLE)
    md = pd.to_datetime(rep.month_dates)
    pre = md.year < 2021
    os_mask = offseason_mask(rep.month_dates)
    syn, act, v = rep.scm.synthetic, rep.target, rep.verdict

    fig, ax = plt.subplots(figsize=(11, 5.4))
    in_os = False
    for i in range(len(md)):
        if os_mask[i] and not in_os:
            start = md[i]; in_os = True
        if (not os_mask[i] or i == len(md) - 1) and in_os:
            ax.axvspan(start, md[i], color="#1d2530", alpha=0.6, zorder=0); in_os = False

    tline = pd.Timestamp("2021-01-01")
    ax.axvline(tline, color=MUTE, ls="--", lw=1.2, zorder=1)
    ax.text(tline, 0.04, "  practice claimed: 2021", color=MUTE, fontsize=9,
            va="bottom", ha="left", transform=ax.get_xaxis_transform())

    post = ~pre
    fill_col = v.color if v.status in ("VERIFIED", "PARTIAL") else "#ea4335"
    ax.fill_between(md[post], syn[post], act[post], where=(act[post] >= syn[post]),
                    color=fill_col, alpha=0.18, zorder=1)
    ax.plot(md, syn, color=BLUE, lw=2.0, ls=(0, (5, 2)),
            label="Synthetic twin (counterfactual)", zorder=3)
    ax.plot(md, act, color=GREEN, lw=2.4, label="Actual NDVI", zorder=4)

    ax.set_ylim(0, 1.0); ax.set_ylabel("NDVI")
    fig.subplots_adjust(top=0.80)
    ax.set_title(title, fontsize=14, fontweight="bold", loc="left", pad=6, color=INK)
    ax.text(0.0, 1.21, v.status, transform=ax.transAxes, fontsize=12, fontweight="bold",
            color="#0f1115", bbox=dict(boxstyle="round,pad=0.4", fc=v.color, ec="none"))
    msg = (f"off-season effect {v.effect_offseason:+.3f} NDVI   ·   p={v.p_value:.3f}"
           f"   ·   {v.confidence:.0f}% confidence   ·   pre-fit RMSE {v.pre_rmse:.3f}")
    ax.text(0.17, 1.225, msg, transform=ax.transAxes, fontsize=10, color=MUTE, va="center")
    ax.legend(loc="upper left", framealpha=0, fontsize=10)
    return fig


def reversal_figure(rep):
    """Yearly off-season additionality + cumulative credited carbon, reversal marked."""
    from .audit import EFFECT_MIN
    plt.rcParams.update(STYLE)
    rv = rep.reversal
    fig, ax = plt.subplots(figsize=(8.0, 4.4))
    cols = [GREEN if e >= EFFECT_MIN else "#ea4335" for e in rv.yearly_effect]
    ax.bar(rv.years, rv.yearly_effect, color=cols, width=0.6, zorder=3)
    ax.axhline(EFFECT_MIN, color=MUTE, ls=":", lw=1.0)
    ax.set_ylabel("off-season NDVI effect", color=GREEN); ax.set_xlabel("year")
    ax2 = ax.twinx()
    ax2.plot(rv.years, rv.cumulative_tco2e, color="#f9ab00", lw=2.4, marker="o")
    ax2.set_ylabel("cumulative credited tCO2e", color="#f9ab00"); ax2.grid(False)
    if rv.detected:
        ax.axvline(rv.reversal_year - 0.5, color="#ea4335", ls="--", lw=1.6)
        ax.text(rv.reversal_year - 0.45, ax.get_ylim()[1] * 0.9, " REVERSAL",
                color="#ea4335", fontweight="bold", fontsize=10)
    fig.subplots_adjust(top=0.88)
    ax.set_title("Permanence monitor", fontsize=12, fontweight="bold", loc="left",
                 color=INK, pad=8)
    return fig


def survival_figure(rep, base_hazard: float):
    """Single-field credit survival curve from the actuary."""
    from .actuary import price_report
    plt.rcParams.update(STYLE)
    rr = price_report(rep, base_hazard, price=50.0)
    fig, ax = plt.subplots(figsize=(8.0, 4.4))
    t = list(range(rr.horizon_years + 1))
    col = "#34a853" if rr.annual_hazard < 0.1 else "#ea4335"
    ax.plot(t, [s * 100 for s in rr.survival_curve], color=col, lw=2.6, marker="o")
    ax.set_ylim(0, 101); ax.set_xlabel("years from now")
    ax.set_ylabel("credit survival probability (%)")
    ax.set_title("Reversal hazard — survival curve", fontsize=12, fontweight="bold",
                 loc="left", color=INK, pad=8)
    ax.text(0.99, 0.92, f"{rr.reversal_prob_horizon*100:.0f}% reversal over "
            f"{rr.horizon_years} yrs", transform=ax.transAxes, ha="right", va="top",
            color=MUTE, fontsize=10)
    return fig
