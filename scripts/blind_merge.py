"""Merge several `scripts.blind_sample` draws into one sample file.

    python -m scripts.blind_merge --out showcase/blind/sample.json \
        showcase/blind/sample_hansen.json showcase/blind/sample_mtbs.json

Each source is a separate invocation of the same seeded sampler (one per
ground-truth dataset, because the datasets need different arguments and one
can fail without taking the others down). Every draw is independent: the
Hansen stages use `substream(seed, 1)` and `substream(seed, 2)`, MTBS uses
`substream(seed, 3)`, so drawing them separately gives exactly the items a
single combined run would have produced.

The merged file keeps the first draw's `criteria`/`hansen` blocks at the top
level (so `scripts.blind_validation` can still describe the sampling), lists
every draw under `draws`, and refuses to merge draws made with different
seeds or containing duplicate item ids -- a silent id collision would make
the results table ambiguous.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os


def merge(paths: list[str]) -> dict:
    draws, items, seeds = [], [], set()
    out: dict = {}
    for p in paths:
        with open(p) as f:
            d = json.load(f)
        seeds.add(d.get("seed"))
        if not out:
            out = {k: v for k, v in d.items() if k not in ("items", "n_items")}
        else:
            # keep whichever draw actually used a dataset, so the doc can describe both
            for key in ("hansen", "criteria"):
                if key in d and key not in out:
                    out[key] = d[key]
            st = out.setdefault("stats", {})
            for k, v in (d.get("stats") or {}).items():
                if k not in st or (isinstance(v, dict) and v.get("used")) or st.get(k) in (None, {}):
                    st[k] = v
        draws.append({"file": os.path.basename(p), "seed": d.get("seed"), "generated": d.get("generated"),
                      "git_commit": d.get("git_commit"), "command": d.get("command"),
                      "n_items": d.get("n_items"), "stats": d.get("stats")})
        items.extend(d.get("items", []))
    if len(seeds) > 1:
        raise SystemExit(f"refusing to merge draws with different seeds: {sorted(seeds)}")
    ids = [it["id"] for it in items]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise SystemExit(f"duplicate item ids across draws: {dupes[:5]}")
    out["items"] = items
    out["n_items"] = len(items)
    out["draws"] = draws
    out["merged"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = merge(a.sources)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    kinds = {}
    for it in out["items"]:
        kinds[(it["source"], it["kind"])] = kinds.get((it["source"], it["kind"]), 0) + 1
    print(f"wrote {a.out}: {out['n_items']} items ("
          + ", ".join(f"{v} {s} {k}s" for (s, k), v in sorted(kinds.items())) + ")")


if __name__ == "__main__":
    main()
