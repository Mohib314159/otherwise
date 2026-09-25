"""End-to-end air-policy verdict: monitors -> weather -> ASCM -> permalink JSON."""
from __future__ import annotations

import hashlib
import json
import os
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from shapely.geometry import shape

from .analysis import AIR_MIN_DONORS, AIR_PROTOCOL, analyse_stratum, combine_air_verdict, AirVerdict
from .cases import AirCase, get_case
from .models import AirStation
from .providers import (AIR_CACHE_DIR, CachedHTTP, ERA5Provider, LAQNProvider, UKAirProvider,
                        difference_boundaries, fetch_ulez_boundary, hourly_to_daily, stations_in_boundary, weekly_mean)
from .weather import weather_normalise

RUNS_DIR = os.environ.get("APP_RUNS_DIR", "data/runs")
AIR_MAX_DONOR_FETCH = int(os.environ.get("APP_AIR_MAX_DONOR_FETCH", "40"))
AIR_MAX_TREATED = int(os.environ.get("APP_AIR_MAX_TREATED", "30"))
AIR_FETCH_WORKERS = int(os.environ.get("APP_AIR_FETCH_WORKERS", "8"))


def _json_safe(value):
    """Represent unavailable diagnostics/chart bands as JSON null, never NaN."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value

# Conservative screen for known UK clean-air-zone / LEZ launches.  These are
# not used as outcome data or as tuning targets; they only stop a control city's
# own policy discontinuity from masquerading as a London counterfactual.
_CONTROL_POLICIES = (
    {"name": "Birmingham Clean Air Zone", "date": "2021-06-01", "lat": 52.4862, "lon": -1.8904, "radius_km": 18},
    {"name": "Bath Clean Air Zone", "date": "2021-03-15", "lat": 51.3811, "lon": -2.3590, "radius_km": 12},
    {"name": "Portsmouth Clean Air Zone", "date": "2021-11-29", "lat": 50.8198, "lon": -1.0880, "radius_km": 12},
    {"name": "Oxford Zero Emission Zone pilot", "date": "2022-02-28", "lat": 51.7520, "lon": -1.2577, "radius_km": 10},
    {"name": "Bradford Clean Air Zone", "date": "2022-09-26", "lat": 53.7950, "lon": -1.7594, "radius_km": 15},
    {"name": "Bristol Clean Air Zone", "date": "2022-11-28", "lat": 51.4545, "lon": -2.5879, "radius_km": 14},
    {"name": "Tyneside Clean Air Zone", "date": "2023-01-30", "lat": 54.9783, "lon": -1.6178, "radius_km": 18},
    {"name": "Sheffield Clean Air Zone", "date": "2023-02-27", "lat": 53.3811, "lon": -1.4701, "radius_km": 15},
    {"name": "Glasgow Low Emission Zone enforcement", "date": "2023-06-01", "lat": 55.8642, "lon": -4.2518, "radius_km": 16},
)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a1, a2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dlat = a2 - a1; dlon = np.deg2rad(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(a1) * np.cos(a2) * np.sin(dlon / 2) ** 2
    return float(6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(max(1e-12, 1 - a))))


def _control_policy_contamination(station: AirStation, start: str, end: str) -> dict | None:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    for policy in _CONTROL_POLICIES:
        launch = date.fromisoformat(policy["date"])
        if not (a <= launch <= b):
            continue
        if _distance_km(station.lat, station.lon, policy["lat"], policy["lon"]) <= policy["radius_km"]:
            return {"station": station.as_dict(), "policy": policy["name"], "launch": policy["date"],
                    "reason": "control-city air policy launched inside registered analysis window"}
    return None


def fetch_case_boundary(case: AirCase, http: CachedHTTP | None = None) -> dict | None:
    http = http or CachedHTTP(AIR_CACHE_DIR)
    if case.zone_mode == "arcgis":
        if case.arcgis_layer is None:
            raise ValueError(f"{case.id} missing arcgis_layer")
        return fetch_ulez_boundary(case.arcgis_layer, http)
    if case.zone_mode == "difference":
        if case.include_layer is None or case.exclude_layer is None:
            raise ValueError(f"{case.id} missing include/exclude layers")
        return difference_boundaries(case.include_layer, case.exclude_layer, http)
    raise ValueError(f"unsupported air zone mode {case.zone_mode}")


def air_run_id(case_id: str, post_months: int | None = None) -> str:
    case = get_case(case_id)
    months = min(max(int(post_months or case.default_post_months), 1), 18)
    payload = (f"{AIR_PROTOCOL}|{case.id}|{case.event_date}|{months}|ground-no2|era5|ascm"
               f"|treated={AIR_MAX_TREATED}|donors={AIR_MAX_DONOR_FETCH}")
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _window(case: AirCase, post_months: int) -> tuple[str, str]:
    event = date.fromisoformat(case.event_date)
    start = date.fromisoformat(case.analysis_start) if case.analysis_start else event - relativedelta(years=case.pre_years)
    end = min(event + relativedelta(months=post_months), date.today())
    return start.isoformat(), end.isoformat()


def _outside_london(s: AirStation) -> bool:
    # Deliberately wider than Greater London: controls near the boundary can be
    # exposed to London traffic displacement and regional policy spillovers.
    lat0, lon0 = np.deg2rad(51.5074), np.deg2rad(-0.1278)
    lat, lon = np.deg2rad(s.lat), np.deg2rad(s.lon)
    a = np.sin((lat - lat0) / 2) ** 2 + np.cos(lat0) * np.cos(lat) * np.sin((lon - lon0) / 2) ** 2
    km = 6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return bool(km >= 60.0)


def _pick_candidates(stations: list[AirStation], stratum: str, event: date, n: int) -> list[AirStation]:
    xs = [s for s in stations if s.stratum == stratum and _outside_london(s) and s.active_on(event)]
    # Stable hash ordering prevents the donor-fetch budget from becoming
    # "alphabetically first cities only". Actual donor choice happens later on
    # pre-policy NO2 and uses no post-policy information.
    xs.sort(key=lambda s: hashlib.sha256(f"{event}:{stratum}:{s.code}".encode()).hexdigest())
    return xs[:n]


def _pick_treated(stations: list[AirStation], case: AirCase, boundary: dict | None) -> list[AirStation]:
    event = date.fromisoformat(case.event_date)
    xs = [s for s in stations if s.stratum in ("traffic", "background") and s.active_on(event)]
    if case.zone_mode in ("arcgis", "difference"):
        if boundary is None:
            raise ValueError(f"{case.zone_mode} air case requires a boundary")
        xs = stations_in_boundary(xs, boundary)
    else:
        raise ValueError(f"unsupported air zone mode {case.zone_mode}")
    # Prefer monitors open longest before the event if a large zone has more
    # sites than the live-run budget. Coverage is rechecked after data fetch.
    xs.sort(key=lambda s: (s.date_opened or date(2100, 1, 1), s.code))
    by = []
    for typ in ("traffic", "background"):
        by.extend([s for s in xs if s.stratum == typ][:AIR_MAX_TREATED])
    return by


def _compress_receipts(receipts: list[dict], station: AirStation) -> list[dict]:
    if not receipts:
        return []
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in receipts:
        if r.get("scope") == "station":
            # Station rejection details must survive observation compression.
            continue
        grouped.setdefault((str(r.get("reason", "other")), str(r.get("sensor", station.source))), []).append(r)
    out = [r for r in receipts if r.get("scope") == "station"]
    for (reason, sensor), rows in grouped.items():
        if len(rows) <= 3 and reason not in ("coverage", "invalid"):
            out.extend(rows)
            continue
        first = rows[0].get("date")
        out.append({"date": first, "sensor": f"{station.source} {station.code}", "reason": reason,
                    "count": sum(int(r.get("count", 1)) for r in rows),
                    "detail": f"{len(rows)} observations/days dropped for this reason"})
    return out


def _fetch_adjusted(station: AirStation, provider, era5: ERA5Provider,
                    start: str, end: str, event_date: str) -> tuple[AirStation, pd.Series | None, dict, list[dict]]:
    receipts: list[dict] = []
    try:
        hourly, rr = provider.hourly_no2(station, start, end)
        receipts.extend(rr)
    except Exception as e:
        return station, None, {}, [{"date": start, "sensor": f"{station.source} {station.code}",
                                    "reason": "read-error", "detail": f"NO2: {type(e).__name__}: {e}"[:180]}]
    daily, cov_receipts = hourly_to_daily(hourly, min_hours=19)
    for r in cov_receipts:
        r["sensor"] = f"{station.source} {station.code}"
    receipts.extend(cov_receipts)
    full_days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    daily = daily.reindex(full_days)
    event_ts = pd.Timestamp(event_date)
    pre_mask = daily.index < event_ts
    post_mask = daily.index >= event_ts
    pre_cov = float(daily.loc[pre_mask].notna().mean()) if pre_mask.any() else 0.0
    post_cov = float(daily.loc[post_mask].notna().mean()) if post_mask.any() else 0.0
    if daily.empty or pre_cov < 0.80 or post_cov < 0.80:
        receipts.append({"date": start, "sensor": f"{station.source} {station.code}", "reason": "coverage",
                         "scope": "station", "daily_pre_coverage": pre_cov, "daily_post_coverage": post_cov,
                         "detail": (f"station coverage pre={pre_cov:.1%}, post={post_cov:.1%}; "
                                    "need at least 80% valid daily means on both sides")})
        return station, None, {"daily_pre_coverage": pre_cov, "daily_post_coverage": post_cov}, _compress_receipts(receipts, station)
    try:
        weather = era5.daily(station.lat, station.lon, start, end)
        adj = weather_normalise(daily, weather, event_date)
    except Exception as e:
        receipts.append({"date": start, "sensor": f"ERA5 {station.code}", "reason": "read-error",
                         "detail": f"weather normalisation: {type(e).__name__}: {e}"[:180]})
        return station, None, {}, _compress_receipts(receipts, station)
    if not adj.applicable:
        receipts.append({"date": start, "sensor": f"ERA5 {station.code}", "reason": "coverage",
                         "detail": adj.note})
        return station, None, adj.metadata(), _compress_receipts(receipts, station)
    weekly = weekly_mean(adj.series, min_days=4)
    # W-SUN bins run Monday..Sunday.  If implementation is not a Monday, the
    # bin containing the event mixes pre- and post-policy days.  Drop that bin
    # for every station rather than assigning the mixture to either regime.
    event_ts = pd.Timestamp(event_date)
    if event_ts.weekday() != 0:
        mixed_week_end = event_ts.to_period("W-SUN").end_time.normalize()
        if mixed_week_end in weekly.index and pd.notna(weekly.loc[mixed_week_end]):
            weekly.loc[mixed_week_end] = np.nan
            receipts.append({"date": str(mixed_week_end.date()),
                             "sensor": f"{station.source} {station.code}",
                             "reason": "event-bin",
                             "detail": "weekly bin crossed the implementation date and was excluded"})
    wmeta = adj.metadata()
    wmeta.update({"daily_pre_coverage": pre_cov, "daily_post_coverage": post_cov})
    return station, weekly, wmeta, _compress_receipts(receipts, station)


def _fetch_many(stations: list[AirStation], provider, era5: ERA5Provider,
                start: str, end: str, event_date: str, progress, stage: str) -> tuple[dict, dict, list[dict]]:
    series: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}
    receipts: list[dict] = []
    total = max(len(stations), 1)
    with ThreadPoolExecutor(max_workers=max(1, AIR_FETCH_WORKERS)) as ex:
        futs = {ex.submit(_fetch_adjusted, s, provider, era5, start, end, event_date): s for s in stations}
        done = 0
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                station, weekly, wmeta, rr = fut.result()
            except Exception as e:
                weekly, wmeta, rr = None, {}, [{"date": start, "sensor": f"{s.source} {s.code}",
                                                "reason": "read-error", "detail": str(e)[:180]}]
                station = s
            done += 1
            progress(stage, done, total)
            receipts.extend(rr)
            meta[station.code] = {"station": station.as_dict(), "weather": wmeta,
                                  "usable": weekly is not None and not weekly.empty}
            if weekly is not None and not weekly.empty:
                series[station.code] = weekly
    return series, meta, receipts


def _research_comparison(case: AirCase, results: dict[str, dict], post_months: int) -> list[dict]:
    """Attach answer keys after inference; never imported by the estimator."""
    out = []
    for pub in case.published:
        row = pub.as_dict()
        if pub.stratum and pub.stratum in results:
            r = results[pub.stratum]
            row["otherwise_pct"] = round(float(r["relative_pct"]), 2)
            row["otherwise_pct_interval"] = [round(float(r["relative_lo_pct"]), 2),
                                               round(float(r["relative_hi_pct"]), 2)]
            row["otherwise_ugm3"] = round(float(r["point"]), 2)
            row["otherwise_ugm3_interval"] = [round(float(r["lo"]), 2), round(float(r["hi"]), 2)]
            # Never call a 12-month estimate a replication of a published
            # 3-month result.  The paper remains useful context, but the
            # quantitative inside/outside check is only meaningful at the same
            # registered horizon.
            horizon_months = None
            if pub.horizon:
                import re as _re
                m = _re.search(r"(\d+)\s*months?", pub.horizon, _re.I)
                horizon_months = int(m.group(1)) if m else None
            if horizon_months is not None and horizon_months != int(post_months):
                row["comparison"] = (f"published horizon is {horizon_months} months; this Otherwise run is "
                                     f"{post_months} months, so no quantitative replication score is assigned")
            elif pub.point_pct is not None:
                lo, hi = sorted(row["otherwise_pct_interval"])
                row["comparison"] = "published estimate inside Otherwise 90% interval" if lo <= pub.point_pct <= hi else "published estimate outside Otherwise 90% interval"
            else:
                row["comparison"] = "published study reported no detectable effect; compare with Otherwise verdict above"
        out.append(row)
    return out


def run_air_verdict(case_id: str, post_months: int | None = None, label: str = "",
                    progress=lambda s, d, t: None, save: bool = True,
                    runs_dir: str = RUNS_DIR) -> dict:
    t0 = time.time()
    case = get_case(case_id)
    if not case.supported:
        raise ValueError(f"Air case {case_id} is not enabled")
    months = int(post_months or case.default_post_months)
    months = min(max(months, 1), 18)
    start, end = _window(case, months)
    rid = air_run_id(case.id, months)
    result_path = Path(runs_dir) / f"{rid}.json"
    if save and result_path.exists():
        # A permalink is a saved observation, not a mutable latest-data alias.
        return json.loads(result_path.read_text(encoding="utf-8"))
    http = CachedHTTP(AIR_CACHE_DIR)
    laqn, aurn, era5 = LAQNProvider(http), UKAirProvider(http), ERA5Provider(http)

    progress("air: ULEZ boundary", 0, 1)
    boundary = fetch_case_boundary(case, http)
    progress("air: London monitor metadata", 0, 1)
    london_sites = laqn.sites("NO2")
    treated_sites = _pick_treated(london_sites, case, boundary)
    if not treated_sites:
        raise RuntimeError("No active LAQN NO2 monitors were found inside this policy zone")

    progress("air: national control metadata", 0, 1)
    national_sites = aurn.sites()
    event = date.fromisoformat(case.event_date)
    policy_exclusions = []
    clean_national = []
    for station in national_sites:
        hit = _control_policy_contamination(station, start, end)
        if hit is not None:
            policy_exclusions.append(hit)
        else:
            clean_national.append(station)
    donor_candidates = []
    # Exact-size placebo cohorts consume `treated_n` controls before constructing
    # their own donor pool.  Fetch enough same-type candidates that a large outer-
    # London treated cohort does not become non-identifiable merely because of a
    # fixed network budget.  The cap prevents an interactive run from exploding.
    for typ in ("traffic", "background"):
        treated_n = sum(s.stratum == typ for s in treated_sites)
        fetch_n = min(70, max(AIR_MAX_DONOR_FETCH, treated_n + AIR_MIN_DONORS + 4))
        donor_candidates.extend(_pick_candidates(clean_national, typ, event, fetch_n))
    if not donor_candidates:
        raise RuntimeError("No non-London AURN monitor metadata could be resolved")

    treated_series, treated_meta, receipts_t = _fetch_many(
        treated_sites, laqn, era5, start, end, case.event_date, progress, "air: London NO2 + ERA5")
    donor_series, donor_meta_full, receipts_d = _fetch_many(
        donor_candidates, aurn, era5, start, end, case.event_date, progress, "air: control NO2 + ERA5")

    # Flatten metadata for the analysis layer; it does not need weather model
    # internals to choose controls.
    treated_station_meta = {c: x["station"] for c, x in treated_meta.items()}
    donor_station_meta = {c: x["station"] for c, x in donor_meta_full.items()}
    results_by_type: dict[str, dict] = {}
    charts: dict[str, dict] = {}
    donors: dict[str, dict] = {}
    stratum_verdicts = {}
    for typ in ("traffic", "background"):
        ts = {s.code: treated_series[s.code] for s in treated_sites if s.stratum == typ and s.code in treated_series}
        ds = {s.code: donor_series[s.code] for s in donor_candidates if s.stratum == typ and s.code in donor_series}
        progress(f"air: {typ} counterfactual", 0, 1)
        analysed = analyse_stratum(ts, ds, case.event_date, months, typ, donor_station_meta, treated_station_meta,
                                  analysis_start=start)
        if analysed is None:
            continue
        result, chart, donor_info, vv = analysed
        results_by_type[typ] = result
        charts[result["signal"]] = chart
        donors[result["signal"]] = donor_info
        stratum_verdicts[typ] = vv

    verdict = combine_air_verdict(stratum_verdicts)
    if case.force_cant_tell:
        reason = case.force_cant_tell_reason or "This registered case is exploratory only."
        verdict = AirVerdict("CANT_TELL", "Can't tell — exploratory case",
                             reason + (" " + verdict.statement if verdict.statement else ""),
                             [reason, *verdict.reasons], verdict.lead_signal)
    signal_results = {r["signal"]: r for r in results_by_type.values()}
    research = _research_comparison(case, results_by_type, months)
    all_receipts = receipts_t + receipts_d
    receipt_counts: dict[str, int] = {}
    for r in all_receipts:
        receipt_counts[r.get("reason", "other")] = receipt_counts.get(r.get("reason", "other"), 0) + 1

    if boundary:
        geom = shape(boundary["geometry"])
        centroid = geom.centroid
        area_geo = boundary
        lat, lon = float(centroid.y), float(centroid.x)
    else:
        area_geo = None
        lat = float(np.mean([s.lat for s in treated_sites]))
        lon = float(np.mean([s.lon for s in treated_sites]))

    covid_note = None
    if case.covid_overlap or (pd.Timestamp(case.event_date) <= pd.Timestamp("2021-12-31") and
                              pd.Timestamp(end) >= pd.Timestamp("2020-03-23")):
        covid_note = ("The analysis window overlaps COVID-era mobility restrictions. Other-city controls absorb common "
                      "national shocks only to the extent those shocks affected sites comparably.")

    out = {
        "id": rid, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "domain": "air", "signal_family": "air_pollution", "case_id": case.id,
        "label": label or case.label, "change_type": "air_no2", "event_date": case.event_date,
        "post_months": months, "window": [start, end],
        "area": {"geojson": area_geo, "ha": None, "lon": round(lon, 5), "lat": round(lat, 5),
                 "landcover": None, "elevation_m": None, "name": case.label},
        "case": case.public_dict(),
        "verdict": {"status": verdict.status, "headline": verdict.headline, "statement": verdict.statement,
                    "reasons": verdict.reasons, "lead_signal": verdict.lead_signal},
        "signals": signal_results,
        "charts": charts,
        "donors": donors,
        "stations": {
            "treated": [s.as_dict() for s in treated_sites
                        if any(s.code in r.get("treated_station_codes", []) for r in results_by_type.values())],
            "treated_requested": len(treated_sites),
            "treated_usable_after_daily_qc": len(treated_series),
            "treated_used_in_estimate": sorted({c for r in results_by_type.values() for c in r.get("treated_station_codes", [])}),
            "control_requested": len(donor_candidates),
            "control_usable_after_daily_qc": len(donor_series),
        },
        "weather": {
            "source": "ERA5 reanalysis via Open-Meteo historical API",
            "trained_pre_event_only": True,
            "method": "blocked-CV ridge with nonlinear weather terms; actual weather replaced by season-matched pre-policy reference weather (±14 day-of-year)",
            "treated_models": {c: x["weather"] for c, x in treated_meta.items() if x["usable"]},
            "control_models": {c: x["weather"] for c, x in donor_meta_full.items() if x["usable"]},
            "excluded_station_diagnostics": [x for x in [*treated_meta.values(), *donor_meta_full.values()] if not x["usable"]],
        },
        "receipts": all_receipts,
        "data_summary": {
            "source": "LAQN treated monitors + DEFRA AURN controls",
            "pollutant": "NO2", "unit": "µg/m³", "aggregation": "hourly -> daily (>=19h; >75%) -> weekly (>=4d)",
            "treated_stations": len(treated_series), "control_stations": len(donor_series),
            "receipts": receipt_counts,
        },
        "research_comparison": research,
        "limits": [
            "Ground monitors measure conditions at fixed points; they are not a population-exposure map.",
            "Traffic and background monitors are analysed separately and never pooled.",
            "AURN controls are matched on monitor type and pre-policy NO₂ trajectory, level, trend and variability; road density, fleet composition and socioeconomic covariates are not yet included.",
            "Weather normalisation is fitted on pre-policy data only; it cannot remove every concurrent local policy or behavioural change.",
            "A London-only unmeasured shock beginning at the same time as ULEZ is not identifiable from these observational time series alone.",
            *( [covid_note] if covid_note else [] ),
            *( [case.force_cant_tell_reason] if case.force_cant_tell and case.force_cant_tell_reason else [] ),
            "For the 2023 case the primary estimand covers newly treated outer London, not already-treated central/inner London.",
            "This ground-monitor implementation does not yet add Sentinel-5P column NO₂; that remains a separate cross-sensor validation layer.",
        ],
        "controls": {
            "mode": "other UK cities", "spillover_exclusion_km": 60,
            "matching": "same site type + pre-policy NO₂ trajectory, level, trend and variability",
            "policy_screen": "exclude known UK CAZ/LEZ/ZEZ launches inside the registered analysis window",
            "policy_exclusions": policy_exclusions,
        },
        "method": {
            "plugin": AIR_PROTOCOL,
            "estimator": "augmented synthetic control (ridge-corrected convex weights)",
            "interval": "90% air-scale conformal moving-block permutation with zero-spanning search and truncation guard",
            "weather": "pre-event-only ridge normalisation using ERA5; season-matched pre-policy reference weather",
            "placebo": "exact-size symmetric in-space cohorts; donor selection and lambda rerun per placebo; both RMSPE-ratio and signed-effect tests required",
            "time_bin": "weekly", "registered_analysis_start": start,
            "minimum_meaningful_effect": "1.0 µg/m³ (design threshold, not a regulatory standard)",
            "answer_key_leakage": "published findings attached only after estimation",
        },
        "timing": {"run_s": round(time.time() - t0, 1)},
    }
    out = _json_safe(out)
    if save:
        os.makedirs(runs_dir, exist_ok=True)
        # Publish a fully written file without ever overwriting another run.
        fd, tmp = tempfile.mkstemp(dir=runs_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(out, f, allow_nan=False)
            try:
                os.link(tmp, result_path)
            except FileExistsError:
                return json.loads(result_path.read_text(encoding="utf-8"))
        finally:
            os.unlink(tmp)
    return out
