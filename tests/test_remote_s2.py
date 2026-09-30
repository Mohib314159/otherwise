"""Server-side control reads (src/app/remote_s2.py): expression builder, offset
handling, the 16-bit PNG code, window/grid rules and the zonal reduction.

No network. The titiler expression is numexpr, which parses with Python's own
grammar, so evaluating it with numpy bound to the same names checks both the
syntax and the arithmetic against the local path in s2.py.
"""
import numpy as np
import pytest
from rasterio import Affine
from shapely.geometry import box

from src.app import remote_s2 as R
from src.app.extract import Zones, labels_for, zone_means
from src.app.s2 import CLEAR_MIN, SCL_CLEAR, _nd, reflectance


def _eval(expr: str, bands: dict) -> list[np.ndarray]:
    env = {f"{k}_b1": v for k, v in bands.items()}
    env.update(where=np.where, floor=np.floor)
    with np.errstate(invalid="ignore", divide="ignore"):
        return [np.asarray(eval(part, {"__builtins__": {}}, env), dtype="float64")
                for part in expr.split(";")]


def _bands(seed=0, n=4000):
    rng = np.random.default_rng(seed)
    b = {k: rng.integers(0, 6000, n).astype("uint16") for k in ("B03", "B04", "B08", "B12")}
    b["B04"][:50] = 0; b["B08"][:50] = 0            # undefined index (a + b = 0)
    b["B04"][50:100] = 900; b["B08"][50:100] = 950  # both below the offset
    b["SCL"] = rng.integers(0, 12, n).astype("uint8")
    return b


def _local(bands, index, baseline):
    r = {k: reflectance(bands[k], baseline) for k in ("B03", "B04", "B08", "B12")}
    a, b = R.INDEX_BANDS[index]
    return _nd(r[a], r[b]), np.isin(bands["SCL"], SCL_CLEAR)


@pytest.mark.parametrize("baseline", ["05.10", "04.00", "03.01", "02.14", None, "junk"])
@pytest.mark.parametrize("index", ["NDVI", "NDWI", "NBR"])
def test_expression_matches_local_reflectance_and_index(baseline, index):
    bands = _bands()
    hi, lo = _eval(R.build_expression(baseline, (index,)), bands)
    assert hi.min() >= 0 and hi.max() <= 255 and lo.min() >= 0 and lo.max() <= 255
    assert np.all(hi == np.floor(hi)) and np.all(lo == np.floor(lo))
    v, clear = R.decode_codes(hi.astype("uint8"), lo.astype("uint8"))
    ref, ref_clear = _local(bands, index, baseline)
    assert np.array_equal(clear, ref_clear)
    usable = ref_clear & np.isfinite(ref)
    assert np.array_equal(np.isfinite(v), usable)
    assert np.max(np.abs(v[usable] - ref[usable])) <= 0.5 / R.SCALE + 1e-6    # local path is float32


def test_offset_only_from_baseline_04():
    assert "1000.0" in R.band_term("B08", "04.00")
    assert "1000.0" in R.band_term("B08", "05.11")
    assert "1000.0" not in R.band_term("B08", "03.01")
    assert "1000.0" not in R.band_term("B08", None)


def test_offset_clips_at_zero_not_negative():
    bands = {k: np.array([500, 1000, 1500], dtype="uint16") for k in ("B04", "B08")}
    out = _eval(R.band_term("B08", "05.00"), bands)[0]
    assert out.tolist() == [0.0, 0.0, 500.0]


def test_offset_changes_the_index():
    # the same DN give a different NDVI with and without the offset
    bands = {"B04": np.array([1500], dtype="uint16"), "B08": np.array([3000], dtype="uint16"),
             "SCL": np.array([4], dtype="uint8")}
    hi, lo = _eval(R.build_expression("05.00", ("NDVI",)), bands)
    v_off = R.decode_codes(hi.astype("uint8"), lo.astype("uint8"))[0][0]
    hi, lo = _eval(R.build_expression("03.00", ("NDVI",)), bands)
    v_raw = R.decode_codes(hi.astype("uint8"), lo.astype("uint8"))[0][0]
    assert v_off == pytest.approx((2000 - 500) / 2500, abs=1e-4)
    assert v_raw == pytest.approx((3000 - 1500) / 4500, abs=1e-4)


def test_codes_reserve_cloud_undefined_and_server_mask():
    hi = np.array([255, 255, 0, 0, 250], dtype="uint8")
    lo = np.array([255, 254, 0, 1, 0], dtype="uint8")
    v, clear = R.decode_codes(hi, lo)
    assert clear.tolist() == [False, True, False, True, True]
    assert np.isnan(v[0]) and np.isnan(v[1]) and np.isnan(v[2])   # cloud, undefined, server-masked
    assert v[3] == -1.0 and v[4] == pytest.approx((250 * 256 - 1) / R.SCALE - 1.0)
    assert R.encode_value(-1.0) == 1 and R.encode_value(1.0) == 2 * R.SCALE + 1 < R.CODE_UNDEF


def test_a_genuine_minus_one_is_not_confused_with_the_server_mask():
    bands = {"B04": np.array([500], dtype="uint16"), "B08": np.array([0], dtype="uint16"),
             "SCL": np.array([4], dtype="uint8")}
    hi, lo = _eval(R.build_expression("02.14", ("NDVI",)), bands)
    v, clear = R.decode_codes(hi.astype("uint8"), lo.astype("uint8"))
    assert clear[0] and v[0] == -1.0


