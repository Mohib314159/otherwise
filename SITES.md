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
| 6 | Construction | Austin, Texas, Tesla Gigafactory site, ~30.22 N 97.62 W | 2020-07-22 | Factory built from July 2020 on a former sand and gravel mine by the Colorado River | [Wikipedia, Gigafactory Texas](https://en.wikipedia.org/wiki/Gigafactory_Texas); [Community Impact, 21 Jul 2020](https://communityimpact.com/austin/southwest-austin-dripping-springs/business/2020/07/21/tesla-will-officially-build-its-next-gigafactory-in-travis-county/) |
| 7 | Mine expansion | Lützerath, North Rhine-Westphalia, ~51.06 N 6.42 E | 2023-01-11 | Village cleared by police from 11 Jan 2023 and excavated for the Garzweiler II lignite mine | [Wikipedia, Lützerath](https://en.wikipedia.org/wiki/L%C3%BCtzerath); [CNN, 14 Jan 2023](https://www.cnn.com/2023/01/14/europe/lutzerath-germany-coal-protests-climate-intl/index.html) |
| 8 | Burn | Table Mountain, Cape Town, slopes above UCT, ~33.95 S 18.46 E | 2021-04-18 | Fire started 08:45 on 18 April 2021; about 600 ha burnt, Rhodes Memorial restaurant and UCT library damaged | [Wikipedia, 2021 Table Mountain fire](https://en.wikipedia.org/wiki/2021_Table_Mountain_fire); [Daily Maverick, 19 Apr 2021](https://www.dailymaverick.co.za/article/2021-04-19-wall-of-fire-reaps-day-of-unforgiving-destruction-in-mother-city/) |
| 9 | Reservoir fill | Hasankeyf, Batman province, Turkey, ~37.71 N 41.41 E | 2020-01-05 | Ilısu reservoir filling since July 2019 reached the town in early January 2020 and submerged it in 2020 | [NASA Earth Observatory, Slowly Flooding History](https://earthobservatory.nasa.gov/images/146439/slowly-flooding-history); [Wikipedia, Old Bridge Hasankeyf](https://en.wikipedia.org/wiki/Old_Bridge,_Hasankeyf) |
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
