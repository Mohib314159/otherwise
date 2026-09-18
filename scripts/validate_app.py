"""Reproduce the app's validation evidence in one command and write
showcase/validation.md: the null-power table from scripts/power.py plus the
known-answer track record from scripts/track_record.py.

    python -m scripts.validate_app
    python -m scripts.validate_app --cache data/cache/5f0bbacbdf08fe51 --units 8

Every number here comes from those two functions; nothing is typed by hand.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from scripts import power, track_record


def _default_cache_dir() -> str:
    """Newest cache directory with the most donor cells and the longest window."""
    candidates = []
    for d in sorted(glob.glob("data/cache/*/")):
        meta_path = os.path.join(d, "meta.json")
        if not os.path.exists(meta_path):
            continue
        meta = json.load(open(meta_path))
        n_donors = meta.get("summary", {}).get("n_donor_cells", 0)
        start = datetime.fromisoformat(meta["start"])
        end = datetime.fromisoformat(meta["end"])
        window_days = (end - start).days
        mtime = os.path.getmtime(meta_path)
        candidates.append((n_donors, window_days, mtime, d.rstrip("/")))
    if not candidates:
        raise SystemExit("no cached area under data/cache/ to validate against")
    max_n = max(c[0] for c in candidates)
    candidates = [c for c in candidates if c[0] == max_n]
    max_window = max(c[1] for c in candidates)
    candidates = [c for c in candidates if c[1] == max_window]
    candidates.sort(key=lambda c: c[2])  # newest last
    return candidates[-1][3]


def _git_short_hash() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or ".",
                              capture_output=True, text=True, check=True)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


EFFECT_GRIDS = {
    "NDVI": (0.0, -0.05, -0.10, -0.20),
    "VH": (0.0, -0.5, -1.0, -2.0),
}


def _power_table(rows: list[dict]) -> str:
    lines = ["| Signal | Injected effect | Detected | Rate | Can't tell |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['signal']} | {r['effect']:+.2f} | {r['detected']}/{r['n']} | "
                     f"{r['rate']:.0%} | {r['cant_tell']}/{r['n']} |")
    return "\n".join(lines)


def _known_answer_table(track: dict) -> str:
    runs = track["runs"]
    lines = ["| Site | Type | Expected | Verdict | Lead signal | Effect (90% interval) | Placebo p | Confirmed | Source |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        if r["effect"] is not None and r["lo"] is not None and r["hi"] is not None:
            effect = f"{r['effect']:+.2f} ({r['lo']:+.2f} to {r['hi']:+.2f})"
        else:
            effect = "-"
        p = f"{r['placebo_p']:.2f}" if r["placebo_p"] is not None else "-"
        confirmed = "yes" if r["confirmed"] else "no"
        source = f"[link]({r['source']})" if r.get("source") else "-"
        lines.append(f"| {r['label']} | {r['type']} | {r['expected']} | {r['status']} | "
                     f"{r['signal']} | {effect} | {p} | {confirmed} | {source} |")
    return "\n".join(lines)


def build(cache_dir: str, n_units: int, signals: list[str]) -> str:
    power_rows = []
    for sig in signals:
        power_rows.extend(power.main(cache_dir, signal=sig, n_units=n_units, effects=EFFECT_GRIDS[sig]))

    track_record.main()
    track = json.load(open("showcase/track_record.json"))
    summary = track["summary"] or {"n": 0, "hits": 0, "misses": 0, "false_alarms": 0, "cant_tell": 0}

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    git_hash = _git_short_hash()

    parts = [
        "# Validation",
        "",
        f"Generated {date_str} at commit `{git_hash}` by `scripts/validate_app.py` "
        f"(cache `{cache_dir}`, {n_units} units per effect).",
        "",
        "## Null power test",
        "",
        _power_table(power_rows),
        "",
        "The injected-effect 0 row is the false-alarm rate.",
        "",
        "## Known-answer sites",
        "",
        _known_answer_table(track),
        "",
        f"{summary['n']} counted · {summary['hits']} correct · {summary['misses']} missed · "
        f"{summary['false_alarms']} false alarms · {summary['cant_tell']} can't tell",
        "",
        "Sites are candidates until confirmed; no number here is typed by hand.",
        "",
    ]
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="cache directory to run the power test against "
                                    "(default: newest with the most donor cells and the longest window)")
    ap.add_argument("--units", type=int, default=20, help="donor cells treated as fake units per effect size")
    ap.add_argument("--signals", default="NDVI,VH", help="comma-separated signals to test (NDVI, VH)")
    a = ap.parse_args(argv)

    cache_dir = a.cache or _default_cache_dir()
    signals = [s.strip() for s in a.signals.split(",") if s.strip()]
    unknown = [s for s in signals if s not in EFFECT_GRIDS]
    if unknown:
        raise SystemExit(f"no effect grid defined for signal(s): {unknown}")

    md = build(cache_dir, a.units, signals)
    os.makedirs("showcase", exist_ok=True)
    with open("showcase/validation.md", "w") as f:
        f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
