"""Air-quality data providers and provenance-preserving parsers.

Primary sources:
- London Air Quality Network / Imperial ERG API for treated London monitors.
- DEFRA UK-AIR AURN annual flat files for non-London controls.
- Open-Meteo's historical API pinned to ERA5 for meteorology.
- GLA/TfL ArcGIS layers for official 2019/2021 ULEZ polygons.

Every HTTP response is cached on disk.  Parsers return explicit receipts rather
than silently coercing malformed measurements into valid observations.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from .models import AirStation, normalise_site_type

AIR_CACHE_DIR = Path(os.environ.get("APP_AIR_CACHE_DIR", "data/air_cache"))
LAQN_BASE = "https://api.erg.ic.ac.uk/AirQuality"
UKAIR_BASE = "https://uk-air.defra.gov.uk"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
GLA_AIR_LAYER = "https://gis.london.gov.uk/arcgis/rest/services/apps/Air_Quality_map_service_01/MapServer"

USER_AGENT = "Otherwise/2 air-policy verifier (public research prototype)"


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:120]


class CachedHTTP:
    def __init__(self, cache_dir: Path | str = AIR_CACHE_DIR, session: requests.Session | None = None):
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,text/html,*/*"})

    def _path(self, namespace: str, url: str, params: dict | None = None, suffix: str = ".bin") -> Path:
        key = url + "?" + urlencode(sorted((params or {}).items()), doseq=True)
        h = hashlib.sha256(key.encode()).hexdigest()[:20]
        return self.cache_dir / namespace / f"{h}{suffix}"

    def get_bytes(self, namespace: str, url: str, params: dict | None = None,
                  *, timeout: float = 45, suffix: str = ".bin") -> bytes:
        p = self._path(namespace, url, params, suffix)
        if p.exists():
            return p.read_bytes()
        r = self.session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        content = r.content
        p.parent.mkdir(parents=True, exist_ok=True)
        # Concurrent cases can request the same historical response.
        fd, name = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        tmp = Path(name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            tmp.replace(p)
        finally:
            tmp.unlink(missing_ok=True)
        return content

    def get_json(self, namespace: str, url: str, params: dict | None = None, *, timeout: float = 45):
        raw = self.get_bytes(namespace, url, params, timeout=timeout, suffix=".json")
        return json.loads(raw.decode("utf-8-sig"))

    def get_text(self, namespace: str, url: str, params: dict | None = None, *, timeout: float = 45) -> str:
        raw = self.get_bytes(namespace, url, params, timeout=timeout, suffix=".txt")
        return raw.decode("utf-8-sig", errors="replace")


def _date_maybe(value) -> date | None:
    if not value or str(value).strip() in ("", "-", "None"):
        return None
    s = str(value).strip()[:10]
    for dayfirst in (False, True):
        try:
            x = pd.to_datetime(s, dayfirst=dayfirst, errors="raise")
            return x.date()
        except Exception:
            pass
    return None


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _species_codes(site: dict) -> set[str]:
    out = set()
    for sp in _as_list(site.get("Species")):
        if isinstance(sp, dict):
            code = sp.get("@SpeciesCode") or sp.get("SpeciesCode") or sp.get("@Code")
            if code:
                out.add(str(code).upper())
    return out


class LAQNProvider:
    """London Air Quality Network metadata and hourly NO2."""

    def __init__(self, http: CachedHTTP | None = None):
        self.http = http or CachedHTTP()

    def sites(self, species: str = "NO2") -> list[AirStation]:
        url = f"{LAQN_BASE}/Information/MonitoringSiteSpecies/GroupName=London/Json"
        data = self.http.get_json("laqn/meta", url)
        raw_sites = ((data or {}).get("Sites") or {}).get("Site") or []
        out: list[AirStation] = []
        for x in _as_list(raw_sites):
            if not isinstance(x, dict):
                continue
            codes = _species_codes(x)
            if codes and species.upper() not in codes:
                continue
            code = x.get("@SiteCode") or x.get("SiteCode")
            lat = x.get("@Latitude") or x.get("Latitude")
            lon = x.get("@Longitude") or x.get("Longitude")
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            raw_type = (x.get("@SiteType") or x.get("@SiteClassification") or
                        x.get("@SiteTypeName") or x.get("SiteType") or "")
            site_opened = _date_maybe(x.get("@DateOpened"))
            site_closed = _date_maybe(x.get("@DateClosed"))
            species_rows = [sp for sp in _as_list(x.get("Species")) if isinstance(sp, dict)
                            and str(sp.get("@SpeciesCode") or sp.get("SpeciesCode") or sp.get("@Code") or "").upper() == species.upper()]
            starts = [_date_maybe(sp.get("@DateMeasurementStarted")) for sp in species_rows]
            finishes = [_date_maybe(sp.get("@DateMeasurementFinished")) for sp in species_rows]
            species_start = min((d for d in starts if d), default=None)
            species_finish = max(finishes) if finishes and all(finishes) else None
            effective_start = max((d for d in (site_opened, species_start) if d), default=None)
            effective_finish = min((d for d in (site_closed, species_finish) if d), default=None)
            out.append(AirStation(
                code=str(code),
                name=str(x.get("@SiteName") or x.get("SiteName") or code),
                lat=lat, lon=lon, site_type=str(raw_type), source="LAQN",
                city="London",
                date_opened=effective_start,
                date_closed=effective_finish,
                metadata={"local_authority": x.get("@LocalAuthorityName"), "species": sorted(codes),
                          "site_date_opened": str(site_opened) if site_opened else None,
                          "site_date_closed": str(site_closed) if site_closed else None,
                          "species_measurement_start": str(species_start) if species_start else None,
                          "species_measurement_finish": str(species_finish) if species_finish else None},
            ))
        return out

    def hourly_no2(self, station: AirStation, start: str, end: str) -> tuple[pd.Series, list[dict]]:
        """Fetch hourly NO2, chunked by <=365 days to keep the ERG endpoint reliable."""
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        chunks: list[pd.Series] = []
        receipts: list[dict] = []
        cur = a
        while cur <= b:
            stop = min(cur + timedelta(days=364), b)
            # ERG EndDate is exclusive; stop is our inclusive final day.
            # Request the next midnight so neither chunk boundaries nor the
            # final requested day lose all 24 measurements.
            exclusive_end = stop + timedelta(days=1)
            url = (f"{LAQN_BASE}/Data/SiteSpecies/SiteCode={station.code}/SpeciesCode=NO2/"
                   f"StartDate={cur.isoformat()}/EndDate={exclusive_end.isoformat()}/Json")
            try:
                data = self.http.get_json(f"laqn/no2/{station.code}", url, timeout=75)
            except Exception as e:
                receipts.append({"date": cur.isoformat(), "sensor": f"LAQN {station.code}",
                                 "reason": "read-error", "detail": f"{type(e).__name__}: {e}"[:180]})
                cur = stop + timedelta(days=1)
                continue
            rows = ((data or {}).get("RawAQData") or {}).get("Data") or []
            dates, values = [], []
            for r in _as_list(rows):
                if not isinstance(r, dict):
                    continue
                ts = r.get("@MeasurementDateGMT") or r.get("MeasurementDateGMT")
                raw = r.get("@Value") if "@Value" in r else r.get("Value")
                try:
                    v = float(raw)
                    dt = pd.to_datetime(ts, utc=True).tz_convert(None)
                    if not np.isfinite(v) or v < 0:
                        raise ValueError("invalid value")
                except Exception:
                    receipts.append({"date": str(ts)[:10], "sensor": f"LAQN {station.code}",
                                     "reason": "invalid", "detail": f"NO2={raw!r}"})
                    continue
                dates.append(dt); values.append(v)
            if dates:
                chunks.append(pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float))
            cur = stop + timedelta(days=1)
        if not chunks:
            return pd.Series(dtype=float), receipts
        s = pd.concat(chunks).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s = s[(s.index >= pd.Timestamp(a)) & (s.index < pd.Timestamp(b + timedelta(days=1)))]
        return s, receipts


# ---- UK-AIR AURN -----------------------------------------------------------

_FIND_SITES_URL = (f"{UKAIR_BASE}/networks/find-sites?action=results&country_id=9999&group_id=4&"
                   "location_type=9999&pollutant=&region_id=9999&site_name=&view=advanced")
_AURN_INFO_URL = f"{UKAIR_BASE}/networks/network-info?view=aurn"


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _norm_name(s: str) -> str:
    s = html.unescape(s).lower()
    s = re.sub(r"\(aurn(?: affiliated)?\)", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def parse_aurn_search_html(text: str) -> list[dict]:
    """Parse DEFRA's monitoring-site table without depending on page styling."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        plain = _strip_tags(row)
        m = re.search(r"^(.*?)\s+UK-AIR ID:\s*(UKA\d+)\s+Location:\s*([-+0-9.]+)\s*,\s*([-+0-9.]+)", plain, re.I)
        if not m:
            continue
        name, uka, lat, lon = m.groups()
        # The first table cell is a result rank, not part of the site name.
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if cells and _strip_tags(cells[0]).isdigit():
            name = re.sub(r"^\d+\s+", "", name)
        typ = ""
        for candidate in ("Urban Traffic", "Urban Background", "Suburban Background",
                          "Rural Background", "Urban Centre", "Roadside", "Kerbside"):
            if candidate.lower() in plain.lower():
                typ = candidate; break
        out.append({"name": name.strip(), "uk_air_id": uka, "lat": float(lat), "lon": float(lon),
                    "site_type": typ})
    return out


