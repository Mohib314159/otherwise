"""Run one pre-registered air-policy case and print the independent estimate.

Examples
--------
python -m scripts.run_air_case ulez-central-2019 --post-months 3
python -m scripts.run_air_case ulez-londonwide-2023 --post-months 3 --label "ULEZ replication"

Published study estimates are never passed into the estimator.  They are attached
only after the run finishes and are printed in a separate section below the
Otherwise result.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.app.air import AIR_CASES, run_air_verdict


def main() -> None:
    # Redirected Windows stdout can otherwise fail on scientific units/NO₂.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("case", choices=sorted(AIR_CASES))
    ap.add_argument("--post-months", type=int, default=None)
    ap.add_argument("--label", default="")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    last = {"stage": None}
    def progress(stage, done, total):
        key = (stage, done, total)
        if key != last.get("key"):
            print(f"[{stage}] {done}/{total}")
            last["key"] = key

    out = run_air_verdict(args.case, args.post_months, label=args.label,
                          progress=progress, save=not args.no_save)
    print("\n=== OTHERWISE ===")
    print(out["verdict"]["headline"])
    print(out["verdict"]["statement"])
    for signal, r in out["signals"].items():
        print(f"{signal:15s} {r['relative_pct']:+7.2f}%  {r['point']:+7.2f} µg/m³  "
              f"90% [{r['lo']:+.2f}, {r['hi']:+.2f}]  placebo p={r['placebo_p']:.3f}")

    print("\n=== PUBLISHED ANSWER KEY (attached after estimation) ===")
    if not out.get("research_comparison"):
        print("No pre-registered published estimate for this case.")
    for r in out.get("research_comparison", []):
        print(f"- {r['citation']}: {r['finding']}")
        if "otherwise_pct" in r:
            print(f"  Otherwise: {r['otherwise_pct']:+.2f}% "
                  f"(90% {r['otherwise_pct_interval'][0]:+.2f}% to {r['otherwise_pct_interval'][1]:+.2f}%)")
            print(f"  {r.get('comparison','')}")
    print(f"\nPermalink id: {out['id']}  -> /v/{out['id']}")


if __name__ == "__main__":
    main()
