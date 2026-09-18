"""
=============================================================================
  THE ONLY FILE YOU WRITE ON LIVE DATA.
=============================================================================

Everything else in this repo is built and tested against the data contract
(src/contract.py). When Treefera hand over their real data on the 25th, your
single job is to fill in `load_treefera()` so it returns a `Dataset`. The
synthetic control, inference, carbon, audit, dashboard and tests then run
unchanged.

Keep it boring. Read their files, compute mean NDVI per field per date, align
everything to one date axis, attach the claim metadata, return a Dataset.

-----------------------------------------------------------------------------
If their data is raw imagery (GeoTIFFs / Sentinel-2 / PlanetScope)
-----------------------------------------------------------------------------
NDVI = (NIR - Red) / (NIR + Red).
  * Sentinel-2:  NIR = B8,  Red = B4
  * PlanetScope: NIR = band 4, Red = band 3
Per field polygon, per date: mask to the polygon, drop clouds (their QA band or
an SCL mask), take the MEAN NDVI over the polygon -> one number. Stack by date.

-----------------------------------------------------------------------------
If you need to pull Sentinel-2 yourself (your pre-25th homework, via Google
Earth Engine — this sandbox can't reach GEE, your laptop can):
-----------------------------------------------------------------------------
    import ee; ee.Initialize()
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(polygon).filterDate("2019-01-01", "2025-12-31")
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40)))

    def field_mean_ndvi(img):
        ndvi = img.normalizedDifference(["B8", "B4"]).rename("ndvi")
        # REDUCE SERVER-SIDE: one mean number per image, not the pixel array.
        stat = ndvi.reduceRegion(reducer=ee.Reducer.mean(), geometry=polygon, scale=10)
        return ee.Feature(None, {"date": img.date().format("YYYY-MM-dd"),
                                 "ndvi": stat.get("ndvi")})

    fc = s2.map(field_mean_ndvi).filter(ee.Filter.notNull(["ndvi"]))
    rows = fc.getInfo()["features"]          # tiny: ~150 rows/field, not 750k

    # !!! DO NOT use getRegion(polygon, 10): that downloads every pixel
    # (a 50 ha field ~ 5000 px x 150 dates ~ 750k rows/field) and will time out /
    # blow your RAM on the morning. reduceRegion(mean) returns ONE number per date.

Use S2_SR_HARMONIZED (it already corrects the S2A/S2B offset). For PlanetScope,
remember the PS2 -> PSB.SD transition mid-archive — our pipeline treats such a
common-mode shift as differenced-out by the synthetic control, but if only the
treated field switched you'd need to harmonise first.
-----------------------------------------------------------------------------
"""
from __future__ import annotations

import numpy as np

from .contract import Dataset, FieldSeries


def load_treefera(path: str) -> Dataset:
    """Read Treefera's data from `path` and return a Dataset.

    TODO(with live data): implement against whatever format they provide. Sketch:

        dates = <sorted unique observation dates as datetime64[D]>
        fields = []
        for each field polygon:
            ndvi = <mean NDVI per date, NaN where cloud/missing, aligned to dates>
            fields.append(FieldSeries(
                field_id=...,
                ndvi=ndvi,
                lat=..., lon=..., area_ha=...,
                claims_adoption=<from their claims table>,
                claimed_year=...,
                claimed_rate_tco2e_ha=...,   # if provided
            ))
        return Dataset(dates=dates, fields=fields)

    Defensive notes for live data:
      * if a field has very few cloud-free dates, the monthly composite will
        interpolate heavily — flag it (the audit will likely return INCONCLUSIVE).
      * if no no-claim donor fields exist, you can't build a counterfactual;
        surface that rather than forcing a fit.
    """
    raise NotImplementedError(
        "Fill load_treefera() with live data. The rest of the pipeline is ready and "
        "tested — see src/contract.py for the exact shape to return."
    )


def selfcheck(ds: Dataset) -> list[str]:
    """Cheap sanity checks to run the moment real data is loaded."""
    issues = []
    T = len(ds.dates)
    if T < 24:
        issues.append(f"only {T} dates — SCM wants a few years of history")
    if not ds.control_ids():
        issues.append("no no-claim donor fields — cannot build a counterfactual")
    for f in ds.fields:
        frac = float(np.mean(np.isnan(f.ndvi)))
        if frac > 0.6:
            issues.append(f"{f.field_id}: {frac:.0%} cloud gaps (heavy interpolation)")
        if np.nanmin(f.ndvi) < -0.2 or np.nanmax(f.ndvi) > 1.0:
            issues.append(f"{f.field_id}: NDVI out of [-1,1] — check band order")
    return issues


