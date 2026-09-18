"""Re-apply the verdict rules to stored runs (showcase/*.json or data/runs/*.json)
without refetching anything. Use after a wording or threshold change."""
from __future__ import annotations

import glob
import json
import sys
from datetime import date

from src.app.verdict import SIGNALS, SignalResult, combine
from src.app.evidence import assess


def refresh(path: str) -> str:
    r = json.load(open(path))
    lead = r["verdict"]["lead_signal"]
    if lead not in r["signals"]:
        return r["verdict"]["status"]
    s = r["signals"][lead]
    sr = SignalResult(**{k: s[k] for k in SignalResult.__dataclass_fields__ if k in s})
    ev = date.fromisoformat(r["event_date"])
    post_label = f"in the {r['post_months']} months after {ev.strftime('%-d %b %Y')}"
    primary = SIGNALS.get(r["change_type"], SIGNALS["other"])[0]
    opt = None
    if primary in r["signals"] and primary != lead:
        o = r["signals"][primary]
        opt = SignalResult(**{k: o[k] for k in SignalResult.__dataclass_fields__ if k in o})
    v = combine(sr, opt, r["change_type"], post_label)
    r["verdict"] = {"status": v.status, "headline": v.headline, "statement": v.statement,
                    "reasons": v.reasons, "lead_signal": v.lead_signal}
    allres = {k: SignalResult(**{kk: x[kk] for kk in SignalResult.__dataclass_fields__ if kk in x})
              for k, x in r["signals"].items()}
    ev = assess(allres, r["change_type"])
    r["evidence"] = {"agreement": ev.agreement, "optical": ev.optical_status, "radar": ev.radar_status,
                     "p_combined": ev.p_combined, "sentence": ev.sentence}
    json.dump(r, open(path, "w"))
    return v.status


if __name__ == "__main__":
    paths = sys.argv[1:] or glob.glob("showcase/*.json")
    for p in paths:
        if p.endswith(("index.json", "track_record.json")) or any(t in p for t in ("_before", "_after", "_frames", "_change")):
            continue
        print(p, refresh(p))
