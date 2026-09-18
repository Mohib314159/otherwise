"""Second worked example (Theme E): same engine detects aquifer abandonment."""
from src.scenarios import generate_aquifer, audit_circle


def test_abandoned_circles_detected_with_correct_year():
    ds = generate_aquifer(seed=11)
    for f in ds.fields:
        if f.truth_label == "abandoned":
            r = audit_circle(ds, f.field_id)
            assert r.collapse_detected is True
            assert r.collapse_year == f.truth_year
            assert r.p_value < 0.05
            assert r.ndvi_lost > 0.3


def test_active_circles_not_flagged():
    ds = generate_aquifer(seed=11)
    flagged = sum(audit_circle(ds, f.field_id).collapse_detected
                  for f in ds.fields if f.truth_label == "active")
    assert flagged == 0


def test_disease_red_edge_detects_before_ndvi():
    from src.scenarios import generate_disease, audit_disease
    ndre, ndvi = generate_disease(seed=13)
    for f in ndre.fields:
        if f.truth_label == "infected":
            re = audit_disease(ndre, f.field_id)
            vi = audit_disease(ndvi, f.field_id)
            assert re.detected is True and re.p_value < 0.05
            assert re.onset_week is not None and vi.onset_week is not None
            # red-edge flags it no later than NDVI (the pre-symptomatic lead)
            assert re.onset_week <= vi.onset_week


def test_disease_no_false_positive_on_healthy():
    from src.scenarios import generate_disease, audit_disease
    ndre, _ = generate_disease(seed=13)
    flagged = sum(audit_disease(ndre, f.field_id).detected
                  for f in ndre.fields if f.truth_label == "healthy")
    assert flagged == 0
