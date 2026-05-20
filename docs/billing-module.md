# BILLING MODULE — Metering, Tariffs, Billing Runs & Outbound Metering API

> **Status:** Promoted to SPEC.md on 2026-05-20 — now a historical design artifact.
> SPEC.md (§1, §3, §4, §5, §6, §8, §9) is the source of truth for the Metering &
> Billing arc. This doc is retained for design rationale and the §18 decision log.
> **Version:** 0.3 (2026-05-20)
> **Owner:** Courtney
> **Companion docs:** [`SPEC.md`](../SPEC.md), [`docs/clients.md`](clients.md), [`docs/providers/wattwatchers.md`](providers/wattwatchers.md)

This document is the working spec for the *Metering & Billing* arc of the platform — the
capability that lets a C&I solar PPA asset owner, an embedded-network operator, or a
metering-data channel partner replace their Wattwatchers (or equivalent) subscription
with That Place. It is intentionally a side doc, not part of SPEC.md, while design is in
flux. Once stable, the agreed sections will be promoted to SPEC.md §3 / §4 / §5 and the
roadmap.

Everything here is subject to revision. Decisions marked ⚑ are explicit open questions.

---

## 1. Purpose & Scope

### 1.1 What this module adds

Three new product capabilities, sitting on top of the existing ingestion / streams / rules /
feeds / reference-datasets stack:

1. **Per-kWh billing engine** — take energy delivered through one or more meters over a
   billing period, apply a tariff, and emit per-customer invoices (CSV, PDF, API).
2. **Hierarchical metering for embedded networks** — parent (gate) meter ⊃ child (tenant)
   meters, with solar allocation across children and parent-meter reconciliation.
3. **Outbound metering API** — a normalised, scoped, read-only feed of interval and
   daily-close kWh per meter, with webhooks on daily close — for billing-SaaS channel
   partners that supply their own invoicing engine.

### 1.2 Who it's for

Three personas, all defined in [`docs/clients.md`](clients.md):

| Persona | Module use |
|---|---|
| Client 2 — Brightfield Energy Partners (PPA asset owner) | Single-tier billing: one site → one host customer → monthly per-kWh invoice |
| Client 3 — Precinct Power Networks (embedded-network operator) | Hierarchical billing: one site → 50–400 child tenants → monthly per-tenant invoices reconciled to a parent meter |
| Partner — Improv-style billing SaaS | Outbound metering API only — does not use the platform's billing engine itself, but consumes its normalised meter data |

Client 1 (Solargrid Energy Australia) does **not** need this module — they monitor third-party-owned
sites and do not bill end customers. The generic IoT platform underneath continues to serve them.

### 1.3 Explicitly in scope (v1)

- AUD only, single-currency
- NEM (Australian National Electricity Market) only
- Flat-rate and time-of-use (TOU) tariffs
- Daily fixed supply charges (a non-energy line item; see §7.4)
- Single-meter and hierarchical (parent + children) sites
- PPA generation tariffs, PPA consumption-from-solar tariffs, embedded-network retail tariffs
- **Solar feed-in / buyback tariff to host** — applied to `grid_export` energy, emits a credit line item on the host's invoice. Same tariff shape as the PPA generation tariff in §7.1, distinguished by being applied to an `export` stream. (Was Q7 / v1.1 — moved into v1.)
- Solar allocation across child meters in an embedded network (pro-rata by interval consumption)
- **Common-area cost apportionment** — energy consumed by `common_area` meters is metered, costed at the embedded-network tariff, and apportioned across tenant billing accounts as a `common_area_share` line item on each tenant's invoice. Default apportionment rule: pro-rata by tenant consumption for the period; three per-site configurable methods (`pro_rata_consumption` / `equal_share` / `by_floor_area`) — see §18 Q20.
- Reconciliation report (parent ≈ Σ children + common area + losses, within configurable tolerance)
- PDF invoice output (per-customer)
- CSV export of a billing run
- Outbound metering API + webhook on daily close
- Mid-cycle billing-account onboarding / offboarding with pro-rata final invoice
- Compliance data export — a per-period, per-site view of the data embedded-network operators need for AER reporting (per-account energy, solar-allocation totals, reconciliation status, comms-loss stats, disconnections, billing disputes). Not AER-format templates — see §18 Q17.
- Security & privacy baseline — at-rest encryption, `BillingAccount` access logging, and a documented PII retention policy — see §18 Q19.

### 1.4 Explicitly out of scope (v1 — flagged for later)

- ⚑ Demand charges (kVA / kW maximum demand) — flagged as v1.1
- ⚑ Block tariffs (tiered rates by volume) — flagged as v1.1
- ⚑ AER-compliant interval-substitution rules — v1 stores a `quality` flag on intervals; the
  substitution *algorithm* (what to put in a gap, regulator-grade) is deferred
- ⚑ LGC / STC creation, registration, surrender, and trading — separate module. Note:
  v1's data plane is deliberately structured to be **LGC-claim-ready** (per-NMI
  generation totals filterable by `quality=measured`, full audit trail to raw
  readings) so operators can support a CER audit using outbound API data — see §4.3.
  The platform itself does not produce or transact certificates.
- ⚑ VPP / FCAS market dispatch — separate module
- ⚑ GST / tax accounting integration — v1 emits an amount-ex-GST + GST-amount per invoice;
  external accounting integration is deferred
- ⚑ WEM (Western Australia) and NT — NEM-only in v1
- ⚑ Multi-currency
- ⚑ Credit notes / refunds / debt collection workflow
- Settlement-grade NMI accreditation — the platform produces *invoice-grade* output, not
  AEMO-MDP-accredited settlement data. Pursuing accreditation is a regulated-entity
  program and is explicitly not undertaken; the boundary is surfaced to end customers
  via a configurable invoice-PDF disclaimer. ✅ Resolved 2026-05-20 (was §18 Q18) —
  see §12.2.

---

## 2. Design Principles

Carries forward from SPEC.md §2 with two emphases:

1. **Everything dynamic and configurable.** Tariff shapes, allocation rules, invoice
   templates, billing-run schedules — all data, not code. Same architectural principle as
   the rest of the platform.
2. **Billing rides on the existing model — it does not replace it.** A "meter" is a `Device`
   with a meter profile. A billable energy quantity is a `Stream` with a `billing_role`. A
   tariff is a `ReferenceDataset` with `scope=tenant`. The billing engine consumes existing
   primitives — it does not introduce a parallel data plane. This keeps dashboards, rules,
   alerts, health, audit, and tenant isolation working unchanged on billing data.
3. **Raw is the source of truth; everything else is derived and reproducible.** Aggregates,
   derived streams, allocations, and billing runs are all reproducible from raw
   `StreamReading` records. A billing run snapshots which readings it used; rerunning from
   the same inputs must produce the same outputs.
4. **Billing-grade audit.** Every invoice line item must be traceable end-to-end: invoice →
   line item → readings used → meter → device → ingestion source → raw payload timestamp.

---

## 3. Conceptual Model

```
Tenant (the platform customer — e.g. Brightfield, Precinct Power)
  └── Site
        └── Device                                    ← may be a meter
              ├── meter_profile (optional)            ← NMI, role, phases, pattern approval
              │     └── parent_meter (self-FK)        ← only set for child meters in EN sites
              └── Stream(s)
                    ├── billing_role (optional)        ← import/export/generation/...
                    └── StreamReading(s)
                          └── quality (measured/estimated/gap/substituted)

Tenant
  └── BillingAccount(s)                                ← the END CUSTOMER (host / EN tenant)
        ├── BillingAccountMeter(s)                     ← which meters/streams belong to this account
        ├── BillingAccountTariffAssignment(s)          ← which tariff applies, when
        └── BillingAccountLifecycle                    ← move-in / move-out dates

Tenant
  └── BillingRun(s)                                    ← one run = one period × one set of accounts
        ├── BillingRunSnapshot                         ← exact reading IDs used
        ├── ReconciliationReport (EN sites only)
        ├── SolarAllocationRecord(s)                   ← per interval × child meter
        ├── BillingLineItem(s)                         ← granular per period/tariff/account
        └── BillingInvoice(s)                          ← one per BillingAccount
              └── invoice_pdf (file in object storage)

Tenant
  └── DataConsumer(s)                                  ← outbound API credential
        ├── allowed_meters / allowed_billing_accounts
        └── Webhook(s)
```

Key relationships:

