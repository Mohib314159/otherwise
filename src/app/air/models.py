from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def normalise_site_type(value: str | None) -> str:
    """Collapse monitoring-network labels to the two strata we analyse.

    ULEZ effects differ sharply at roadside/traffic and background monitors, so
    these strata are never pooled in the estimator.
    """
    s = (value or "").strip().lower().replace("_", " ")
    if any(k in s for k in ("traffic", "roadside", "kerbside", "kerb")):
        return "traffic"
    if any(k in s for k in ("background", "urban centre", "urban center", "suburban")):
        return "background"
    return "unknown"


@dataclass(frozen=True)
class AirStation:
    code: str
    name: str
    lat: float
    lon: float
    site_type: str
    source: str
    city: str = ""
    uk_air_id: str | None = None
    date_opened: date | None = None
    date_closed: date | None = None
    metadata: dict = field(default_factory=dict, compare=False)

    @property
    def stratum(self) -> str:
        return normalise_site_type(self.site_type)

    def active_on(self, when: date) -> bool:
        if self.date_opened and self.date_opened > when:
            return False
        if self.date_closed and self.date_closed < when:
            return False
        return True

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "lat": round(float(self.lat), 6),
            "lon": round(float(self.lon), 6),
            "site_type": self.site_type,
            "stratum": self.stratum,
            "source": self.source,
            "city": self.city,
            "uk_air_id": self.uk_air_id,
        }
