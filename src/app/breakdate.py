""""When did it change?" mode: search for the break date instead of assuming it.

The verdict mode takes the event date as given. This mode takes the binned
matrix and asks, for every candidate break index t in a window, how much worse
the area diverges from its synthetic control after t than before it. The
statistic is the RMSPE ratio used by the in-space placebo:

    S(t) = sqrt(mean(effect[t:]^2)) / sqrt(mean(effect[:t]^2))

with the augmented SCM refitted on bins < t for each t (same donors, one ridge
penalty chosen once on the earliest pre-period). The chosen break is argmax S.

Searching over dates inflates the maximum, so the inference must search too.
Each donor cell in turn plays the area (fitted on the other donors), the same
search over the same window is run, and its maximum S*_j is recorded. The
p-value is the rank of the area's S_max among those placebo maxima:

    p_search = (count(S*_j >= S_max) + 1) / (m + 1)

so the date search is part of the null, not a free pass. A break is "detected"
only if p_search <= 0.10 and the mean post-break effect is at least min_effect.

The distribution of placebo break indices is returned as well: if placebo cells
mostly "break" at the same bin, that is a shared shift (sensor, weather,
harmonisation), not evidence about the area.
"""
from __future__ import annotations

import contextlib
import ctypes
from dataclasses import dataclass, field

import numpy as np

from .estimator import fit_ascm

MIN_PRE_BINS = 20      # a candidate break needs at least this many bins before it
MIN_POST_BINS = 3      # and at least this many after it
P_SEARCH_MAX = 0.10
WINDOW_FRACTION = (0.40, 0.85)


@dataclass
class BreakResult:
    index: int                        # chosen break bin (post = bins >= index)
    date: str | None                  # bin date at the break, if dates were given
    stat: float                       # S_max, RMSPE ratio at the chosen break
    p_search: float                   # placebo-of-the-maximum p-value
    point: float                      # mean effect over bins >= index
    sign: int                         # sign of `point` (-1, 0, +1)
    curve: np.ndarray                 # S(t) for t in [s0, s1); curve[k] is bin s0 + k
    placebo_max_stats: np.ndarray     # (m,) max S over the window for each placebo unit
    placebo_break_indices: np.ndarray  # (m,) argmax bin index for each placebo unit
    detected: bool
    window: tuple[int, int] = (0, 0)  # [s0, s1) in bin indices
    lam: float = 0.0
    placebo_units: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))


def default_window(B: int) -> tuple[int, int]:
    """[s0, s1) from 40% to 85% of the bins, clamped so every candidate keeps
    MIN_PRE_BINS before it and MIN_POST_BINS after it."""
    s0 = int(WINDOW_FRACTION[0] * B)
    s1 = int(WINDOW_FRACTION[1] * B)
    return clamp_window(B, s0, s1)


def clamp_window(B: int, s0: int, s1: int) -> tuple[int, int]:
    s0 = max(int(s0), MIN_PRE_BINS)
    s1 = min(int(s1), B - MIN_POST_BINS + 1)     # last candidate t = B - MIN_POST_BINS
    if s1 <= s0:
        raise ValueError(f"no candidate break dates: {B} bins leave no index with "
                         f">= {MIN_PRE_BINS} bins before and >= {MIN_POST_BINS} after")
    return s0, s1


_THREAD_SYMBOLS = ("scipy_openblas_set_num_threads64_", "scipy_openblas_set_num_threads",
                   "openblas_set_num_threads64_", "openblas_set_num_threads")


@contextlib.contextmanager
def _blas_threads(n: int = 1):
    """Best-effort: run the block with `n` OpenBLAS threads, restore afterwards.

    The search is thousands of ~100x100 ridge solves. With OpenBLAS spinning
    up one thread per core for each of them, a solve that takes ~2 ms single-
    threaded took ~90 ms on a 4-core container, and the search minutes instead
    of seconds. Finds the loaded OpenBLAS copies (numpy's and scipy's ship
    separately) via /proc/self/maps; a no-op where that is unavailable.
    """
    restore = []
    try:
        with open("/proc/self/maps") as f:
            libs = sorted({ln.split()[-1] for ln in f if "openblas" in ln.lower() and ".so" in ln})
        for path in libs:
            lib = ctypes.CDLL(path)
            for name in _THREAD_SYMBOLS:
                setter = getattr(lib, name, None)
                getter = getattr(lib, name.replace("set_", "get_"), None)
                if setter is None or getter is None:
                    continue
                getter.restype = ctypes.c_int
                old = int(getter())
                setter(ctypes.c_int(n))
                restore.append((setter, old))
                break
    except Exception:
        pass
    try:
        yield
    finally:
        for setter, old in restore:
            try:
                setter(ctypes.c_int(old))
            except Exception:
                pass


