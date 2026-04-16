# Reference Datasets Guide

> **Audience:**
> - **That Place Admin** — creating datasets and managing rows
> - **Tenant Admin** — assigning datasets to sites and using them in rules

---

## What is a Reference Dataset?

A reference dataset is a lookup table managed by That Place Admin. It holds structured reference values — tariff rates, emission factors, fuel price indices, or any other tabular data — that tenants can reference in rule conditions without those values being hardcoded.

Two datasets ship pre-loaded on every new platform installation:

| Dataset | Slug | What it contains |
|---------|------|-----------------|
| Network Tariffs (NEM) | `network-tariffs` | Electricity network (use-of-system) tariff rates for all 8 Australian NEM DNSPs; time-of-use and versioned by financial year |
| CO2 Emission Factors | `co2-factors` | Grid electricity CO2-equivalent emission factors by NEM region; versioned by financial year |

If those datasets already cover your use case, skip to [Part B — Assigning a Dataset to a Site](#part-b--tenant-admin-assigning-a-dataset-to-a-site).

---

## Concepts

### Dimension schema vs value schema

Every dataset has two schema parts:

- **Dimension schema** — the lookup key columns. These identify *which* row applies. Example: `state`, `dnsp`, `tariff_type`.
- **Value schema** — the data columns. These are the actual numbers or values returned at evaluation time. Example: `rate_cents_per_kwh`, `daily_supply_charge_cents`.

Think of it as: dimensions are the *keys you search by*, values are *what you get back*.

### Versioning

When `has_version` is enabled, every row carries a version label (e.g. `"2025-26"`). Tenants can pin to a specific version or leave it blank to always use the latest. This supports annual updates — you add the new year's rows with a new version string and existing tenants automatically roll over.

### Time-of-use (TOU)

When `has_time_of_use` is enabled, each row can carry:
- `applicable_days` — which days of the week the row applies (0=Mon … 6=Sun)
- `time_from` / `time_to` — the time window

At evaluation time the row resolver filters by the current day and time in the **tenant's timezone**. A row with no TOU fields set applies at all times.

---

## Part A — That Place Admin: Creating and Managing a Dataset

### Step 1: Create the dataset schema

Navigate to **Admin → Reference Datasets → New Dataset**.

| Field | Description |
|-------|-------------|
| **Name** | Human-readable name (e.g. `Water Usage Rates`) |
| **Slug** | URL-safe identifier, unique across all datasets (e.g. `water-usage-rates`). Set once — cannot be changed after rows are added. |
| **Description** | Optional. Shown to Tenant Admins when they browse available datasets. |
| **Has Versioning** | Enable if rows will be updated periodically (annually, quarterly). Each version is a string label, e.g. `"2025-26"`. |
| **Has Time-of-Use** | Enable if different values apply at different times of day or days of week. |

#### Dimension schema

Add one entry per lookup column. Each entry has:

| Sub-field | Description | Example |
|-----------|-------------|---------|
| `key` | Machine-readable column name — used in CSV headers and dimension filters | `dnsp` |
| `label` | Human-readable label shown in the UI | `Distributor` |
| `type` | Data type: `string` or `numeric` | `string` |

**Worked example — network tariffs:**
```
key: state        label: State       type: string
key: dnsp         label: DNSP        type: string
key: tariff_type  label: Tariff Type type: string
key: voltage_level label: Voltage    type: string
```

#### Value schema

Add one entry per data column. Each entry has:

| Sub-field | Description | Example |
|-----------|-------------|---------|
| `key` | Machine-readable column name — used in CSV headers and rule conditions | `rate_cents_per_kwh` |
| `label` | Human-readable label | `Energy Rate` |
| `type` | Data type: `numeric`, `string`, or `boolean` | `numeric` |
| `unit` | Optional unit label shown in the rule builder | `c/kWh` |

**Worked example — network tariffs:**
```
key: rate_cents_per_kwh         label: Energy Rate          type: numeric  unit: c/kWh
key: daily_supply_charge_cents  label: Daily Supply Charge  type: numeric  unit: c/day
key: capacity_charge_cents_per_kva label: Capacity Charge   type: numeric  unit: c/kVA/day
```

Click **Save**. The dataset exists but has no rows yet.

---

### Step 2: Add rows

You can add rows one at a time through the UI or in bulk via CSV upload. For datasets with more than a handful of rows, CSV import is strongly recommended.

#### Option A — Adding rows individually

Navigate to **Admin → Reference Datasets → [Dataset Name] → Rows → Add Row**.

| Field | Required | Description |
|-------|----------|-------------|
| **Version** | If `has_version` is on | Period label, e.g. `2025-26` |
| **Dimension fields** | Yes | One input per dimension schema column |
| **Value fields** | Yes | One input per value schema column |
| **Applicable Days** | If `has_time_of_use` is on | Checkboxes: Mon Tue Wed Thu Fri Sat Sun |
| **Time From / Time To** | If `has_time_of_use` is on | Wall-clock times in `HH:MM` format. Leave both blank to apply at all times. |
| **Valid From / Valid To** | No | Optional date range — use if this row becomes effective on a future date or expires |

#### Option B — Bulk CSV import

Navigate to **Admin → Reference Datasets → [Dataset Name] → Rows → Import CSV**.

Upload a UTF-8 CSV file. Column requirements:

**Required columns** (must match your schema's `key` values exactly):
- All dimension schema keys
- All value schema keys

**Optional columns** (include only if your dataset uses them):

| Column | Format | Description |
|--------|--------|-------------|
| `version` | Text string, e.g. `2025-26` | Required if `has_version` is enabled |
| `applicable_days` | Comma-separated integers, e.g. `0,1,2,3,4` | 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun. Leave blank = applies all days |
| `time_from` | `HH:MM` | Start of TOU window, e.g. `07:00` |
| `time_to` | `HH:MM` | End of TOU window, e.g. `21:00`. Can wrap midnight (e.g. `21:00` → `07:00`) |
| `valid_from` | `YYYY-MM-DD` | Row becomes active on this date |
| `valid_to` | `YYYY-MM-DD` | Row expires on this date |

**Upsert behaviour:** rows are matched by `version` + all dimension columns. If a matching row already exists it is updated; otherwise it is created. Existing rows not present in the CSV are left untouched.

**Worked example — network tariffs CSV:**

```csv
version,state,dnsp,tariff_type,voltage_level,rate_cents_per_kwh,daily_supply_charge_cents,capacity_charge_cents_per_kva,applicable_days,time_from,time_to
2025-26,QLD,Energex,residential_tou,LV,29.50,98.00,,0,07:00,21:00
2025-26,QLD,Energex,residential_tou,LV,10.20,98.00,,,21:00,07:00
2025-26,QLD,Energex,residential_tou,LV,10.20,98.00,,5,
2025-26,NSW,Ausgrid,residential_tou,LV,32.50,110.00,,0,07:00,21:00
2025-26,NSW,Ausgrid,residential_tou,LV,12.80,110.00,,,21:00,07:00
```

> **Note:** To specify multiple days, use a separate row per day group, or use a comma-separated list **inside a quoted cell**: `"0,1,2,3,4"`. For example, to apply a rate Monday–Friday: `applicable_days` = `"0,1,2,3,4"`.

The import returns a summary:
```
{ "imported": 42, "errors": [] }
```

If any rows fail, the error list shows the row number and reason. The entire import is rolled back if errors occur — fix all errors and re-upload.

---

### Step 3: Verify rows

After importing, navigate to **Admin → Reference Datasets → [Dataset Name] → Rows**.

Use the **Version** filter dropdown to view rows by version. Check that:
- The row count matches your source data
- At least one row appears for each dimension combination you expect
- TOU rows cover all hours without gaps (for TOU datasets)

---

### Annual update workflow

Adding a new financial year requires only uploading a new CSV with the updated version string — no existing rows are modified.

1. Prepare your updated CSV with `version: "2026-27"` in every row
2. Upload via **Import CSV** on the dataset's Rows page
3. Tenants with `version: null` assignments automatically resolve to `"2026-27"` from the effective date of the new rows
4. Tenants with a pinned version (e.g. `"2025-26"`) continue to use the old rates until they update their assignment

---

## Part B — Tenant Admin: Assigning a Dataset to a Site

A dataset assignment tells the platform which subset of rows applies to a particular site (or your whole tenant). It also acts as the connection point when building rule conditions.

### Creating an assignment

Navigate to **Settings → Sites → [Site Name] → Dataset Assignments → Add Assignment**.

| Field | Required | Description |
|-------|----------|-------------|
| **Dataset** | Yes | Select from the available dataset library |
| **Scope** | Yes | `Site` (applies to this site only) or `Tenant-wide` (applies across all sites without a more specific assignment) |
| **Dimension Filter** | Yes | The dimension values that identify your rows. Enter one value per dimension key. Example: `dnsp = Ausgrid`, `tariff_type = residential_tou`, `state = NSW` |
| **Version** | No | Pin to a specific version (e.g. `2025-26`) or leave blank to always use the latest |
| **Effective From** | Yes | The date from which this assignment is active |
| **Effective To** | No | Leave blank for ongoing assignments |

> **Tip:** You do not need to specify all dimension keys in the filter — only the ones that uniquely identify your site's applicable rows. For example, if all rows for a given `dnsp` and `tariff_type` are already unique, you don't need to also include `voltage_level`.

### Previewing the resolved value

Before saving a rule that uses this assignment, you can preview exactly what value the platform will return right now.

Navigate to the assignment and click **Preview Resolved Value**.

The platform runs the full resolution logic — dimension filter → version selection → TOU filter in your tenant's timezone — and returns the matching row's values:

```json
{
  "resolved_values": {
    "rate_cents_per_kwh": 32.50,
    "daily_supply_charge_cents": 110.0,
    "capacity_charge_cents_per_kva": null
  }
}
```

If the preview returns an error, see [Troubleshooting resolution errors](#troubleshooting-resolution-errors) below.

---

## Using a Reference Dataset in a Rule

Once an assignment exists for a site, you can use it as a condition source in the rule builder.

Navigate to **Rules → New Rule → Conditions** and select **Reference Value** as the condition type.

| Setting | Description |
|---------|-------------|
| **Dataset** | Select the dataset (e.g. `Network Tariffs`) |
| **Value Key** | Which value column to evaluate (e.g. `rate_cents_per_kwh`) |
| **Operator** | Comparison operator: `>`, `<`, `>=`, `<=`, `==` |
| **Threshold** | The value to compare against |

The rule builder shows a live preview of the currently resolved value next to the value key dropdown so you can confirm the right row is being picked.

**Example rule:** *"Alert when the current network tariff rate exceeds 25 c/kWh"*
- Condition type: Reference Value
- Dataset: Network Tariffs
- Value key: `rate_cents_per_kwh`
- Operator: `>`
- Threshold: `25`

At evaluation time, the platform resolves the rate for the site's assigned tariff and time-of-use period, then compares it to the threshold. The rule fires when the rate crosses 25 c/kWh — for example, as the clock moves from an off-peak window into a peak window.

> Reference-value-only rules (rules where every condition uses reference data rather than a live device stream) are automatically re-evaluated every 5 minutes by a background task, so TOU boundary crossings are caught without needing a device reading to trigger evaluation.

---

## Troubleshooting Resolution Errors

**`No active rows found for dataset "..." with filter {...}`**
The dimension filter on your assignment does not match any rows. Check:
- Spelling and capitalisation of dimension values (matching is case-insensitive but must otherwise be exact)
- That rows with the matching dimensions exist and are marked active
- That the current date falls within the row's `valid_from` / `valid_to` range (if set)

**`Dataset "..." has no active versioned rows`**
The dataset has `has_version = true` but no rows exist yet, or all rows are inactive. Import rows first.

**`No rows for dataset "..." match the current time (...)`**
A TOU dataset has rows but none cover the current time window. This usually means there is a gap in your TOU coverage — the hours between one row's `time_to` and the next row's `time_from` are uncovered. Ensure your TOU rows together cover all 24 hours. A row with no `time_from` / `time_to` acts as a catch-all fallback.

**`Ambiguous resolution: N rows match`**
More than one row matches the dimension filter and TOU window. This indicates overlapping rows — for example, two rows with the same dimensions and overlapping time windows. Review your rows and ensure no two active rows can match simultaneously for the same dimension combination.

---

## Pre-loaded Datasets Reference

### `network-tariffs` — Network Tariffs (NEM)

| Property | Value |
|----------|-------|
| Has versioning | Yes — financial year format, e.g. `2025-26` |
| Has time-of-use | Yes — rows carry `applicable_days`, `time_from`, `time_to` |
| Dimension keys | `state`, `dnsp`, `tariff_type`, `voltage_level` |
| Value keys | `rate_cents_per_kwh`, `daily_supply_charge_cents`, `capacity_charge_cents_per_kva` |

Tariff data is not pre-loaded — rates must be imported each financial year via CSV. Source your rates from each DNSP's published network pricing schedule (see `docs/providers/` for links).

**Typical assignment dimension filter:**
```json
{ "state": "NSW", "dnsp": "Ausgrid", "tariff_type": "residential_tou", "voltage_level": "LV" }
```

---

### `co2-factors` — CO2 Emission Factors

| Property | Value |
|----------|-------|
| Has versioning | Yes — financial year format, e.g. `2023-24` |
| Has time-of-use | No |
| Dimension keys | `state`, `grid` |
| Value keys | `kg_co2e_per_kwh` |

2023–24 NEM region factors are pre-loaded. Source: Australian National Greenhouse Accounts Factor and Methods Workbook 2024.

**Typical assignment dimension filter:**
```json
{ "state": "QLD", "grid": "NEM" }
```

---

---

## How-To: Update Network Tariffs Each Financial Year

Every July, DNSP network pricing schedules change. Follow these steps to load the new year's rates without affecting tenants mid-year.

### Step 1 — Obtain the new tariff data

Download each DNSP's published network pricing schedule for the new financial year. See `docs/providers/` for direct links to each DNSP's pricing page.

You need these values per tariff code:
- Peak energy rate (c/kWh)
- Off-peak energy rate (c/kWh, if the tariff is TOU)
- Shoulder rate (c/kWh, if applicable)
- Daily supply charge (c/day)
- Capacity charge (c/kVA/day, if applicable)

### Step 2 — Prepare the CSV

Copy `backend/apps/feeds/seed_data/network_tariffs_template.csv` as your starting point.

Rules:
- Set `version` to the new financial year string, e.g. `2026-27`
- Include every row for every DNSP × tariff code × TOU period combination
- Time windows must cover all 24 hours with no gaps — include a catch-all row (blank `time_from` / `time_to`) for any periods not otherwise covered
- `applicable_days` uses comma-separated integers `0`–`6` inside a **quoted cell** if multiple days: `"0,1,2,3,4"`

**Peak/off-peak example for a single DNSP:**

```csv
version,state,dnsp,tariff_type,voltage_level,rate_cents_per_kwh,daily_supply_charge_cents,capacity_charge_cents_per_kva,applicable_days,time_from,time_to
2026-27,NSW,Ausgrid,residential_tou,LV,34.00,115.00,,"0,1,2,3,4",07:00,21:00
2026-27,NSW,Ausgrid,residential_tou,LV,13.50,115.00,,,21:00,07:00
2026-27,NSW,Ausgrid,residential_tou,LV,13.50,115.00,,"5,6",,
```

### Step 3 — Upload via the Admin UI

1. Navigate to **Admin → Reference Datasets → Network Tariffs (NEM) → Rows → Import CSV**
2. Upload your prepared CSV
3. The import is an **upsert** — rows matched by `version` + all dimension columns are updated; new combinations are created; rows from previous versions are untouched
4. Check the summary: `{ "imported": N, "errors": [] }`
5. If there are errors, the entire import is rolled back — fix the listed rows and re-upload

Alternatively, using the management command directly in the container:
```bash
docker-compose exec backend python manage.py load_reference_data --csv network-tariffs /path/to/tariffs_2026_27.csv
```

### Step 4 — Verify

1. Navigate to **Admin → Reference Datasets → Network Tariffs (NEM) → Rows**
2. Use the **Version** dropdown to filter to `2026-27`
3. Confirm row counts match your source data

### Step 5 — Tenant rollover

Tenants with **unpinned** version assignments automatically resolve to the latest active version. No action required.

Tenants with a **pinned** version (e.g. `"2025-26"`) continue using old rates until:
- They update their assignment's `Version` field to `"2026-27"`, or
- They clear the pin to use the latest version automatically

Notify tenant admins of the new version and advise them to review their assignments.

---

## How-To: Add a New Reference Dataset

Use this when you need a lookup table for a new type of reference data — for example, water usage tariffs, carbon credits pricing, or fuel levies.

### Step 1 — Design the schema

Before creating anything, decide:

| Question | Example answer |
|----------|---------------|
| What are you looking up by? | State, zone, tariff class — these are your **dimension keys** |
| What values do you return? | Rate per megalitre, fixed charge — these are your **value keys** |
| Will rates change periodically? | Yes → enable `has_version` |
| Do rates vary by time of day? | Yes → enable `has_time_of_use` |

Write out the schema before touching the UI — it's much harder to change once rows are loaded.

**Example schema — water usage tariffs:**
```
Dimension keys: state (string), utility (string), usage_tier (string)
Value keys:     rate_cents_per_kl (numeric, c/kL), service_charge_cents_per_day (numeric, c/day)
has_version:    true  (annual pricing schedules)
has_time_of_use: false
```

### Step 2 — Create the dataset

Navigate to **Admin → Reference Datasets → New Dataset**.

Fill in the name, slug, and description, then add your dimension and value schema entries.

> The slug cannot be changed once rows are added. Choose it carefully — e.g. `water-usage-tariffs`.

### Step 3 — Add rows

Prepare a CSV following the same format as network tariffs (see above). Every row must include all dimension keys and all value keys. Optional columns (`version`, `valid_from`, `valid_to`) can be added as needed.

Upload via **Import CSV** or the management command.

### Step 4 — Set up tenant assignments

Once the dataset exists with rows, Tenant Admins can assign it to their sites:

**Admin → Settings → Sites → [Site Name] → Dataset Assignments → Add Assignment**

Advise them of:
- The dimension filter values that apply to their site
- Whether to pin a version or use latest
- Which value key(s) to reference in rule conditions

### Step 5 — Use in rule conditions

In the rule builder, conditions of type **Reference Value** will now show the new dataset in the picker. The rule builder displays the currently resolved value next to the value key so tenants can confirm the right row is selected before saving.

---

*Related: `SPEC.md § Feature: Reference Datasets`, `docs/device-connection.md`*
