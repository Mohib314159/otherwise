"""Turn an effect estimate, its interval and the placebo checks into a verdict.

Three answers only: REAL, NOT_REAL, CANT_TELL. The rules are explicit so a
professional can disagree with a threshold rather than with a black box.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Smallest change we call meaningful, per signal. Normalised indices are on a
# -1..1 scale; radar is in dB. These are design thresholds, not measurements.
MIN_EFFECT = {"NDVI": 0.05, "NDWI": 0.05, "NBR": 0.05, "VV": 1.0, "VH": 1.0, "RATIO": 1.0}
PRE_RMSE_FLOOR = {"NDVI": 0.02, "NDWI": 0.02, "NBR": 0.02, "VV": 0.3, "VH": 0.3, "RATIO": 0.3}
ALPHA = 0.10                 # 90% conformal interval
PLACEBO_P_MAX = 0.10         # in-space placebo must be at least this rare
MIN_DONORS = 20
MIN_PRE_BINS = 20
MIN_POST_BINS = 3

# change type -> (primary optical signal, expected sign, radar corroboration)
SIGNALS = {
    "clearing":     ("NDVI", -1, [("VH", -1)]),
    "regrowth":     ("NDVI", +1, [("VH", +1)]),
    "flood":        ("NDWI", +1, [("VV", -1)]),
    "burn":         ("NBR",  -1, [("VH", -1)]),
    "construction": ("NDVI", -1, [("VV", +1)]),
    "other":        ("NDVI",  0, [("VV",  0)]),
}
SIGNAL_WORDS = {"NDVI": "greenness (NDVI)", "NDWI": "surface water index (NDWI)",
                "NBR": "burn ratio (NBR)", "VV": "radar backscatter (VV)",
                "VH": "radar backscatter (VH)", "RATIO": "radar cross-ratio (VH/VV)"}


@dataclass
class SignalResult:
    signal: str
    sensor: str
    expected_sign: int
    point: float
    lo: float
    hi: float
    p_zero: float
    pre_rmse: float
    placebo_pre_rmse_median: float
    n_pre: int
    n_post: int
    n_donors: int
    placebo_p: float
    placebo_p_effect: float
    placebo_n: int
    time_placebo_flags: list[bool] = field(default_factory=list)
    placebo_effect_median: float = 0.0     # median post-event gap across placebo cells

    @property
    def min_effect(self) -> float:
        return MIN_EFFECT[self.signal]

    @property
    def pre_fit_ok(self) -> bool:
        """A poor pre-event fit blocks a verdict unless the effect dwarfs it.

        The conformal interval and the RMSPE-ratio placebo already scale with
        the pre-event residuals, so this absolute gate is a safety net for
        marginal effects, not a veto on an effect 4x larger than the fit error.
        """
        loose = self.pre_rmse <= max(1.5 * self.placebo_pre_rmse_median, PRE_RMSE_FLOOR[self.signal])
        return loose or abs(self.point) >= 4.0 * self.pre_rmse

    def excludes_zero_in_direction(self) -> bool:
        s = self.expected_sign
        if s > 0:
            return self.lo > 0
        if s < 0:
            return self.hi < 0
        return self.lo > 0 or self.hi < 0

    def rules_out_meaningful(self) -> bool:
        m = self.min_effect
        s = self.expected_sign
        if s > 0:
            return self.hi < m
        if s < 0:
            return self.lo > -m
        return self.lo > -m and self.hi < m

    def opposite_direction(self) -> bool:
        s = self.expected_sign
        return (s > 0 and self.hi < 0) or (s < 0 and self.lo > 0)


@dataclass
class Verdict:
    status: str                # REAL | NOT_REAL | CANT_TELL
    headline: str
    statement: str
    reasons: list[str]
    lead_signal: str


def _fmt(v: float, signal: str) -> str:
    return f"{abs(v):.1f} dB" if signal in ("VV", "VH", "RATIO") else f"{abs(v):.2f}"


def _signed(v: float, signal: str) -> str:
    unit = " dB" if signal in ("VV", "VH", "RATIO") else ""
    d = 1 if unit else 2
    return f"{v:+.{d}f}{unit}".replace("+", "+").replace("-", "\u2212")


def decide(r: SignalResult, change_type: str, post_label: str) -> Verdict:
    reasons: list[str] = []
    word = SIGNAL_WORDS[r.signal]
    direction = "fell" if r.point < 0 else "rose"
    core = (f"{word[0].upper() + word[1:]} {direction} by {_fmt(r.point, r.signal)} relative to the "
            f"control trajectory {post_label} (90% interval {_signed(r.lo, r.signal)} to {_signed(r.hi, r.signal)}).")
    k = max(int(round(r.placebo_p * (r.placebo_n + 1))) - 1, 0)
    placebo = (f"Of {r.placebo_n} untouched cells given the same test, "
               f"{k} showed a divergence this large (placebo p = {r.placebo_p:.2f}).")

    # --- can we say anything at all? ---
    if r.n_donors < MIN_DONORS:
        reasons.append(f"only {r.n_donors} usable control cells (need {MIN_DONORS})")
    if r.n_pre < MIN_PRE_BINS:
        reasons.append(f"only {r.n_pre} clear observation periods before the event (need {MIN_PRE_BINS})")
    if r.n_post < MIN_POST_BINS:
        reasons.append(f"only {r.n_post} clear observation periods after the event (need {MIN_POST_BINS})")
    if not r.pre_fit_ok:
        reasons.append("the control trajectory does not track the area well enough before the event "
                       f"(pre-event error {_fmt(r.pre_rmse, r.signal)} vs typical {_fmt(r.placebo_pre_rmse_median, r.signal)})")
    if abs(r.placebo_effect_median) >= r.min_effect and np.sign(r.placebo_effect_median) == np.sign(r.point):
        reasons.append("the control cells themselves shifted by "
                       f"{_signed(r.placebo_effect_median, r.signal)} at the event date, so the event "
                       "probably extends beyond the 12 km control ring and no untouched control exists here")
    if r.lo == r.hi:
        reasons.append("no effect size was compatible with the data under the conformal test; "
                       "the post-event behaviour does not look like a simple shift")
    if reasons:
        return Verdict("CANT_TELL", "Can't tell", core + " " + placebo + " But: " + "; ".join(reasons) + ".",
                       reasons, r.signal)

    # --- evidence for the claimed change ---
    if r.excludes_zero_in_direction() and abs(r.point) >= r.min_effect:
        if r.placebo_p <= PLACEBO_P_MAX:
            if any(r.time_placebo_flags):
                reasons.append("a fake event date in the pre-period also produced a 'significant' effect; "
                               "treat the confidence as lower than the interval suggests")
            return Verdict("REAL", "Real change", core + " " + placebo, reasons, r.signal)
        reasons.append(f"the placebo check found divergences this large in untouched cells too often "
                       f"(placebo p = {r.placebo_p:.2f})")
        return Verdict("CANT_TELL", "Can't tell", core + " " + placebo + " " + reasons[-1].capitalize() + ".",
                       reasons, r.signal)
    if r.opposite_direction():
        reasons.append(f"the area moved in the opposite direction to a {change_type} event")
        return Verdict("NOT_REAL", "Not what was claimed", core + " " + placebo + " " +
                       "That is the opposite of what the claimed event would do.", reasons, r.signal)
    if r.rules_out_meaningful():
        reasons.append(f"a change of at least {_fmt(r.min_effect, r.signal)} in {word} is ruled out by the interval")
        return Verdict("NOT_REAL", "No real change", core + " " + placebo + " "
                       "The interval rules out a meaningful change beyond what the controls did.",
                       reasons, r.signal)
    reasons.append("the interval is too wide to rule a meaningful change in or out")
    return Verdict("CANT_TELL", "Can't tell", core + " " + placebo + " " +
                   "The interval is too wide to rule a meaningful change in or out.", reasons, r.signal)
