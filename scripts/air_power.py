"""Synthetic null/effect calibration for the *air inference layer*.

This does not validate the LAQN/AURN fetchers or weather model.  It stress-tests
the weekly panel -> donor selection -> ASCM -> symmetric cohort placebo -> verdict
path with known truth, and reports REAL / NOT_REAL / CAN'T_TELL rather than hiding
abstentions in a single accuracy number.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.app.air.analysis import analyse_stratum


def panel(seed: int, effect: float, stratum: str = "traffic"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2017-01-01", periods=150, freq="W-SUN")
    event = pd.Timestamp("2019-04-08")
    t = np.arange(len(idx))
    seasonal = 34 + 8*np.cos(2*np.pi*t/52) + 2*np.sin(2*np.pi*t/26)
    national = rng.normal(0, 1.2, len(idx)).cumsum() * 0.12
    latent = seasonal + national

    donors = {}
    dmeta = {}
    for j in range(32):
        s = latent + rng.normal(0, 2.5, len(idx)) + rng.normal(0, 2.5)
        code = f"D{j:02d}"
        donors[code] = pd.Series(s, idx)
        dmeta[code] = {"code": code, "name": code, "lat": 52 + j/100, "lon": -2.0,
                       "site_type": stratum, "source": "synthetic"}

    treated = {}
    tmeta = {}
    post = idx >= event
    for j in range(6):
        s = latent + rng.normal(0, 2.1, len(idx)) + rng.normal(0, 1.4)
        s = s + effect * post.astype(float)
        code = f"T{j:02d}"
        treated[code] = pd.Series(s, idx)
        tmeta[code] = {"code": code, "name": code, "lat": 51.5, "lon": -0.1,
                       "site_type": stratum, "source": "synthetic"}
    return treated, donors, dmeta, tmeta, event.date().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--effect", type=float, default=-6.0, help="Injected µg/m³ post-policy effect")
    ap.add_argument("--out", default="showcase/air_power.json")
    args = ap.parse_args()

    rows = []
    for truth, eff in (("null", 0.0), ("effect", args.effect)):
        for seed in range(args.seeds):
            tr, dr, dm, tm, event = panel(seed, eff)
            got = analyse_stratum(tr, dr, event, 6, "traffic", dm, tm)
            if got is None:
                rows.append({"truth": truth, "seed": seed, "status": "CANT_TELL", "reason": "analysis returned no panel"})
                continue
            result, _chart, _donors, verdict = got
            rows.append({"truth": truth, "seed": seed, "status": verdict.status,
                         "point": result["point"], "lo": result["lo"], "hi": result["hi"],
                         "placebo_p": result["placebo_p"]})

    summary = {}
    for truth in ("null", "effect"):
        xs = [x for x in rows if x["truth"] == truth]
        counts = {s: sum(x["status"] == s for x in xs) for s in ("REAL", "NOT_REAL", "CANT_TELL")}
        n = len(xs)
        summary[truth] = {
            "n": n, "counts": counts,
            "real_rate": counts["REAL"] / n if n else None,
            "abstention_rate": counts["CANT_TELL"] / n if n else None,
            "false_real_rate": (counts["REAL"] / n if n else None) if truth == "null" else None,
            "detection_rate": (counts["REAL"] / n if n else None) if truth == "effect" else None,
        }
    payload = {"injected_effect_ugm3": args.effect, "summary": summary, "runs": rows}
    p = Path(args.out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(payload, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
