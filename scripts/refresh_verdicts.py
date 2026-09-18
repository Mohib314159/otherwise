"""Re-apply the verdict rules to stored runs (showcase/*.json or data/runs/*.json)
without refetching anything. Use after a wording or threshold change."""
from __future__ import annotations

import glob
import json
import sys
from datetime import date

from src.app.verdict import SignalResult, decide


def refresh(path: str) -> str:
    r = json.load(open(path))
    lead = r["verdict"]["lead_signal"]
    if lead not in r["signals"]:
        return r["verdict"]["status"]
    s = r["signals"][lead]
    sr = SignalResult(**{k: s[k] for k in SignalResult.__dataclass_fields__ if k in s})
    ev = date.fromisoformat(r["event_date"])
    post_label = f"in the {r['post_months']} months after {ev.strftime('%-d %b %Y')}"
    v = decide(sr, r["change_type"], post_label)
    r["verdict"] = {"status": v.status, "headline": v.headline, "statement": v.statement,
                    "reasons": v.reasons, "lead_signal": v.lead_signal}
    json.dump(r, open(path, "w"))
    return v.status


if __name__ == "__main__":
    paths = sys.argv[1:] or glob.glob("showcase/*.json")
    for p in paths:
        if p.endswith(("index.json", "track_record.json")) or "_before" in p or "_after" in p:
            continue
        print(p, refresh(p))
