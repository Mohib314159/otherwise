"""Air-pollution signal plugin for Otherwise.

Ground NO2 is the first production air signal.  The module deliberately keeps
all domain-specific acquisition/weather logic outside the land pipeline; both
pipelines meet again at the same ASCM/conformal counterfactual machinery.
"""

from .cases import AIR_CASES, AirCase, get_case
from .run import air_run_id, fetch_case_boundary, run_air_verdict

__all__ = ["AIR_CASES", "AirCase", "get_case", "air_run_id", "fetch_case_boundary", "run_air_verdict"]
