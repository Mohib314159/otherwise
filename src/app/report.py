"""Markdown report rendering for a run JSON.

Pure formatting over the schema `run_verdict()` (src/app/run.py) produces and
saves to disk — see showcase/*.json for real examples. This module never
computes anything statistical; it only reads fields that are already there
and writes "n/a" for anything missing. Do not invent numbers here.
"""
from __future__ import annotations

import json

RADAR_SIGNALS = {"VV", "VH", "RATIO"}

SIGNAL_LABEL = {
    "NDVI": "greenness (NDVI)",
    "NDWI": "surface water (NDWI)",
    "NBR": "burn ratio (NBR)",
    "VV": "radar VV backscatter (dB)",
    "VH": "radar VH backscatter (dB)",
    "RATIO": "radar VH/VV (dB)",
    "NO2_TRAFFIC": "roadside / traffic NO₂",
    "NO2_BACKGROUND": "urban-background NO₂",
}

CHANGE_TYPE_LABEL = {
    "clearing": "Clearing", "regrowth": "Regrowth", "flood": "Flood",
    "burn": "Burn", "construction": "Construction", "other": "Other",
}

RECEIPT_REASON_LABEL = {
    "cloud": "Cloud or shadow over the area",
    "haze": "Haze the classifier missed",
    "duplicate": "Duplicate acquisition (tile overlap, merged)",
    "orbit": "Different radar orbit (look angle)",
    "edge": "Radar swath edge",
    "read-error": "Could not read scene",
}

DATA_ATTRIBUTION = (
    "Contains modified Copernicus Sentinel data. Land cover \u00a9 ESA WorldCover. "
    "Terrain \u00a9 Copernicus DEM. Data via Microsoft Planetary Computer."
)

MAX_RECEIPT_ROWS = 100


def _na(v):
    return "n/a" if v is None else v


def _s(v):
    """String or 'n/a', never crashes on odd types."""
    return "n/a" if v is None else str(v)


def fmt_signal(signal: str | None, value) -> str:
    """Indices to 3 decimals, radar (dB) to 2 decimals. 'n/a' if missing."""
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if signal in RADAR_SIGNALS:
        return f"{v:.2f} dB"
    if signal in ("NO2_TRAFFIC", "NO2_BACKGROUND"):
        return f"{v:.2f} µg/m³"
    return f"{v:.3f}"


def fmt_p(value) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.3f}"


def interval_str(signal, lo, hi) -> str:
    if lo is None or hi is None:
        return "n/a"
    return f"{fmt_signal(signal, lo)} to {fmt_signal(signal, hi)}"


def placebo_k(p, n):
    """k = max(round(p*(n+1)) - 1, 0), or None if p/n are missing."""
    if not isinstance(p, (int, float)) or not isinstance(n, (int, float)):
        return None
    return max(round(float(p) * (float(n) + 1)) - 1, 0)


def _fmt_date(iso) -> str:
    if not iso or not isinstance(iso, str):
        return "n/a"
    try:
        from datetime import date as _date
        y, m, d = iso[:10].split("-")
        return _date(int(y), int(m), int(d)).strftime("%-d %b %Y")
    except Exception:
        return iso


def _escape_cell(v) -> str:
    return _s(v).replace("|", "\\|").replace("\n", " ")


def _effect_lines(signal_key, sig: dict) -> list[str]:
    lines = [
        f"- Signal: {SIGNAL_LABEL.get(signal_key, signal_key or 'n/a')}",
        f"- Point estimate: {fmt_signal(signal_key, sig.get('point'))}",
        f"- 90% interval: {interval_str(signal_key, sig.get('lo'), sig.get('hi'))}",
        f"- Minimum meaningful effect: {fmt_signal(signal_key, sig.get('min_effect'))}",
        f"- Pre-event fit error (RMSE): {fmt_signal(signal_key, sig.get('pre_rmse'))}",
        f"- Pre-event observations: {_na(sig.get('n_pre'))}",
        f"- Post-event observations: {_na(sig.get('n_post'))}",
        f"- Donor cells used: {_na(sig.get('n_donors'))}",
    ]
    return lines


