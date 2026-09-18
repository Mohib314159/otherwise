"""
CarbonTwin - a risk desk for carbon credits.

Run:  streamlit run src/dashboard.py     (or: make run)

Three honest, defensible layers on one synthetic-control core:
  VERIFY   causal additionality + fraud, with a p-value
  MONITOR  permanence - detect a credit reversing in real time
  PRICE    reversal probability + an illustrative risk premium (the actuary)

Layout, top to bottom:
  1. Portfolio risk roll-up (verified tonnage, fraud exposure $, reversal at risk)
  2. Audit queue (where to send inspectors, REJECTED first)
  3. Per-field: counterfactual + verdict, then permanence + reversal-risk pricing

With live data, swap generate() for load_treefera(path); nothing else changes.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from src.synth_data import generate
from src.pipeline import run_audit
from src.portfolio import summarize
from src.actuary import price_report
from src.plots import counterfactual_figure, reversal_figure, survival_figure

st.set_page_config(page_title="CarbonTwin", layout="wide", page_icon="🛰️")

st.markdown("""
<style>
  .stApp { background:#0f1115; }
  h1,h2,h3,h4,p,span,div,label { color:#e8eaed !important; }
  .verdict-chip{display:inline-block;padding:4px 14px;border-radius:999px;
    font-weight:700;color:#0f1115;font-size:0.95rem;}
  .metric-card{background:#161a20;border:1px solid #2a2f3a;border-radius:12px;
    padding:14px 16px;}
  .metric-card .v{font-size:1.5rem;font-weight:700;}
  .metric-card .l{color:#9aa0a6;font-size:0.75rem;text-transform:uppercase;letter-spacing:.04em;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_reports():
    ds = generate(seed=7)
    reports = {f.field_id: run_audit(ds, f.field_id)
               for f in ds.fields if f.claims_adoption}
    ps = summarize(list(reports.values()), price=50.0)
    truth = {f.field_id: f.truth_label for f in ds.fields}
    return reports, ps, truth


reports, ps, truth = load_reports()


def card(col, value, label):
    col.markdown(f'<div class="metric-card"><div class="v">{value}</div>'
                 f'<div class="l">{label}</div></div>', unsafe_allow_html=True)


st.markdown("# 🛰️ CarbonTwin")
st.markdown("#### A risk desk for carbon credits — verify additionality, monitor "
            "permanence, and price reversal risk, all from orbit with a p-value.")

# ---- 1. portfolio risk roll-up --------------------------------------------
st.markdown("### Portfolio risk")
p1, p2, p3, p4 = st.columns(4)
card(p1, f"{ps.verified_tco2e:,.0f}", "verified tCO₂e/yr")
card(p2, f"${ps.fraud_exposure_value:,.0f}", f"fraud exposure / yr ({ps.fraud_fields} fields)")
card(p3, f"{ps.reversal_at_risk_tco2e:,.0f}", f"tCO₂e at reversal risk ({ps.reversal_fields})")
card(p4, f"{ps.base_reversal_rate*100:.0f}%", "observed reversal rate")
st.caption("Fraud exposure = carbon farms *claimed* but the statistics can't verify. "
           "Scale this across a national book and it becomes the headline number.")

st.divider()

# ---- 2. audit queue --------------------------------------------------------
st.markdown("### Audit queue")
order = {"REJECTED": 0, "INCONCLUSIVE": 1, "PARTIAL": 2, "VERIFIED": 3, "BASELINE": 4}
rows = []
for fid, rep in reports.items():
    v = rep.verdict
    rev = "⚠️ reversing" if rep.reversal.detected else "—"
    rows.append({
        "Field": fid, "Verdict": v.status,
        "Off-season effect": round(v.effect_offseason, 3),
        "p-value": round(v.p_value, 3),
        "tCO₂e/yr": round(rep.carbon.central_tco2e_yr, 1),
        "Permanence": rev,
        "Action": {"REJECTED": "🔴 site visit", "INCONCLUSIVE": "🟣 monitor",
                   "PARTIAL": "🟠 credit verified part", "VERIFIED": "🟢 credit",
                   "BASELINE": "⚪ none"}[v.status],
    })
queue = pd.DataFrame(rows).sort_values(by="Verdict", key=lambda s: s.map(order)).reset_index(drop=True)
st.dataframe(queue, use_container_width=True, hide_index=True)

st.divider()

# ---- 3. per-field detail ---------------------------------------------------
left, right = st.columns([3, 2])
with left:
    fid = st.selectbox("Inspect a field", list(reports.keys()))
with right:
    st.caption(f"(synthetic ground truth: **{truth.get(fid)}** — hidden from the model)")

rep = reports[fid]
v = rep.verdict

st.markdown(f'<span class="verdict-chip" style="background:{v.color}">{v.status}</span>'
            f'&nbsp;&nbsp;<b>{v.headline}</b>', unsafe_allow_html=True)

dy = rep.detected_adoption_year
st.caption(f"🛰️ Detected adoption year (from the data, not the claim): "
           f"**{dy if dy else 'none detected'}**  ·  farmer claimed: **2021**")

c1, c2, c3, c4 = st.columns(4)
card(c1, f"{v.effect_offseason:+.3f}", "off-season NDVI effect")
card(c2, f"{v.p_value:.3f}", "placebo p-value")
card(c3, f"{v.confidence:.0f}%", "confidence")
lo, hi = rep.carbon.low_tco2e_yr, rep.carbon.high_tco2e_yr
card(c4, f"{rep.carbon.central_tco2e_yr:.0f}", f"tCO₂e/yr (range {lo:.0f}–{hi:.0f})")

st.pyplot(counterfactual_figure(rep, f"Field {fid}"), use_container_width=True)
st.markdown(f"**Why this verdict:** {v.reason}")
if rep.carbon.central_tco2e_yr > 0:
    st.caption("⚠️ " + rep.carbon.note)

# ---- permanence + reversal-risk pricing -----------------------------------
st.markdown("### Permanence & reversal risk")
rr = price_report(rep, ps.base_annual_hazard, price=50.0)
if rep.reversal.detected:
    st.error(f"⚠️ {rep.reversal.headline}")
else:
    st.success(f"✓ {rep.reversal.headline}")

if rr.applicable:
    r1, r2, r3 = st.columns(3)
    card(r1, f"{rr.annual_hazard*100:.1f}%/yr", "reversal hazard")
    card(r2, f"{rr.reversal_prob_horizon*100:.0f}%", f"{rr.horizon_years}-yr reversal prob")
    card(r3, f"${rr.annual_premium_per_tco2e:.2f}/t", "illustrative premium")

g1, g2 = st.columns(2)
with g1:
    st.pyplot(reversal_figure(rep), use_container_width=True)
with g2:
    st.pyplot(survival_figure(rep, ps.base_annual_hazard), use_container_width=True)
if rr.applicable:
    st.caption("⚠️ " + rr.note)

# donor transparency + method
top = sorted(zip(rep.scm.donor_ids, rep.scm.weights), key=lambda x: -x[1])[:4]
st.caption("Synthetic twin built from donors: "
           + ", ".join(f"{d} ({w:.2f})" for d, w in top if w > 0.01))

with st.expander("How it works / defend it"):
    st.markdown("""
- **Verify** — synthetic control: a convex blend of no-claim neighbours fitted to
  pre-2021 NDVI. Convex weights forbid extrapolation. Significance by Abadie
  placebo permutation (p-value). Thresholds adapt to the dataset's own noise floor.
- **Monitor** — we keep running the control forward; if a verified credit's
  additionality collapses relative to its own peak, we flag a reversal with the year.
- **Price** — hazard = portfolio reversal base rate × this field's trajectory
  stability; exponential survival gives a reversal probability and an *illustrative*
  premium. Standard actuarial maths, applied to orbital MRV. Indicative, not a quote.
- **Clouds** — monthly median composite; fields whose off-season window is mostly
  cloud-interpolated return INCONCLUSIVE rather than a fake flat line.
- **Carbon** — literature band 0.2–2.0 tCO₂e/ha/yr, placed by signal strength for
  triage only; needs soil calibration. The defensible claim is the *statistics*.
""")
