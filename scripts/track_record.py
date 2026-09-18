"""Build showcase/track_record.json from every showcase entry with a documented
expected answer. Sites without a source are listed but never counted."""
from __future__ import annotations

import json
import os


def main():
    idx = json.load(open("showcase/index.json"))
    rows, n = [], 0
    hits = false_alarms = misses = cant = 0
    for e in idx:
        p = f"showcase/{e['id']}.json"
        if not os.path.exists(p):
            continue
        r = json.load(open(p))
        lead = r["verdict"]["lead_signal"]
        sig = r["signals"].get(lead, {})
        row = {"id": r["id"], "label": e["label"], "type": r["change_type"], "expected": e.get("expected"),
               "confirmed": bool(e.get("confirmed")), "status": r["verdict"]["status"],
               "headline": r["verdict"]["headline"], "signal": lead,
               "effect": sig.get("point"), "lo": sig.get("lo"), "hi": sig.get("hi"),
               "placebo_p": sig.get("placebo_p"), "source": e.get("source") or None,
               "event_date": r["event_date"]}
        counted = bool(e.get("expected")) and (bool(e.get("source")) or e.get("expected") == "NOT_REAL")
        row["counted"] = counted
        if counted:
            n += 1
            st = row["status"]
            if st == "CANT_TELL":
                cant += 1
            elif st == e["expected"]:
                hits += 1
            elif e["expected"] == "NOT_REAL":
                false_alarms += 1
            else:
                misses += 1
        rows.append(row)
    summary = {"n": n, "hits": hits, "misses": misses, "false_alarms": false_alarms, "cant_tell": cant,
               "note": "Expected answers come from the documented sources; sites marked unconfirmed are "
                       "candidates awaiting confirmation. No-change sites rest on the absence of any documented event."}
    json.dump({"runs": rows, "summary": summary if n else None}, open("showcase/track_record.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
