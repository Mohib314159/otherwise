"""Automatic donor selection: which nearby cells are fair controls?

Three filters and one ranking, all reported back so the page can say why a
cell was or was not used:
  1. coverage: the cell must be observed on >= 70% of the treated area's dates
  2. land cover: same dominant WorldCover class as the treated area (pre-event map)
  3. terrain: within 150 m of the treated area's elevation
  4. rank by pre-event RMSE to the treated series, keep the best K
Filters 2-3 are relaxed, in that order, if they would leave fewer than
`min_pool` cells, and the relaxation is reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .covariates import Covariates


@dataclass
class DonorSelection:
    index: np.ndarray                    # indices into the donor columns (0-based donors)
    pre_rmse: np.ndarray                 # RMSE of each kept donor to the treated pre series
    notes: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def select_donors(matrix: np.ndarray, pre: np.ndarray, donor_cov: np.ndarray,
                  cov: Covariates | None, k: int = 80, min_pool: int = 30,
                  elev_tol_m: float = 150.0) -> DonorSelection:
    """matrix: (B, 1+n_good) after prep.complete; donor_cov: (n_all,) coverage of every
    grid cell, used to map the good columns back to grid indices."""
    good_idx = np.where(donor_cov >= 0.70)[0]          # same rule as prep.complete
    n = matrix.shape[1] - 1
    assert len(good_idx) == n, "column/grid mismatch"
    y = matrix[pre, 0]
    D = matrix[pre, 1:]
    rmse = np.sqrt(np.mean((D - y[:, None]) ** 2, axis=0))
    counts = {"grid": int(len(donor_cov)), "covered": int(n)}
    notes = []
    mask = np.ones(n, dtype=bool)
    if cov is not None:
        lc_t = int(cov.landcover[0])
        lc = cov.landcover[good_idx + 1]
        same = (lc == lc_t) if lc_t else np.ones(n, dtype=bool)
        if same.sum() >= min_pool:
            mask &= same
            counts["same_landcover"] = int(same.sum())
            notes.append(f"kept cells whose dominant land cover is {cov.label(0)} like the area")
        else:
            notes.append(f"only {int(same.sum())} cells share the area's land cover ({cov.label(0)}); "
                         f"land-cover filter relaxed")
        el = cov.elevation[good_idx + 1]; el_t = cov.elevation[0]
        if np.isfinite(el_t):
            near = np.abs(np.nan_to_num(el, nan=el_t) - el_t) <= elev_tol_m
            if (mask & near).sum() >= min_pool:
                mask &= near
                counts["similar_elevation"] = int((mask).sum())
                notes.append(f"kept cells within {elev_tol_m:.0f} m of the area's elevation ({el_t:.0f} m)")
            else:
                notes.append("elevation filter relaxed (too few cells would remain)")
    cand = np.where(mask)[0]
    order = cand[np.argsort(rmse[cand])]
    keep = order[:k]
    counts["kept"] = int(len(keep))
    notes.append(f"ranked by pre-event similarity; kept the best {len(keep)}")
    return DonorSelection(keep, rmse[keep], notes, counts)
