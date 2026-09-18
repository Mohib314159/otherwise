"""
VALIDATION HARNESS - proves the method recovers planted ground truth.

Run: python -m scripts.validate
Prints a confusion matrix (truth vs verdict), reversal detection, and the
portfolio risk roll-up. Because the synthetic data hides a known truth in every
field, a clean recovery here is real evidence the pipeline works.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.synth_data import generate
from src.pipeline import run_audit
from src.portfolio import summarize
from src.actuary import price_report

EXPECTED = {
    "adopter":      "VERIFIED",
    "over_claimer": "PARTIAL",
    "weak":         {"INCONCLUSIVE", "PARTIAL", "VERIFIED"},
    "reverter":     {"VERIFIED", "PARTIAL"},     # verified for the period it ran
    "liar":         "REJECTED",
    "control":      "BASELINE",
}


def main():
    ds = generate(seed=7)
    reports = [run_audit(ds, f.field_id) for f in ds.fields]
    rows = []
    for f, rep in zip(ds.fields, reports):
        rows.append({
            "field": f.field_id, "truth": f.truth_label, "claims": f.claims_adoption,
            "verdict": rep.verdict.status,
            "eff_os": round(rep.verdict.effect_offseason, 3),
            "p": round(rep.inference.p_value, 3),
            "tCO2e/yr": round(rep.carbon.central_tco2e_yr, 1),
            "adopt_yr": (rep.detected_adoption_year if rep.detected_adoption_year else "-"),
            "reversal": (f"{rep.reversal.reversal_year}" if rep.reversal.detected else "-"),
        })
    df = pd.DataFrame(rows).sort_values(["truth", "field"]).reset_index(drop=True)
    pd.set_option("display.width", 150); pd.set_option("display.max_rows", 100)
    print("\n=== PER-FIELD AUDIT (synthetic data, known ground truth) ===")
    print(df.to_string(index=False))

    claimed = df[df["claims"]].copy()
    print("\n=== CONFUSION: claimed fields (truth -> verdict) ===")
    print(pd.crosstab(claimed["truth"], claimed["verdict"]).to_string())

    def ok(truth, verdict):
        exp = EXPECTED[truth]
        return verdict in exp if isinstance(exp, set) else verdict == exp
    df["correct"] = df.apply(lambda r: ok(r["truth"], r["verdict"]), axis=1)
    print("\n=== RECOVERY RATE BY TRUTH TYPE ===")
    for k, v in df.groupby("truth")["correct"].mean().items():
        print(f"  {k:12s}: {v*100:5.1f}%  ({int(df[df.truth==k].correct.sum())}/{(df.truth==k).sum()})")
    fp = (df[df.truth == "control"].verdict == "VERIFIED").mean()
    print(f"\n  control false-positive (VERIFIED) rate: {fp*100:.1f}%  (placebo null ~5% expected)")
    print(f"  OVERALL recovery: {df['correct'].mean()*100:.1f}%")

    # reversal recovery
    rev_truth = df[df.truth == "reverter"]
    rev_detected = (rev_truth.reversal != "-").mean() if len(rev_truth) else 0.0
    print(f"\n=== PERMANENCE MONITORING ===")
    print(f"  reverters with reversal correctly detected: {rev_detected*100:.0f}%  "
          f"({(rev_truth.reversal != '-').sum()}/{len(rev_truth)})")
    false_rev = df[(df.truth != 'reverter')]
    fr = (false_rev.reversal != '-').sum()
    print(f"  false reversal alerts on non-reverters: {fr}")

    # portfolio + actuary
    ps = summarize(reports, price=50.0)
    print(f"\n=== PORTFOLIO RISK (price $50/tCO2e) ===")
    print(f"  fields: {ps.n_fields}   verdicts: {ps.counts}")
    print(f"  verified tonnage:        {ps.verified_tco2e:8.1f} tCO2e/yr")
    print(f"  verified @ >=95% conf:   {ps.verified_at_95_tco2e:8.1f} tCO2e/yr")
    print(f"  FRAUD exposure:          {ps.fraud_exposure_tco2e:8.1f} tCO2e/yr claimed-but-unverified "
          f"= ${ps.fraud_exposure_value:,.0f}/yr across {ps.fraud_fields} fields")
    print(f"  reversal at risk:        {ps.reversal_at_risk_tco2e:8.1f} tCO2e across {ps.reversal_fields} fields")
    print(f"  observed reversal rate:  {ps.base_reversal_rate*100:.1f}%  "
          f"(annual hazard {ps.base_annual_hazard*100:.1f}%/yr)")

    print(f"\n=== ORBITAL ACTUARY (illustrative, sample fields) ===")
    for f, rep in zip(ds.fields, reports):
        rr = price_report(rep, ps.base_annual_hazard, price=50.0)
        if rr.applicable:
            print(f"  {f.field_id} ({f.truth_label:11s}): hazard {rr.annual_hazard*100:4.1f}%/yr  "
                  f"10yr reversal {rr.reversal_prob_horizon*100:4.1f}%  "
                  f"premium ${rr.annual_premium_per_tco2e:5.2f}/t  -> ${rr.annual_premium_value:,.0f}/yr")

    df.to_csv("data/validation_results.csv", index=False)
    print("\nsaved -> data/validation_results.csv")


if __name__ == "__main__":
    main()