# ===========================================================================
#  CONCRETE, WORKING LOADERS  -- so with live data you pick the matching one and
#  tweak column names, instead of writing a parser from scratch under a clock.
#  The CSV loaders are fully tested (see tests/test_adapter.py). The GeoTIFF
#  loader is real rasterio code, guarded so an import can't break the app.
# ===========================================================================
import numpy as _np
import pandas as _pd


_META_COLS = ("lat", "lon", "area_ha", "claims_adoption", "claimed_year",
              "claimed_rate_tco2e_ha", "truth_label", "truth_year")


def _build_dataset(dates, per_field_ndvi, meta) -> Dataset:
    """Assemble a Dataset from aligned arrays. dates: sorted datetime64[D];
    per_field_ndvi: {fid: ndvi array aligned to dates}; meta: {fid: {...}}."""
    fields = []
    for fid, ndvi in per_field_ndvi.items():
        m = meta.get(fid, {})
        fields.append(FieldSeries(
            field_id=str(fid), ndvi=_np.asarray(ndvi, float),
            lat=float(m.get("lat", _np.nan)), lon=float(m.get("lon", _np.nan)),
            area_ha=float(m.get("area_ha", _np.nan)) if m.get("area_ha") is not None else float("nan"),
            claims_adoption=bool(m.get("claims_adoption", False)),
            claimed_year=(int(m["claimed_year"]) if m.get("claimed_year") not in (None, "", float("nan")) and not (isinstance(m.get("claimed_year"), float) and _np.isnan(m.get("claimed_year"))) else None),
            claimed_rate_tco2e_ha=(float(m["claimed_rate_tco2e_ha"]) if m.get("claimed_rate_tco2e_ha") not in (None, "") and not (isinstance(m.get("claimed_rate_tco2e_ha"), float) and _np.isnan(m.get("claimed_rate_tco2e_ha"))) else None),
            truth_label=(str(m["truth_label"]) if m.get("truth_label") not in (None, "") else None),
            truth_year=(int(m["truth_year"]) if m.get("truth_year") not in (None, "") and not (isinstance(m.get("truth_year"), float) and _np.isnan(m.get("truth_year"))) else None),
        ))
    return Dataset(dates=_np.asarray(dates, dtype="datetime64[D]"), fields=fields)


def from_long_csv(path: str, field_col="field_id", date_col="date",
                  ndvi_col="ndvi") -> Dataset:
    """Load a TIDY (long) CSV: one row per (field, date).

    Required columns: field_id, date, ndvi.
    Optional per-field metadata (first non-null value used): lat, lon, area_ha,
    claims_adoption, claimed_year, claimed_rate_tco2e_ha, truth_label, truth_year.

    This is the easiest target format: whatever Treefera hand you, coerce it into
    [field_id, date, ndvi] and you are done.
    """
    df = _pd.read_csv(path)
    df[date_col] = _pd.to_datetime(df[date_col])
    dates = _np.array(sorted(df[date_col].dt.normalize().unique()), dtype="datetime64[D]")
    date_index = {d: i for i, d in enumerate(dates)}

    per_field, meta = {}, {}
    for fid, g in df.groupby(field_col):
        arr = _np.full(len(dates), _np.nan)
        for d, v in zip(g[date_col].dt.normalize().to_numpy().astype("datetime64[D]"),
                        g[ndvi_col].to_numpy()):
            arr[date_index[d]] = v
        per_field[fid] = arr
        meta[fid] = {c: (g[c].dropna().iloc[0] if c in g and g[c].notna().any() else None)
                     for c in _META_COLS}
    return _build_dataset(dates, per_field, meta)


def from_wide_csv(path: str, field_col="field_id") -> Dataset:
    """Load a WIDE CSV: one row per field; date columns hold NDVI.

    Any column that parses as a date is treated as an observation; the remaining
    recognised columns (see _META_COLS) are metadata.
    """
    df = _pd.read_csv(path)
    date_cols, parsed = [], {}
    for c in df.columns:
        if c == field_col or c in _META_COLS:
            continue
        try:
            parsed[c] = _pd.to_datetime(c)
            date_cols.append(c)
        except (ValueError, TypeError):
            pass
    order = sorted(date_cols, key=lambda c: parsed[c])
    dates = _np.array([parsed[c].to_datetime64() for c in order], dtype="datetime64[D]")

    per_field, meta = {}, {}
    for _, row in df.iterrows():
        fid = row[field_col]
        per_field[fid] = _np.array([row[c] for c in order], float)
        meta[fid] = {c: (row[c] if c in df.columns and _pd.notna(row[c]) else None)
                     for c in _META_COLS}
    return _build_dataset(dates, per_field, meta)


