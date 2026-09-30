"""Air-pollution signal plugin for Otherwise.

Ground NO2 is the first production air signal.  The module deliberately keeps
all domain-specific acquisition/weather logic outside the land pipeline; both
pipelines meet again at the same ASCM/conformal counterfactual machinery.

The case registry is light and imported eagerly. The run machinery (pandas,
scipy via the estimator) is resolved lazily on first attribute access, so the
web process can list cases without loading the analysis stack.
"""

from .cases import AIR_CASES, AirCase, get_case

_LAZY = {"air_run_id", "fetch_case_boundary", "run_air_verdict"}

__all__ = ["AIR_CASES", "AirCase", "get_case", "air_run_id", "fetch_case_boundary", "run_air_verdict"]


def __getattr__(name):
    if name in _LAZY:
        from . import run as _run
        return getattr(_run, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
