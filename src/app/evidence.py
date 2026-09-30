"""Weigh optical and radar evidence for a change side by side.

Indices from one sensor (NDVI/NDWI/NBR from Sentinel-2; VV/VH/RATIO from
Sentinel-1) are strongly correlated with each other, so a sensor contributes
at most ONE p-value: its primary signal for the change type. The two sensors
are then combined with a Bonferroni correction over the sensors that were
actually available, which is conservative by construction.

Statuses per sensor:
  supportive     the signal on its own gets REAL from verdict.decide (every gate:
                 donors, pre bins, pre-fit, controls shifted, interval, minimum
                 effect, in-space and in-time placebos)
  contradicting  interval excludes zero on the opposite side
  neutral        anything else
  unavailable    signal missing or fewer than MIN_POST_BINS post-event bins
"""
from __future__ import annotations

from dataclasses import dataclass

from .verdict import MIN_POST_BINS, SIGNAL_WORDS, SIGNALS, SignalResult, decide

RADAR = ("VV", "VH", "RATIO")


@dataclass
class Evidence:
    optical: SignalResult | None
    radar: SignalResult | None
    optical_status: str      # supportive | contradicting | neutral | unavailable
    radar_status: str
    p_combined: float | None
    agreement: str           # both | optical-only | radar-only | none | conflict
    sentence: str            # one plain-English sentence for the verdict page


def status_of(r: SignalResult | None, change_type: str = "other") -> str:
    """'supportive' only when this signal on its own would get a REAL from
    `verdict.decide`: the same donor, pre-bin, pre-fit, controls-shifted, placebo
    and in-time-placebo gates the verdict applies. Anything weaker let the page
    say "optical and radar agree" under a CAN'T TELL (REDTEAM E9)."""
    if r is None or r.n_post < MIN_POST_BINS:
        return "unavailable"
    if decide(r, change_type, "").status == "REAL":
        return "supportive"
    if r.opposite_direction():
        return "contradicting"
    return "neutral"


def _mag(v: float, signal: str) -> str:
    """Unsigned magnitude: indices to 2 dp, radar to 1 dp (unit added by the caller)."""
    return f"{abs(v):.1f}" if signal in RADAR else f"{abs(v):.2f}"


def _signed(v: float, signal: str) -> str:
    """Signed value with a unicode minus, no unit."""
    d = 1 if signal in RADAR else 2
    s = f"{v:.{d}f}"
    return s.replace("-", "−")


def _moved(r: SignalResult) -> str:
    """'greenness (NDVI) fell by 0.20' / 'radar backscatter (VH) rose by 1.5 dB'."""
    word = SIGNAL_WORDS[r.signal]
    direction = "fell" if r.point < 0 else "rose"
    unit = " dB" if r.signal in RADAR else ""
    return f"{word} {direction} by {_mag(r.point, r.signal)}{unit}"


def _inconclusive(r: SignalResult) -> str:
    """'radar backscatter (VH) −0.3 dB, interval −1.2 to 0.6'."""
    word = SIGNAL_WORDS[r.signal]
    unit = " dB" if r.signal in RADAR else ""
    return (f"{word} {_signed(r.point, r.signal)}{unit}, interval "
            f"{_signed(r.lo, r.signal)} to {_signed(r.hi, r.signal)}")


def _one_sided(shows: str, shows_r: SignalResult, other: str, other_r: SignalResult | None,
               other_status: str) -> str:
    head = f"{shows} shows the change ({_moved(shows_r)})"
    if other_status == "unavailable" or other_r is None:
        return f"{head}; {other} has too few observations to weigh in."
    return f"{head}; {other} is inconclusive ({_inconclusive(other_r)})."


def _sentence(ev_optical: SignalResult | None, ev_radar: SignalResult | None,
              o_status: str, r_status: str, agreement: str, p_comb: float | None) -> str:
    if agreement == "both":
        return (f"Optical and radar agree: {_moved(ev_optical)} and {_moved(ev_radar)} "
                f"(combined placebo p = {p_comb:.2f}).")
    if agreement == "optical-only":
        return _one_sided("Optical", ev_optical, "radar", ev_radar, r_status)
    if agreement == "radar-only":
        return _one_sided("Radar", ev_radar, "optical", ev_optical, o_status)
    if agreement == "conflict":
        return (f"Optical and radar disagree: {_moved(ev_optical)} while {_moved(ev_radar)}; "
                "treat the result with caution.")
    moved = [r for r in (ev_optical, ev_radar)
             if r is not None and r.n_post >= MIN_POST_BINS and r.excludes_zero_in_direction()]
    if moved:
        # A signal can move clearly yet fail a gate (effect below the minimum, a
        # poor pre-event fit, too few controls). Saying "no change" there would
        # be false, so give the numbers and leave the reason to the verdict.
        return ("Neither optical nor radar passes every test on its own: "
                + "; ".join(_inconclusive(r) for r in moved) + ".")
    return "Neither optical nor radar shows a change beyond what the controls did."


def assess(results: dict[str, SignalResult], change_type: str) -> Evidence:
    """Pick each sensor's primary signal for `change_type`, grade it, and combine.

    `results` is keyed by signal name, as run.py builds it. Only the two primary
    signals are consulted; secondary indices from the same sensor are ignored
    because they are not independent evidence.
    """
    spec = SIGNALS.get(change_type, SIGNALS["other"])
    optical_sig = spec[0]
    radar_sig = spec[2][0][0]
    optical = results.get(optical_sig)
    radar = results.get(radar_sig)

    o_status = status_of(optical, change_type)
    r_status = status_of(radar, change_type)

    available = [r for r, s in ((optical, o_status), (radar, r_status)) if s != "unavailable"]
    k = len(available)
    p_comb = min(1.0, k * min(r.placebo_p for r in available)) if k else None

    statuses = {o_status, r_status}
    if o_status == "supportive" and r_status == "supportive":
        agreement = "both"
    elif "supportive" in statuses and "contradicting" in statuses:
        agreement = "conflict"
    elif o_status == "supportive":
        agreement = "optical-only"
    elif r_status == "supportive":
        agreement = "radar-only"
    else:
        agreement = "none"

    sentence = _sentence(optical, radar, o_status, r_status, agreement, p_comb)
    return Evidence(optical=optical, radar=radar, optical_status=o_status, radar_status=r_status,
                    p_combined=p_comb, agreement=agreement, sentence=sentence)