- A platform `Tenant` (e.g. Brightfield) bills many `BillingAccount`s (e.g. Centuria
  Property Group, Aegis Aged Care, etc. — Brightfield's hosts).
- A `BillingAccount` consumes / generates energy through one or more meters
  (`BillingAccountMeter`) — and the meters are `Device` records belonging to the same
  Tenant.
- For embedded networks, a `BillingAccount` corresponds to a single tenant of the precinct
  (e.g. "Shop 14, Riverside Town Centre"). The platform Tenant (Precinct Power) has
  hundreds of `BillingAccount`s per site.

---

## 4. Prerequisite Features

These three features are prerequisites for billing. They are useful on their own (better
dashboards, better rules) and should land before the billing engine itself.

### 4.1 Derived / Computed Streams

**Why:** WW Modbus, CET PMC, and most NMI meters expose **cumulative** kWh registers
(`kWh_Import` counter that only ever increases). Billing needs **interval** kWh
(`kWh consumed in this 5-minute window`). Same need for "consumed-from-solar" (a computed
combination of grid import, grid export, and generation). Today the WW provider doc tells
operators to "calculate the delta in the rules engine or downstream tool" — no.

**Concept:** a `DerivedStream` is configured once and writes regular `StreamReading`
records on a virtual stream. Same pattern as the existing `_battery`/`_signal` virtual
streams. From that point on, dashboards, rules, alerts, exports, and billing all treat the
derived stream as just another stream.

**Supported formulas (v1):**

| Type | Description | Params |
|------|-------------|--------|
| `delta` | New value = current source reading − previous source reading; drops negative deltas (counter reset). | source stream, max_gap_minutes |
| `sum` | New value = Σ source-stream readings at the same timestamp. | source streams |
| `difference` | New value = source A − source B at the same timestamp. | source A, source B |
| `scale` | New value = source × factor. | source, factor |
| `max` / `min` over window | Rolling max/min over N minutes. | source, window_minutes — note: this is what windowed-aggregate rule conditions also need (SPEC §3 phase 5). Share the implementation. |

**Evaluation:**

- Triggered by source-stream `StreamReading` save (same Celery dispatch path as rule
  evaluation; a `DerivedStreamSourceIndex` mirrors `RuleStreamIndex`).
- Output is a `StreamReading` with `quality` inherited from the worst-quality input
  (measured + measured → measured; measured + estimated → estimated; any gap → gap).
- Idempotent on `(stream_id, timestamp)` — re-running on the same inputs produces the same
  reading.

**Storage:** the derived stream is a normal `Stream` record. Its `stream_type` is set to
`derived` (new enum value) so the UI can show provenance.

- **Single-source derived streams** (e.g. cumulative→interval `delta` on one meter) live
  on their source `Device`.
- **Cross-device derived streams** (e.g. `consumed_from_solar` = `generation` (inverter)
  − `grid_export` (gate meter)) live on a per-site **virtual `Device`** with role
  `site_composite` (no physical hardware; auto-created on first cross-device derived
  stream at a site). ✅ Resolved 2026-05-14 (was §18 Q1). Rationale: no arbitrary choice
  of "which source meter owns this", clean delete semantics if a source meter is
  decommissioned, and the UI cleanly separates "what each meter measures" from
  "site-level composites."

**v1.1 formula additions** (deferred — not blocking v1 billing):

| Type | Description | Example use |
|------|-------------|-------------|
| `product` | New value = source A × source B at the same timestamp | Power × elapsed time → energy where no kWh counter exists |
| `quotient` | New value = source A ÷ source B at the same timestamp | Performance ratio = actual generation / expected generation |
| `piecewise` | New value follows a configurable if/then/else rule over one or more source streams | "If `grid_export` > 0, use `feed_in_tariff`; else 0" — though this is better expressed in the rules engine in most cases |

### 4.2 Interval Aggregation Engine

**Why:** billing for a month over 30-minute intervals = ~1,440 intervals × N meters; doing
that on raw readings every billing run is fine for a few sites but scales badly for
embedded networks with thousands of child meters. Reports and dashboards also benefit.

**Concept:** rolling aggregates of stream readings at fixed periods (5 min, 30 min, 1 hour,
1 day, 1 month). Stored in `IntervalAggregate` records, maintained by a Celery beat task,
backfillable on demand.

**Aggregation kinds per stream:**

- `sum` — for energy streams (kWh import over an hour = sum of the 5-minute intervals)
- `mean` — for instantaneous streams (average voltage over an hour)
- `min` / `max` — for instantaneous streams (peak demand over an hour)
- `last` — for cumulative counters (the last reading in the period; deltas come from
  consecutive period-end readings or from a derived stream)

Configured per stream (default: `sum` for energy, `mean` for power/voltage/current,
`last` for cumulative). Multiple aggregations per stream allowed.

**Quality summary per aggregate:** counts of source readings by quality (measured /
estimated / gap / substituted), plus a single derived "aggregate quality" (worst-input
rule).

**Retention:** all aggregate periods retained forever in v1, mirroring the raw-reading
retention policy. ✅ Resolved 2026-05-14 (was §18 Q3). Rationale: engineering cost of
rollup logic (quality-flag preservation across collapsed periods, re-billing at full
fidelity for old periods, overlapping with active billing runs) is real and not justified
by storage savings at current scale. Revisit if and when raw-reading retention is
revisited at the SPEC level.

### 4.3 Data Quality Flags

**Why:** billing must be able to flag intervals where the value was not directly measured.
AER embedded-network rules require estimation under specific conditions; a regulator-grade
substitution algorithm is *out of v1 scope*, but **flagging** is in scope and must land
before billing.

**Schema additions:**

- `StreamReading.quality` (enum: `measured` / `estimated` / `substituted` / `gap`).
  Default `measured`. Set by ingestion path (raw readings = `measured`), by derived-stream
  worst-input propagation, or by an interval-fill task (`gap` → no data; `substituted` →
  filled by an explicit estimation policy when one is implemented).
- `IntervalAggregate.quality_breakdown` (JSONB: `{measured: 287, estimated: 1, gap: 0}` for
  a 5-min-interval daily aggregate from 30-min source data).
- `BillingLineItem.quality_summary` (JSONB, rolled up further).

**v1 stance on estimation and substitution** ✅ Resolved 2026-05-14 (was §18 Q12 + Q13):

- v1 leaves gap intervals **unfilled** — they remain `gap`. The billing run flags them
  on the affected invoice line item via `quality_summary`, and the operator decides
  the cycle-close response (investigate comms, re-run with recovered data, hold the
  account, or enter a manual adjustment line before finalizing).
- v1 does **not** ship any automated estimation algorithm. Linear-interpolation /
  prior-period substitution / weather-normalised substitution are all deferred to v1.1.
- AER-compliant settlement substitution rules (NER Chapter 7 / MSATS procedures) are
  out of scope entirely — they belong to a separate compliance project, not a v1.1
  enhancement. v1's positioning per §1.4 is **invoice-grade output, not AEMO-MDP-
  accredited settlement data** and that line is held deliberately.
- **Operators are responsible for cycle-close gap resolution in v1.** This is explicit
  in the contract with operators so there are no surprises.

**LGC-claim-ready data** (a deliberate v1 capability, distinct from LGC trading which
remains out of scope per §1.4):

The combination of (a) NMI + pattern-approval on every billing meter (§4), (b) raw
readings retained forever per SPEC, (c) the `quality` enum on every reading + roll-up
to `quality_breakdown` on aggregates and `quality_summary` on line items, (d) the
`generation` / `storage` / `bess_charge` / `bess_discharge` separation (§4, §5.2),
and (e) the §2 end-to-end audit trail means an operator (or their LGC agent) can
extract per-accredited-NMI generation kWh, filter to **measured-only** intervals, and
trace each kWh back to a raw payload timestamp — sufficient to support an LGC claim
audit by the Clean Energy Regulator. The platform does not create / register /
surrender / trade certificates; that workflow is out of scope (see §1.4 and §19), but
the data plane is LGC-audit-ready by construction. **This positioning must be
preserved** as the module evolves — any future estimation/substitution work must
keep the `quality` provenance so that LGC-eligible kWh remains identifiable.

---

## 5. Metering Model

### 5.1 The Meter Profile

A meter is a `Device` that produces billing-grade energy readings. Rather than introduce a
parallel `Meter` entity, add a one-to-one optional `MeterProfile` to `Device`. Devices
without a profile are unaffected (the existing council irrigation sensor stays an
irrigation sensor).

**New entity — `MeterProfile`** (one-to-one with `Device`):

| Field | Type | Description |
|---|---|---|
| device_id | FK | The meter |
| nmi | string, optional | National Metering Identifier (10 or 11 digits — NEM) |
| meter_role | enum | `gate` (parent of an embedded network) / `child` (tenant meter in an EN) / `generation` (solar revenue meter — generation-only, positive kWh) / `storage` (BESS / battery — bidirectional; produces `bess_charge` + `bess_discharge` streams) / `consumption` (single-tier site host meter) / `common_area` (landlord / common services) / `sub_check` (informational; not billed) |
| parent_meter_id | self-FK | Required when role = `child` or `common_area` and the site is hierarchical; null otherwise. The parent must have role = `gate` |
| pattern_approval | string, optional | e.g. `NMI-M6`, `M14` — informational; used in invoice footers and audit reports |
| phases | int (1 or 3) | Single-phase or three-phase |
| install_date | date, optional | First commissioning; informational |
| serial_number_secondary | string, optional | Secondary serial (CET PMC serial when the meter is a WW 6M+One bundle) |

The existing `Device.serial_number` remains the primary identifier (the WW 6M+MB's
serial, in the bundled case).

### 5.2 Stream Billing Role

Add `Stream.billing_role` (nullable enum):

`grid_import` / `grid_export` / `generation` / `bess_charge` / `bess_discharge` /
`consumption` / `consumption_from_solar` / `net` / `null`

`bess_charge` and `bess_discharge` are always emitted as a pair from a `storage` meter
(see §4) — `bess_charge` is energy flowing into the battery (positive kWh); `bess_discharge`
is energy flowing out (positive kWh). Treating them as two unsigned streams (rather than a
single signed `generation` stream with negatives) keeps reconciliation arithmetic clean:
the available solar pool in §6 is `Σ generation − gate_export`, with `bess_discharge`
explicitly excluded.

The billing engine looks for streams with a non-null `billing_role` on meters in a billing
account's scope.

Typical mappings:

| Meter type | Source stream | billing_role |
|---|---|---|
| CET PMC via WW Modbus | `modbus_kwh_import` (cumulative) → `kwh_import_interval` (derived `delta`) | `grid_import` |
| Same meter | `modbus_kwh_export` (cumulative) → derived `delta` | `grid_export` |
| Inverter via vendor API | `energy_total` (cumulative) → derived `delta` | `generation` |
| Site composite | computed `generation` − `grid_export` (derived `difference`) | `consumption_from_solar` |

### 5.3 Hierarchical Sites

A site is hierarchical when at least one of its meters has `meter_role = gate`. All child
meters at that site must reference the gate meter via `parent_meter_id`. The platform
enforces this at write time:

- A `gate` meter has no `parent_meter_id`
- A `child` / `common_area` meter at a hierarchical site must have a non-null
  `parent_meter_id` pointing to a `gate` meter on the same site
- A site has at most one `gate` meter in v1. ✅ Resolved 2026-05-14 (was §18 Q4). None
  of the named billing personas need multi-gate sites in v1; relaxing this is a v1.1
  expansion (would require Σ-gates reconciliation arithmetic, gate-scoped solar
  allocation, and possibly multi-parent children).
- Deactivating a `gate` meter is blocked while child meters are still active

---

## 6. End-Customer Model

The platform Tenant is the *operator* (Brightfield, Precinct Power). The *end customer*
the operator bills is a **`BillingAccount`** — a new entity.

### 6.1 `BillingAccount`

| Field | Type | Description |
|---|---|---|
| id | int | |
| tenant_id | FK | The operator |
| name | string | e.g. "Centuria Property Group", "Shop 14 — Riverside" |
| customer_reference | string, optional | Operator-side customer code (free text) |
| contact_email | string | |
| contact_phone | string, optional | |
| billing_address | JSONB | Lines, suburb, state, postcode |
| abn | string, optional | Australian Business Number (printed on invoice) |
| account_type | enum | `ppa_host` / `en_tenant` / `internal` (e.g. landlord common services) |
| parent_account_id | self-FK, nullable | For grouping — e.g. one corporate parent → many sub-accounts. Informational only in v1; not used by the billing engine |
| invoice_email_recipients | array of email | Where invoices go on finalize |
| is_active | bool | |
| activated_at | datetime | |
| deactivated_at | datetime, nullable | Move-out — used to pro-rata a final invoice |
| floor_area_sqm | decimal, optional | Net lettable area. Only required when the site's `common_area_apportionment_method` is `by_floor_area` (§18 Q20) |
| created_at | datetime | |

### 6.2 `BillingAccountMeter`

Links a `BillingAccount` to one or more `Stream`s on one or more meter `Device`s.

| Field | Type | Description |
|---|---|---|
| id | int | |
| billing_account_id | FK | |
| stream_id | FK → Stream | The specific stream that's billed (e.g. the `grid_import` interval kWh derived stream on a CET PMC) |
| effective_from | datetime | When this meter started being attributed to this account |
| effective_to | datetime, nullable | When it stopped (account moved out, meter swapped) |

Linking is at *stream* level, not just *device* level, because one meter typically carries
several billing-role streams (import, export, generation) that may belong to different
accounts. In the PPA case, a single host meter's `grid_import` and the on-site inverter's
`generation` (and the derived `consumption_from_solar`) may all bill back to the same host
account at different rates — separate stream entries with the same `billing_account_id`.

⚑ **Open:** do we need a `proportion` field for shared meters (e.g. two tenants behind one
sub-meter, splitting 60/40)? Not in v1 — discourage the case; require physical
sub-metering. Note as v1.1 candidate.

### 6.3 `BillingAccountTariffAssignment`

The bridge from a billing account to a tariff (which is a `ReferenceDataset`).

| Field | Type | Description |
|---|---|---|
| id | int | |
| billing_account_id | FK | |
| stream_id | FK → Stream, nullable | If null, this tariff applies to *all* billing-roleed streams on the account. If set, it scopes to one (e.g. different rate for the `generation` stream vs the `grid_import` stream) |
| dataset_id | FK → ReferenceDataset | The PPA tariff (scope=tenant) |
| dimension_filter | JSONB | Same shape as `TenantDatasetAssignment.dimension_filter` — picks the right rows in the dataset |
| version | string, nullable | Pin a version (e.g. "2025-26") or null = always latest |
| effective_from | date | |
| effective_to | date, nullable | |

Reuses the row-resolution logic from `TenantDatasetAssignment` (SPEC §3 Feature: Reference
Datasets) — same code path, different anchor.

---

## 7. Tariff Model

Tariffs use the existing `ReferenceDataset` engine with `scope=tenant`. No new tariff
entity. This is deliberately consistent with the existing `network-tariffs` system dataset
seeded for all 8 NEM DNSPs.

### 7.1 PPA generation tariff (Brightfield example)

Dataset config:

```
slug:               ppa-generation-tariffs
scope:              tenant
has_version:        true
has_time_of_use:    false   ← typical PPA: flat $/kWh. Set true for TOU PPAs.
dimension_schema:   [{key: "contract_code"}]
value_schema:       [{key: "rate_cents_per_kwh", unit: "c/kWh"}]
```

Example row:

| version | dimensions | values |
|---------|-----------|--------|
| 2025-26 | `{contract_code: "CENTURIA-2024"}` | `{rate_cents_per_kwh: 11.00}` |

Assigned to a `BillingAccount` via `BillingAccountTariffAssignment` with
`dimension_filter: {contract_code: "CENTURIA-2024"}`, scoped to the `generation` stream.

### 7.2 PPA consumption-from-solar tariff (Brightfield example)

Same shape as 7.1 but `consumption_from_solar` stream. Higher rate (typical 16–20 c/kWh,
priced below grid retail).

### 7.3 Embedded-network retail tariff (Precinct Power example)

```
slug:               en-retail-tariffs
scope:              tenant
has_version:        true
has_time_of_use:    true
dimension_schema:   [{key: "tariff_code"}, {key: "period_name"}]
value_schema:       [{key: "rate_cents_per_kwh"}, {key: "daily_supply_cents"}]
```

TOU rows (peak / off-peak / shoulder) with `applicable_days` + `time_from` / `time_to`
exactly as in the seeded `network-tariffs` dataset.

### 7.4 What can be expressed today vs what's flagged

| Tariff shape | v1 | Notes |
|---|---|---|
| Flat rate | ✅ | Single row |
| Time-of-use (peak/off-peak/shoulder) | ✅ | Reuses `has_time_of_use` |
| Daily supply charge | ✅ | Separate value column in the row |
| Versioning (annual update) | ✅ | Reuses `has_version` |
| Solar buyback / feed-in tariff (to host) | ✅ | Same shape as §7.1 PPA generation tariff; applied to a `grid_export` stream; emits a credit line item (`line_kind=credit`). Confirmed v1 because future apartment-complex / strata embedded networks may export surplus to the grid. |
| Common-area cost apportionment | ✅ | Not a tariff per se — common-area energy is metered, costed at the EN tariff, then split across tenant accounts as a `common_area_share` line item. Apportionment method is per-site configurable: `pro_rata_consumption` (default) / `equal_share` / `by_floor_area` (✅ §18 Q20). |
| ⚑ Block tariff (tier rates by kWh consumed) | v1.1 | Needs new condition logic in row resolver |
| ⚑ Demand charge ($/kVA or $/kW max demand) | v1.1 | Needs `derived_stream` for max-demand + a new line-item kind |

---

## 8. Billing Period & Billing Run

### 8.1 Billing period

There is no separate `BillingPeriod` entity in v1. A billing run carries its own
`period_start` and `period_end` (datetimes, inclusive/exclusive respectively). Recurring
schedules are managed by a `BillingSchedule` (8.4) which is a generator of billing runs.

### 8.2 `BillingRun`

| Field | Type | Description |
|---|---|---|
| id | int | |
| tenant_id | FK | |
| site_id | FK, nullable | If set, scope is one site. If null, scope is determined by the `billing_account_ids` set |
| billing_account_ids | int array | Accounts in scope; if empty, all active accounts in the site/tenant |
| period_start | datetime (UTC) | |
| period_end | datetime (UTC) | |
| timezone | string | Snapshot of tenant timezone at run time — fixes TOU resolution |
| status | enum | `draft` / `computing` / `review` / `finalized` / `voided` / `failed` |
| created_by | FK → User | |
| created_at | datetime | |
| computed_at | datetime, nullable | When computation finished |
| finalized_at | datetime, nullable | When admin signed off |
| finalized_by | FK → User, nullable | |
| reconciliation_status | enum, nullable | `ok` / `variance_within_tolerance` / `variance_exceeded` — only for hierarchical runs |
| notes | text | Free-text for the admin to record context |

A `BillingRun` is **immutable once finalized**. To correct a finalized run, void it and
create a new one — same pattern as accounting systems. Void workflow detail in §9.4.

### 8.3 `BillingRunSnapshot`

| Field | Type | Description |
|---|---|---|
| billing_run_id | FK | |
| stream_id | FK → Stream | |
| period_start_reading_id | FK → StreamReading, nullable | The reading used as the "start" cumulative value (for delta-from-cumulative billing) |
| period_end_reading_id | FK → StreamReading | The reading used as the "end" cumulative value |
| interval_aggregate_ids | int array | When billing from interval aggregates, the exact aggregate rows used |
| computed_kwh | numeric | The total kWh attributed to this stream in this run |
| quality_summary | JSONB | `{measured_intervals, estimated_intervals, gap_intervals}` |

The snapshot is what makes a billing run reproducible and auditable — the regulator's
question "where did the 84,217 kWh on invoice INV-2026-000147 come from?" is answered by
joining run → snapshot → readings.

### 8.4 `BillingSchedule` (optional, for automated recurring runs)

| Field | Type | Description |
|---|---|---|
| id | int | |
| tenant_id | FK | |
| name | string | e.g. "Monthly PPA — calendar month" |
| site_id / billing_account_ids | | Scope |
| cadence | enum | `monthly_calendar` / `monthly_anchor` (a day-of-month) / `quarterly` / `custom_cron` ⚑ |
| anchor_day | int 1–31, nullable | For `monthly_anchor` |
| period_offset_days | int | How many days after period end to run (e.g. 3 = invoice on the 3rd) |
| auto_finalize | bool | If true, runs auto-finalize when reconciliation = ok; otherwise human review required |
| is_active | bool | |

Schedules dispatch `BillingRun` records via a Celery beat task.

---

## 9. Billing Run Algorithm

The end-to-end algorithm, run as a Celery task chain dispatched on `BillingRun` creation.

### 9.1 Inputs

- `BillingRun` (period, scope, timezone)
- The set of `BillingAccount`s in scope and their active `BillingAccountMeter`s
- The active `BillingAccountTariffAssignment`s for each account
- For hierarchical sites: the `gate` meter and its child meters
- The site's `TenantDatasetAssignment`s for any network-tariff lookups needed (e.g.
  computing a host's "deemed grid rate" to show savings on the PPA invoice — optional)

### 9.2 Steps

```
1. Resolve scope
   - Expand billing_account_ids if empty; filter by active && (activated_at <= period_end)
     && (deactivated_at is null || deactivated_at > period_start)
   - For each account, determine its effective BillingAccountMeter set during the period
     (split into sub-periods if a meter moved in/out mid-period)

2. Pull data
   - For each stream in scope, load interval aggregates over [period_start, period_end] at
     the smallest aggregation period that meets the tariff's resolution requirement
     (TOU tariffs → 30 min minimum; flat tariffs → daily is sufficient)
   - Where a stream is a 'derived' delta-from-cumulative, the aggregation engine already
     produced interval kWh values — use those directly
   - For raw counter streams without a configured derived delta: compute deltas on the fly
     for this run only (and flag this — the operator should have set up a derived stream)

3. (Hierarchical sites only) Compute solar allocation
   - For each interval in [period_start, period_end]:
     a. Read total generation from the gate's site (sum across generation meters)
     b. Compute net allocation pool = generation - export_at_gate (kWh that stayed inside
        the network this interval)
     c. Allocate the pool across child accounts proportionally to each child's
        grid_import_interval value for that interval (pro-rata by interval consumption)
     d. Write a SolarAllocationRecord per (interval, child account)

4. (Hierarchical sites only) Reconcile
   - For each interval, compute: gate_import + generation ≈ Σ child_consumption + common_area
     + losses
   - Sum over the period. Compare variance vs the site's reconciliation_tolerance_percent.
   - Set BillingRun.reconciliation_status accordingly. variance_exceeded → status = 'review'

5. Compute line items per account
   - For each BillingAccount:
     - For each (BillingAccountMeter, sub-period, tariff_assignment):
       - Resolve the tariff: dataset row(s) matching dimension_filter, version selection,
         TOU bucketing in tenant timezone, validity windows
       - Apply the rate(s) to the period's kWh — one BillingLineItem per (account, period,
         tariff_period_name) e.g. one for 'peak', one for 'off-peak'
       - For supply charges: one BillingLineItem per (account, period, 'daily_supply') with
         (days_in_period × daily_supply_cents)
       - For generation/consumption-from-solar PPAs: separate line items keyed to those
         streams
       - Carry quality_summary forward
     - Sum line items → invoice_subtotal_ex_gst
     - GST = subtotal × `Tenant.gst_rate` (configurable per tenant; default 0.10 — see §14)
     - Total = subtotal + GST

6. Generate invoices
   - One BillingInvoice per account
   - Allocate invoice_number from the tenant's invoice-number sequence
   - Render PDF (template — tenant-branded; 12.x)
   - Store PDF in object storage (S3 / MinIO via django-storages)

7. Update run status
   - status = 'review' if reconciliation_status = variance_exceeded
   - else status = 'computing' → 'draft' (awaiting human finalize) OR 'finalized' (if
     auto_finalize is true)
   - On finalize: send invoice emails to BillingAccount.invoice_email_recipients
```

### 9.3 Concurrency & retries

- A `BillingRun` runs as a Celery task chain. Each step is idempotent on `billing_run_id`.
- If a step fails, the run is marked `failed` with the failing step recorded. Restart from
  the last successful step.
- Only one in-flight run per `(site_id, period_start, period_end)` — enforced via a Redis
  flag (same `SET NX` pattern as the rule engine, SPEC §3 Rule Evaluation).
- Finalize is an atomic DB transaction. Once finalized, the run + its line items + its
  invoices + the snapshot are all immutable.

### 9.4 Reruns and voids

- A `draft` or `review` run can be re-computed (replaces all line items, snapshot,
  invoices, allocations). Any user with run-create permission can re-compute.
- A `finalized` run cannot be edited. To correct, **void** it (status → `voided`) and
  create a new run for the same period. Voided runs and their line items, invoices, and
  allocations are retained immutably for audit. ✅ Resolved 2026-05-14 (was §18 Q8):
  - **Authorisation:** void is **Tenant Admin only** (not Operator, not View-Only) —
    Voids reverse customer-facing commitments and warrant Admin authorisation.
  - **Credit notes:** No formal `CreditNote` entity in v1 — credit notes / refunds /
    debt collection remain explicitly out of scope per §1.4. The void → new-run flow is
    the v1 correction mechanism; settlement of any over-payment is handled in the
    operator's downstream accounting system.
  - **Customer notification:** On void, if any invoice in the voided run has
    `delivery_status = delivered`, a void-notification email is sent automatically to
    that invoice's `invoice_email_recipients` ("Invoice INV-…-… has been voided; a
    corrected invoice will follow"). Invoices that were never delivered (`pending` /
    `failed` / `sent` but not yet `delivered`) skip the notification. A `silent_void`
    request flag suppresses notifications entirely (for purely internal corrections
    where delivery_status was wrong).

