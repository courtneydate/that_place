# Client Personas

This document describes client personas used for end-to-end platform testing and demo
environments. Each persona represents a realistic B2B customer segment and is used to
drive meaningful test data, user story scenarios, and acceptance testing.

---

## Segment overview

| # | Persona | Segment | Defining requirement | Primary phases |
|---|---------|---------|----------------------|----------------|
| 1 | Solargrid Energy Australia | C&I solar EPC + O&M operator (monitors *clients'* sites) | Unified portfolio monitoring & fast fault response across many vendors | 1–4 |
| 2 | Brightfield Energy Partners | C&I solar + BESS PPA asset owner — *build–own–operate* | Platform-independent metering + **automated per-kWh PPA billing export** (replaces the Wattwatchers per-device SaaS) | 3–5 |
| 3 | Precinct Power Networks | Embedded network operator — multi-tenant microgrids | **Hierarchical sub-metering + per-tenant billing run** reconciled to the parent (gate) meter | 3–5 |
| P | Improv-style billing SaaS | Channel / data-integration partner (not a dashboard buyer) | A normalised metering **data feed API** (REST/MQTT) to drop into their own billing engine | 3–5 |

> Personas 2, 3 and P are derived from `wattwatchers_prospects_v2.xlsx`. The common thread across that prospect list is **platform independence from Wattwatchers** plus **automated per-kWh billing** — requirements Persona 1 barely exercises, which is why they are added as separate personas rather than folded into Solargrid.

## Client 1 — Solargrid Energy Australia

**Type:** Commercial & Industrial (C&I) Solar Developer / O&M Operator
**Segment:** Mid-market EPC + O&M
**Status:** Primary test persona — Phase 1–4 functional testing

### Company profile

| Field | Detail |
|-------|--------|
| Company name | Solargrid Energy Australia Pty Ltd |
| Founded | 2016 |
| HQ | Melbourne, Victoria |
| Regional offices | Brisbane QLD, Sydney NSW |
| Headcount | 38 |
| Annual revenue | AUD $10–14M |
| Market | C&I solar (EPC, O&M, PPA) — 50 kW to 500 kW systems |
| Active portfolio | 95 sites across VIC, QLD, and NSW |

### Typical projects

| Type | Share | Description |
|------|-------|-------------|
| Rooftop commercial | 60% | Retail, warehouses, manufacturing, offices |
| Solar carports | 25% | Businesses with constrained roofs or tenant-owned buildings |
| Ground-mount | 15% | Industrial parks, rural agribusiness |

### Asset types monitored

| Asset | Count / notes |
|-------|---------------|
| Inverters | Fronius Symo, SMA Sunny Tripower, Growatt — 3–10 per site |
| Billing meters | CETA PMC-340B (3-phase) on most sites; PMC-220 on small single-phase sites |
| Energy monitors | Watt Watchers 6M+One (main switchboard + solar output circuits) |
| Battery storage | 18 sites with 50–200 kWh BESS (growing) |
| HVAC | 28 commercial sites with building HVAC requiring load-shift automation |
| Sites with export limits | 22 sites on DNSP-constrained feeders (mainly QLD Energex/Ergon) |

### Pain points

1. **Fragmented data.** Production data is spread across Fronius Solar.web, SMA Sunny Portal,
   Watt Watchers Fleet Management, and manual inverter reads — no unified portfolio view.
2. **Slow fault response.** Average 6–12 hours to detect underperformance without automated alerts.
   Technicians must visit site and connect directly to inverters.
3. **Export limit compliance.** 22 sites require manual inverter curtailment to stay within
   DNSP export limits. No automated response to grid signals.
4. **Missed load-shifting.** No integration between solar production and HVAC schedules —
   air conditioning runs regardless of solar availability.
5. **Reporting overhead.** Monthly customer reports are manually compiled from multiple sources:
   8–15 hours/month of admin time per operations manager.
6. **Scalability.** Adding 20–30 sites per year; current manual processes are not scaling.

### Platform features used

| Priority | Feature | Use case |
|----------|---------|----------|
| 1 | Portfolio dashboard | Map view of all 95 sites, colour-coded by status; per-site KPI cards |
| 1 | Alerts & notifications | Inverter efficiency drop, meter comms loss, export curtailment events |
| 2 | Rules engine | Automated curtailment, HVAC load-shift to peak solar hours |
| 2 | Historical reporting | 12-month production graphs, customer-facing PDF reports |
| 3 | MQTT / Modbus ingestion | Fronius/SMA via MQTT; CETA PMC via Watt Watchers Modbus API |
| 3 | API data export | Pull into billing systems and Solargrid's own analytics |

### User roles

| Role | Count | Primary tasks |
|------|-------|---------------|
| Operations Manager | 2 | Daily fleet review, alert triage, technician dispatch, monthly reporting |
| Site Technician | 10 | On-site fault diagnosis, remote troubleshooting via live data |
| Engineering Lead | 1 | System design, inverter tuning, complex fault investigation |
| Account Manager | 3 | Customer report delivery, PPA compliance, performance queries |

### Data requirements

| Measurement | Source | Frequency | Purpose |
|-------------|--------|-----------|---------|
| Active power (kW) per inverter | Fronius/SMA MQTT | 30 s | Live dashboard, fault detection |
| Energy yield (kWh) per site | Watt Watchers short energy | 5 min | Reporting, performance ratio |
| Grid import/export (kWh) | CETA PMC via Watt Watchers Modbus API | 5 min | Export compliance, billing |
| Voltage per phase | Watt Watchers Modbus API | 5 min | Power quality monitoring |
| Inverter fault codes | Fronius/SMA MQTT | Event-driven | Alert triggering |
| HVAC compressor status | Modbus TCP (building BMS) | 60 s | Load-shift automation |

### Test data seed values (VIC sites)

Use these values when seeding demo data for Solargrid:

| Parameter | Value |
|-----------|-------|
| Tenant slug | `solargrid` |
| Site count | 12 (test environment subset of 95 production sites) |
| Typical system size | 120 kW |
| Daily generation (sunny day) | 576 kWh (120 kW × 4.8 peak sun hours) |
| Export limit (constrained sites) | 30 kW |
| Billing meter model | CETA PMC-340B |
| Watt Watchers device model | 6M+One |
| Inverter brand (primary) | Fronius Symo |
| Alert threshold — power drop | > 20% drop over 5 minutes (clear sky condition) |
| HVAC load-shift window | 10:00–15:00 AEST (peak solar) |

### Expected alert scenarios for testing

- Inverter efficiency falls below 85% of expected output → notify Operations Manager
- Meter communication lost > 15 minutes → notify Operations Manager + Engineering Lead
- Site export power exceeds 30 kW for > 2 minutes → trigger curtailment rule (MQTT publish)
- Daily generation < 60% of forecast by 14:00 (clear sky) → notify assigned technician
- Battery SoC > 95% with export limit active → trigger HVAC pre-cool load shift

### Budget expectations

| Item | Expected range (AUD) |
|------|---------------------|
| Platform subscription | $300–500/month (fleet management tier) |
| Per-site fee | $60–90/site/month |
| Estimated ROI payback | 12–18 months (reduced truck rolls + prevented yield loss) |

---

## Client 2 — Brightfield Energy Partners

**Type:** C&I Solar + Battery PPA Developer / Asset Owner — *build–own–operate*
**Segment:** Institutionally-backed behind-the-meter (BTM) PPA fleet
**Status:** Secondary test persona — multi-source ingestion, PPA billing engine (Phase 5), Wattwatchers-replacement scenario

### Company profile

| Field | Detail |
|-------|--------|
| Company name | Brightfield Energy Partners Pty Ltd |
| Founded | 2017 |
| HQ | Sydney, NSW |
| Regional offices | Melbourne VIC, Brisbane QLD |
| Headcount | 22 (lean — asset management & finance heavy; installs subcontracted to EPCs) |
| Backing | Infrastructure / clean-energy fund (CEFC-style co-investment, 2024) |
| Model | Funds, builds, owns and operates rooftop + carport solar (and increasingly BESS) on C&I host sites; 7–25 yr PPAs; bills the host per kWh generated and/or consumed-from-solar |
| Active portfolio | 180 sites, ~60 MW deployed; 200 MW development pipeline |
| Hosts | Manufacturing, logistics / distribution centres, aged care, retail chains, healthcare, commercial property (REITs) |

### Typical projects

| Type | Share | Description |
|------|-------|-------------|
| Rooftop C&I solar (PPA-financed) | 65% | Warehouses, factories, distribution centres, large-format retail |
| Solar + BESS | 25% | Peak shaving, arbitrage, LGC value, demand-charge reduction |
| Solar carports | 10% | Hosts with constrained or tenant-owned roofs |

### Asset types monitored

| Asset | Count / notes |
|-------|---------------|
| Inverters | SMA Sunny Tripower, Sungrow SG, Fronius Tauro, Huawei SUN2000 — 4–20 per site |
| NMI billing meters | **CET PMC-340B (3-phase), NMI M6 pattern-approved** — mandatory for BTM trade; PMC-220 on small single-phase sites |
| Communicating device | Currently **Wattwatchers 6M+MB** (reads the CET PMC over Modbus, pushes to WW cloud) — the per-device subscription they want to cut; migrating selected sites to a direct Modbus gateway |
| Battery storage | 45 sites, 100 kWh – 2 MWh BESS, each with its own Modbus / MQTT telemetry |
| Generation meters | Separate generation meter on some sites in addition to the trade meter |

### Pain points

1. **Wattwatchers subscription cost at scale.** ~AUD $123/device/year ($4/mo monitoring + $75/yr billing-data API) × a fleet that grows with a 200 MW pipeline. Institutional investors scrutinise per-MW O&M cost — this line item is squarely in scope.
2. **Vendor lock-in.** PMC billing data is only reachable via the WW REST API (not in WW's own apps), the API is CORS-restricted, and PPA contracts that name Wattwatchers make hardware changes a re-papering exercise.
3. **Manual / brittle billing.** Monthly per-kWh invoices are assembled from WW API pulls plus spreadsheets — roughly one analyst-week per month; reconciliation errors cause billing disputes with hosts.
4. **No unified fleet view.** Production data is split across SMA Sunny Portal, Sungrow iSolarCloud, Huawei FusionSolar, Wattwatchers Fleet, and separate BESS dashboards.
5. **BESS not optimised.** Battery dispatch is not coordinated with site load, solar, tariff windows, or LGC value.
6. **Reporting overhead.** Quarterly asset-performance packs for investors and annual host reports are compiled by hand.

### Platform features used

| Priority | Feature | Use case |
|----------|---------|----------|
| 1 | Multi-source ingestion | WW REST API v3 (`/devices`, `/long-energy/{id}`, `/modbus/{id}` for PMC) **and** direct Modbus TCP from the CET PMC via own gateway; inverter vendor APIs; MQTT from BESS |
| 1 | Automated PPA billing export | Monthly per-site kWh totals (generated + consumed-from-solar), tariff applied, CSV / PDF / API invoice export → host + accounting system |
| 1 | Portfolio dashboard | 180 sites, performance ratio and $/MWh per site, billing status, comms health |
| 2 | Rules engine | BESS dispatch (peak shave, arbitrage), underperformance alerts, meter comms-loss alerts, export-limit curtailment |
| 2 | Historical reporting | Investor asset packs, host performance reports, LGC/generation summaries |
| 3 | Commands | Inverter curtailment and BESS setpoints via MQTT publish (registered topic patterns) |
| 3 | Data export API | Feed settlement data into the corporate finance / asset-management system |

### User roles

| Role | Count | Primary tasks |
|------|-------|---------------|
| Head of Asset Management | 1 | Fleet performance, investor reporting, exception management |
| Billing & Settlements Analyst | 2 | Monthly billing runs, host invoicing, reconciliation, dispute resolution |
| Asset Performance Engineer | 2 | Underperformance investigation, inverter/BESS tuning |
| O&M Coordinator | 1 | Dispatches subcontracted field technicians on alerts |
| Commercial Manager | 2 | PPA origination, host relationships, performance queries |

### Data requirements

| Measurement | Source | Frequency | Purpose |
|-------------|--------|-----------|---------|
| Energy generated (kWh) per site | CET PMC via Modbus / WW `long-energy` | 5 min + daily close | PPA billing (generation PPAs) |
| Energy consumed-from-solar (kWh) per site | CET PMC / inverter | 5 min | PPA billing (consumption PPAs) |
| Grid import/export (kWh) | CET PMC (trade meter) | 5–30 min | Net metering, export-limit compliance |
| Active power (kW) per inverter | Vendor API / MQTT | 30–60 s | Live dashboard, fault detection |
| BESS SoC, charge/discharge power | Modbus / MQTT | 30 s | Dispatch optimisation |
| Inverter fault codes | Vendor API | Event-driven | Alert triggering |
| Revenue-grade interval data (NMI) | CET PMC | 30 min | Settlement-grade billing & audit trail |

### Test data seed values

| Parameter | Value |
|-----------|-------|
| Tenant slug | `brightfield` |
| Site count | 15 (test subset of 180 production sites) |
| Typical system size | 250 kW solar + 215 kWh BESS |
| Billing meter model | CET PMC-340B (NMI M6 pattern-approved) |
| Communicating device | Wattwatchers 6M+MB (legacy) → direct Modbus gateway (target) |
| WW API | REST v3, `api-v3.wattwatchers.com.au`, Bearer token, 5 req/s / 10,000 req/day; energy in watt-seconds → kWh = ÷ 3,600,000 |
| PPA tariff — generation | $0.11/kWh |
| PPA tariff — consumption | $0.18/kWh |
| Billing cycle | Monthly (calendar month); invoice issued day +3 |
| Inverter brands | SMA Sunny Tripower, Sungrow SG, Huawei SUN2000 |
| Alert threshold — performance ratio | < 0.75 over a clear-sky day |
| Per-device cost being replaced | ~AUD $123/device/year (WW: $4/mo monitoring + $75/yr billing data) |

### Expected alert / automation scenarios for testing

- Monthly billing run completes → generate per-host invoices; flag any site with > 5% kWh variance vs the prior month → notify Billing & Settlements Analyst
- CET PMC Modbus read fails > 30 min → notify O&M Coordinator (billing data at risk)
- Site performance ratio < 0.75 on a clear-sky day → notify Asset Performance Engineer
- BESS SoC < 20% before the peak-tariff window → suppress the discharge schedule + notify
- Inverter offline > 1 h during daylight → notify + create an O&M ticket
- Site export power exceeds the DNSP limit > 2 min → curtail inverters (MQTT publish)

### Budget expectations

| Item | Expected range (AUD) |
|------|----------------------|
| Platform subscription | $400–700/month (fleet tier) |
| Per-site fee | $40–70/site/month — must net out below the Wattwatchers per-device cost it replaces |
| Migration | One-off historical backfill from the WW API |
| Estimated ROI payback | 6–12 months (eliminated WW SaaS + billing-labour saved) |

---

## Client 3 — Precinct Power Networks

**Type:** Embedded Network Operator (ENO) / Microgrid Operator — multi-tenant BTM solar + BESS
**Segment:** Commercial precincts, shopping centres, strata / mixed-use, industrial estates
**Status:** Tertiary test persona — hierarchical sub-metering, per-tenant billing run (Phase 5), high metering-point density

### Company profile

| Field | Detail |
|-------|--------|
| Company name | Precinct Power Networks Pty Ltd |
| Founded | 2019 |
| HQ | Sydney, NSW |
| Headcount | 30 |
| Regulatory | AER embedded-network exemption holder; works with a registered Embedded Network Manager (ENM) |
| Model | Long-term rooftop lease on a host property → installs solar + BESS → operates as the precinct's energy provider → bills **every tenant behind the parent (gate) meter** per kWh, at a discount to grid retail |
| Active portfolio | 35 precinct sites; 70+ in pipeline. Flagship: "Riverside Town Centre" — 2.6 MW solar + 4 MW / 10 MWh BESS, ~270 tenants |
| Connection points under management | ~6,000 NMI child (tenant) meters |

### Typical projects

| Type | Share | Description |
|------|-------|-------------|
| Shopping centres / retail precincts | 45% | Many small-to-mid tenants behind one gate meter |
| Strata residential + mixed-use | 25% | Apartment/townhouse complexes, build-to-rent |
| Industrial estates / business parks | 20% | Multi-unit warehouse and light-industrial estates |
| Commercial towers | 10% | Single-building, multi-tenant |

### Asset types monitored

| Asset | Count / notes |
|-------|---------------|
| Parent (gate) meter | 1 per site — NMI, revenue-grade, 30-min interval |
| Tenant child meters | 50–400 per site — NMI pattern-approved DIN-rail meters (CET PMC-220 and similar), read over Modbus |
| Common-area / landlord supply meters | 1–several per site — lifts, lighting, HVAC, car park |
| Solar inverters | SMA, Sungrow, GoodWe — 10–60 per site |
| Battery storage | 1 per major site — 250 kWh – 10 MWh BESS, Modbus / MQTT telemetry |
| EV charger meters | Growing — present on some sites |

### Pain points

1. **Massive sub-metering fleet.** Thousands of child meters across sites; per-device metering SaaS (Wattwatchers et al.) is the single largest platform OpEx line — cost scales with every connection point.
2. **Complex monthly billing run.** Each tenant invoice = child-meter consumption × embedded-network tariff − allocated on-site solar + apportioned common-area charges; tenants move in/out mid-cycle (pro-rata); the whole run must reconcile back to the parent meter (no leakage). Today this is a multi-person, multi-day exercise per cycle.
3. **Solar allocation fairness.** On-site generation must be allocated across tenants transparently and auditably — both the regulator and tenants scrutinise the method.
4. **Tenant churn.** Onboarding/offboarding (opening/closing NMI child accounts, pro-rata final bills) is manual.
5. **BESS value stacking.** The battery is used for demand-charge reduction at the parent meter, arbitrage, and increasingly VPP/FCAS — none of it coordinated.
6. **Compliance & audit.** AER exemption conditions, NMI metering accuracy, and tenant dispute handling require an auditable data trail per meter per interval.

### Platform features used

| Priority | Feature | Use case |
|----------|---------|----------|
| 1 | Hierarchical metering model | site → parent (gate) meter → solar/BESS → many child (tenant) meters; reconciliation: parent ≈ Σ children + common area + losses |
| 1 | Embedded-network billing engine | Per-tenant monthly invoice (kWh × tariff − solar allocation + common-area share), pro-rata for mid-cycle moves, batch export to billing / AR |
| 1 | Multi-source ingestion | Modbus from DIN-rail child meters via on-site gateways; WW REST API where WW devices exist; inverter vendor APIs; MQTT from BESS |
| 2 | Rules engine | BESS demand-charge management at the parent meter, child-meter comms-loss alerts, anomalous-tenant-consumption alerts |
| 2 | Tenant data feed | Read-only per-tenant consumption + solar share (powers a tenant-facing app) |
| 2 | Reporting | AER compliance reports, landlord performance reports, solar self-consumption % |
| 3 | VPP / FCAS dispatch hooks | MQTT publish to BESS — roadmap |

### User roles

| Role | Count | Primary tasks |
|------|-------|---------------|
| Network Operations Manager | 1 | Fleet health, reconciliation exceptions, BESS strategy |
| Billing Operations team | 3 | Monthly billing runs, tenant onboarding/offboarding, dispute resolution |
| Metering & Compliance Officer | 1 | NMI accuracy, AER reporting, audit trail |
| Field Services Coordinator | 1 | Dispatches technicians on meter/inverter faults |
| Tenant Support | 2 | Tenant queries, consumption explanations, billing corrections |

### Data requirements

| Measurement | Source | Frequency | Purpose |
|-------------|--------|-----------|---------|
| Tenant child-meter consumption (kWh) | DIN-rail meter via Modbus / WW API | 5–30 min | Per-tenant billing |
| Parent (gate) meter import/export (kWh) | NMI revenue meter | 30 min | Reconciliation, demand charge |
| Solar generation (kWh) per array | Inverter / generation meter | 5 min | Solar allocation across tenants |
| Maximum demand (kW) at the parent meter | Parent meter | 30 min | Demand-charge optimisation |
| BESS SoC, power, throughput | Modbus / MQTT | 30 s | Demand management, value stacking |
| Common-area supply (kWh) | Landlord meters | 30 min | Common-area apportionment |
| Meter comms heartbeat | All meters | 5 min | Billing-integrity alerts |

### Test data seed values

| Parameter | Value |
|-----------|-------|
| Tenant slug | `precinctpower` |
| Site count | 6 (test subset of 35 production sites) |
| Flagship test site | "Riverside Town Centre" — 2.6 MW solar, 4 MW / 10 MWh BESS, 270 child meters |
| Child meter model | CET PMC-220 / DIN-rail Modbus meters (NMI pattern-approved) |
| Parent meter | NMI revenue meter, 30-min interval |
| Embedded-network tariff (tenant) | $0.22/kWh (vs ~$0.30/kWh grid retail) |
| Solar allocation rule | Pro-rata by tenant consumption during each generation interval; allocation record stored per interval |
| Billing cycle | Monthly; parent-meter reconciliation tolerance ±1.5% |
| BESS strategy | Cap parent-meter demand at 1.8 MW |
| Alert threshold — child meter no data | > 60 min → billing-integrity alert |
| Alert threshold — reconciliation variance | > 1.5% of parent-meter energy → hold the billing run |

### Expected alert / automation scenarios for testing

- Monthly billing run → generate all tenant invoices, reconcile the sum to the parent meter, flag variance > 1.5% → notify Metering & Compliance Officer and hold the run
- Tenant move-out logged → close the child NMI, issue a pro-rata final invoice
- Child meter offline > 60 min → billing-integrity alert to Billing Operations; if unresolved by cycle close, estimate consumption per AER rules
- Parent-meter demand approaching 1.8 MW → BESS discharge (MQTT publish)
- Solar generation interval → allocate kWh across active tenants and persist the allocation record (audit trail)
- BESS SoC < 15% before the evening peak → notify + suppress further discharge

### Budget expectations

| Item | Expected range (AUD) |
|------|----------------------|
| Platform subscription | $600–1,200/month (enterprise / multi-site embedded-network tier) |
| Per-metering-point fee | $1–3/child meter/month — must beat per-device WW pricing at thousands of points |
| Per-site setup | Gateway provisioning + child-meter onboarding |
| Estimated ROI payback | 4–9 months (replaces per-device metering SaaS + collapses the manual billing run) |

---

## Partner persona — Improv-style billing SaaS (channel / data-integration partner)

**Type:** Solar-PPA billing software / ESCO that already serves many PPA operators
**Status:** Channel-partner persona — *not* a dashboard buyer; integrates at the data layer

This persona exists because the prospect list flags billing-SaaS partners (e.g. Improv, named by Wattwatchers as their PPA billing partner) as the highest-leverage route to market — one integration brings many downstream PPA operators onto the platform at once.

### What's different about their requirements

- They **do not want the dashboard, rules UI, or alerts** — they have their own billing engine and customer portal.
- They want a **normalised metering data feed**: one API to pull per-site / per-meter interval and daily-close kWh regardless of the underlying device (Wattwatchers 6M+One via REST, CET PMC via Modbus gateway, inverter APIs, raw MQTT) — i.e. the platform is an *aggregation and normalisation layer* under their billing engine.
- Hard requirements: stable REST + webhook/MQTT delivery, consistent units (kWh, not watt-seconds), gap/estimate flags on intervals, NMI identifiers preserved, audit trail per interval, predictable rate limits, multi-tenant data isolation so operator A never sees operator B's meters.
- Commercials: per-meter or per-site data-access fee, white-label / referral arrangement; they resell access to their own PPA-operator customers.

### Platform features used

| Priority | Feature | Use case |
|----------|---------|----------|
| 1 | Data export API + webhooks | Pull/push normalised interval + daily kWh per meter into their billing engine |
| 1 | Multi-source ingestion & normalisation | Wattwatchers REST, Modbus meters, inverter APIs, MQTT — one schema out |
| 1 | Tenant data isolation | Each PPA operator is a separate tenant; the partner sees only what's authorised |
| 2 | Comms-health / data-quality flags | Surface gaps and estimates so their invoices stay defensible |
| 3 | Bulk device/site provisioning API | Onboard a new PPA operator's fleet programmatically |

### Test data seed values

| Parameter | Value |
|-----------|-------|
| Tenant slug | `improv-partner` |
| Model | Reads metering data for N downstream PPA-operator tenants |
| Downstream operators (test) | 3 sub-tenants, ~10 sites each |
| Delivery | REST pull (`/api/v1/...`) + webhook on daily close |
| Units contract | kWh, UTC timestamps, NMI preserved, `estimated`/`gap` flags per interval |
| Commercial model | Per-meter data-access fee; white-label |

---

> Add additional client personas below as new segments are onboarded for testing.