def parse_aurn_site_codes_html(text: str) -> dict[str, str]:
    """Map normalised site name -> UK-AIR short code from the AURN selector."""
    out: dict[str, str] = {}
    for val, label in re.findall(r"<option\b[^>]*value=[\"']([^\"']+)[\"'][^>]*>(.*?)</option>", text,
                                 flags=re.I | re.S):
        code = val.strip()
        if not re.fullmatch(r"[A-Za-z0-9]{2,8}", code):
            continue
        name = _strip_tags(label)
        if name and name.lower() not in ("select", "please select"):
            out[_norm_name(name)] = code.upper()
    # Some deployments render site links rather than a select.
    for code, label in re.findall(r"site_id=([A-Za-z0-9]{2,8})[^>]*>(.*?)</a>", text, flags=re.I | re.S):
        name = _strip_tags(label)
        if name:
            out[_norm_name(name)] = code.upper()
    return out


class UKAirProvider:
    """DEFRA AURN metadata discovery and annual flat-file NO2 reads."""

    def __init__(self, http: CachedHTTP | None = None):
        self.http = http or CachedHTTP()

    def sites(self) -> list[AirStation]:
        table = self.http.get_text("ukair/meta", _FIND_SITES_URL, timeout=60)
        selector = self.http.get_text("ukair/meta", _AURN_INFO_URL, timeout=60)
        code_map = parse_aurn_site_codes_html(selector)
        rows = parse_aurn_search_html(table)
        out = []
        for r in rows:
            code = code_map.get(_norm_name(r["name"])) or r["uk_air_id"]
            out.append(AirStation(code=code, name=r["name"], lat=r["lat"], lon=r["lon"],
                                  site_type=r["site_type"], source="UK-AIR AURN",
                                  city=r["name"].split()[0], uk_air_id=r["uk_air_id"]))
        return out

    @staticmethod
    def _find_col(cols: Iterable[str], kind: str) -> str | None:
        def norm(x): return re.sub(r"[^a-z0-9]+", " ", str(x).lower()).strip()
        pairs = [(c, norm(c)) for c in cols]
        if kind == "date":
            return next((c for c, n in pairs if n in ("date", "measurement date") or n.startswith("date ")), None)
        if kind == "time":
            return next((c for c, n in pairs if n in ("time", "measurement time") or n.startswith("time ")), None)
        if kind == "no2":
            preferred = [c for c, n in pairs if (n == "no2" or n.startswith("nitrogen dioxide")) and "status" not in n and "unit" not in n]
            return preferred[0] if preferred else None
        return None

    @classmethod
    def parse_column_csv(cls, text: str, receipts: list[dict] | None = None,
                         sensor: str = "AURN NO2") -> pd.Series:
        # The files have historically varied in encoding and occasional header
        # decoration.  Try normal CSV first, then find the first line containing
        # both Date and NO2 and restart there.
        candidate = text
        try:
            df = pd.read_csv(io.StringIO(candidate), low_memory=False)
        except Exception:
            df = pd.DataFrame()
        if df.empty or cls._find_col(df.columns, "date") is None or cls._find_col(df.columns, "no2") is None:
            lines = text.splitlines()
            start = next((i for i, line in enumerate(lines)
                          if re.search(r"\bdate\b", line, re.I) and re.search(r"NO2|nitrogen dioxide", line, re.I)), None)
            if start is None:
                return pd.Series(dtype=float)
            try:
                df = pd.read_csv(io.StringIO("\n".join(lines[start:])), low_memory=False)
            except Exception:
                return pd.Series(dtype=float)
        dc, tc, nc = cls._find_col(df.columns, "date"), cls._find_col(df.columns, "time"), cls._find_col(df.columns, "no2")
        if dc is None or nc is None:
            return pd.Series(dtype=float)
        dates = df[dc].astype(str)
        idx = pd.to_datetime(dates, dayfirst=True, errors="coerce", utc=True).dt.tz_convert(None)
        if tc is not None:
            times = df[tc].astype(str).str.strip()
            # Annual DEFRA files label GMT hour ENDING 01:00..24:00.
            # Store the start of that hour: the 24:00 row belongs to 23:00
            # on the labelled date, including December 31.
            hours = pd.to_numeric(times.str.extract(r"^(\d{1,2}):00(?::00)?$")[0], errors="coerce")
            ending = bool(re.search(r"GMT\s+hour\s+ending", text, flags=re.I))
            valid_hour = hours.between(1 if ending else 0, 24)
            offset = hours - (1 if ending else 0)
            idx = (idx + pd.to_timedelta(offset.where(valid_hour), unit="h")).where(valid_hour)
        vals = pd.to_numeric(df[nc], errors="coerce")
        valid_value = vals.notna() & np.isfinite(vals) & (vals >= 0)
        # Repeated status headers are mangled to status.1/status.2 by pandas.
        # Only the status immediately following the NO2 column applies to NO2.
        pos = list(df.columns).index(nc)
        status_col = df.columns[pos + 1] if pos + 1 < len(df.columns) else None
        valid_status = pd.Series(True, index=df.index)
        if status_col is not None and re.match(r"^status(?:\.\d+)?$", str(status_col), re.I):
            statuses = df[status_col].astype(str).str.strip().str.upper()
            valid_status = statuses.isin(["R", "P", "P*", "V"])
        ok = idx.notna() & valid_value & valid_status
        if receipts is not None:
            for i in df.index[~ok]:
                reason = "invalid-time" if pd.isna(idx.loc[i]) else ("invalid-status" if not valid_status.loc[i] else "invalid")
                receipts.append({"date": str(dates.loc[i])[:10], "sensor": sensor,
                                 "reason": reason, "detail": f"NO2={df.loc[i, nc]!r}; row rejected ({reason})"})
        if not ok.any():
            return pd.Series(dtype=float)
        s = pd.Series(vals[ok].to_numpy(float), index=pd.DatetimeIndex(idx[ok]), dtype=float).sort_index()
        return s[~s.index.duplicated(keep="last")]

    def _flat_code(self, station: AirStation) -> str:
        if not station.code.upper().startswith("UKA"):
            return station.code
        url = f"{UKAIR_BASE}/networks/site-info?provider=&uka_id={station.uk_air_id or station.code}"
        text = self.http.get_text("ukair/site-info", url, timeout=45)
        m = re.search(r"flat_files\?site_id=([A-Za-z0-9]{2,8})", text, flags=re.I)
        if not m:
            raise RuntimeError(f"could not resolve UK-AIR short code for {station.name} ({station.code})")
        return m.group(1).upper()

    def hourly_no2(self, station: AirStation, start: str, end: str) -> tuple[pd.Series, list[dict]]:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        series = []
        receipts = []
        try:
            flat_code = self._flat_code(station)
        except Exception as e:
            return pd.Series(dtype=float), [{"date": start, "sensor": f"AURN {station.code}",
                                             "reason": "read-error", "detail": str(e)[:180]}]
        for year in range(a.year, b.year + 1):
            url = f"{UKAIR_BASE}/datastore/data_files/site_data/{flat_code}_{year}.csv?v=1"
            try:
                text = self.http.get_text(f"ukair/no2/{flat_code}", url, timeout=75)
                s = self.parse_column_csv(text, receipts=receipts, sensor=f"AURN {station.code}")
            except Exception as e:
                receipts.append({"date": f"{year}-01-01", "sensor": f"AURN {station.code}",
                                 "reason": "read-error", "detail": f"{type(e).__name__}: {e}"[:180]})
                continue
            if s.empty:
                receipts.append({"date": f"{year}-01-01", "sensor": f"AURN {station.code}",
                                 "reason": "no-data", "detail": "annual file had no parseable NO2 column"})
            else:
                series.append(s)
        if not series:
            return pd.Series(dtype=float), receipts
        s = pd.concat(series).sort_index()
        s = s[(s.index.date >= a) & (s.index.date <= b)]
        return s[~s.index.duplicated(keep="last")], receipts


