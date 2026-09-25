"""Pre-registered air-policy cases.

Published findings live here *only* as answer-key metadata for the report.  The
estimator never imports or sees those values; ``run_air_verdict`` attaches them
only after the counterfactual has been fit.  This keeps the known answer out of
control selection, weather normalisation, ASCM fitting and verdict thresholds.

The dates/geographies below are protocol choices, not knobs tuned to reproduce
published estimates.  Where a study window is useful because it avoids a known
confounder (T-Charge/COVID), that rationale is exposed in ``notes`` and in the
permalink JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PublishedFinding:
    citation: str
    url: str
    finding: str
    stratum: str | None = None
    point_pct: float | None = None
    point_ugm3: float | None = None
    horizon: str | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass(frozen=True)
class AirCase:
    id: str
    label: str
    event_date: str
    description: str
    zone_mode: str                    # arcgis | difference
    arcgis_layer: int | None = None
    include_layer: int | None = None
    exclude_layer: int | None = None
    default_post_months: int = 3
    pre_years: int = 3                # fallback only when analysis_start is absent
    analysis_start: str | None = None
    announcement_date: str | None = None
    covid_overlap: bool = False
    supported: bool = True
    force_cant_tell: bool = False
    force_cant_tell_reason: str | None = None
    notes: tuple[str, ...] = ()
    published: tuple[PublishedFinding, ...] = field(default_factory=tuple)

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "event_date": self.event_date,
            "description": self.description,
            "zone_mode": self.zone_mode,
            "arcgis_layer": self.arcgis_layer,
            "include_layer": self.include_layer,
            "exclude_layer": self.exclude_layer,
            "default_post_months": self.default_post_months,
            "analysis_start": self.analysis_start,
            "announcement_date": self.announcement_date,
            "covid_overlap": self.covid_overlap,
            "supported": self.supported,
            "force_cant_tell": self.force_cant_tell,
            "force_cant_tell_reason": self.force_cant_tell_reason,
            "notes": list(self.notes),
            "published": [p.as_dict() for p in self.published],
        }


AIR_CASES: dict[str, AirCase] = {
    "ulez-central-2019": AirCase(
        id="ulez-central-2019",
        label="Central London ULEZ — 2019 launch",
        event_date="2019-04-08",
        description=("Did roadside and urban-background NO₂ inside the original central London ULEZ "
                     "fall more than comparable monitors elsewhere in the UK?"),
        zone_mode="arcgis",
        arcgis_layer=4,
        default_post_months=3,
        # Deliberately begins after the October-2017 T-Charge regime was already
        # established.  It also matches the broad study window used by Tong et al.
        analysis_start="2018-03-08",
        announcement_date="2017-11-03",
        notes=(
            "Original ULEZ used the existing central London Congestion Charge zone.",
            "The baseline starts after the October-2017 T-Charge transition so that another central-London emissions intervention is not introduced mid-baseline.",
            "Ground monitors are primary: the 2019 zone is too small for a clean TROPOMI test.",
        ),
        published=(
            PublishedFinding(
                citation="Ma, Graham & Stettler (2021), Environmental Research Letters",
                url="https://doi.org/10.1088/1748-9326/ac30c1",
                finding=("Meteorology-normalised regression-discontinuity analysis reported a small "
                         "initial average NO₂ effect (under 3%), with larger reductions at some sites."),
                horizon="initial weeks",
            ),
            PublishedFinding(
                citation="Tong et al. (2025), npj Clean Air",
                url="https://www.nature.com/articles/s44407-025-00030-9",
                finding="ASCM + weather normalisation: 19.6% (13.3 µg/m³) at central urban-traffic sites after 3 months.",
                stratum="traffic", point_pct=-19.6, point_ugm3=-13.3, horizon="3 months",
            ),
            PublishedFinding(
                citation="Tong et al. (2025), npj Clean Air",
                url="https://www.nature.com/articles/s44407-025-00030-9",
                finding="ASCM + weather normalisation: 8.2% (2.7 µg/m³) at central urban-background sites after 3 months.",
                stratum="background", point_pct=-8.2, point_ugm3=-2.7, horizon="3 months",
            ),
        ),
    ),
    "ulez-inner-2021": AirCase(
        id="ulez-inner-2021",
        label="Inner London ULEZ — 2021 expansion",
        event_date="2021-10-25",
        description="Exploratory check: did NO₂ fall more inside the North/South Circular expansion than in comparable UK monitors?",
        zone_mode="arcgis",
        arcgis_layer=5,
        default_post_months=3,
        analysis_start="2021-07-19",
        covid_overlap=True,
        force_cant_tell=True,
        force_cant_tell_reason=(
            "The 2021 expansion sits too close to the end of England's COVID restrictions to establish a clean, sufficiently long pre-policy baseline. "
            "The estimate is shown as a sensitivity analysis only."
        ),
        notes=(
            "The event sits inside the COVID-era mobility disturbance; this case is intentionally prevented from returning a decisive headline.",
            "Tong et al. (2025) excluded this phase from their main causal analysis for the same identification problem.",
        ),
    ),
    "ulez-londonwide-2023": AirCase(
        id="ulez-londonwide-2023",
        label="London-wide ULEZ — 2023 expansion",
        event_date="2023-08-29",
        description=("Did NO₂ in the newly covered outer-London area fall further after ULEZ expanded London-wide?"),
        # The newly treated geography is the 2023 London-wide/LEZ footprint minus
        # the already-treated 2021 inner-London ULEZ.  Using all London would mix
        # already-treated central/inner monitors into the treated cohort.
        zone_mode="difference",
        include_layer=6,              # TfL London-wide LEZ footprint / 2023 ULEZ boundary basis
        exclude_layer=5,              # 2021 inner-London ULEZ
        default_post_months=3,
        analysis_start="2021-07-19", # avoids fitting straight through lockdown restrictions
        notes=(
            "Primary treated geography is newly covered outer London: official London-wide LEZ footprint minus the official 2021 ULEZ polygon.",
            "The baseline begins after the final English COVID legal restrictions, avoiding a lockdown discontinuity inside the fitted pre-period.",
            "Because compliance changed before launch, this estimates the incremental change after 29 August 2023, not every anticipatory effect of the announced expansion.",
        ),
        published=(
            PublishedFinding(
                citation="Tong et al. (2025), npj Clean Air",
                url="https://www.nature.com/articles/s44407-025-00030-9",
                finding="No detectable additional effect on NO₂ after the 2023 London-wide expansion.",
                stratum="traffic", horizon="3 months",
            ),
            PublishedFinding(
                citation="Tong et al. (2025), npj Clean Air",
                url="https://www.nature.com/articles/s44407-025-00030-9",
                finding="No detectable additional effect on NO₂ after the 2023 London-wide expansion.",
                stratum="background", horizon="3 months",
            ),
        ),
    ),
}


def get_case(case_id: str) -> AirCase:
    try:
        return AIR_CASES[case_id]
    except KeyError as e:
        raise ValueError(f"Unknown air case {case_id!r}") from e