def _placebo_lines(sig: dict) -> list[str]:
    """Both placebo statistics, each labelled for what it actually measures.

    `placebo_p` ranks the post/pre RMSPE ratio; `placebo_p_effect` ranks the
    signed post-event gap. The old single line reported the ratio rank under the
    label "cells with a divergence at least this large", which is the other
    quantity, and never showed p_effect at all (CRITIQUE #7).
    """
    p, n = sig.get("placebo_p"), sig.get("placebo_n")
    p_eff = sig.get("placebo_p_effect")
    lines = [
        f"- Placebo n (untouched cells tested): {_na(n)}",
        f"- Placebo p by fit ratio: {fmt_p(p)} "
        f"({_na(placebo_k(p, n))} of {_na(n)} cells whose post-event fit error grew, against their own "
        f"pre-event fit, at least as much as this area's did)",
    ]
    if isinstance(p_eff, (int, float)):
        lines.append(
            f"- Placebo p by gap size: {fmt_p(p_eff)} "
            f"({_na(placebo_k(p_eff, n))} of {_na(n)} cells whose post-event gap was at least as large, "
            f"in the same direction)")
    if sig.get("placebo_symmetric") is False:
        lines.append("- Note: these placebo units did not re-run the area's own control selection, so "
                     "this p-value is anti-conservative (see DECISIONS.md, CRITIQUE #4)")
    return lines


def _time_placebo_table(entries: list) -> list[str]:
    if not entries:
        return ["n/a"]
    lines = ["| Fake event date | Effect | 90% interval | Flagged |", "|---|---|---|---|"]
    for t in entries:
        if not isinstance(t, dict):
            continue
        signal_key = None  # unitless here; format falls back to 3dp, fine for a fake-date table
        eff = t.get("effect")
        lo, hi = t.get("lo"), t.get("hi")
        lines.append(
            f"| {_escape_cell(_fmt_date(t.get('date')))} | {fmt_signal(signal_key, eff)} | "
            f"{interval_str(signal_key, lo, hi)} | {'yes' if t.get('flagged') else 'no'} |"
        )
    return lines



def _render_air_report(run: dict) -> str:
    case = run.get("case") or {}
    verdict = run.get("verdict") or {}
    signals = run.get("signals") or {}
    donors = run.get("donors") or {}
    stations = run.get("stations") or {}
    data = run.get("data_summary") or {}
    research = run.get("research_comparison") or []
    limits = run.get("limits") or []
    method = run.get("method") or {}
    out = [f"# {run.get('label') or case.get('label') or 'Air-pollution analysis'}", ""]
    out += [case.get("description") or "Did NO₂ change more than it would have in comparable places?", ""]
    out += ["## Verdict", f"**{verdict.get('status', 'n/a')}** — {verdict.get('headline', 'n/a')}", "",
            str(verdict.get("statement") or "n/a"), ""]
    for key, sig in signals.items():
        out += [f"## {SIGNAL_LABEL.get(key, key)}",
                f"- Effect vs no-policy trajectory: {fmt_signal(key, sig.get('point'))}",
                f"- 90% interval: {interval_str(key, sig.get('lo'), sig.get('hi'))}",
                f"- Relative effect: {sig.get('relative_pct', 'n/a'):.2f}%" if isinstance(sig.get('relative_pct'), (int,float)) else "- Relative effect: n/a",
                f"- Counterfactual post-policy mean: {fmt_signal(key, sig.get('counterfactual_post_mean'))}",
                f"- Treated monitors: {_na(sig.get('treated_station_count'))}",
                f"- Control monitors used: {_na(sig.get('n_donors'))}",
                f"- Pre-event weekly observations: {_na(sig.get('n_pre'))}",
                f"- Post-event weekly observations: {_na(sig.get('n_post'))}",
                f"- Pre-fit RMSE: {fmt_signal(key, sig.get('pre_rmse'))}",
                f"- Symmetric in-space placebo p: {fmt_p(sig.get('placebo_p'))}",
                f"- Gap-size placebo p: {fmt_p(sig.get('placebo_p_effect'))}",
                f"- Placebo cohorts: {_na(sig.get('placebo_n'))}; cohort size {_na(sig.get('placebo_cohort_size'))}",
                ""]
        di = donors.get(key) or {}
        ss = di.get("stations") or []
        if ss:
            out += ["Controls with non-zero/selected ASCM pool membership:", "",
                    "| Station | Type | Source | Weight |", "|---|---|---|---:|"]
            weights = di.get("weights") or []
            for i, st in enumerate(ss):
                out.append(f"| {_escape_cell(st.get('name'))} | {_escape_cell(st.get('site_type'))} | "
                           f"{_escape_cell(st.get('source'))} | {(weights[i] if i < len(weights) else 0):.4f} |")
            out.append("")
    out += ["## Data and weather",
            f"- Sources: {_s(data.get('source'))}",
            f"- Pollutant: {_s(data.get('pollutant'))} ({_s(data.get('unit'))})",
            f"- Aggregation: {_s(data.get('aggregation'))}",
            f"- Usable treated monitors: {_na(stations.get('treated_usable'))}",
            f"- Usable non-London controls fetched: {_na(stations.get('control_usable'))}",
            "- Weather: ERA5; each monitor is normalised by a ridge model fitted and selected on pre-policy observations only.",
            "- Traffic/roadside and background monitors are analysed separately.", ""]
    if research:
        out += ["## Published-study comparison",
                "Published values are attached only after Otherwise has estimated the counterfactual; they are not estimator inputs.", "",
                "| Study | Published finding | Otherwise | Comparison |", "|---|---|---|---|"]
        for r in research:
            ours = "n/a"
            if isinstance(r.get("otherwise_pct"), (int,float)):
                ours = f"{r['otherwise_pct']:+.2f}% ({r.get('otherwise_ugm3', 0):+.2f} µg/m³)"
            out.append(f"| {_escape_cell(r.get('citation'))} | {_escape_cell(r.get('finding'))} | "
                       f"{_escape_cell(ours)} | {_escape_cell(r.get('comparison'))} |")
        out.append("")
    out += ["## Honest limits"]
    out += [f"- {_s(x)}" for x in limits] if limits else ["- n/a"]
    out.append("")
    out += ["## Receipts"]
    receipts = run.get("receipts") or []
    if receipts:
        out += ["| Date | Sensor | Reason | Detail |", "|---|---|---|---|"]
        for r in receipts[:MAX_RECEIPT_ROWS]:
            out.append(f"| {_escape_cell(_fmt_date(r.get('date')))} | {_escape_cell(r.get('sensor'))} | "
                       f"{_escape_cell(r.get('reason'))} | {_escape_cell(r.get('detail'))} |")
        if len(receipts) > MAX_RECEIPT_ROWS:
            out += ["", f"... and {len(receipts)-MAX_RECEIPT_ROWS} more."]
    else:
        out.append("n/a")
    out += ["", "## Method"]
    out += [f"- {k}: {_s(v)}" for k, v in method.items()] if method else ["- n/a"]
    out += ["", "## Reproduce", f"Run `{_s(run.get('id'))}`, created {_s(run.get('created'))}.", "",
            "POST to `/api/run`:", "", "```json",
            json.dumps({"domain":"air", "case_id":run.get("case_id"), "post_months":run.get("post_months"),
                        "label":run.get("label") or ""}, indent=2), "```", "",
            "---",
            "Ground NO₂: London Air Quality Network (Imperial ERG) and DEFRA UK-AIR AURN. "
            "Weather: ERA5 via Open-Meteo historical API. ULEZ boundary: TfL/GLA open data.", ""]
    return "\n".join(out)


