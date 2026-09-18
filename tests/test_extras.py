"""Distribution-shape extractors + phenology extraction."""
import numpy as np
import pytest

xr = pytest.importorskip("xarray")


def _cube(path, ny=60, nx=60, T=24):
    """Left third uniform (low skew/bimodality), middle bimodal (two NDVI populations)."""
    rng = np.random.default_rng(5)
    times = np.array([np.datetime64("2021-01") + np.timedelta64(m, "M") for m in range(T)]
                     ).astype("datetime64[ns]")
    uni = np.zeros((ny, nx), bool); uni[:, : nx // 3] = True
    bim = np.zeros((ny, nx), bool); bim[:, nx // 3: 2 * nx // 3] = True

    def band(base):
        b = np.full((T, ny, nx), float(base), np.float32) + rng.normal(0, 20, (T, ny, nx))
        # make the middle third bimodal in B08/B04 (half pixels high, half low)
        half = np.zeros((ny, nx), bool); half[: ny // 2, :] = True
        b[:, bim & half] += 1400
        b[:, bim & ~half] -= 400
        return np.clip(b, 0, 12000).astype("uint16")

    data = dict(B02=band(400), B03=band(700), B04=band(800), B05=band(1400), B06=band(2600),
                B07=band(3000), B08=band(3200), B8A=band(3200), B11=band(2000), B12=band(1500))
    xr.Dataset({k: (("time", "y", "x"), v) for k, v in data.items()}
               | {"n_obs": (("time", "y", "x"), np.full((T, ny, nx), 5, np.uint8))},
               coords=dict(time=times, y=np.arange(ny) * 10.0, x=np.arange(nx) * 10.0)
               ).to_zarr(path, mode="w")


def test_bimodality_flags_split_fields(tmp_path):
    from src.field_signals import signal_dataset
    p = str(tmp_path / "c.zarr"); _cube(p)
    ds = signal_dataset(p, signal="texture_bimodality", tile=20)
    uni = [np.nanmean(f.ndvi) for f in ds.fields if f.lon < 200]
    bim = [np.nanmean(f.ndvi) for f in ds.fields if 200 <= f.lon < 400]
    assert np.nanmean(bim) > np.nanmean(uni)         # bimodal parcels score higher


def test_skew_extractor_runs(tmp_path):
    from src.field_signals import signal_dataset
    p = str(tmp_path / "c.zarr"); _cube(p)
    assert len(signal_dataset(p, signal="texture_skew", tile=20).fields) >= 4


def test_phenology_finds_peak_and_season():
    from src.phenology import extract_phenology
    dates = np.arange(np.datetime64("2021-01-01"), np.datetime64("2021-12-31"),
                      np.timedelta64(16, "D")).astype("datetime64[D]")
    doy = (dates - dates.astype("datetime64[Y]")).astype("timedelta64[D]").astype(int) + 1
    ndvi = 0.15 + 0.7 * np.exp(-((doy - 200.0) ** 2) / (2 * 40.0 ** 2))   # peak ~day 200
    ph = extract_phenology(ndvi, dates)[2021]
    assert 170 <= ph["pos"] <= 230                    # peak recovered near day 200
    assert ph["sos"] < ph["pos"] < ph["eos"]          # ordered
    assert ph["amplitude"] > 0.5