def _ratio(effect: np.ndarray, t: int) -> float:
    post = np.sqrt(np.mean(effect[t:] ** 2))
    pre = np.sqrt(np.mean(effect[:t] ** 2))
    return float(post / (pre + 1e-9))


def search_curve(y: np.ndarray, D: np.ndarray, s0: int, s1: int, lam: float) -> np.ndarray:
    """S(t) for t in [s0, s1). y: (B,), D: (n, B) donors, both finite."""
    B = y.shape[0]
    idx = np.arange(B)
    out = np.empty(s1 - s0)
    for k, t in enumerate(range(s0, s1)):
        f = fit_ascm(y, D, idx < t, lam=lam)
        out[k] = _ratio(f.effect, t)
    return out


def _validate(M: np.ndarray) -> np.ndarray:
    M = np.asarray(M, dtype=float)
    if M.ndim != 2 or M.shape[1] < 3:
        raise ValueError(f"M must be (B, 1+n) with n >= 2 donors, got {M.shape}")
    if not np.all(np.isfinite(M)):
        raise ValueError("M contains NaN or inf; pass the completed matrix from prep.binned")
    return M


def find_break(M: np.ndarray, dates: np.ndarray | None = None,
               window: tuple[int, int] | None = None, max_units: int = 40,
               min_effect: float = 0.05, lam: float | None = None) -> BreakResult:
    """Search [s0, s1) for the break date of column 0 of M, with placebo inference.

    M: (B, 1+n) complete matrix, column 0 the area, columns 1..n donors.
    dates: (B,) bin dates (any type str() can render), optional.
    window: (s0, s1) bin indices, clamped; default from `default_window`.
    max_units: how many donors play the area in the placebo search (evenly spaced).
    min_effect: smallest |mean post effect| that counts as a detection.
    lam: ridge penalty; None chooses it once on bins < s0 via `fit_ascm`.
    """
    M = _validate(M)
    B, n1 = M.shape
    n = n1 - 1
    if dates is not None and len(dates) != B:
        raise ValueError(f"dates has {len(dates)} entries for {B} bins")
    s0, s1 = default_window(B) if window is None else clamp_window(B, window[0], window[1])
    y = M[:, 0]
    D = M[:, 1:].T                                  # (n, B)
    idx = np.arange(B)
    units = np.arange(n) if n <= max_units else np.linspace(0, n - 1, max_units).round().astype(int)
    pl_max = np.empty(len(units))
    pl_idx = np.empty(len(units), dtype=int)
    with _blas_threads(1):
        if lam is None:
            lam = fit_ascm(y, D, idx < s0).lam     # chosen once, on the earliest pre-period
        lam = float(lam)
        curve = search_curve(y, D, s0, s1, lam)
        k = int(np.argmax(curve))
        t_hat = s0 + k
        f = fit_ascm(y, D, idx < t_hat, lam=lam)
        point = float(np.mean(f.effect[t_hat:]))
        s_max = float(curve[k])
        for i, j in enumerate(units):
            keep = np.ones(n, dtype=bool); keep[j] = False
            c = search_curve(D[j], D[keep], s0, s1, lam)
            kk = int(np.argmax(c))
            pl_max[i] = c[kk]
            pl_idx[i] = s0 + kk
    p_search = float((np.sum(pl_max >= s_max) + 1) / (len(units) + 1))
    detected = bool(p_search <= P_SEARCH_MAX and abs(point) >= min_effect)
    date = None if dates is None else str(dates[t_hat])
    return BreakResult(t_hat, date, s_max, p_search, point, int(np.sign(point)), curve,
                       pl_max, pl_idx, detected, (s0, s1), lam, units)


def refine_uncertainty(curve: np.ndarray, s0: int, frac: float = 0.9) -> tuple[int, int]:
    """Crude plausible range for the break: bin indices whose S(t) >= frac * S_max.

    `curve[k]` is the statistic at bin `s0 + k`. Returns (lo_index, hi_index),
    inclusive. The range is the span of the near-maximal set, so a bimodal curve
    yields a wide range rather than two disjoint ones.
    """
    curve = np.asarray(curve, dtype=float)
    if curve.size == 0 or not np.any(np.isfinite(curve)):
        raise ValueError("empty or non-finite curve")
    near = np.where(curve >= frac * np.nanmax(curve))[0]
    return int(s0 + near.min()), int(s0 + near.max())