def render_report(run: dict) -> str:
    run = run if isinstance(run, dict) else {}
    if run.get("domain") == "air":
        return _render_air_report(run)
    label = run.get("label") or "Drawn area"
    change_type = run.get("change_type")
    event_date = run.get("event_date")
    post_months = run.get("post_months")
    area = run.get("area") or {}
    verdict = run.get("verdict") or {}
    signals = run.get("signals") or {}
    charts = run.get("charts") or {}
    data_summary = run.get("data_summary") or {}
    receipts = run.get("receipts") or []
    method = run.get("method") or {}

    out: list[str] = []
    out.append(f"# {label}")
    out.append("")

    # ---- claim summary ------------------------------------------------
    ct_label = CHANGE_TYPE_LABEL.get(change_type, _s(change_type))
    claim = (
        f"{ct_label} claimed on {_fmt_date(event_date)}, evaluated over the "
        f"{_na(post_months)} months after. Area {_na(area.get('ha'))} ha, "
        f"{_s(area.get('landcover'))}, centroid {_na(area.get('lat'))}, {_na(area.get('lon'))}."
    )
    out.append(claim)
    out.append("")

    # ---- verdict --------------------------------------------------------
    out.append("## Verdict")
    out.append(f"**{_s(verdict.get('status'))}** \u2014 {_s(verdict.get('headline'))}")
    out.append("")
    out.append(_s(verdict.get("statement")))
    reasons = verdict.get("reasons") or []
    if reasons:
        out.append("")
        out.append("Reasons:")
        for r in reasons:
            out.append(f"- {_s(r)}")
    out.append("")

    # ---- effect (lead signal) -------------------------------------------
    lead_key = verdict.get("lead_signal")
    lead_sig = signals.get(lead_key) if lead_key else None
    out.append("## Effect")
    if lead_sig:
        out.extend(_effect_lines(lead_key, lead_sig))
    else:
        out.append("n/a")
    out.append("")

    # ---- placebo checks (lead signal) ------------------------------------
    out.append("## Placebo checks")
    if lead_sig:
        out.extend(_placebo_lines(lead_sig))
        out.append("")
        out.append("Fake event dates (tested in the pre-period):")
        out.extend(_time_placebo_table((charts.get(lead_key) or {}).get("time_placebos") or []))
    else:
        out.append("n/a")
    out.append("")

    # ---- other signals ----------------------------------------------------
    out.append("## Other signals")
    other_keys = [k for k in signals if k != lead_key]
    if other_keys:
        for k in other_keys:
            sig = signals.get(k) or {}
            out.append(f"### {SIGNAL_LABEL.get(k, k)}")
            out.extend(_effect_lines(k, sig))
            out.extend(_placebo_lines(sig))
            tp = (charts.get(k) or {}).get("time_placebos") or []
            if tp:
                out.append("")
                out.append("Fake event dates:")
                out.extend(_time_placebo_table(tp))
            out.append("")
    else:
        out.append("n/a")
        out.append("")

    # ---- data ---------------------------------------------------------------
    out.append("## Data")
    out.append(f"- Sentinel-2 scenes found / covering the area: {_na(data_summary.get('s2_scenes_found'))} / "
               f"{_na(data_summary.get('s2_scenes_covering'))}")
    out.append(f"- Sentinel-2 observations used: {_na(data_summary.get('s2_observations'))}")
    out.append(f"- Sentinel-1 scenes found / covering the area: {_na(data_summary.get('s1_scenes_found'))} / "
               f"{_na(data_summary.get('s1_scenes_covering'))}")
    out.append(f"- Sentinel-1 observations used: {_na(data_summary.get('s1_observations'))}")
    out.append(f"- Radar orbit: {_s(data_summary.get('s1_orbit'))}")
    out.append(f"- Donor cells: {_na(data_summary.get('n_donor_cells'))}")
    receipt_counts = data_summary.get("receipts") or {}
    if receipt_counts:
        parts = ", ".join(f"{_s(reason)}: {_s(n)}" for reason, n in receipt_counts.items())
        out.append(f"- Receipts by reason: {parts}")
    else:
        out.append("- Receipts by reason: n/a")
    out.append("")

    # ---- receipts -------------------------------------------------------------
    out.append("## Receipts")
    if receipts:
        out.append("| Date | Sensor | Reason | Detail |")
        out.append("|---|---|---|---|")
        for r in receipts[:MAX_RECEIPT_ROWS]:
            if not isinstance(r, dict):
                continue
            out.append(f"| {_escape_cell(_fmt_date(r.get('date')))} | {_escape_cell(r.get('sensor'))} | "
                       f"{_escape_cell(RECEIPT_REASON_LABEL.get(r.get('reason'), r.get('reason')))} | "
                       f"{_escape_cell(r.get('detail'))} |")
        if len(receipts) > MAX_RECEIPT_ROWS:
            out.append("")
            out.append(f"... and {len(receipts) - MAX_RECEIPT_ROWS} more.")
    else:
        out.append("n/a")
    out.append("")

    # ---- method -----------------------------------------------------------------
    out.append("## Method")
    if method:
        for k, v in method.items():
            out.append(f"- {k}: {_s(v)}")
    else:
        out.append("- n/a")
    out.append("")
    out.append("Counterfactual: augmented synthetic control (Ben-Michael, Feller & Rothstein 2021). "
               "Uncertainty: conformal inference (Chernozhukov, W\u00fcthrich & Zhu 2021).")
    out.append("")

    # ---- reproduce ----------------------------------------------------------------
    out.append("## Reproduce")
    out.append(f"Run `{_s(run.get('id'))}`, created {_s(run.get('created'))}.")
    out.append("")
    out.append("POST to `/api/run`:")
    out.append("")
    body = {
        "geojson": area.get("geojson"),
        "event_date": event_date,
        "change_type": change_type,
        "post_months": post_months,
        "label": run.get("label") or "",
    }
    out.append("```json")
    out.append(json.dumps(body, indent=2, default=str))
    out.append("```")
    out.append("")

    # ---- attribution ----------------------------------------------------------------
    out.append("---")
    out.append(DATA_ATTRIBUTION)
    out.append("")

    return "\n".join(out)
