"""Sub-5m extractors: texture separates uniform parcels from patchy; all signals run."""
import numpy as np
import pytest

xr = pytest.importorskip("xarray")


def _cube(path, ny=60, nx=60, T=24):
    """Left third = UNIFORM high NDVI (managed); middle = PATCHY (weeds); right = bare."""
    rng = np.random.default_rng(2)
    times = np.array([np.datetime64("2021-01") + np.timedelta64(m, "M") for m in range(T)]
                     ).astype("datetime64[ns]")
    uni = np.zeros((ny, nx), bool); uni[:, : nx // 3] = True
    patch = np.zeros((ny, nx), bool); patch[:, nx // 3: 2 * nx // 3] = True
    bare = ~(uni | patch)

    def band(bu, bp, bb, patch_noise):
        b = np.zeros((T, ny, nx), np.float32)
        for t in range(T):
            b[t][uni] = bu
            b[t][patch] = bp
            b[t][bare] = bb
        b[:, patch] += rng.normal(0, patch_noise, b[:, patch].shape)   # patchy = noisy
        b += rng.normal(0, 25, b.shape)
        return np.clip(b, 0, 12000).astype("uint16")

    data = dict(B02=band(400, 420, 1500, 200), B03=band(700, 720, 1800, 200),
                B04=band(600, 1500, 2200, 600), B05=band(1400, 1500, 2300, 300),
                B06=band(2600, 2400, 2400, 300), B07=band(3000, 2800, 2450, 300),
                B08=band(3800, 3000, 2600, 900), B8A=band(3900, 3000, 2600, 900),
                B11=band(2000, 2100, 3200, 300), B12=band(1500, 1600, 3000, 300))
    nobs = np.full((T, ny, nx), 5, np.uint8)
    xr.Dataset({k: (("time", "y", "x"), v) for k, v in data.items()}
               | {"n_obs": (("time", "y", "x"), nobs)},
               coords=dict(time=times, y=np.arange(ny) * 10.0, x=np.arange(nx) * 10.0)
               ).to_zarr(path, mode="w")


def test_texture_separates_uniform_from_patchy(tmp_path):
    from src.field_signals import signal_dataset
    p = str(tmp_path / "c.zarr"); _cube(p)
    ds = signal_dataset(p, signal="texture_std", tile=20)
    # parcels in the left third (uniform) should have lower texture than the middle (patchy)
    left = [np.nanmean(f.ndvi) for f in ds.fields if f.lon < 200]
    mid = [np.nanmean(f.ndvi) for f in ds.fields if 200 <= f.lon < 400]
    assert np.nanmean(mid) > np.nanmean(left)


def test_all_signals_build_auditable_datasets(tmp_path):
    from src.field_signals import signal_dataset
    from src.contract import monthly_composite
    p = str(tmp_path / "c.zarr"); _cube(p)
    for sig in ("texture_std", "texture_contrast", "albedo", "perimeter_ratio"):
        ds = signal_dataset(p, signal=sig, tile=20)
        assert len(ds.fields) >= 4
        _, matrix, _ = monthly_composite(ds)
        assert matrix.shape[0] == len(ds.fields)
