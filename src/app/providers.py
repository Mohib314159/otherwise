"""STAC providers. One small interface, two implementations.

Planetary Computer is primary (Sentinel-2 L2A with SCL, and Sentinel-1 RTC).
Earth Search is a second Sentinel-2 provider with no signing step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from shapely.geometry import shape

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
ES_STAC = "https://earth-search.aws.element84.com/v1"

_S2_BANDS = ("B03", "B04", "B08", "B12", "SCL")
_ES_NAMES = {"B03": "green", "B04": "red", "B08": "nir", "B12": "swir22", "SCL": "scl"}


@dataclass
class Scene:
    id: str
    sensor: str                     # "S2" or "S1"
    datetime: datetime
    hrefs: dict[str, str]           # band/polarisation -> COG href (unsigned)
    props: dict = field(default_factory=dict)
    provider: str = ""
    geometry: object = None         # shapely geometry of the footprint (WGS84)
    epsg: int | None = None         # projection of the assets, from proj:epsg / proj:code

    @property
    def minute_key(self) -> str:
        return self.datetime.strftime("%Y-%m-%dT%H:%M")

    @property
    def date(self) -> str:
        return self.datetime.strftime("%Y-%m-%d")


def _parse_dt(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _epsg(p: dict) -> int | None:
    if p.get("proj:epsg"):
        return int(p["proj:epsg"])
    code = p.get("proj:code") or ""
    if code.upper().startswith("EPSG:"):
        return int(code.split(":")[1])
    return None


def _geom(it: dict):
    try:
        return shape(it["geometry"]) if it.get("geometry") else None
    except Exception:
        return None


def _search(url: str, collection: str, bbox: list[float], start: str, end: str,
            query: dict | None = None, limit: int = 250) -> list[dict]:
    body = {"collections": [collection], "bbox": bbox,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": limit}
    if query:
        body["query"] = query
    items: list[dict] = []
    next_body = body
    for _ in range(50):                     # pagination guard
        r = requests.post(f"{url}/search", json=next_body, timeout=90)
        r.raise_for_status()
        js = r.json()
        items.extend(js.get("features", []))
        nxt = [l for l in js.get("links", []) if l.get("rel") == "next"]
        if not nxt:
            break
        link = nxt[0]
        if link.get("method", "GET").upper() == "POST" and link.get("body"):
            next_body = {**body, **link["body"]} if link.get("merge") else link["body"]
        else:
            r = requests.get(link["href"], timeout=90)
            r.raise_for_status()
            js = r.json()
            items.extend(js.get("features", []))
            break
    return items


class PlanetaryComputer:
    name = "planetary-computer"

    def __init__(self):
        import planetary_computer as pc
        self._pc = pc

    def sign(self, href: str) -> str:
        return self._pc.sign(href)

    def search_s2(self, bbox, start, end, max_cloud: float = 95.0) -> list[Scene]:
        items = _search(PC_STAC, "sentinel-2-l2a", bbox, start, end,
                        query={"eo:cloud_cover": {"lt": max_cloud}})
        out = []
        for it in items:
            a = it["assets"]
            if not all(b in a for b in _S2_BANDS):
                continue
            p = it["properties"]
            out.append(Scene(id=it["id"], sensor="S2", datetime=_parse_dt(p["datetime"]),
                             hrefs={b: a[b]["href"] for b in _S2_BANDS},
                             props={"baseline": p.get("s2:processing_baseline", "00.00"),
                                    "cloud_cover": p.get("eo:cloud_cover"),
                                    "tile": p.get("s2:mgrs_tile"),
                                    "platform": p.get("platform")},
                             provider=self.name, geometry=_geom(it), epsg=_epsg(p)))
        return out

    def search_s1(self, bbox, start, end) -> list[Scene]:
        items = _search(PC_STAC, "sentinel-1-rtc", bbox, start, end)
        out = []
        for it in items:
            a = it["assets"]
            if "vv" not in a or "vh" not in a:
                continue
            p = it["properties"]
            out.append(Scene(id=it["id"], sensor="S1", datetime=_parse_dt(p["datetime"]),
                             hrefs={"VV": a["vv"]["href"], "VH": a["vh"]["href"]},
                             props={"orbit_state": p.get("sat:orbit_state"),
                                    "relative_orbit": p.get("sat:relative_orbit"),
                                    "platform": p.get("platform")},
                             provider=self.name, geometry=_geom(it), epsg=_epsg(p)))
        return out


class EarthSearch:
    name = "earth-search"

    def sign(self, href: str) -> str:
        return href

    def search_s2(self, bbox, start, end, max_cloud: float = 95.0) -> list[Scene]:
        items = _search(ES_STAC, "sentinel-2-l2a", bbox, start, end,
                        query={"eo:cloud_cover": {"lt": max_cloud}})
        out = []
        for it in items:
            a = it["assets"]
            if not all(_ES_NAMES[b] in a for b in _S2_BANDS):
                continue
            p = it["properties"]
            out.append(Scene(id=it["id"], sensor="S2", datetime=_parse_dt(p["datetime"]),
                             hrefs={b: a[_ES_NAMES[b]]["href"] for b in _S2_BANDS},
                             props={"baseline": p.get("s2:processing_baseline", "00.00"),
                                    "cloud_cover": p.get("eo:cloud_cover"),
                                    "tile": p.get("grid:code", "").replace("MGRS-", ""),
                                    "platform": p.get("platform")},
                             provider=self.name, geometry=_geom(it), epsg=_epsg(p)))
        return out

    def search_s1(self, bbox, start, end) -> list[Scene]:
        return []       # Earth Search has GRD only; RTC comes from Planetary Computer
