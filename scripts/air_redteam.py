"""Deterministic adversarial checks for the ground-NO2 causal pipeline.

These are not real ULEZ results.  They are synthetic attacks designed to catch
specific false-positive mechanisms before a live run is trusted.  The final
"coincident_local_shock" case is intentionally marked as an identification
limit: an unmeasured London-only shock beginning on the exact policy date is not
separable from the policy using these time series alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.app.air.analysis import AIR_PROTOCOL, analyse_stratum


def panel(seed: int = 123, n_donors: int = 24):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-04-10", periods=170, freq="W-SUN")
    event = pd.Timestamp("2019-04-08")
    common = 42 + 5 * np.sin(2 * np.pi * np.arange(len(idx)) / 52.18)
    donors, dm = {}, {}
    for j in range(n_donors):
        code = f"D{j:02d}"
        donors[code] = pd.Series(common + rng.normal(0, 1.0, len(idx)) + rng.normal(0, 2), idx)
        dm[code] = {"code": code, "name": code, "lat": 52 + j*.01, "lon": -2,
                    "site_type": "Urban Traffic", "stratum": "traffic", "source": "synthetic"}
    base = np.mean(np.vstack([donors[f"D{j:02d}"].to_numpy() for j in range(4)]), axis=0)
    treated, tm = {}, {}
    for j in range(3):
        code = f"T{j}"
        treated[code] = pd.Series(base + rng.normal(0, .5, len(idx)), idx)
        tm[code] = {"code": code, "name": code, "lat": 51.5, "lon": -.1,
                    "site_type": "Roadside", "stratum": "traffic", "source": "synthetic"}
    return treated, donors, dm, tm, idx, event


def attack(name: str):
    tr, dr, dm, tm, idx, event = panel()
    post = idx >= event
    if name == "null":
        pass
    elif name == "true_minus6":
        for c in tr: tr[c].loc[post] -= 6
    elif name == "monitor_dropout":
        tr["T0"] += 12
        tr["T0"].loc[post] = np.nan
    elif name == "one_station_drives":
        tr["T0"].loc[post] -= 18
    elif name == "preexisting_decline":
        lead = idx >= event - pd.Timedelta(weeks=13)
        ramp = -0.55 * np.arange(lead.sum())
        for c in tr: tr[c].loc[lead] += ramp
    elif name == "national_common_shock":
        for c in tr: tr[c].loc[post] -= 6
        for c in dr: dr[c].loc[post] -= 6
    elif name == "coincident_local_shock":
        for c in tr: tr[c].loc[post] -= 6
    else:
        raise ValueError(name)
    got = analyse_stratum(tr, dr, event.date().isoformat(), 3, "traffic", dm, tm)
    if got is None:
        return {"attack": name, "status": "CANT_TELL", "point": None, "details": {}}
    r, _chart, _donors, v = got
    return {"attack": name, "status": v.status, "point": round(float(r["point"]), 3),
            "details": {"pretrend": r.get("pretrend"), "jackknife": r.get("treated_jackknife"),
                        "placebo_p": r.get("placebo_p"), "placebo_p_effect": r.get("placebo_p_effect")}}


def main():
    expected = {
        "null": {"NOT_REAL", "CANT_TELL"},
        "true_minus6": {"REAL"},
        "monitor_dropout": {"NOT_REAL", "CANT_TELL"},
        "one_station_drives": {"CANT_TELL"},
        "preexisting_decline": {"CANT_TELL"},
        "national_common_shock": {"NOT_REAL", "CANT_TELL"},
    }
    names = list(expected) + ["coincident_local_shock"]
    rows = [attack(n) for n in names]
    failures = []
    for row in rows:
        name = row["attack"]
        if name in expected and row["status"] not in expected[name]:
            failures.append({"attack": name, "got": row["status"], "expected": sorted(expected[name])})
    payload = {
        "protocol": AIR_PROTOCOL,
        "scope": "synthetic adversarial regression checks; not ULEZ validation",
        "known_identification_limit": "coincident_local_shock",
        "passes": len(expected) - len(failures), "checks": len(expected),
        "failures": failures, "runs": rows,
    }
    out = Path("showcase/air_redteam.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    for r in rows:
        print(f"{r['attack']:26s} {r['status']:10s} point={r['point']}")
    print(f"identifiable attacks passed: {payload['passes']}/{payload['checks']}")
    print("coincident_local_shock is a documented residual identification limit, not a pass/fail gate")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