# ---- common aggregation ----------------------------------------------------

def hourly_to_daily(series: pd.Series, min_hours: int = 19) -> tuple[pd.Series, list[dict]]:
    if series.empty:
        return pd.Series(dtype=float), []
    s = series.sort_index()
    grp = s.resample("D")
    mean = grp.mean()
    count = grp.count()
    dropped = count < min_hours
    receipts = [{"date": str(d.date()), "sensor": "NO2", "reason": "coverage",
                 "detail": f"{int(count.loc[d])}/24 valid hourly measurements; need {min_hours}"}
                for d in count.index[dropped]]
    mean[dropped] = np.nan
    return mean, receipts


def weekly_mean(series: pd.Series, min_days: int = 4) -> pd.Series:
    if series.empty:
        return series
    g = series.resample("W-SUN")
    out, n = g.mean(), g.count()
    out[n < min_days] = np.nan
    return out


# ---- ERA5 via Open-Meteo ---------------------------------------------------

class ERA5Provider:
    def __init__(self, http: CachedHTTP | None = None):
        self.http = http or CachedHTTP()

    def daily(self, lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
        params = {
            "latitude": round(float(lat), 5), "longitude": round(float(lon), 5),
            "start_date": start, "end_date": end, "timezone": "GMT", "models": "era5",
            "hourly": ",".join(["temperature_2m", "precipitation", "wind_speed_10m",
                                "wind_direction_10m", "boundary_layer_height"]),
        }
        try:
            data = self.http.get_json("era5", OPEN_METEO_ARCHIVE, params=params, timeout=90)
        except Exception:
            # Boundary-layer height is not available in every Open-Meteo model
            # release.  Retry without it rather than losing all meteorology.
            params["hourly"] = ",".join(["temperature_2m", "precipitation", "wind_speed_10m",
                                         "wind_direction_10m"])
            data = self.http.get_json("era5", OPEN_METEO_ARCHIVE, params=params, timeout=90)
        h = (data or {}).get("hourly") or {}
        idx = pd.to_datetime(h.get("time", []), utc=True, errors="coerce").tz_convert(None)
        if len(idx) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(index=pd.DatetimeIndex(idx))
        def arr(key):
            a = h.get(key)
            return np.asarray(a, dtype=float) if a is not None else np.full(len(idx), np.nan)
        df["temperature_2m"] = arr("temperature_2m")
        df["precipitation"] = arr("precipitation")
        speed = arr("wind_speed_10m")
        direction = np.deg2rad(arr("wind_direction_10m"))
        # Meteorological direction is where wind comes FROM.  Signs do not
        # matter for prediction as long as the transform is consistent.
        df["wind_u"] = speed * np.sin(direction)
        df["wind_v"] = speed * np.cos(direction)
        df["boundary_layer_height"] = arr("boundary_layer_height")
        daily = pd.DataFrame(index=df.resample("D").mean().index)
        daily["temperature_2m"] = df["temperature_2m"].resample("D").mean()
        daily["precipitation"] = df["precipitation"].resample("D").sum(min_count=1)
        daily["wind_u"] = df["wind_u"].resample("D").mean()
        daily["wind_v"] = df["wind_v"].resample("D").mean()
        daily["boundary_layer_height"] = df["boundary_layer_height"].resample("D").mean()
        return daily


# ---- ULEZ boundary ---------------------------------------------------------

def fetch_ulez_boundary(layer: int, http: CachedHTTP | None = None) -> dict:
    http = http or CachedHTTP()
    url = f"{GLA_AIR_LAYER}/{int(layer)}/query"
    params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": 4326, "f": "geojson"}
    data = http.get_json(f"gla/ulez/{layer}", url, params=params, timeout=60)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"GLA ULEZ layer {layer}: {data['error']}")
    feats = (data or {}).get("features") or []
    if not feats:
        raise RuntimeError(f"GLA ULEZ layer {layer} returned no features")
    geom = unary_union([shape(f["geometry"]) for f in feats if f.get("geometry")])
    return {"type": "Feature", "properties": {"source": "GLA/TfL", "layer": layer, "url": url},
            "geometry": geom.__geo_interface__}


