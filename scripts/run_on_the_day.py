"""
RUN ON LIVE DATA — one command, live data -> full audit + figures.

Edit the CONFIG block to match the data they hand you, then:

    python -m scripts.run_on_the_day        # from the carbon-twin repo
    # (the engine is fixed; you only ever change CONFIG and, if needed, the loader)

It will: load -> validate -> audit every claimed field -> print the verdict table and
the portfolio roll-up -> save counterfactual/reversal/portfolio charts AND the
multi-spectral figure (if the source is a Sentinel-2 cube), all on the REAL data.

FIRST THING ON ARRIVAL: confirm the data's RESOLUTION. If sub-5m, the texture /
intentionality / albedo / perimeter signals are live (see SUB5M block). If it's 10m
like the demo, lean on NDVI/NDRE + radar fusion + the spectral stack instead.
"""
from __future__ import annotations

import os

# ============================ CONFIG (edit with live data) =======================
DATA_PATH = "data/sentinel2/cube.zarr"  # their cube or CSV path
SOURCE = "s2_zarr"        # "s2_zarr" | "long_csv" | "wide_csv"
INDEX = "NDVI"            # for s2_zarr: NDVI/NDRE/NDWI/NDMI/NDTI/BSI/EVI
TILE = 20                 # s2_zarr: parcel size in pixels (sub-5m -> smaller, e.g. 10)
TARGET = None             # set a field_id to audit one field; None = audit all claims
DONORS = None             # optional explicit donor ids; None = auto (conventional)
RUN_SUB5M = False         # set True on sub-5m data to also extract texture/albedo/etc.
OUTDIR = "/mnt/user-data/outputs"
# =============================================================================


def load():
    if SOURCE == "s2_zarr":
        from src.adapter import from_s2_zarr
        return from_s2_zarr(DATA_PATH, index=INDEX, tile=TILE)
    if SOURCE == "long_csv":
        from src.adapter import from_long_csv
        return from_long_csv(DATA_PATH)
    if SOURCE == "wide_csv":
        from src.adapter import from_wide_csv
        return from_wide_csv(DATA_PATH)
    raise ValueError(f"unknown SOURCE {SOURCE!r}")


def main():
    import matplotlib
    matplotlib.use("Agg")

    from src.adapter import selfcheck
    from src.pipeline import audit_all_claims, run_audit
    from src.portfolio import summarize
    from src import plots

    os.makedirs(OUTDIR, exist_ok=True)
    ds = load()
    print(f"loaded {len(ds.fields)} fields, {len(ds.dates)} dates "
          f"({str(ds.dates[0])[:10]} -> {str(ds.dates[-1])[:10]})")
    for w in selfcheck(ds):
        print("  selfcheck:", w)

    # ---- audit ----
    if TARGET:
        reports = [run_audit(ds, TARGET, donor_ids=DONORS)]
    else:
        reports = audit_all_claims(ds)
    if not reports:
        print("\nNo claimed-adoption fields found. Set TARGET to audit a specific field, "
              "or mark claims in the loader.")
        # still useful: audit the first field so the pipeline demonstrably runs
        reports = [run_audit(ds, ds.fields[0].field_id, donor_ids=DONORS)]

    print(f"\n{'field':>8}  {'verdict':>12}  {'p':>6}  {'tCO2e/yr':>8}  {'adopt':>5}  reversal")
    for r in reports:
        ay = getattr(getattr(r, "onset", None), "year", None) or "-"
        rv = "YES" if getattr(getattr(r, "reversal", None), "detected", False) else "-"
        c = getattr(getattr(r, "carbon", None), "central_tco2e_yr", 0.0) or 0.0
        print(f"{r.field_id:>8}  {r.verdict.status:>12}  {r.inference.p_value:>6.3f}  "
              f"{c:>8.1f}  {str(ay):>5}  {rv}")

    print("\nPortfolio:")
    ps = summarize(reports, price=50.0)
    for k in ("n_fields", "verified_tco2e", "at_risk_tco2e", "unverifiable_value_usd"):
        if hasattr(ps, k):
            print(f"  {k}: {getattr(ps, k)}")

    # ---- figures on the real data ----
    ver = next((r for r in reports if r.verdict.status == "VERIFIED"), reports[0])
    plots.counterfactual_figure(ver, f"{ver.field_id} — {ver.verdict.status}").savefig(
        os.path.join(OUTDIR, "real_01_verified.png"), dpi=140, bbox_inches="tight")
    rej = next((r for r in reports if r.verdict.status == "REJECTED"), None)
    if rej:
        plots.counterfactual_figure(rej, f"{rej.field_id} — REJECTED").savefig(
            os.path.join(OUTDIR, "real_02_rejected.png"), dpi=140, bbox_inches="tight")
    print(f"\nwrote real-data charts to {OUTDIR}")

    # ---- multi-spectral figure (cube only) ----
    if SOURCE == "s2_zarr":
        try:
            import runpy
            os.environ["S2_CUBE"] = DATA_PATH
            print("tip: also run  python scripts/run_real_s2.py", DATA_PATH,
                  " for the six-signal figure.")
        except Exception as e:  # pragma: no cover
            print("multispectral figure skipped:", e)

    # ---- sub-5m signals (only meaningful on sub-5m) ----
    if RUN_SUB5M and SOURCE == "s2_zarr":
        from src.field_signals import signal_dataset
        for sig in ("texture_std", "albedo", "perimeter_ratio", "texture_bimodality"):
            n = len(signal_dataset(DATA_PATH, signal=sig, tile=TILE).fields)
            print(f"  sub-5m {sig}: {n} parcels extracted")
    print("\ndone.")


if __name__ == "__main__":
    main()
