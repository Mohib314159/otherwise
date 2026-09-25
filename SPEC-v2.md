# SPEC v2 — Otherwise becomes multi-signal

Read this together with SPEC.md, CLAUDE.md and DECISIONS.md. Everything in those still applies (honesty rules, no invented numbers, merge and push after each step, log decisions in DECISIONS.md, never touch `DONOTREAD/`).

## The idea in one line
Researchers spend months answering "did this policy or event actually make a difference?", one question at a time. Otherwise answers it in minutes, for any place, with the evidence shown and its own accuracy published — first for land (done), now for **air pollution**, then UK open data, urban heat and night lights.

Our engine already works on any per-unit time series (see the original CarbonTwin README: "any signal that can be reduced to a 1-D per-unit series flows through the same engine"). v2 turns that claim into the product.

## Why this is worth doing (checked Sep 2026)
- The questions (ULEZ, clean air zones, crime policies, tree-planting cooling, conflict blackouts) have all been studied — but only as one-off academic papers or agency reports.
- I found no public, self-serve tool that gives a counterfactual verdict for a chosen place and date on any of these signals. Finance (EventStudyTools) and marketing (CausalImpact, GeoLift) already have tools — we are **not** doing those.
- Heavily studied cases become our **answer keys**: if Otherwise independently reproduces published findings, that is instant credibility.

## Guiding rules
1. **Land must keep working exactly as now.** No regressions to the land pipeline, showcase, verdict page or desktop UI. Run the existing test suite and land power test after every merge.
2. **One signal at a time.** Air must be validated and live before starting the next signal.
3. **Every signal gets its own known-answer tests and null power test before it is shown to users.** Same discipline as land: detection rate, false-alarm rate, can't-tell rate, published on the track-record page.
4. **Honest about resolution and confounders.** Each signal's verdict page states plainly what the data can and cannot see.
5. **Heavy computation runs offline** (showcase, validation). The Render free tier (512 MB) only does light live runs; if a signal can't run live within memory, it is showcase-only with a clear message.

---

## Part A — Generalise the engine (do first)

Refactor so a "signal" is a plugin. Suggested interface (improve it if you see better):

- `units(region)` → the comparison units: grid cells (satellite), stations (ground monitors), or admin areas (open data).
- `fetch(units, time_range)` → per-unit time series, plus **receipts** (what was dropped and why).
- `covariates(units)` → what donors are matched on (land cover/terrain for land; population density, road density, baseline pollution, climate zone for air; etc.).
- `confounders(units, time_range)` → optional series to adjust for before the engine runs (e.g. weather for air).
- Display metadata: signal name, units (e.g. µmol/m², µg/m³), direction of "improvement", minimum meaningful effect, default bin size, seasonality handling.

The shared core stays the same: donor selection (similarity-matched, excluding the treated area and a spillover buffer), augmented SCM, conformal intervals, in-space and in-time placebos, verdict rules, receipts, permalinks, reports.

UI: add a signal picker ("Land change / Air pollution / …"). Verdict page structure stays the same; wording adapts ("the air got cleaner by X more than similar places did").

Done when: land runs through the plugin interface with identical results (compare against stored showcase verdicts), tests green.

---

## Part B — Air pollution (the second signal)

### Question it answers
"Did air pollution (NO₂) in this area change more than it would have anyway, compared with similar places that didn't get the policy/event?"

### Data (verify availability and licences; pick what works)
1. **Satellite NO₂: Sentinel-5P TROPOMI** tropospheric NO₂ column (Planetary Computer hosts Sentinel-5P Level-2; also ESA/Copernicus). Pixels ≈ 3.5 × 5.5 km since Aug 2019 (coarser before). Measures the whole column, not street level. Use QA filtering (e.g. qa_value threshold) and log dropped observations as receipts.
2. **Ground monitors:** London Air Quality Network (Imperial ERG API), DEFRA UK-AIR (national network), and **OpenAQ** for global coverage. Street-level, hourly. This is what most published ULEZ studies used — it is our strongest source for small zones.
3. **Weather: ERA5 reanalysis** (wind speed/direction, boundary layer height, temperature, precipitation). Weather is the biggest confounder for NO₂.

Offer both sources where available; show them side by side when they agree or disagree.

