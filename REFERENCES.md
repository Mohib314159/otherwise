# References & scientific grounding

CarbonTwin is built on peer-reviewed methods, not invented ones. This is the
grounding for the maths and the remote-sensing signal — useful for the Q&A and
for the "is this rigorous?" criterion. *(Verify exact citation details before any
formal/published use; descriptive entries link the source.)*

## The causal method (synthetic control)

- **Abadie, Diamond & Hainmueller (2010).** *Synthetic Control Methods for
  Comparative Case Studies.* JASA. — origin of modern SCM (also Abadie &
  Gardeazabal 2003). The convex, non-negative, sum-to-one weights and the
  placebo/permutation inference come from this line of work.
- **Fick, S. E., et al. (2021).** *Evaluating natural experiments in ecology:
  using synthetic controls in assessments of remotely sensed land treatments.*
  Ecological Applications. — the **first** application of SCM to remote-sensing
  land-cover time series. Establishes the three data requirements we satisfy:
  (1) treated + untreated units, (2) a known treatment date, (3) time-series
  response data.
- **Sills, E. O., et al. (2015).** *Estimating the Impacts of Local Policy
  Innovation: The Synthetic Control Method Applied to Tropical Deforestation.*
  PLOS ONE 10:e0132590. — SCM on remotely-sensed deforestation; the template for
  "one treated unit, a donor pool, a long satellite record".
- Further EO/ecology uses since 2021: high-seas fish stocks (Lawson & Smith 2023),
  prescribed-burning effect on wildfire severity (Wu et al. 2023), FSC
  certification vs deforestation. SCM has been shown to detect effects that
  interrupted-time-series, before-after, and BACI designs miss.

## The signal (cover-crop / regen-ag detection from satellite)

- **Field-level cover-cropping detection from Harmonized Landsat–Sentinel-2,
  MODIS, and PlanetScope time series** (Int. J. Applied Earth Obs. Geoinformation,
  2025). https://www.sciencedirect.com/science/article/pii/S156984322500651X —
  validates phenology-based, field-level cover-crop detection from **PlanetScope**
  (the Theme-B sensor); reported accuracies 68.6% (cereal rye) – 89.0% (wheat),
  higher on larger fields. Confirms our off-season NDVI phenology approach and the
  need for PlanetScope radiometric calibration.
- **Status of Phenological Research Using Sentinel-2 Data: A Review** (Remote
  Sensing, 2020). https://www.mdpi.com/2072-4292/12/17/2760 — land-surface
  phenology metrics (start/peak/end of season) from VI time series; the basis for
  our transition-year detection.

## The SAR roadmap (Sentinel-1, the honest extension)

- **Veloso et al. (2017); Navarro et al. (2016).** Sentinel-1 SAR can replace
  optical under cloud and *enhance* VI analysis when fused. C-band backscatter /
  cross-ratio is sensitive to standing biomass and the 3-D canopy–soil structure —
  i.e. it responds to **soil disturbance (tillage)**, which optical NDVI does not.
  This is why no-till (Theme B, 2023) is the case for radar.
- **Comparing land-surface phenology of European crops from Sentinel-1 and -2**
  (Remote Sensing of Environment). https://pmc.ncbi.nlm.nih.gov/articles/PMC7841528/

## What is novel here (the honest claim)

The *method* (SCM) and the *signal* (phenology-based cover-crop detection) are
both established. What is new is the **combination and the application**:

1. SCM applied at **field scale** to **carbon-credit additionality** (most EO-SCM
   work is at municipality/landscape scale, for policy evaluation).
2. Turning the placebo p-value into a **fraud / false-claim audit** — verifying a
   claim, not just estimating an effect.
3. **Permanence / reversal monitoring** — running the control forward to catch a
   credit collapsing, which the one-shot policy-evaluation literature does not do.
4. An **actuarial reversal-pricing** layer on top.
5. Demonstrating the engine is **regime-agnostic** (Iowa carbon ↔ Saudi aquifer
   abandonment) — the "natural experiment from space" generalisation in Fick (2021),
   pushed toward an operational MRV product.

SCM has only been used on satellite data since 2021, across a handful of domains.
Pointing it at carbon-MRV fraud and permanence at field scale is, as far as this
literature shows, unexplored.

## Industry & cutting-edge context (2024–2026)

- **Additionality = counterfactual baseline (industry consensus).** SOC crediting
  requires changes to be *additional*, "typically determined through comparisons to
  counterfactual baselines — what would have occurred had management remained the
  same" (e.g. Climate Action Reserve Soil Enrichment Protocol; Verra VM0042). The
  best protocols use **dynamic baselines** combining historical management with
  weather — which is structurally what our synthetic control produces. *This is the
  single most important framing: our method IS a rigorous, data-driven dynamic
  counterfactual baseline.*
- **Real cover-crop effect size.** Indigo Ag's large-scale soil-carbon MRV
  (CAR1459, 553,743 ha) found cover cropping ≈ **1.29 tCO₂e/ha/yr** on average
  (ScienceDirect, J. Environmental Management, 2024) — validates our 0.2–2.0 band.
- **Market context.** Voluntary ag-carbon market fell ~57% in 2024 ($84.9M→$36.1M)
  on quality concerns; digital-MRV investment ~$2.3B; ~90% of carbon transactions
  expected to require satellite verification by 2027; ~5% of projects pass the
  strictest integrity screens (Sustainability Atlas; Senken, 2025–26). The market
  J.P. Morgan MD; Caroline Grey); ~$40–44M raised; 500+ forest projects; advisor
  Manuela Veloso (Head of AI Research, J.P. Morgan). Already markets **additionality
  + durability** (Anew Climate partnership) and **reversal-risk** pricing (fire/
  flood/drought), mostly for **forest carbon** using ML. Our differentiation:
  econometric **synthetic control** (causal, auditable, p-value) at **field-scale
  regen ag**, plus an explicit fraud/false-claim verdict.
- **Method peers.** Most soil-carbon MRV uses hybrid soil-sampling + biogeochemical
  modelling (DayCent-CR, RothC) + ML (Indigo Ag; ESA SatMRV; InSoil). Causal
  inference / synthetic control is rare here — our methodological angle.