---

## 10. Brightfield Walkthrough (Single-tier PPA)

End-to-end, using the `brightfield` test-data seed values from `docs/clients.md` §Client 2.

**Site:** "Acme Manufacturing — Sydney" — one rooftop solar system + BESS, one host
(Centuria Property Group sub-portfolio site).

**Meters:**

| Device | meter_role | nmi | Streams (billing_role) |
|---|---|---|---|
| `CET PMC-340B @ site main switchboard` | `consumption` | NEM31000xxxxx | `grid_import` (derived delta), `grid_export` (derived delta) |
| `Sungrow inverter` | `generation` | — | `generation` (derived delta from `energy_total`) |
| (Derived) — `consumption_from_solar` | — | — | `consumption_from_solar` (= generation − grid_export, derived) |

**Billing accounts:**

- One `BillingAccount` — name "Centuria Property Group — Acme Mfg Sydney", `account_type = ppa_host`

**Tariff assignments:**

| Tariff (dataset) | Stream | Rate |
|---|---|---|
| `ppa-generation-tariffs` `contract_code: CENTURIA-2024` | `generation` | 11.00 c/kWh |
| `ppa-consumption-from-solar-tariffs` same contract | `consumption_from_solar` | 18.00 c/kWh |

**Billing run:** monthly calendar, runs on the 3rd of each month for the prior month.

