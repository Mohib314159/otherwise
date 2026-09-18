"""Run the verdict on the known-answer candidate sites (SITES.md) and write
showcase/<id>.json plus showcase/index.json. Sites stay 'candidate' until Mohib
confirms them; nothing here invents an expected answer without a source."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

from shapely.geometry import box, mapping

from src.app.run import run_verdict

SITES = [
    dict(key="grunheide", label="Grünheide, Germany: forest cleared for the Tesla factory",
         bbox=(13.789, 52.393, 13.797, 52.3975), event="2020-02-13", type="clearing", post=12,
         expected="REAL", source="https://www.pv-magazine.com/2020/02/17/court-stops-tree-clearance-for-teslas-proposed-berlin-gigafactory/",
         blurb="About 92 ha of pine forest felled in February 2020."),
    dict(key="rhodes", label="Rhodes, Greece: July 2023 wildfire",
         bbox=(27.915, 36.085, 27.925, 36.095), event="2023-07-18", type="burn", post=6,
         expected="REAL", source="https://mapping.emergency.copernicus.eu/news/information-bulletin-169-the-copernicus-emergency-management-service-maps-some-critical-wildfires-in-greece-update/",
         blurb="Copernicus EMS mapped 17,629 ha burnt from 18 July 2023."),
    dict(key="saddleworth", label="Saddleworth Moor, England: June 2018 moorland fire",
         bbox=(-2.012, 53.515, -1.998, 53.524), event="2018-06-24", type="burn", post=6,
         expected="REAL", source="https://en.wikipedia.org/wiki/2018_United_Kingdom_wildfires",
         blurb="Moorland fire from 24 June 2018 that grew to about 8 km² by 27 June."),
    dict(key="sindh", label="Sindh, Pakistan: 2022 monsoon floods near Lake Manchar",
         bbox=(67.745, 27.095, 67.755, 27.105), event="2022-08-25", type="flood", post=3,
         expected="REAL", source="https://earthobservatory.nasa.gov/images/150306/lake-manchar-is-overflowing",
         blurb="Lake Manchar grew from 334 to 512 km² between 11 and 26 August 2022."),
    dict(key="austin", label="Austin, Texas: Tesla Gigafactory built on a gravel-pit site",
         bbox=(-97.625, 30.221, -97.615, 30.226), event="2020-07-22", type="construction", post=12,
         expected="REAL", source="https://en.wikipedia.org/wiki/Gigafactory_Texas",
         blurb="Construction began in July 2020 on a former sand and gravel mine by the Colorado River."),
    dict(key="lutzerath", label="Lützerath, Germany: village and fields taken by the Garzweiler mine",
         bbox=(6.412, 51.055, 6.424, 51.061), event="2023-01-11", type="clearing", post=12,
         expected="REAL", source="https://en.wikipedia.org/wiki/L%C3%BCtzerath",
         blurb="The village was cleared from 11 January 2023 and excavated for lignite during 2023."),
    dict(key="tablemountain", label="Cape Town: April 2021 Table Mountain fire",
         bbox=(18.452, -33.955, 18.462, -33.947), event="2021-04-18", type="burn", post=6,
         expected="REAL", source="https://en.wikipedia.org/wiki/2021_Table_Mountain_fire",
         blurb="Fire from 18 April 2021 that burnt about 600 ha of fynbos and buildings."),
    dict(key="hasankeyf", label="Hasankeyf, Turkey: old town flooded by the Ilısu reservoir",
         bbox=(41.405, 37.711, 41.415, 37.716), event="2020-01-05", type="flood", post=6,
         expected="REAL", source="https://earthobservatory.nasa.gov/images/146439/slowly-flooding-history",
         blurb="The Ilısu reservoir, filling since July 2019, reached the town in early January 2020."),
    dict(key="richmond", label="Richmond Park, London: nothing documented",
         bbox=(-0.280, 51.440, -0.270, 51.446), event="2022-06-01", type="clearing", post=12,
         expected="NOT_REAL", source="", blurb="A protected grassland with no documented change; a false-alarm check."),
    dict(key="jau", label="Jaú National Park, Brazil: nothing documented",
         bbox=(-62.605, -1.905, -62.595, -1.895), event="2022-06-01", type="clearing", post=12,
         expected="NOT_REAL", source="", blurb="Primary forest interior with no documented clearing; a false-alarm check."),
]


def main(keys=None):
    index_path = "showcase/index.json"
    index = json.load(open(index_path)) if os.path.exists(index_path) else []
    for s in SITES:
        if keys and s["key"] not in keys:
            continue
        geo = mapping(box(*s["bbox"]))
        t = time.time()
        print(f"== {s['key']} ({s['type']} {s['event']})", flush=True)
        try:
            out = run_verdict(geo, s["event"], s["type"], s["post"], label=s["label"],
                              progress=lambda st, d, tt: None, save=True, runs_dir="showcase")
        except Exception as e:
            traceback.print_exc()
            continue
        v = out["verdict"]
        lead = v["lead_signal"]
        sig = out["signals"].get(lead, {})
        print(f"   {v['status']:9s} {lead} point={sig.get('point', float('nan')):+.3f} "
              f"[{sig.get('lo', float('nan')):+.3f},{sig.get('hi', float('nan')):+.3f}] placebo p={sig.get('placebo_p', float('nan')):.3f} "
              f"n_pre={sig.get('n_pre')} n_post={sig.get('n_post')} donors={sig.get('n_donors')} "
              f"pre_rmse={sig.get('pre_rmse', float('nan')):.3f} {time.time() - t:.0f}s", flush=True)
        print("   ", v["statement"], flush=True)
        try:
            from src.app.imagery import make_thumbnails
            info = make_thumbnails(geo, s["event"], "showcase", out["id"])
            for tag, meta in info.items():
                json.dump(meta, open(f"showcase/{out['id']}_{tag}.json", "w"))
            print("    imagery:", {k: v_["date"] for k, v_ in info.items()}, flush=True)
        except Exception:
            traceback.print_exc()
        index = [e for e in index if e.get("key") != s["key"]]
        index.append({"key": s["key"], "id": out["id"], "label": s["label"], "blurb": s["blurb"],
                      "expected": s["expected"], "source": s["source"], "type": s["type"],
                      "confirmed": False})
        json.dump(index, open(index_path, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
