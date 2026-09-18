"""
Render the demo visuals to assets/ as PNGs.
Run: python -m scripts.render

These are the exact panels the dashboard shows, rendered statically so they can
be checked / dropped into slides.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from src.synth_data import generate
from src.pipeline import run_audit
from src.audit import COLORS, EFFECT_MIN
from src.portfolio import summarize
from src.actuary import price_report
from src.plots import counterfactual_figure, BG, PANEL, INK, MUTE, GREEN, GRID, STYLE

plt.rcParams.update(STYLE)
AMBER = "#f9ab00"; RED = "#ea4335"; BLUE2 = "#6aa3ff"


def counterfactual_chart(rep, fname, title):
    fig = counterfactual_figure(rep, title)
    fig.savefig(f"assets/{fname}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def reversal_timeline(rep, fname):
    rv = rep.reversal
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    cols = [GREEN if e >= EFFECT_MIN else RED for e in rv.yearly_effect]
    ax.bar(rv.years, rv.yearly_effect, color=cols, width=0.6, zorder=3,
           label="off-season additionality / yr")
    ax.axhline(EFFECT_MIN, color=MUTE, ls=":", lw=1.2)
    ax.text(rv.years[0], EFFECT_MIN, " verifiable floor", color=MUTE, fontsize=8, va="bottom")
    ax.set_ylabel("off-season NDVI effect", color=GREEN)
    ax.set_xlabel("year")

    ax2 = ax.twinx()
    ax2.plot(rv.years, rv.cumulative_tco2e, color=AMBER, lw=2.6, marker="o",
             label="cumulative credited tCO2e")
    ax2.set_ylabel("cumulative credited tCO2e", color=AMBER)
    ax2.grid(False)

    if rv.detected:
        ax.axvline(rv.reversal_year - 0.5, color=RED, ls="--", lw=1.6)
        ax.text(rv.reversal_year - 0.45, ax.get_ylim()[1] * 0.92, " REVERSAL",
                color=RED, fontweight="bold", fontsize=11)
    fig.subplots_adjust(top=0.84)
    ax.set_title(f"Permanence monitor — Field {rep.field_id}", fontsize=14,
                 fontweight="bold", loc="left", color=INK, pad=26)
    ax.text(0.0, 1.03, rv.headline, transform=ax.transAxes, color=MUTE, fontsize=9)
    fig.savefig(f"assets/{fname}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def hazard_curves(steady, reverter, base_hazard, fname):
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    for rep, col, name in [(steady, GREEN, "steady adopter"), (reverter, RED, "reverting field")]:
        rr = price_report(rep, base_hazard, price=50.0)
        t = list(range(rr.horizon_years + 1))
        ax.plot(t, [s * 100 for s in rr.survival_curve], color=col, lw=2.6,
                marker="o", label=f"{name}: {rr.reversal_prob_horizon*100:.0f}% 10-yr reversal")
    ax.set_ylim(0, 101)
    ax.set_xlabel("years from now"); ax.set_ylabel("credit survival probability (%)")
    ax.set_title("Reversal hazard — carbon credit survival curves", fontsize=13,
                 fontweight="bold", loc="left", color=INK, pad=8)
    ax.text(0.99, 0.05, "active credit: S(t)=exp(-hazard·t), hazard = base rate ×\n"
            "trajectory stability. Confirmed reversal: treated as impaired (S→0).",
            transform=ax.transAxes, ha="right",
            va="bottom", color=MUTE, fontsize=8)
    ax.legend(loc="upper right", framealpha=0)
    fig.tight_layout()
    fig.savefig(f"assets/{fname}", dpi=150)
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def portfolio_bar(ps, fname):
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    labels = ["Verified\n(creditable)", "Reversal\nat risk", "Fraud\n(claimed, unverified)"]
    vals = [ps.verified_tco2e, ps.reversal_at_risk_tco2e, ps.fraud_exposure_tco2e]
    ax.bar(labels, vals, color=[GREEN, AMBER, RED], width=0.6, zorder=3)
    for i, v in enumerate(vals):
        ax.text(i, v, f" {v:,.0f}", ha="center", va="bottom", color=INK, fontsize=11)
    ax.set_ylabel("tCO2e / yr")
    fig.subplots_adjust(top=0.84)
    ax.set_title("Portfolio carbon risk roll-up", fontsize=13, fontweight="bold",
                 loc="left", color=INK, pad=26)
    ax.text(0.0, 1.03, f"fraud exposure \\${ps.fraud_exposure_value:,.0f}/yr across "
            f"{ps.fraud_fields} fields  ·  observed reversal rate "
            f"{ps.base_reversal_rate*100:.0f}%  ·  price \\${ps.price:.0f}/t",
            transform=ax.transAxes, color=MUTE, fontsize=9)
    fig.savefig(f"assets/{fname}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def placebo_plot(rep, fname):
    inf = rep.inference
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.hist(inf.placebo_ratios, bins=12, color="#3a4250", edgecolor=GRID,
            label="placebo fields (null)")
    ax.axvline(inf.target_ratio, color=GREEN, lw=2.6,
               label=f"this field (ratio={inf.target_ratio:.1f})")
    ax.set_xlabel("RMSPE ratio  (post-treatment divergence / pre-treatment fit)")
    ax.set_ylabel("count")
    ax.set_title(f"Placebo permutation test  —  p = {inf.p_value:.3f}",
                 fontsize=13, fontweight="bold", loc="left", color=INK, pad=10)
    ax.text(0.99, 0.95, "the real field diverges far more than any\n"
            "fake-treated neighbour: that's the significance",
            transform=ax.transAxes, ha="right", va="top", color=MUTE, fontsize=9)
    ax.legend(loc="upper left", framealpha=0)
    fig.tight_layout()
    fig.savefig(f"assets/{fname}", dpi=150)
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def verdict_map(ds, reports, fname):
    fig, ax = plt.subplots(figsize=(8.2, 7.2))
    ax.set_facecolor(PANEL)
    rep_by = {r.field_id: r for r in reports}
    for f in ds.fields:
        if f.field_id in rep_by:
            v = rep_by[f.field_id].verdict
            col, ec, lw = v.color, INK, 1.2
        else:
            col, ec, lw = COLORS["BASELINE"], GRID, 0.5
        ax.scatter(f.lon, f.lat, s=24 + f.area_ha * 4.0, c=col,
                   edgecolors=ec, linewidths=lw, alpha=0.92, zorder=3)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title("Field audit map  —  Grinnell, Iowa (synthetic)",
                 fontsize=13, fontweight="bold", loc="left", color=INK, pad=10)
    legend = [Patch(fc=COLORS[k], ec="none", label=k.title()) for k in
              ["VERIFIED", "PARTIAL", "INCONCLUSIVE", "REJECTED", "BASELINE"]]
    ax.legend(handles=legend, loc="upper right", framealpha=0, fontsize=9)
    ax.grid(True, color=GRID, lw=0.5)
    fig.tight_layout()
    fig.savefig(f"assets/{fname}", dpi=150)
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def aquifer_chart(rep, fname):
    md = pd.to_datetime(rep.month_dates)
    fig, ax = plt.subplots(figsize=(11, 5.0))
    if rep.collapse_detected:
        cline = pd.Timestamp(f"{rep.collapse_year}-01-01")
        ax.axvline(cline, color=RED, ls="--", lw=1.6)
        ax.text(cline, 0.04, "  aquifer abandonment", color=RED, fontsize=9,
                va="bottom", ha="left", transform=ax.get_xaxis_transform())
    ax.fill_between(md, rep.synthetic, rep.target, where=(rep.synthetic >= rep.target),
                    color=RED, alpha=0.18, zorder=1)
    ax.plot(md, rep.synthetic, color=BLUE2, lw=2.0, ls=(0, (5, 2)),
            label="Synthetic twin (still-irrigated counterfactual)", zorder=3)
    ax.plot(md, rep.target, color=GREEN, lw=2.2, label="Actual NDVI", zorder=4)
    ax.set_ylim(0, 0.9); ax.set_ylabel("NDVI")
    fig.subplots_adjust(top=0.80)
    ax.set_title(f"Pivot-circle abandonment — {rep.field_id} (Theme E, same engine)",
                 fontsize=14, fontweight="bold", loc="left", color=INK, pad=6)
    status = f"ABANDONED {rep.collapse_year}" if rep.collapse_detected else "ACTIVE"
    chip = RED if rep.collapse_detected else GREEN
    ax.text(0.0, 1.21, status, transform=ax.transAxes, fontsize=12, fontweight="bold",
            color="#0f1115", bbox=dict(boxstyle="round,pad=0.4", fc=chip, ec="none"))
    ax.text(0.30, 1.225, f"NDVI lost {rep.ndvi_lost:.2f}   ·   p={rep.p_value:.3f}   "
            f"·   same SCM + placebo engine as Iowa", transform=ax.transAxes,
            fontsize=10, color=MUTE, va="center")
    ax.legend(loc="lower left", framealpha=0, fontsize=10)
    fig.savefig(f"assets/{fname}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def disease_chart(re_rep, ndvi_onset_week, fname):
    md = pd.to_datetime(re_rep.dates)
    fig, ax = plt.subplots(figsize=(11, 5.0))
    ax.fill_between(md, re_rep.synthetic, re_rep.target, where=(re_rep.synthetic >= re_rep.target),
                    color=RED, alpha=0.16, zorder=1)
    ax.plot(md, re_rep.synthetic, color=BLUE2, lw=2.0, ls=(0, (5, 2)),
            label="Synthetic healthy twin (red-edge)", zorder=3)
    ax.plot(md, re_rep.target, color="#a142f4", lw=2.3, label="Actual red-edge (NDRE)", zorder=4)
    if re_rep.onset_week is not None:
        ax.axvline(md[re_rep.onset_week], color="#a142f4", lw=1.8,
                   label=f"red-edge detection (wk {re_rep.onset_week})")
    if ndvi_onset_week is not None:
        ax.axvline(md[ndvi_onset_week], color=MUTE, ls=":", lw=1.8,
                   label=f"NDVI would detect (wk {ndvi_onset_week})")
        lead = ndvi_onset_week - (re_rep.onset_week or ndvi_onset_week)
        ax.annotate("", xy=(md[re_rep.onset_week], 0.2), xytext=(md[ndvi_onset_week], 0.2),
                    arrowprops=dict(arrowstyle="<->", color=INK))
        mid = md[(re_rep.onset_week + ndvi_onset_week) // 2]
        ax.text(mid, 0.23, f"{lead}-week\nlead", color=INK, ha="center", fontsize=10, fontweight="bold")
    ax.set_ylim(0, 0.7); ax.set_ylabel("red-edge stress index (NDRE)")
    fig.subplots_adjust(top=0.80)
    ax.set_title(f"Pre-symptomatic disease — {re_rep.field_id} (Theme F, same engine)",
                 fontsize=14, fontweight="bold", loc="left", color=INK, pad=6)
    ax.text(0.0, 1.21, "DETECTED EARLY", transform=ax.transAxes, fontsize=12, fontweight="bold",
            color="#0f1115", bbox=dict(boxstyle="round,pad=0.4", fc="#a142f4", ec="none"))
    ax.text(0.34, 1.225, f"infection flagged in red-edge {ndvi_onset_week and (ndvi_onset_week-re_rep.onset_week)} "
            f"weeks before greenness   ·   p={re_rep.p_value:.3f}", transform=ax.transAxes,
            fontsize=10, color=MUTE, va="center")
    ax.legend(loc="lower left", framealpha=0, fontsize=9)
    fig.savefig(f"assets/{fname}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def fusion_chart(rep, fname):
    md = pd.to_datetime(rep.dates)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.6), sharex=True)

    # optical panel: cover-crop rise
    ax1.plot(md, rep.ndvi_synth, color=BLUE2, lw=1.8, ls=(0, (5, 2)),
             label="Synthetic twin")
    ax1.plot(md, rep.ndvi_target, color=GREEN, lw=2.0, label="NDVI (optical, has cloud gaps)")
    if rep.cover_year:
        ax1.axvline(pd.Timestamp(f"{rep.cover_year}-01-01"), color=GREEN, lw=1.6)
        ax1.text(pd.Timestamp(f"{rep.cover_year}-02-01"), 0.05,
                 f" cover crops detected {rep.cover_year}", color=GREEN, fontsize=9,
                 va="bottom", transform=ax1.get_xaxis_transform())
    ax1.set_ylabel("NDVI"); ax1.set_ylim(0, 0.9)
    ax1.set_title("Optical channel — detects the cover-crop year (a rise)",
                  fontsize=12, fontweight="bold", loc="left", color=INK, pad=6)
    ax1.legend(loc="upper left", framealpha=0, fontsize=9)

    # radar panel: tillage fall
    ax2.fill_between(md, rep.till_synth, rep.till_target,
                     where=(rep.till_synth >= rep.till_target), color="#fbbc04", alpha=0.18)
    ax2.plot(md, rep.till_synth, color=BLUE2, lw=1.8, ls=(0, (5, 2)),
             label="Synthetic twin (still tilling)")
    ax2.plot(md, rep.till_target, color="#fbbc04", lw=2.0, label="SAR tillage signal (simulated)")
    if rep.notill_year:
        ax2.axvline(pd.Timestamp(f"{rep.notill_year}-01-01"), color="#fbbc04", lw=1.8)
        ax2.text(pd.Timestamp(f"{rep.notill_year}-02-01"), 0.78,
                 f" no-till detected {rep.notill_year}", color="#fbbc04", fontsize=9,
                 va="top", transform=ax2.get_xaxis_transform())
    ax2.set_ylabel("tillage / soil disturbance"); ax2.set_ylim(0, 0.9)
    ax2.set_title("Radar channel — detects the no-till year (a fall optical can't see)",
                  fontsize=12, fontweight="bold", loc="left", color=INK, pad=6)
    ax2.legend(loc="upper right", framealpha=0, fontsize=9)

    fig.suptitle(f"Dual-channel fusion — {rep.field_id}: both transitions, one engine "
                 f"(cover {rep.cover_year} + no-till {rep.notill_year})",
                 fontsize=13.5, fontweight="bold", color=INK, x=0.5, y=0.98)
    fig.subplots_adjust(top=0.90, hspace=0.28)
    fig.savefig(f"assets/{fname}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def management_scatter(ndvi_ds, tex_ds, fname):
    from src.management import discriminate, TEXTURE_MAX
    cols = {"cover_crop": GREEN, "weeds": "#fbbc04", "conventional": MUTE}
    names = {"cover_crop": "planted cover crop", "weeds": "weeds (incidental)",
             "conventional": "conventional (bare)"}
    fig, ax = plt.subplots(figsize=(10, 6.2))
    seen = set()
    for f in ndvi_ds.fields:
        v = discriminate(ndvi_ds, tex_ds, f.field_id)
        lbl = names[f.truth_label] if f.truth_label not in seen else None
        seen.add(f.truth_label)
        ax.scatter(v.green_uplift, v.texture, c=cols[f.truth_label], s=90,
                   edgecolor="#0f1115", linewidth=0.6, label=lbl, zorder=3)
    ax.axhline(TEXTURE_MAX, color=RED, ls="--", lw=1.4)
    ax.text(-0.028, TEXTURE_MAX + 0.004, "texture threshold — above = patchy (weeds), below = uniform (managed)",
            color=RED, fontsize=9)
    ax.axvline(0.06, color=MUTE, ls=":", lw=1.2)
    ax.text(0.052, 0.075, "← no winter green", color=MUTE, fontsize=9, rotation=90, va="center")
    ax.set_xlim(-0.04, 0.19); ax.set_ylim(0, 0.16)
    ax.set_xlabel("off-season NDVI uplift  (greenness — same for cover crop AND weeds)")
    ax.set_ylabel("within-field texture (sub-5m)  (uniform ↓  vs  patchy ↑)")
    ax.set_title("Intentionality: texture tells a planted cover crop from weeds — NDVI can't",
                 fontsize=13, fontweight="bold", loc="left", color=INK, pad=10)
    ax.text(0.99, 0.04, "managed vs incidental vegetation, from sub-5m within-field uniformity",
            transform=ax.transAxes, ha="right", va="bottom", color=MUTE, fontsize=8)
    ax.legend(loc="upper right", framealpha=0, fontsize=10)
    fig.subplots_adjust(top=0.91, left=0.095, right=0.97, bottom=0.11)
    fig.savefig(f"assets/{fname}", dpi=150)
    plt.close(fig)
    print(f"  wrote assets/{fname}")


def main():
    ds = generate(seed=7)
    reports = [run_audit(ds, f.field_id) for f in ds.fields if f.claims_adoption]
    ps = summarize(reports, price=50.0)

    verified = next(r for r in reports if r.verdict.status == "VERIFIED"
                    and not r.reversal.detected)
    rejected = next(r for r in reports if r.verdict.status == "REJECTED")
    reverter = next(r for r in reports if r.reversal.detected)

    print("rendering visuals:")
    counterfactual_chart(verified, "01_verified.png",
                         f"Field {verified.field_id} — honest adopter")
    counterfactual_chart(rejected, "02_rejected.png",
                         f"Field {rejected.field_id} — claimed adoption, caught")
    placebo_plot(verified, "03_placebo.png")
    verdict_map(ds, reports, "04_map.png")
    reversal_timeline(reverter, "05_reversal.png")
    hazard_curves(verified, reverter, ps.base_annual_hazard, "06_hazard.png")
    portfolio_bar(ps, "07_portfolio.png")

    # second worked example: same engine, Theme E (aquifer abandonment)
    from src.scenarios import generate_aquifer, audit_circle, generate_disease, audit_disease
    aq = generate_aquifer(11)
    abandoned = next(f.field_id for f in aq.fields if f.truth_label == "abandoned")
    aquifer_chart(audit_circle(aq, abandoned), "08_aquifer.png")

    # third worked example: same engine, Theme F (pre-symptomatic disease)
    ndre, ndvi = generate_disease(13)
    sick = next(f.field_id for f in ndre.fields if f.truth_label == "infected")
    re_rep = audit_disease(ndre, sick)
    vi_rep = audit_disease(ndvi, sick)
    disease_chart(re_rep, vi_rep.onset_week, "09_disease.png")

    # dual-channel optical + radar fusion (answers the FULL Theme-B question)
    from src.radar import generate_regen_dual, audit_fusion
    rn, rt = generate_regen_dual(17)
    rf = next(f.field_id for f in rn.fields if f.truth_label == "full_regen")
    fusion_chart(audit_fusion(rn, rt, rf), "10_radar.png")

    # intentionality: cover crop vs weeds from sub-5m texture
    from src.management import generate_management
    mn, mt = generate_management(23)
    management_scatter(mn, mt, "11_intentionality.png")
    print("done.")


if __name__ == "__main__":
    main()
