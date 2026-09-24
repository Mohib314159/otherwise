# Making the ULEZ case actually work

Status: both ULEZ runs came back "Can't tell". That may be the honest answer, but the current design is leaving a lot of detectable signal on the table. Fix the design first, then re-run. Verify every date and published figure from primary sources.

## Why it's hard (state this on the page)
- The real effect is **small**: published evaluations report modest NO₂ reductions for the central zone and little additional gain after the 2023 expansion. We are trying to detect a few percent, not a forest disappearing.
- **Weather dominates** day-to-day NO₂ — wind speed and direction, boundary-layer height, temperature.
- **COVID** (from spring 2020) swamps 2019-era windows.
- **Fleet turnover and anticipation**: compliant vehicles arrive *before* the start date, so a step change at the start date is the wrong model.

## Design changes, highest value first

1. **Use ground monitors as the primary source** (LAQN + AURN/UK-AIR), not satellite. TROPOMI pixels are a few km wide and measure a whole air column; the published studies used ground data. Keep satellite as a secondary, clearly-labelled view.
2. **Roadside minus background, within each city.** For each city, take roadside stations minus nearby urban-background stations. This differences out regional weather and the national downward trend, and isolates the traffic-related part, which is what ULEZ acts on. Then run the engine on those differenced series: treated = London roadside-minus-background, donors = the same quantity in other cities.
3. **De-weather with ERA5 before the engine**, fitting the weather model on **pre-event data only** (no leakage). Test that de-weathering alone doesn't create false alarms in the null power test.
4. **Filter to traffic hours**: weekdays, daytime only. Nights and weekends dilute a traffic policy's effect.
5. **Test NOₓ as well as NO₂.** NOₓ is closer to what vehicles emit; NO₂ is partly chemistry.
6. **Choose windows that avoid COVID.**
   - Central zone (Apr 2019): pre-period 2017–Mar 2019, post-period Apr 2019–Feb 2020. Stop before lockdown.
   - London-wide (Aug 2023): clean window either side.
   - Inner expansion (Oct 2021): post-COVID but recovery-distorted; flag it.
7. **Model a ramp, not a step.** Allow a phase-in window around the start date, and test the announcement date as well as the start date with in-time placebos.
8. **Donor cities**: match on baseline level, station type and population/road density, and **exclude cities with their own clean-air zone in the window** (e.g. Birmingham's CAZ from Jun 2021). Use many stations so the placebo pool is large: with 20 donors the p-value can't go below about 0.048, with 200 it can.
9. **Publish the power, not just the verdict.** Report the **minimum detectable effect**: "with this data we can detect a change of X% or more". If the published estimate is below our detection limit, say exactly that. That turns "can't tell" from a shrug into a credible, quotable statement: *we can rule out effects larger than X, and the published estimate sits below what this design can resolve.*

## Known-answer set for air
- **A big, sharp point source** to prove the pipeline can detect anything at all: the closure of Ratcliffe-on-Soar (the UK's last coal power station, Sep 2024) is the best candidate — verify the date and any published NO₂ analysis.
- **COVID lockdown (Mar 2020)** as a positive control: every city drops, so with city donors the *relative* effect should be near zero — a good test that the design doesn't invent effects from shared shocks.
- **Nulls**: cities with no policy change, and fake event dates.
- Only then the ULEZ phases, compared against the published estimates in a "matches the published studies" table.

## What to show on the verdict page
- The plain-English verdict, then **effect size with interval**, then the detection limit.
- Roadside-minus-background chart for London against the donor cities' same quantity.
- The weather-adjustment step named, with what was adjusted for.
- Honest limits box: small expected effect, COVID overlap, anticipation, station coverage.

## Done when
- The known-answer set passes (big source detected, COVID relative-null not flagged, nulls clean).
- Null power test reports the false-alarm rate for air.
- The ULEZ cases are published with effect, interval, detection limit and a comparison against published studies — whatever the verdict turns out to be.
