"""
Multi-spectral extraction from the REAL Treefera Sentinel-2 demo cube.

Self-contained: drop this file next to the example notebooks (the folder that
holds `data/`) and run it in the demo env:

    uv run python run_real_s2.py
    # or: python run_real_s2.py  /path/to/sentinel2/cube.zarr

It opens the cube, applies the Baseline-04.00 harmonisation (+1000 DN step at
2022-01-25), masks n_obs==0, and extracts a STACK of physical signals from one
cube of raw bands:

    NDVI  greenness/biomass   NDRE red-edge stress   NDWI water
    NDMI  veg moisture (SWIR)  NDTI tillage/residue   BSI bare soil

It saves `s2_multispectral.png`: the index maps for the clearest month + the
harmonised seasonal time series. This is the "we abuse the whole spectrum, on
your real data" artefact — every one of these signals feeds the same engine.
"""
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import xarray as xr

OPTICAL = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
CUTOVER = np.datetime64("2022-01-25")


def harmonise(cube):
    times = cube["time"].values.astype("datetime64[D]")
    post = (times >= CUTOVER)[:, None, None]
    nodata = cube["n_obs"].values == 0
    R = {}
    for b in OPTICAL:
        if b in cube:
            dn = cube[b].values.astype("float32")
            dn = np.where(post, np.clip(dn - 1000.0, 0, None), dn)
            r = dn / 10000.0
            r[nodata] = np.nan
            R[b] = r
    return R


def nd(a, b):
    d = a + b
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(d != 0, (a - b) / d, np.nan)


def stack(cube):
    R = harmonise(cube); g = R.get
    s = {"NDVI": nd(g("B08"), g("B04")), "NDRE": nd(g("B08"), g("B05")),
         "NDWI": nd(g("B03"), g("B08")), "NDMI": nd(g("B08"), g("B11")),
         "NDTI": nd(g("B11"), g("B12"))}
    num = (g("B11") + g("B04")) - (g("B08") + g("B02"))
    den = (g("B11") + g("B04")) + (g("B08") + g("B02"))
    with np.errstate(invalid="ignore", divide="ignore"):
        s["BSI"] = np.where(den != 0, num / den, np.nan)
    return s


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/sentinel2/cube.zarr"
    if not Path(path).exists():
        sys.exit(f"cube not found: {path}\npass the path: python run_real_s2.py <cube.zarr>")
    cube = xr.open_zarr(path)
    times = cube["time"].values.astype("datetime64[D]")
    s = stack(cube)

    # clearest PRE-2022 month for the maps (radiometrically safe stretch)
    nobs = cube["n_obs"].values
    clear = nobs.reshape(nobs.shape[0], -1).mean(1)
    clear = np.where(times < np.datetime64("2022-01-01"), clear, -1)
    t = int(np.argmax(clear))
    month = str(times[t])[:7]

    maps = ["NDVI", "NDRE", "NDWI", "NDTI"]
    cmaps = {"NDVI": "RdYlGn", "NDRE": "RdYlGn", "NDWI": "Blues", "NDTI": "YlOrBr"}
    fig = plt.figure(figsize=(13, 7.5))
    for i, name in enumerate(maps):
        ax = fig.add_subplot(2, 4, i + 1)
        im = ax.imshow(s[name][t], cmap=cmaps[name], vmin=-0.5, vmax=0.9)
        ax.set_title(f"{name} — {month}", fontsize=11, fontweight="bold")
        ax.axis("off"); fig.colorbar(im, ax=ax, shrink=0.7)

    ax = fig.add_subplot(2, 1, 2)
    for name in ["NDVI", "NDRE", "NDWI", "NDMI", "NDTI", "BSI"]:
        series = np.nanmean(s[name].reshape(s[name].shape[0], -1), axis=1)
        ax.plot(times, series, marker="o", ms=3, lw=1.4, label=name)
    ax.axvline(CUTOVER, color="0.5", ls="--", lw=1, label="baseline 04.00 (harmonised)")
    ax.set_title("Six physical signals from one cube — harmonised monthly means (real Sentinel-2)",
                 fontsize=12, fontweight="bold")
    ax.set_ylabel("index value"); ax.grid(alpha=0.3)
    ax.legend(ncol=7, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.suptitle("CarbonTwin — multi-spectral extraction from real Treefera Sentinel-2 data",
                 fontsize=13.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig("s2_multispectral.png", dpi=140, bbox_inches="tight")
    print(f"selected month: {month}")
    print(f"extracted signals: {list(s)}")
    print("wrote s2_multispectral.png")


if __name__ == "__main__":
    main()