Output:

```
Invoice INV-2026-000147 — Centuria Property Group — Acme Mfg Sydney
Period: 2026-04-01 → 2026-04-30 (Sydney time)

  Generation (PPA)                       28,415 kWh × $0.1100 = $3,125.65
  Consumption from solar (PPA)           22,090 kWh × $0.1800 = $3,976.20
                                                       ────────
                                                          Subtotal $7,101.85
                                                              GST    $710.19
                                                       ────────
                                                            Total  $7,812.04

  Data quality:
    Generation:               measured 100%, estimated 0%, gap 0%
    Consumption from solar:   measured 99.8%, estimated 0%, gap 0.2% (3 intervals)

  Auditable lineage: BillingRun #4429 → BillingRunSnapshot rows 12,481–12,484
```

The PDF is rendered to S3 / MinIO. The invoice email goes to the recipients on the
BillingAccount.

---

## 11. Precinct Power Walkthrough (Hierarchical / Embedded Network)

End-to-end, using the `precinctpower` seed values from `docs/clients.md` §Client 3.

**Site:** "Riverside Town Centre" — 2.6 MW solar, 4 MW / 10 MWh BESS, 270 tenants.

**Meters (abbreviated):**

| Device | meter_role | parent | Streams |
|---|---|---|---|
| Gate meter (NMI XXX) | `gate` | — | `grid_import`, `grid_export` |
| Solar string A (inverter) | `generation` | — | `generation` |
| Solar string B (inverter) | `generation` | — | `generation` |
| BESS controller | `storage` | — | `bess_charge`, `bess_discharge` |
| Common-area meter | `common_area` | gate | `grid_import` |
| Shop 14 child meter | `child` | gate | `grid_import` |
| Shop 22 child meter | `child` | gate | `grid_import` |
| … 270 of these | | | |

