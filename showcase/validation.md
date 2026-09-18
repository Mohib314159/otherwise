# Validation

Generated 2026-09-18 20:32 UTC at commit `1865e81` by `scripts/validate_app.py` (cache `data/cache/2e7bc87757370036`, 8 units per effect).

## Null power test

| Signal | Injected effect | Detected | Rate | Can't tell |
|---|---|---|---|---|
| NDVI | +0.00 | 0/8 | 0% | 0/8 |
| NDVI | -0.05 | 2/8 | 25% | 0/8 |
| NDVI | -0.10 | 5/8 | 62% | 0/8 |
| NDVI | -0.20 | 8/8 | 100% | 0/8 |
| VH | +0.00 | 0/8 | 0% | 0/8 |
| VH | -0.50 | 0/8 | 0% | 0/8 |
| VH | -1.00 | 3/8 | 38% | 0/8 |
| VH | -2.00 | 8/8 | 100% | 0/8 |

The injected-effect 0 row is the false-alarm rate.

## Known-answer sites

| Site | Type | Expected | Verdict | Lead signal | Effect (90% interval) | Placebo p | Confirmed | Source |
|---|---|---|---|---|---|---|---|---|
| Grünheide, Germany: forest cleared for the Tesla factory | clearing | REAL | REAL | NDVI | -0.61 (-0.57 to -0.45) | 0.03 | no | [link](https://www.pv-magazine.com/2020/02/17/court-stops-tree-clearance-for-teslas-proposed-berlin-gigafactory/) |
| Saddleworth Moor, England: June 2018 moorland fire | burn | REAL | CANT_TELL | VH | -0.91 (-0.73 to +0.35) | 0.02 | no | [link](https://en.wikipedia.org/wiki/2018_United_Kingdom_wildfires) |
| Rhodes, Greece: July 2023 wildfire | burn | REAL | CANT_TELL | NBR | -0.06 (-0.06 to -0.06) | 0.61 | no | [link](https://mapping.emergency.copernicus.eu/news/information-bulletin-169-the-copernicus-emergency-management-service-maps-some-critical-wildfires-in-greece-update/) |
| Sindh, Pakistan: 2022 monsoon floods near Lake Manchar | flood | REAL | CANT_TELL | NDWI | -0.13 (-0.13 to -0.13) | 0.51 | no | [link](https://earthobservatory.nasa.gov/images/150306/lake-manchar-is-overflowing) |
| Richmond Park, London: nothing documented | clearing | NOT_REAL | CANT_TELL | NDVI | -0.01 (-0.10 to +0.09) | 0.93 | no | - |
| Jaú National Park, Brazil: nothing documented | clearing | NOT_REAL | CANT_TELL | NDVI | -0.01 (-0.07 to +0.06) | 0.64 | no | - |

6 counted · 1 correct · 0 missed · 0 false alarms · 5 can't tell

Sites are candidates until confirmed; no number here is typed by hand.