def test_expression_limits_and_band_count():
    assert R.build_expression("05.00", ("NDVI",)).count(";") == 1
    assert R.build_expression("05.00", ("NDVI", "NBR")).count(";") == 3
    with pytest.raises(ValueError):
        R.build_expression("05.00", ("NDVI", "NDWI", "NBR"))
    p = R.request_params("X", 32630, "e", 4)
    assert [v for k, v in p if k == "rescale"] == ["0,255"] * 4
    assert ("dst_crs", "epsg:32630") in p and ("coord_crs", "epsg:32630") in p
    assert ("resampling", "nearest") in p


def test_assets_referenced_are_the_ones_the_index_needs():
    e = R.build_expression("05.00", ("NBR",))
    assert "B08_b1" in e and "B12_b1" in e and "SCL_b1" in e and "B04_b1" not in e


def test_output_grid_matches_local_decimated_read_rounding():
    # 24 600 m x 25 260 m window at 10 m = 2460 x 2526 px -> 615 x 631.5 -> 632
    assert R.output_grid((677400.0, 5689980.0, 702000.0, 5715240.0), 40.0) == (615, 632)
    # same answer from the 20 m SCL (1230 x 1263 px, x0.5)
    assert R.output_grid((677400.0, 5689980.0, 702000.0, 5715240.0), 40.0, 20.0) == (615, 632)


def test_clip_bounds_to_tile():
    tile = (600000.0, 5690220.0, 709800.0, 5800020.0)
    assert R.clip_bounds((677400.0, 5689980.0, 702000.0, 5715240.0), tile) == \
        (677400.0, 5690220.0, 702000.0, 5715240.0)
    assert R.clip_bounds((0, 0, 1, 1), tile) is None
    assert R.clip_bounds((1, 2, 3, 4), None) == (1, 2, 3, 4)


def test_label_transform_is_the_local_convention():
    t = R.label_transform((100.0, 200.0, 500.0, 900.0), 40.0)
    assert t == Affine(40.0, 0.0, 100.0, 0.0, -40.0, 900.0)


def test_reduce_cells_matches_extract_zone_means_and_clear_rule():
    cells = [box(0, 0, 400, 400), box(400, 0, 800, 400), box(0, 400, 400, 800)]
    zones = Zones(cells, 32630, (0.0, 0.0, 800.0, 800.0))
    tr = R.label_transform(zones.bounds, 40.0)
    labels = labels_for(zones, tr, (20, 20))
    rng = np.random.default_rng(1)
    vals = rng.uniform(-1, 1, (20, 20))
    clear = rng.uniform(0, 1, (20, 20)) < 0.9
    clear[:10, :10] = False                           # cell 3 (top-left) cloudy
    vals_masked = np.where(clear, vals, np.nan)
    vals_masked[15, 15] = np.nan                      # clear but undefined
    means, cf, n_px = R.reduce_cells([vals_masked], clear, labels, 3)
    ref, _, n_tot = zone_means(np.nan_to_num(vals_masked), np.isfinite(vals_masked), labels, 3)
    assert np.allclose(means[0], ref, equal_nan=True)
    assert n_px.tolist() == n_tot.tolist() == [100, 100, 100]
    assert cf[2] == 0.0 and cf[0] > CLEAR_MIN - 0.2


def test_item_fields_from_stac_dict_and_scene():
    it = {"id": "S2X", "properties": {"s2:processing_baseline": "05.10", "proj:code": "EPSG:32630"},
          "assets": {"SCL": {"proj:bbox": [1, 2, 3, 4]}}}
    assert R.item_fields(it) == ("S2X", "05.10", 32630, (1, 2, 3, 4))
    from datetime import datetime, timezone
    from src.app.providers import Scene
    sc = Scene("S2Y", "S2", datetime(2020, 1, 1, tzinfo=timezone.utc), {}, {"baseline": "02.14"}, epsg=32631)
    assert R.item_fields(sc) == ("S2Y", "02.14", 32631, None)


def test_process_scene_remote_keeps_the_process_scene_contract(monkeypatch):
    from datetime import datetime, timezone
    from src.app.providers import Scene
    zones = Zones([box(0, 0, 400, 400), box(400, 0, 800, 400)], 32630, (0.0, 0.0, 800.0, 800.0))
    sc = Scene("S2Z", "S2", datetime(2021, 5, 1, 10, 30, tzinfo=timezone.utc), {}, {"baseline": "05.00"},
               epsg=32630)

    def fake(scene, epsg, polys, res, index, zones):
        return R.SceneCells(scene.id, {"NDVI": np.array([0.5, np.nan])}, np.array([0.9, 0.2]), np.array([100, 100]))
    monkeypatch.setattr(R, "fetch_scene_cells", fake)
    obs, rec = R.process_scene_remote(sc, zones)
    assert rec is None and obs.values["NDVI"][0] == 0.5
    assert set(obs.values) == {"NDVI", "NDWI", "NBR"} and np.all(np.isnan(obs.values["NBR"]))
    assert obs.minute_key == "2021-05-01T10:30"

    def cloudy(scene, epsg, polys, res, index, zones):
        return R.SceneCells(scene.id, {"NDVI": np.array([np.nan, np.nan])}, np.array([0.5, 0.1]), np.array([100, 100]))
    monkeypatch.setattr(R, "fetch_scene_cells", cloudy)
    obs, rec = R.process_scene_remote(sc, zones)
    assert obs is None and rec.reason == "cloud"
    with pytest.raises(ValueError):
        R.process_scene_remote(sc, zones, require_zone0=True)
