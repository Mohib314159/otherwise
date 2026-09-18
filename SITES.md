# Known-answer sites (proposed, awaiting Mohib's confirmation)

These are the candidate ground-truth cases for validating the method. Each has
a documented event with a public source. Until Mohib confirms them they are
labelled "candidate" in the app and in `DECISIONS.md`. Polygons are drawn
inside the documented footprint, never on its edge.

| # | Type | Where | Event date | What is documented | Source |
|---|---|---|---|---|---|
| 1 | Clearing | Grünheide, Brandenburg, Germany (Tesla Gigafactory site), ~52.39 N 13.79 E | 2020-02-13 (felling began; court allowed completion 2020-02-20) | ~92 ha of pine forest cleared for the factory site within days | [pv magazine, 17 Feb 2020](https://www.pv-magazine.com/2020/02/17/court-stops-tree-clearance-for-teslas-proposed-berlin-gigafactory/); [Industry Europe, court approval](https://industryeurope.com/sectors/transportation/tesla-given-court-approval-for-gigafactory-forest-clearance/) |
| 2 | Burn | South-east Rhodes, Greece (Kiotari / Gennadi / Laerma), ~36.08 N 27.95 E | 2023-07-18 (fire start) | Copernicus EMS rapid mapping EMSR675 activated 19 July 2023; final burnt area 17,628.7 ha | [Copernicus EMS bulletin 169](https://mapping.emergency.copernicus.eu/news/information-bulletin-169-the-copernicus-emergency-management-service-maps-some-critical-wildfires-in-greece-update/); [ECHO Daily Flash 24 Jul 2023](https://reliefweb.int/report/greece/greece-wildfires-update-greek-civil-protection-jrc-effis-copernicus-emsr-echo-daily-flash-24-july-2023) |
| 2b | Burn (smaller than the control ring) | Saddleworth Moor, Greater Manchester, England, ~53.52 N 2.00 W | 2018-06-24 (fire start) | Moorland fire that grew to ~8 km² by 27 June 2018; the largest UK wildfire in decades | [Wikipedia, 2018 UK wildfires](https://en.wikipedia.org/wiki/2018_United_Kingdom_wildfires); [IOPscience, air-quality impact of the Saddleworth Moor fire](https://iopscience.iop.org/article/10.1088/1748-9326/ab8496) |
| 3 | Flood | Sindh, Pakistan, west of the Indus around Lake Manchar / Dadu, ~26.9 N 67.6 E | 2022-08-25 (peak monsoon inundation; lake swelled 11–26 Aug, overflowed early Sep) | Lake Manchar grew from 333.76 km² (11 Aug) to 512.25 km² (26 Aug 2022); Copernicus EMSR629 delineation | [NASA Earth Observatory, Lake Manchar](https://earthobservatory.nasa.gov/images/150306/lake-manchar-is-overflowing); [NHESS 2023, Sentinel-1 analysis of the 2022 flood](https://nhess.copernicus.org/articles/23/3305/2023/) |
| 4 | Nothing happened | Richmond Park, London (acid grassland core), ~51.44 N 0.27 W | any date (2022-06-01 used) | National Nature Reserve; no documented land-use change | Site is a Site of Special Scientific Interest and NNR; absence of change is asserted from the absence of any documented event, which is the weakest kind of ground truth and is labelled as such |
| 5 | Nothing happened | Primary forest interior, Jaú National Park, Amazonas, Brazil, ~1.9 S 62.6 W | any date (2022-06-01 used) | Protected park interior, no documented clearing | Same caveat as site 4 |

## Why these

- Site 1 is a clearing with a date known to the day and a footprint known to
  the hectare, in a temperate climate with decent optical coverage.
- Site 2 is a burn with a Copernicus EMS damage grading, but it turned out to
  be **larger than the 12 km control ring**: the control cells burnt too, and
  the tool honestly returned CAN'T TELL with that reason. It stays as an example
  of the method's limit. Site 2b (Saddleworth, ~8 km²) fits inside the ring.
- Site 3 is a flood that stood for weeks, so the 5-day optical revisit and the
  radar both see it. But like Rhodes it is **larger than the control ring**
  (the 2022 flood covered tens of thousands of km²), so the controls flooded
  too and the tool cannot separate the area from its surroundings. It stays as
  a documented limit. A flood smaller than ~10 km across, in a sunny climate,
  is still needed for a fair flood test; suggestions welcome.
- Sites 4 and 5 are the false-alarm checks: the tool must say "not real" or
  "can't tell", never "real".

## What I need from Mohib

Confirm or replace these five. If you know a documented clearing, flood or
burn you would rather use (ideally one relevant to a company you are emailing),
give me a place and a date and I will swap it in.