✅ **Resolved 2026-05-14.** BESS is its own `meter_role = storage` (§4) and emits two
unsigned interval streams `bess_charge` and `bess_discharge` (§5.2). LGCs attach only
to `generation`, not `bess_discharge`, so keeping the two roles distinct preserves the
audit trail needed for LGC/STC accounting and AER reporting.

**Billing accounts:**

- 270 `BillingAccount`s — one per tenant — each with one `BillingAccountMeter`
  pointing at its child meter's `grid_import` interval stream
- One `internal` BillingAccount per site for the common-area meter(s). This account is not
  invoiced externally — it accumulates the common-area cost for the period, which is then
  apportioned across the 270 tenant accounts as a `common_area_share` line item on each
  tenant invoice. Default apportionment rule is pro-rata by tenant grid_import for the
  period; the per-site `common_area_apportionment_method` selects one of three v1
  methods — `pro_rata_consumption` / `equal_share` / `by_floor_area` (the last reads
  `BillingAccount.floor_area_sqm`). ✅ Resolved 2026-05-20 (was §18 Q20).

**Tariff assignment:**

Each tenant account is assigned **two** tariff rows from `en-retail-tariffs`:

- A `consumed_from_solar` rate (lower — e.g. $0.18/kWh) applied to the tenant's
  solar-allocated kWh for the period
- A `grid_import` rate (higher — e.g. $0.22/kWh) applied to the tenant's remaining
  consumption (`grid_import − consumed_from_solar`) for the period

Each tenant invoice carries **two `energy` line items** — one per rate. The total $ is
identical to the alternative "single rate − discount line" formulation, but the line items
read naturally on the invoice and the solar-share / grid-share split is preserved verbatim
for AER reporting and tenant audit. ✅ Resolved 2026-05-14 (was §18 Q6).

**Solar allocation:** every interval, the solar pool (generation − gate_export) is
allocated across active child accounts in proportion to their grid_import that interval.
A `SolarAllocationRecord` is written per (interval, child account).

**Reconciliation:** at run finalize, the run computes:

```
gate_import + Σ generation − gate_export  vs  Σ child_grid_import + common_area + losses
```

over the period. If variance > 1.5% → run goes to `review`; admin investigates (likely
meter comms gaps).

**Output:** 270 PDF invoices, plus a per-site reconciliation report, plus a per-site
audit pack (AER-style: every interval, every meter, every quality flag).

---

## 12. Invoices & PDF Output

### 12.1 Invoice numbering

Per-tenant sequence. Format template stored on `Tenant`:

| Field | Type | Default |
|---|---|---|
| `invoice_number_format` | string | `INV-{YYYY}-{seq:06d}` |
| `invoice_number_sequence` | int | 0 (atomic increment per issued invoice) |

Atomic increment via `SELECT FOR UPDATE` on the Tenant row at invoice creation time.

### 12.2 PDF template

A single configurable HTML/CSS template per tenant (uploaded by tenant admin), rendered
server-side with **WeasyPrint** (✅ Resolved 2026-05-14 — was §18 Q10). Rationale:
Python-native (no Node/Chromium dependency), runs cleanly in the Django container,
CSS 2.1 + partial CSS 3 coverage which is sufficient for invoice layouts (tabular line
items, headers/footers, logos, GST breakdown). Headless Chrome would have been overkill
for the layout complexity; xhtml2pdf is no longer actively maintained. Default template
provided.

Template variables: invoice number, period, billing account fields, line items, totals,
data-quality summary, audit reference (run ID + snapshot range), the operator's branding
(logo, ABN, contact), and AER-required boilerplate for embedded networks.