def from_geotiff_stack(rasters: list, polygons: dict, nir_band: int = 4,
                       red_band: int = 3) -> Dataset:
    """Mean NDVI per polygon per date from a stack of GeoTIFFs (real rasterio).

    rasters  : list of (date, filepath) -- one multi-band image per date
    polygons : {field_id: shapely geometry} in the raster CRS
    Sentinel-2 NIR/Red = B8/B4; PlanetScope = band 4/3 (1-indexed).

    rasterio/shapely are heavy geo deps; we import lazily so the rest of the app
    never depends on them being installed.
    """
    import rasterio                       # noqa: heavy optional dep
    from rasterio.mask import mask as _mask

    dates = _np.array(sorted(d for d, _ in rasters), dtype="datetime64[D]")
    date_index = {d: i for i, d in enumerate(dates)}
    per_field = {fid: _np.full(len(dates), _np.nan) for fid in polygons}

    for d, fp in rasters:
        with rasterio.open(fp) as src:
            for fid, geom in polygons.items():
                try:
                    clip, _ = _mask(src, [geom], crop=True, filled=True)
                except Exception:
                    continue
                nir = clip[nir_band - 1].astype(float)
                red = clip[red_band - 1].astype(float)
                valid = (nir + red) > 0
                if valid.any():
                    ndvi = (nir[valid] - red[valid]) / (nir[valid] + red[valid])
                    per_field[fid][date_index[_np.datetime64(d, "D")]] = float(_np.mean(ndvi))
    return _build_dataset(dates, per_field, {fid: {} for fid in polygons})


def to_long_csv(dataset: Dataset, path: str) -> None:
    """Dump a Dataset to a tidy CSV (handy for sample/expected-format files)."""
    rows = []
    for f in dataset.fields:
        for d, v in zip(dataset.dates, f.ndvi):
            rows.append({"field_id": f.field_id, "date": _pd.Timestamp(d).date(),
                         "ndvi": v, "lat": f.lat, "lon": f.lon, "area_ha": f.area_ha,
                         "claims_adoption": f.claims_adoption,
                         "claimed_year": f.claimed_year,
                         "claimed_rate_tco2e_ha": f.claimed_rate_tco2e_ha})
    _pd.DataFrame(rows).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Real Sentinel-2 ingestion (Treefera demo cube -> our contract)
# ---------------------------------------------------------------------------
def from_s2_zarr(path: str, index: str = "NDVI", tile: int = 20,
                 claim_year: int | None = None) -> "Dataset":
    """Open a real Sentinel-2 Zarr cube and return a Dataset our engine can audit.

    Pipeline: open cube -> harmonise Baseline-04.00 (+1000 DN) -> compute the
    chosen spectral index -> tile the (y, x) grid into `tile`x`tile` parcels ->
    each parcel's spatial-mean index over time becomes a FieldSeries.

    The cube is a single scene (e.g. the NZ demo, which is forest/river, not
    farm fields), so tiling manufactures the *parcels* the SCM engine compares.
    With live data, an Iowa field cube flows through the identical path. `index` can
    be any signal from spectral.index_stack: NDVI, NDRE, NDWI, NDMI, NDTI, BSI, EVI.
    """
    import numpy as _np
    import xarray as _xr

    from .spectral import index_stack

    cube = _xr.open_zarr(path)
    stack = index_stack(cube)
    if index not in stack:
        raise ValueError(f"{index} unavailable; cube supports {list(stack)}")
    arr = stack[index]                                   # (T, ny, nx), NaN=nodata
    dates = cube["time"].values.astype("datetime64[D]")
    T, ny, nx = arr.shape

    # parcel-centre coordinates (projected x/y stored as lat/lon proxies)
    ys = cube["y"].values if "y" in cube.coords else _np.arange(ny)
    xs = cube["x"].values if "x" in cube.coords else _np.arange(nx)

    fields = []
    pid = 0
    for iy in range(0, ny - tile + 1, tile):
        for ix in range(0, nx - tile + 1, tile):
            block = arr[:, iy:iy + tile, ix:ix + tile]
            with _np.errstate(invalid="ignore"):
                series = _np.nanmean(block.reshape(T, -1), axis=1)   # NaN if all-nodata
            if _np.isfinite(series).sum() < max(4, T // 4):
                continue                                  # too cloudy to use
            fields.append(FieldSeries(
                field_id=f"P{pid:03d}",
                ndvi=series,                              # contract field holds any index
                lat=float(_np.mean(ys[iy:iy + tile])),
                lon=float(_np.mean(xs[ix:ix + tile])),
                area_ha=float((tile * 10) ** 2 / 1e4),    # 10 m pixels -> ha
                claims_adoption=False,
                truth_label=index))                       # tag which signal this is
            pid += 1
    return Dataset(dates=dates, fields=fields)
