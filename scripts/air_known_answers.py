"""Run the pre-registered air-policy answer keys without tuning to the literature.

Writes showcase/air_validation.json.  This script is intentionally boring: each
case is run exactly once with its pre-registered default horizon and only *after*
that estimate exists are the published findings copied into the table.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.app.air import AIR_CASES, run_air_verdict

OUT = Path("showcase/air_validation.json")


def main() -> None:
    rows = []
    for cid, case in AIR_CASES.items():
        if not case.supported:
            continue
        print(f"\n--- {case.label} ---")
        out = run_air_verdict(cid, case.default_post_months)
        row = {
            "case_id": cid,
            "label": case.label,
            "event_date": case.event_date,
            "post_months": case.default_post_months,
            "run_id": out["id"],
            "verdict": out["verdict"],
            "signals": {
                k: {x: v.get(x) for x in ("point", "lo", "hi", "relative_pct", "relative_lo_pct",
                                           "relative_hi_pct", "placebo_p", "placebo_n", "n_donors")}
                for k, v in out["signals"].items()
            },
            "published": out.get("research_comparison", []),
        }
        rows.append(row)
        print(out["verdict"]["headline"])
        for sig, r in row["signals"].items():
            print(f"  {sig}: {r['relative_pct']:+.1f}%  90% [{r['relative_lo_pct']:+.1f}, {r['relative_hi_pct']:+.1f}] "
                  f"placebo p={r['placebo_p']:.3f}")
    payload = {"generated_by": "scripts.air_known_answers", "tuning_rule": "published values attached after estimation", "runs": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