A **settlement-grade disclaimer** footer (`Tenant.invoice_settlement_disclaimer`,
editable boilerplate — default: *"Issued on platform-aggregated meter data. Not AEMO
settlement-grade. Subject to NMI metering accuracy of source meters."*) renders by
default on `en_tenant` invoices and is available-but-off for `ppa_host` invoices. It
keeps the §1.4 invoice-grade-not-settlement-grade boundary visible to end customers.
✅ Resolved 2026-05-20 (was §18 Q18).

### 12.3 Storage

Invoices stored in object storage (S3/MinIO) at
`invoices/{tenant_slug}/{YYYY}/{invoice_number}.pdf`. URLs are signed, short-lived (10
minutes) for in-app preview; permanent URLs are not exposed.

### 12.4 Delivery

On finalize: email each `BillingInvoice` to its account's `invoice_email_recipients` with
the PDF attached *and* a signed URL valid for 14 days. Failures logged and retried once
(same delivery infrastructure as alert notifications, SPEC §3 Notifications).

✅ Resolved 2026-05-14 (was §18 Q11): Delivery is **automatic on finalize**, not gated by
a separate "send invoices" action. Operators who want a staged "compute → audit → send"
workflow use `BillingSchedule.auto_finalize = false` (the run sits in `draft` for review,
and the Admin's explicit Finalize action both locks the run and triggers email). Each
`BillingInvoice` is dispatched as its **own** Celery task so one bad recipient address
does not fail the whole run; per-invoice status lives on `BillingInvoice.delivery_status`.
Manual resend remains available via `POST /api/v1/invoices/:id/resend/` (§15).

---

## 13. Outbound Metering API (Channel Partners — Improv)

A read-only, scoped, normalised feed of meter data — separate auth from the platform JWT,
because the consumer is a service account that lives outside the operator's tenant.

### 13.1 `DataConsumer`

| Field | Type | Description |
|---|---|---|
| id | int | |
| tenant_id | FK | The operator that authorised the consumer (e.g. a PPA operator authorising Improv to pull their data) |
| name | string | e.g. "Improv Billing" |
| api_key_hash | string | SHA-256 of the raw key; raw never stored |
| allowed_meter_ids | int array | Subset of the tenant's meter devices |
| allowed_billing_account_ids | int array, nullable | If set, scopes to a subset of accounts; null = all |
| allowed_scopes | string array | Subset of: `intervals`, `daily`, `billing_runs`, `webhooks` |
| rate_limit_per_minute | int | Default 60. **Per-consumer**, not per-tenant — different consumers have different commercial tiers and a misbehaving consumer must not starve sibling consumers of the same tenant. ✅ Resolved 2026-05-14 (was §18 Q14). Per-consumer rate-limit metrics emitted via Prometheus so ops can see consumers approaching their cap. |
| is_active | bool | |
| created_at | datetime | |
| last_used_at | datetime, nullable | |

Auth header: `X-Consumer-Key: <raw_key>`. (Distinct header so it can't be confused with
the JWT `Authorization: Bearer ...`).

### 13.2 Endpoints (under `/api/v1/external/`)

```
GET  /api/v1/external/metering/meters/                          # list allowed meters + NMIs
GET  /api/v1/external/metering/intervals/?meters=&from=&to=     # interval kWh, 30-min default
GET  /api/v1/external/metering/daily/?meters=&from=&to=         # daily close kWh per meter
GET  /api/v1/external/metering/billing-runs/?from=&to=          # finalized runs only
GET  /api/v1/external/metering/billing-runs/:id/                # run detail + line items
GET  /api/v1/external/metering/billing-runs/:id/snapshot/       # the reading-level audit data
```

Response normalisation:

- Units always kWh
- Timestamps always UTC, ISO 8601
- NMI preserved on every row
- Every interval has a `quality` field (`measured` / `estimated` / `gap`)
- Cursor pagination, max 1,000 rows per page. **Opaque base64 cursors**, consistent with
  SPEC §5 — clients treat them as black boxes (the platform can change the underlying
  strategy without breaking partners). Timestamp-style `?after=<timestamp>` was
  considered and rejected because of timestamp-collision skip-or-dupe bugs.
  ✅ Resolved 2026-05-14 (was §18 Q16).

### 13.3 Webhooks

| Field | Type | Description |
|---|---|---|
| id | int | |
| data_consumer_id | FK | |
| event_types | string array | Subset of: `daily_close`, `billing_run_finalized`, `billing_run_voided`, `billing_account_lifecycle`. ✅ Resolved 2026-05-14 (was §18 Q15). `billing_run_voided` is mandatory for partners subscribed to `billing_run_finalized` — without it, voids leave stale data downstream. Additional event types (`interval_data_late_arrival`, `data_quality_alert`, etc.) added on demand. |
| target_url | string (https only) | |
| secret | string | Used for HMAC-SHA256 signing of payloads |
| is_active | bool | |

Delivery: at-least-once. Retries with exponential backoff (1m, 5m, 30m, 4h, 24h) on
non-2xx response. Payload signed with `secret` in an `X-That-Place-Signature` header.

---

## 14. Data Model — Full Additions

Combined summary of all new entities introduced by this module (mirroring SPEC.md §4
style). Existing entities (`Device`, `Stream`, `StreamReading`, `ReferenceDataset`) gain
new fields as noted in §5, §6, §7.

| Entity | Relationships | Key fields |
|---|---|---|
| `MeterProfile` | one-to-one with Device | device_id, nmi, meter_role (gate/child/generation/consumption/common_area/sub_check), parent_meter_id (self-FK to Device.meter_profile), pattern_approval, phases, install_date, serial_number_secondary |
| `DerivedStream` | belongs to Device (or virtual device) | id, device_id, key, label, unit, formula_type (delta/sum/difference/scale/window_min/window_max), source_stream_ids (array), params (JSONB), is_active, created_at |
| `DerivedStreamSourceIndex` | links Stream ↔ DerivedStream | derived_stream_id, source_stream_id — analogous to RuleStreamIndex |
| `IntervalAggregate` | belongs to Stream | id, stream_id, period (5m/30m/1h/1d/1mo), period_start (UTC), value (numeric), aggregation_kind (sum/mean/min/max/last), quality_breakdown (JSONB), computed_at |
| `BillingAccount` | belongs to Tenant; optional parent_account_id self-FK | id, tenant_id, name, customer_reference, contact_email, contact_phone, billing_address (JSONB), abn, account_type (ppa_host/en_tenant/internal), parent_account_id, invoice_email_recipients (array), floor_area_sqm (decimal, optional — NLA, for `by_floor_area` apportionment), is_active, activated_at, deactivated_at, created_at |
| `BillingAccountMeter` | belongs to BillingAccount; refs Stream | id, billing_account_id, stream_id, effective_from, effective_to |
| `BillingAccountAuditLog` | belongs to BillingAccount; refs User | id, billing_account_id, actor_user_id, action (created/viewed/updated/deactivated), changed_fields (JSONB — before/after), occurred_at — PII access log; analogous to SPEC's `RuleAuditLog` (§18 Q19) |
| `BillingAccountTariffAssignment` | belongs to BillingAccount; refs ReferenceDataset | id, billing_account_id, stream_id (nullable), dataset_id, dimension_filter (JSONB), version, effective_from, effective_to |
| `BillingRun` | belongs to Tenant | id, tenant_id, site_id (nullable), billing_account_ids (int array), period_start (UTC), period_end (UTC), timezone, status, created_by, created_at, computed_at, finalized_at, finalized_by, reconciliation_status, notes |
| `BillingRunSnapshot` | belongs to BillingRun; refs Stream + StreamReading | billing_run_id, stream_id, period_start_reading_id, period_end_reading_id, interval_aggregate_ids (array), computed_kwh, quality_summary (JSONB) |
| `BillingLineItem` | belongs to BillingRun + BillingAccount | id, billing_run_id, billing_account_id, stream_id (nullable for daily supply / common-area share / adjustment lines), line_kind (`energy` / `supply` / `discount` / `adjustment` / `credit` (feed-in/export buyback) / `common_area_share`), period_name (peak/off_peak/flat/...), kwh (nullable for non-energy lines), rate_cents_per_kwh (nullable for non-energy lines), amount_cents, gst_cents, quality_summary (JSONB), source_account_id (nullable; set when this line is apportioned from another account — e.g. common-area share, links back to the `internal` common-area account) |
| `BillingInvoice` | belongs to BillingRun + BillingAccount | id, billing_run_id, billing_account_id, invoice_number (unique per tenant), period_start, period_end, subtotal_cents, gst_cents, total_cents, pdf_object_key (S3/MinIO path), issued_at, delivered_at (nullable), delivery_status (sent/delivered/failed) |
| `SolarAllocationRecord` | belongs to BillingRun + BillingAccount | billing_run_id, billing_account_id, interval_start (UTC), allocated_kwh, allocation_method (pro_rata_consumption / equal_share / fixed_proportion ⚑) |
| `ReconciliationReport` | belongs to BillingRun | billing_run_id, site_id, gate_import_kwh, gate_export_kwh, generation_kwh, sum_child_import_kwh, common_area_kwh, computed_loss_kwh, variance_percent, status (ok/within_tolerance/exceeded) |
| `BillingSchedule` | belongs to Tenant | id, tenant_id, name, site_id, billing_account_ids (array), cadence, anchor_day, period_offset_days, auto_finalize, is_active |
| `DataConsumer` | belongs to Tenant | id, tenant_id, name, api_key_hash, allowed_meter_ids (array), allowed_billing_account_ids (array, nullable), allowed_scopes (array), rate_limit_per_minute, is_active, created_at, last_used_at |
| `DataConsumerWebhook` | belongs to DataConsumer | id, data_consumer_id, event_types (array, subset of `daily_close` / `billing_run_finalized` / `billing_run_voided` / `billing_account_lifecycle`), target_url, secret, is_active |
| `WebhookDelivery` | belongs to DataConsumerWebhook | id, webhook_id, event_type, payload (JSONB), attempt_count, last_attempt_at, status (pending/delivered/failed/abandoned), response_code (nullable) |

Existing-entity additions:

| Entity | Added fields |
|---|---|
| `Stream` | `billing_role` (enum nullable: grid_import/grid_export/generation/consumption/consumption_from_solar/net), `aggregation_kind_default` (enum: sum/mean/min/max/last) |
| `StreamReading` | `quality` (enum: measured/estimated/substituted/gap; default measured) |
| `Site` | `is_hierarchical` (bool, default false), `reconciliation_tolerance_percent` (decimal, default 1.5), `embedded_network_exemption_id` (string, nullable — AER registration reference), `common_area_apportionment_method` (enum: pro_rata_consumption/equal_share/by_floor_area; default pro_rata_consumption — §18 Q20) |
| `Tenant` | `invoice_number_format` (string), `invoice_number_sequence` (int), `invoice_pdf_template_id` (FK to a stored template, nullable), `gst_rate` (decimal, default 0.10), `invoice_settlement_disclaimer` (text, nullable — editable boilerplate, rendered by default on en_tenant invoices; §18 Q18) |

---

## 15. API Endpoints

Mirrors SPEC.md §5 style. All under `/api/v1/` unless noted; all require JWT auth except
the `/api/v1/external/` namespace which uses `X-Consumer-Key`.

```
# Meters (helper view over Device with MeterProfile populated)
GET    /api/v1/meters/                                  # ?site=, ?role=, ?nmi=
GET    /api/v1/meters/:id/
PUT    /api/v1/meters/:id/meter-profile/                # set/update NMI, role, parent, etc.

# Derived streams
GET    /api/v1/devices/:id/derived-streams/
POST   /api/v1/devices/:id/derived-streams/
PUT    /api/v1/derived-streams/:id/
DELETE /api/v1/derived-streams/:id/
POST   /api/v1/derived-streams/:id/backfill/            # recompute over a date range

# Interval aggregates (read-only — maintained by the engine)
GET    /api/v1/streams/:id/aggregates/                  # ?period=&from=&to=
POST   /api/v1/streams/:id/aggregates/backfill/         # admin only

# Billing accounts
GET    /api/v1/billing-accounts/                        # ?type=, ?site=, ?active=
POST   /api/v1/billing-accounts/
GET    /api/v1/billing-accounts/:id/
PUT    /api/v1/billing-accounts/:id/
DELETE /api/v1/billing-accounts/:id/                    # soft delete = deactivate
POST   /api/v1/billing-accounts/:id/meters/             # link a stream
DELETE /api/v1/billing-accounts/:id/meters/:link_id/
POST   /api/v1/billing-accounts/:id/tariff-assignments/
PUT    /api/v1/billing-accounts/:id/tariff-assignments/:assign_id/

# Billing runs
GET    /api/v1/billing-runs/                            # ?site=, ?status=, ?period_start=
POST   /api/v1/billing-runs/                            # create + dispatch computation
GET    /api/v1/billing-runs/:id/
POST   /api/v1/billing-runs/:id/recompute/              # only if status in (draft, review)
POST   /api/v1/billing-runs/:id/finalize/               # locks the run + sends invoices
POST   /api/v1/billing-runs/:id/void/                   # only if status = finalized
GET    /api/v1/billing-runs/:id/line-items/
GET    /api/v1/billing-runs/:id/snapshot/
GET    /api/v1/billing-runs/:id/reconciliation/         # hierarchical sites only
GET    /api/v1/billing-runs/:id/allocations/            # hierarchical sites only
GET    /api/v1/billing-runs/:id/export.csv              # streaming CSV of all line items

# Compliance data export (embedded-network operators — §18 Q17)
GET    /api/v1/sites/:id/compliance-export/             # ?period_start=&period_end= — per-account energy, solar-allocation totals, reconciliation status, comms-loss, disconnections, disputes

# Invoices
GET    /api/v1/invoices/                                # ?billing_account=, ?run=
GET    /api/v1/invoices/:id/
GET    /api/v1/invoices/:id/pdf/                        # signed short-lived URL
POST   /api/v1/invoices/:id/resend/                     # re-email to recipients

# Billing schedules
GET    /api/v1/billing-schedules/
POST   /api/v1/billing-schedules/
PUT    /api/v1/billing-schedules/:id/
DELETE /api/v1/billing-schedules/:id/
POST   /api/v1/billing-schedules/:id/run-now/           # manual trigger of a scheduled cadence

# Data consumers (channel-partner credentials)
GET    /api/v1/data-consumers/
POST   /api/v1/data-consumers/                          # returns raw key once; hash stored
GET    /api/v1/data-consumers/:id/
PUT    /api/v1/data-consumers/:id/
DELETE /api/v1/data-consumers/:id/                      # deactivates
POST   /api/v1/data-consumers/:id/rotate-key/           # issues new key, invalidates old
GET    /api/v1/data-consumers/:id/webhooks/
POST   /api/v1/data-consumers/:id/webhooks/
DELETE /api/v1/data-consumers/:id/webhooks/:wh_id/
GET    /api/v1/data-consumers/:id/webhook-deliveries/   # delivery log

# OUTBOUND (X-Consumer-Key auth, separate namespace)
GET    /api/v1/external/metering/meters/
GET    /api/v1/external/metering/intervals/             # ?meters=&from=&to=&period=30m
GET    /api/v1/external/metering/daily/                 # ?meters=&from=&to=
GET    /api/v1/external/metering/billing-runs/          # finalized only
GET    /api/v1/external/metering/billing-runs/:id/
GET    /api/v1/external/metering/billing-runs/:id/snapshot/
```

---

## 16. UI / UX Notes

New screens (mirroring SPEC.md §6 style). All desktop-first; the field-mobile app is out
of scope here.

**Meter Configuration** (Tenant Admin)
- Filter on the device list for "meters only"; flag a device as a meter by attaching a
  meter profile (NMI, role, phases, optional parent)
- Bulk import meter profiles from CSV (matches existing reference-dataset CSV import
  pattern)

**Derived Streams** (Tenant Admin)
- Per-device tab — list, create, edit, backfill
- Formula picker + source-stream picker reuses the rule builder's stream picker

**Billing Accounts** (Tenant Admin)
- List with filters (site, type, status); count of meters and active tariffs per account
- Detail: meters tab (link/unlink streams), tariffs tab (assignments timeline), invoices
  tab (history), lifecycle tab (activated/deactivated dates)
- Bulk import from CSV for embedded-network operators (270 accounts = needs CSV)

**Billing Runs** (Tenant Admin)
- List: status badges (draft/computing/review/finalized/failed/voided), period, scope,
  totals
- Detail: line items table, invoices, reconciliation panel (hierarchical sites),
  allocations panel (hierarchical sites), snapshot drill-down, recompute / finalize / void
  actions
- "New billing run" wizard: scope (site or accounts), period, dry-run preview

**Billing Schedules** (Tenant Admin)
- List + create/edit; cadence picker, scope, auto-finalize toggle
- Next run / last run shown inline

**Tariffs** (Tenant Admin)
- A new "Tariffs" navigation item (separate from Reference Datasets) that's actually a
  filtered view of Reference Datasets — only `scope=tenant` datasets with billing-relevant
  schemas. Hides the system-scope datasets to reduce confusion
- Built-in editors for the standard PPA + EN tariff shapes (a thin layer over the existing
  ReferenceDataset row editor)

**Data Consumers** (Tenant Admin — channel-partner integration)
- List, create (returns the raw API key once for copy), rotate, deactivate
- Per-consumer: allowed meters, allowed accounts, allowed scopes, rate limit, recent
  request log, webhook config, delivery log

**Reconciliation Dashboard** (Tenant Admin, hierarchical sites)
- Per-site card showing latest reconciliation status, variance trend, last billing run
- Drill-down: per-interval breakdown, child-meter health

**Compliance Data Export** (Tenant Admin, embedded-network sites)
- Per-period, per-site export of the data an operator needs for AER reporting:
  per-account energy, solar-allocation totals, reconciliation status, comms-loss
  stats, disconnections, billing disputes. CSV + on-screen view. Not an AER-format
  template — see §18 Q17

**Invoice Template Manager** (Tenant Admin)
- Upload / preview / activate an HTML template; sample render against the most recent
  finalized run

---

## 17. Suggested Phasing (Roadmap Hooks)

The module is realistically four phases. Each is one "phase" in the ROADMAP.md sense (3–4
sprints).

| Phase | Sprints | Theme |
|---|---|---|
| **Phase B1 — Foundations** | ~3 sprints | Derived streams, interval aggregation engine, data quality flags, MeterProfile, NMI on meters, stream billing_role |
| **Phase B2 — Single-tier PPA Billing** | ~3 sprints | BillingAccount, BillingAccountMeter, BillingAccountTariffAssignment, PPA tariff datasets, BillingRun + algorithm for non-hierarchical sites, BillingLineItem, BillingInvoice + PDF, invoice email delivery, BillingSchedule |
| **Phase B3 — Embedded Networks** | ~3 sprints | Hierarchical metering (parent_meter, gate role), solar allocation, reconciliation, EN retail tariffs, EN-specific PDF/invoice template, AER reporting helpers, bulk billing-account CSV import |
| **Phase B4 — Outbound Metering API** | ~2 sprints | DataConsumer + external API namespace, webhooks, signed payloads, delivery log, partner onboarding docs |

Each phase ships independent value:

- **B1** unlocks better dashboards (delta + aggregate views) and better rules (windowed
  conditions) even before billing exists.
- **B2** is sufficient for Brightfield-style customers.
- **B3** is what Precinct Power needs. A **B3-readiness security review** (NDB runbook,
  APP 12/13 tooling scope, Privacy Impact Assessment) is a gate before the first
  embedded network goes live — see §18 Q19.
- **B4** is the Improv channel play.

Total: ~11 sprints, comparable to redoing Phase 4 of the existing roadmap.

---

## 18. Open Questions — Consolidated

⚑ flagged decisions to resolve before each phase begins:

**Architecture / shared**
1. ✅ **Resolved 2026-05-14.** Cross-device derived streams live on a per-site virtual
   `Device` with role `site_composite`; single-source derived streams stay on their
   source device. See §4.1. Also: `product` (×), `quotient` (÷), and `piecewise`
   formulas deferred to v1.1 — v1 ships with `delta`, `sum`, `difference`, `scale`,
   `max/min over window` only.
2. ✅ **Resolved 2026-05-14.** Separate `storage` meter_role with two unsigned billing
   roles `bess_charge` / `bess_discharge`. Keeps LGC accounting and reconciliation
   arithmetic clean; preserves the audit trail required for AER reporting. See §4
   meter_role enum, §5.2 billing_role enum, §11.2 example row.
3. ✅ **Resolved 2026-05-14.** All aggregate periods retained forever in v1, mirroring
   raw-reading retention. Engineering cost of rollup logic outweighs storage savings at
   current scale. See §4.2.
4. ✅ **Resolved 2026-05-14.** Single `gate` meter per site in v1. None of the named
   billing personas need multi-gate sites; relaxing this is a v1.1 expansion. See §5.3.

**Tariffs**
5. ✅ **Resolved 2026-05-14.** v1 scope holds: NEM-only, AUD, flat-rate + TOU + daily
   fixed supply charge. Block tariffs and demand charges remain v1.1. No known
   prospect contract in `wattwatchers_prospects_v2.xlsx` requires demand charges or
   blocks (confirmed by Courtney). Brightfield PPAs are flat $/kWh; Precinct Power's
   embedded-network tenant tariffs are flat-or-TOU $/kWh; the demand charge on
   Precinct Power's parent-meter DNSP bill is recovered through embedded margin in
   the per-kWh tenant tariff, not passed through as a demand line item.
6. ✅ **Resolved 2026-05-14.** Split-rate: two `energy` line items per tenant invoice —
   `consumed_from_solar × en-solar-tariff` (lower rate) and `(grid_import −
   consumed_from_solar) × en-grid-tariff` (higher rate). Same total $ as a single-rate +
   discount-line, but the invoice reads naturally and AER reporting gets the solar-share
   / grid-share breakdown verbatim. See §11.2 tariff-assignment section.
7. ✅ **Resolved 2026-05-14.** Solar buyback / feed-in tariff to host **moves into v1**.
   Modelled as a PPA-generation-tariff-shaped `ReferenceDataset` applied to the host
   site's `grid_export` stream, emitting a `credit` line item. Rationale: future
   apartment-complex / strata embedded networks may export surplus to the grid, and
   it is cheaper to build the line-item kind once than retro-fit it.

**Billing run**
8. ✅ **Resolved 2026-05-14.** Void workflow: Tenant Admin only; no formal credit notes
   in v1 (void → new-run is the correction mechanism); customer notification sent
   automatically only when a voided invoice was already `delivered`, suppressible via a
   `silent_void` flag. See §9.4.
9. ✅ **Resolved 2026-05-14.** GST configurable per tenant via `Tenant.gst_rate`
   (decimal, default 0.10). Per-invoice / per-line-item GST overrides deferred to v1.1
   if a real mixed-supply use case appears. See §9 step 5 and §14 Tenant additions.
10. ✅ **Resolved 2026-05-14.** WeasyPrint. Python-native, no Node/Chromium dependency,
    CSS coverage sufficient for invoice layouts. See §12.2.
11. ✅ **Resolved 2026-05-14.** Automatic on finalize. Staged "compute → audit → send"
    is achieved via `BillingSchedule.auto_finalize = false` (the run sits in `draft`
    until an Admin explicitly Finalizes, which both locks and emails). Each invoice
    dispatches as its own Celery task to isolate failures. Manual resend at
    `POST /api/v1/invoices/:id/resend/`. See §12.4.

**Data quality**
12. ✅ **Resolved 2026-05-14.** No automated estimation in v1. Gaps remain `gap`,
    flagged on line items; operators handle cycle-close gap resolution manually.
    Deferred to v1.1 (configurable policy). Constraint: any future estimation must
    preserve `quality` provenance so LGC-eligible kWh remains identifiable. See §4.3.
13. ✅ **Resolved 2026-05-14.** AER-compliant settlement substitution rules are a
    separate compliance project, not a v1.1 enhancement. v1 positioning held:
    invoice-grade output, not AEMO-MDP-accredited settlement data. See §4.3 and §1.4.
    Note: this defer also keeps the v1 data plane LGC-claim-ready — operators filter
    on `quality=measured` for CER audit.

**Outbound API**
14. ✅ **Resolved 2026-05-14.** Per-consumer rate limiting via
    `DataConsumer.rate_limit_per_minute` (default 60). Per-consumer Prometheus metrics
    emitted for ops visibility. No tenant-level cap in v1 — revoke a runaway key
    instead. See §13.1.
15. ✅ **Resolved 2026-05-14.** Four event types in v1: `daily_close`,
    `billing_run_finalized`, `billing_run_voided`, `billing_account_lifecycle`.
    `billing_run_voided` added beyond the original three so partners consuming
    `billing_run_finalized` hear about Q8 voids and avoid stale downstream data.
    Additional event types added on demand. See §13.3.
16. ✅ **Resolved 2026-05-14.** Opaque base64 cursor pagination, consistent with SPEC §5.
    Clients treat cursors as black boxes; the platform can change the underlying
    strategy without breaking partners. `?after=<timestamp>` was rejected due to
    timestamp-collision skip-or-dupe bugs. See §13.2.

**Compliance / regulatory**
17. ✅ **Resolved 2026-05-20.** No AER-format report templates in v1. Instead v1
    exposes the underlying data: a per-period, per-site **compliance data export**
    (per-account energy, solar-allocation totals, reconciliation status, comms-loss
    stats, disconnections, billing disputes), the `ReconciliationReport` per run
    (§11 / §14), and the outbound metering API (§13) + CSV export (§12) for the
    structural data. v1 does **not** ship AER-format PDF/XML submissions or
    hard-coded ENM-format templates. Rationale: AER report formats change
    periodically; Precinct Power already runs its submissions through a registered
    ENM; different exemption classes need different reports; a buggy auto-generated
    statutory report would damage operator credibility. See §1.3, §15, §16. Cascade:
    Q21 added below.
18. ✅ **Resolved 2026-05-20.** NMI metering accreditation stays out of scope — the
    platform produces **invoice-grade** output, not AEMO-MDP-accredited settlement
    data. Pursuing accreditation would reopen Q12/Q13 (it mandates conforming
    estimation/substitution rules) and is a regulated-entity program that no named
    persona needs: the gate-NMI settlement role is already held by the operator's
    ENM (Precinct Power) or existing metering arrangements (Brightfield). The
    boundary is held AND made visible — a configurable invoice-PDF footer disclaimer
    (`Tenant.invoice_settlement_disclaimer`, editable boilerplate, default *"Issued
    on platform-aggregated meter data. Not AEMO settlement-grade. Subject to NMI
    metering accuracy of source meters."*) that **defaults on for `en_tenant`
    invoices** and is available-but-off for `ppa_host` invoices — plus documentation
    of the boundary in operator onboarding docs and the outbound API docs. Note: the
    distinction is meter *pattern approval* (the hardware — already true, recorded on
    `MeterProfile.pattern_approval`) vs MDP *accreditation* (the data pathway — not
    pursued). See §1.4, §12.2, §14 Tenant additions.
19. ✅ **Resolved 2026-05-20.** A defined security baseline is committed in v1;
    organisational pieces are deferred to a **B3-readiness security review** before
    the first embedded network goes live. Committed in v1: (a) at-rest encryption on
    the production DB (RDS encryption / MinIO server-side encryption); (b) in-transit
    encryption — already true (HTTPS, JWT); (c) access logging on every read/write of
    `BillingAccount` via a new `BillingAccountAuditLog` entity (who, when, what
    changed — analogous to SPEC's `RuleAuditLog`); (d) a documented retention policy —
    PII retained 7 years after account deactivation (ATO tax-record retention), then
    purged with an audit trail. Deferred to the B3-readiness security review: a formal
    Notifiable Data Breach (NDB) runbook; APP 12 right-to-access tooling (fulfillable
    manually in v1); APP 13 right-to-erasure tooling (complicated by tax retention —
    needs legal review); a Privacy Impact Assessment as a required B3 deliverable.
    Rationale: EN tenant data (names, addresses, per-interval consumption, invoices)
    is PII under the Privacy Act 1988 — acute for the ~25% of Precinct Power's
    portfolio that is strata-residential / mixed-use. See §14 `BillingAccountAuditLog`,
    §17.

**Added 2026-05-14 (cascade from Q5/Q7 resolution)**

20. ✅ **Resolved 2026-05-20.** Common-area apportionment exposes **three** per-site
    configurable methods in v1: `pro_rata_consumption` (default — pro-rata by tenant
    grid_import for the period), `equal_share`, and `by_floor_area` (reads tenant net
    lettable area from `BillingAccount.floor_area_sqm`). `by_tenant_count` is dropped —
    it is a special case of `equal_share`. The selected method is stored per site on
    `Site.common_area_apportionment_method`. See §1.3, §7.4, §11, §14.

**Added 2026-05-20 (cascade from Q17 resolution)**

21. ⚑ Which AER report format should v1.1 implement first? Parked until a real
    embedded-network operator names a specific report / exemption class. v1's
    compliance data export (Q17) is the interim answer; promote a concrete format to
    a v1.1 work item once an ENO names one.

---

## 19. What This Doc Does Not Cover

Out of scope here (handled elsewhere or in a future doc):

- Tenant onboarding workflow for billing customers (existing SPEC §3 Tenant Management)
- Authentication for operators (existing JWT system)
- Rate-limit and abuse handling on the outbound API beyond per-consumer caps (platform-
  wide infra concern)
- BESS dispatch optimisation (a separate module — composable today from rules + AEMO
  feed + commands, but a "smart battery" engine is its own arc)
- LGC / STC / carbon credit tracking
- Demand response / VPP / FCAS market participation
- Mobile/field UX for billing-account operations (explicit non-goal — billing users are
  desktop)

---

## 20. Promotion Path to SPEC.md

When this doc stabilises (target: each ⚑ above either resolved or explicitly punted to a
later version), the following promotion happens:

1. **§1 of SPEC.md** — already updating in the small-edits pass; add Metering & Billing
   as a primary product capability.
2. **§3 Features** — add new feature sections sourced from §4 (Derived Streams), §5
   (Metering Model), §6 (End-Customer Model), §7 (Tariff Model), §8–11 (Billing Runs),
   §12 (Invoices), §13 (Outbound API) of this doc.
3. **§4 Data Model** — extend the entity table with the rows in §14 of this doc.
4. **§5 API & Integration** — extend the endpoint list with §15 of this doc.
5. **§6 UI/UX** — extend with the screens in §16 of this doc.
6. **§8 Milestones** — add Phases B1–B4 from §17 of this doc.
7. **§9 Open Questions** — fold any still-open ⚑ items into SPEC.md's flagged-items list.

After promotion, this doc becomes a historical design artifact and SPEC.md is the source
of truth — same path Feeds + Reference Datasets followed.