def difference_boundaries(include_layer: int, exclude_layer: int, http: CachedHTTP | None = None) -> dict:
    """Return official include geometry minus an already-treated exclusion zone.

    Used for the 2023 ULEZ expansion so the treated area is *newly covered*
    outer London rather than all of London.  Both source geometries are cached
    and provenance is preserved in the returned feature properties.
    """
    http = http or CachedHTTP()
    outer = shape(fetch_ulez_boundary(include_layer, http)["geometry"])
    inner = shape(fetch_ulez_boundary(exclude_layer, http)["geometry"])
    geom = outer.difference(inner)
    if geom.is_empty:
        raise RuntimeError(f"boundary difference {include_layer} - {exclude_layer} is empty")
    return {
        "type": "Feature",
        "properties": {
            "source": "GLA/TfL",
            "operation": "difference",
            "include_layer": int(include_layer),
            "exclude_layer": int(exclude_layer),
        },
        "geometry": geom.__geo_interface__,
    }


def stations_in_boundary(stations: Iterable[AirStation], boundary_geojson: dict) -> list[AirStation]:
    geom = shape(boundary_geojson["geometry"] if boundary_geojson.get("type") == "Feature" else boundary_geojson)
    return [s for s in stations if geom.covers(Point(float(s.lon), float(s.lat)))]
