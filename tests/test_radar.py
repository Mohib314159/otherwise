"""Dual-channel fusion: optical detects cover crops (2021), radar detects no-till (2023)."""
from src.radar import generate_regen_dual, audit_fusion


def test_fusion_detects_both_transitions_for_regen_fields():
    ndvi, till = generate_regen_dual(seed=17)
    for f in ndvi.fields:
        if f.truth_label == "full_regen":
            r = audit_fusion(ndvi, till, f.field_id)
            assert r.cover_year == 2021 and r.cover_p < 0.05
            assert r.notill_year == 2023 and r.notill_p < 0.05


def test_conventional_fields_show_neither_transition():
    ndvi, till = generate_regen_dual(seed=17)
    for f in ndvi.fields:
        if f.truth_label == "conventional":
            r = audit_fusion(ndvi, till, f.field_id)
            assert r.cover_year is None
            assert r.notill_year is None
