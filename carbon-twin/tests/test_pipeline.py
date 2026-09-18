"""End-to-end: the method recovers planted ground truth on synthetic data."""
from src.synth_data import generate
from src.pipeline import run_audit


def test_adopter_verified_and_liar_rejected():
    ds = generate(seed=7)
    by_truth = {}
    for f in ds.fields:
        by_truth.setdefault(f.truth_label, f.field_id)
    adopter = run_audit(ds, by_truth["adopter"])
    liar = run_audit(ds, by_truth["liar"])
    assert adopter.verdict.status == "VERIFIED"
    assert liar.verdict.status == "REJECTED"
    # never credit the liar
    assert liar.carbon.central_tco2e_yr == 0.0


def test_no_control_is_credited():
    ds = generate(seed=7)
    for f in ds.fields:
        if f.truth_label == "control":
            rep = run_audit(ds, f.field_id)
            assert rep.verdict.status != "VERIFIED"


def test_spatial_buffer_excludes_near_donors():
    from src.contract import haversine_m
    ds = generate(seed=7)
    fid = next(f.field_id for f in ds.fields if f.truth_label == "adopter")
    base = run_audit(ds, fid)
    buf = run_audit(ds, fid, buffer_m=900)
    # buffer never adds donors, and removes at least the ones within range
    assert len(buf.scm.donor_ids) <= len(base.scm.donor_ids)
    t = ds.by_id(fid)
    for d in buf.scm.donor_ids:
        f = ds.by_id(d)
        dist = haversine_m(t.lat, t.lon, f.lat, f.lon)
        assert (dist >= 900) or (dist != dist)  # kept only if >=buffer or unknown
    # still produces a valid verdict
    assert buf.verdict.status in {"VERIFIED", "PARTIAL", "INCONCLUSIVE", "REJECTED", "BASELINE"}
