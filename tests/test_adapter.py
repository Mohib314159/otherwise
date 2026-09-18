"""The day-of path: raw file -> adapter -> Dataset -> pipeline, end to end."""
import os
import numpy as np
from src.synth_data import generate
from src.adapter import to_long_csv, from_long_csv, from_wide_csv
from src.pipeline import run_audit


def _by_truth(ds):
    out = {}
    for f in ds.fields:
        out.setdefault(f.truth_label, f.field_id)
    return out


def test_long_csv_roundtrip_runs_full_pipeline(tmp_path):
    ds = generate(seed=7)
    p = os.path.join(tmp_path, "ndvi_long.csv")
    to_long_csv(ds, p)

    loaded = from_long_csv(p)
    assert len(loaded.dates) == len(ds.dates)
    assert set(loaded.ids) == set(ds.ids)

    bt = _by_truth(ds)
    adopter = run_audit(loaded, bt["adopter"])
    liar = run_audit(loaded, bt["liar"])
    assert adopter.verdict.status == "VERIFIED"
    assert liar.verdict.status == "REJECTED"


def test_loaded_ndvi_matches_source(tmp_path):
    ds = generate(seed=7)
    p = os.path.join(tmp_path, "ndvi_long.csv")
    to_long_csv(ds, p)
    loaded = from_long_csv(p)
    a = ds.by_id("F00").ndvi
    b = loaded.by_id("F00").ndvi
    both = ~(np.isnan(a) | np.isnan(b))
    assert np.allclose(a[both], b[both], atol=1e-6)


def test_metadata_survives_the_adapter(tmp_path):
    ds = generate(seed=7)
    p = os.path.join(tmp_path, "ndvi_long.csv")
    to_long_csv(ds, p)
    loaded = from_long_csv(p)
    # a claimant stays a claimant with its claimed year
    claimant = next(f for f in ds.fields if f.claims_adoption)
    lc = loaded.by_id(claimant.field_id)
    assert lc.claims_adoption is True
    assert lc.claimed_year == claimant.claimed_year
