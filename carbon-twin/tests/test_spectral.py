"""Multi-spectral extraction on a synthetic cube matching the Treefera S2 format.

Validates: Baseline-04.00 harmonisation removes the +1000 step; the index stack
computes sensible values; from_s2_zarr tiles a cube into auditable parcels.
"""
import numpy as np
import pytest

xr = pytest.importorskip("xarray")


def _make_cube(path, ny=60, nx=60, T=24):
    """Synthetic S2 cube: uint16 bands, n_obs, monthly, +1000 step at 2022-01-25."""
    rng = np.random.default_rng(0)
    times = np.array([np.datetime64("2021-01") + np.timedelta64(m, "M") for m in range(T)]
                     ).astype("datetime64[ns]")
    post = (times.astype("datetime64[D]") >= np.datetime64("2022-01-25"))

    # three land types across the scene: vegetation / water / bare soil
    veg = np.zeros((ny, nx), bool); veg[:, : nx // 3] = True
    water = np.zeros((ny, nx), bool); water[:, nx // 3: 2 * nx // 3] = True
    bare = ~(veg | water)

    def band(base_veg, base_water, base_bare, season=0.0):
        b = np.zeros((T, ny, nx), np.float32)
        for t in range(T):
            s = 1.0 + season * np.sin(2 * np.pi * (t % 12) / 12.0)
            b[t][veg] = base_veg * s
            b[t][water] = base_water
            b[t][bare] = base_bare
        b += rng.normal(0, 40, b.shape)
        b[post] += 1000.0                       # the artefact we must remove
        return np.clip(b, 0, 12000).astype("uint16")

    data = dict(
        B02=band(400, 600, 1500), B03=band(700, 900, 1800), B04=band(600, 500, 2200, 0.2),
        B05=band(1400, 450, 2300), B06=band(2600, 430, 2400), B07=band(3000, 420, 2450),
        B08=band(3800, 300, 2600, 0.3), B8A=band(3900, 300, 2600),
        B11=band(2000, 200, 3200), B12=band(1500, 180, 3000),
    )
    nobs = np.full((T, ny, nx), 5, np.uint8)
    nobs[rng.random((T, ny, nx)) < 0.1] = 0      # scattered nodata
    ds = xr.Dataset({k: (("time", "y", "x"), v) for k, v in data.items()}
                    | {"n_obs": (("time", "y", "x"), nobs)},
                    coords=dict(time=times, y=np.arange(ny) * 10.0, x=np.arange(nx) * 10.0))
    ds.to_zarr(path, mode="w")
    return veg


def test_harmonisation_removes_baseline_step(tmp_path):
    from src.spectral import index_stack
    p = str(tmp_path / "cube.zarr")
    veg = _make_cube(p)
    cube = xr.open_zarr(p)
    ndvi = index_stack(cube)["NDVI"]              # (T, y, x), harmonised
    veg_ndvi = np.nanmean(ndvi.reshape(ndvi.shape[0], -1)[:, veg.reshape(-1)], axis=1)
    pre, post = veg_ndvi[:12], veg_ndvi[12:]
    # without harmonisation the post step would crater NDVI; check it stays close
    assert abs(np.nanmean(post) - np.nanmean(pre)) < 0.06
    assert np.nanmean(veg_ndvi) > 0.4            # vegetation reads green


def test_index_stack_has_all_signals_in_range(tmp_path):
    from src.spectral import index_stack
    p = str(tmp_path / "cube.zarr"); _make_cube(p)
    stack = index_stack(xr.open_zarr(p))
    for name in ("NDVI", "NDRE", "NDWI", "NDMI", "NDTI", "BSI", "EVI"):
        assert name in stack
        vals = stack[name][np.isfinite(stack[name])]
        assert vals.min() >= -1.5 and vals.max() <= 1.5


def test_from_s2_zarr_tiles_into_auditable_parcels(tmp_path):
    from src.adapter import from_s2_zarr
    from src.contract import Dataset, monthly_composite
    p = str(tmp_path / "cube.zarr"); _make_cube(p)
    ds = from_s2_zarr(p, index="NDVI", tile=20)
    assert isinstance(ds, Dataset) and len(ds.fields) >= 4
    md, matrix, observed = monthly_composite(ds)        # builds a usable panel
    assert matrix.shape[0] == len(ds.fields)