### Method specifics
- **Weather adjustment:** de-weather each unit's series before SCM (e.g. a regression / gradient-boosting weather-normalisation model trained on pre-period data only — see ACP 2025 "Rethinking machine learning weather normalisation"). Must be fitted on pre-event data only to avoid leaking the effect. Log the choice and test that de-weathering doesn't create false alarms (null power test).
- **Units and donors:** treated = stations or grid cells inside the zone; donors = comparable stations/cells in **other cities** not subject to the policy (matched on baseline level, site type — roadside vs background — population/road density). Exclude a spillover buffer around the zone (traffic displacement to boundary roads is a known effect).
- **Anticipation:** people change vehicles before a policy starts. Support testing both the announcement date and the start date, and run in-time placebos.
- **Concurrent shocks:** COVID lockdowns (spring 2020 onward) hit every city — donors absorb this, but flag any event window overlapping 2020 and show it on the verdict page.
- **Seasonality:** NO₂ has strong seasonal cycles; handle with seasonal terms or matched-season bins.

### Known-answer cases (verify every date and published finding from primary sources before using)
- **London ULEZ central zone** — launched 8 Apr 2019. Published studies (e.g. Imperial College) report only a small initial effect. Ground monitors are the main source here; the zone is too small for many satellite pixels.
- **ULEZ inner-London expansion** — 25 Oct 2021.
- **ULEZ London-wide expansion** — 29 Aug 2023. Published work (e.g. University of Birmingham, 2025) reports little additional gain after expansion because compliance was already high. Large enough area for satellite as well as ground data.
- **Birmingham Clean Air Zone** — launched 1 Jun 2021.
- **Madrid Central low-emission zone** — Nov 2018 (published studies exist; check findings).
- **Point-source closure: Ratcliffe-on-Soar**, the UK's last coal power station, closed 30 Sep 2024 — a sharp, well-documented drop that satellite NO₂ should be able to see.
- **Nulls:** comparable cities with no policy change at the same dates, and fake event dates.

Goal: build a **"matches the published studies"** table — our effect size and interval vs the published estimate, for each case. If we disagree with a study, say so and investigate; don't tune the method to agree.

### Verdict page for air
- One plain-English line at the top: e.g. "Air got cleaner, but by no more than similar cities did" or "NO₂ fell 12% more than in comparable cities".
- Chart: area vs no-policy trajectory (de-weathered), gap chart, satellite map of NO₂ before/after, station map.
- Honest limits box: resolution, column vs street level, weather adjustment used, concurrent events.
- Link to the published studies for showcase cases.

### Done when
- Engine runs air on satellite and ground sources, de-weathered.
- Known-answer table built and shown on the track-record page; null power test passes (false-alarm rate reported).
- ULEZ London-wide and Ratcliffe-on-Soar are showcase entries with full verdict pages.
- Live air runs either fit in Render memory or are clearly marked showcase-only.

---

## Part C — Later signals (only after air is live and validated; don't start these now)

1. **UK open data:** monthly street-level crime by LSOA (data.police.uk), house prices (HM Land Registry Price Paid Data), traffic counts (DfT). Question: did a council policy change X compared with similar areas? Users: councils, journalists, think tanks. Watch for reporting changes and small counts.
2. **Urban heat:** Landsat Collection 2 surface temperature (Planetary Computer `landsat-c2-l2`). Question: did tree planting / green roofs / cool pavements cool the area more than similar neighbourhoods? Summer-only, cloud-free acquisitions; ~100 m thermal resolution.
3. **Night lights:** NASA Black Marble (VNP46) daily night-time lights. Question: did lights drop or recover more than comparable areas (power outages, conflict, recovery)? Users: humanitarian/UN agencies, World Bank, journalists. Handle moonlight, snow, cloud, and gas flares.

Each follows the same rule: known-answer cases + null power test before going live.

---

## Order of work
1. Part A (plugin refactor, land unchanged).
2. Part B air: ground monitors + ERA5 de-weathering first (strongest for ULEZ), then satellite NO₂.
3. Known-answer table + null power test for air.
4. Air verdict page + showcase entries (ULEZ London-wide, Ratcliffe-on-Soar).
5. Update README, METHOD.md and the landing page to present Otherwise as a multi-signal "did it work?" tool.

Merge and push after each step. Log every significant decision in DECISIONS.md. If something in this spec is wrong or there's a clearly better approach, take it and explain why.
