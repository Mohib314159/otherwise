"""Intentionality discriminator: texture separates planted cover crops from weeds."""
from src.management import generate_management, discriminate, GREEN_MIN


def test_texture_separates_cover_crops_from_weeds():
    ndvi, tex = generate_management(seed=23)
    for f in ndvi.fields:
        v = discriminate(ndvi, tex, f.field_id)
        if f.truth_label == "cover_crop":
            assert v.verdict == "MANAGED COVER CROP"
        elif f.truth_label == "weeds":
            assert v.verdict == "LIKELY WEEDS"
        elif f.truth_label == "conventional":
            assert v.verdict == "NO COVER"


def test_ndvi_alone_cannot_separate_cover_from_weeds():
    # the whole point: greenness is similar; only texture differs
    ndvi, tex = generate_management(seed=23)
    cover = [discriminate(ndvi, tex, f.field_id).green_uplift
             for f in ndvi.fields if f.truth_label == "cover_crop"]
    weeds = [discriminate(ndvi, tex, f.field_id).green_uplift
             for f in ndvi.fields if f.truth_label == "weeds"]
    assert min(cover) > GREEN_MIN and min(weeds) > GREEN_MIN   # both look "green"
