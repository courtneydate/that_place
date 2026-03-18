# SoilScout Provider Configuration

SoilScout manufactures wireless soil monitoring sensors that measure moisture, temperature,
salinity, conductivity, and more. Devices communicate via cellular and report to the
SoilScout cloud platform.

- **API base:** `https://soilscouts.fi/api/v1`
- **API version tested:** v1.89 (September 2025) — verified during platform setup March 2026
- **API docs:** https://soilscouts.fi/api/v1/?format=openapi

---

## Registration values

Enter these in **FM Admin → API Provider Library → New Provider**.

### Basic info

| Field | Value |
|-------|-------|
| Name | `SoilScout` |
| Slug | `soilscout` |
| Description | `SoilScout wireless soil sensors. Measures moisture, temperature, salinity, conductivity, and water balance.` |
| Base URL | `https://soilscouts.fi/api/v1` |
| Auth type | `OAuth2 Password Grant` |
| Poll interval | `900` (15 minutes — matches access token lifetime) |

> **Base URL must not have a trailing slash.** Enter `https://soilscouts.fi/api/v1`, not `https://soilscouts.fi/api/v1/`.

---

### Auth (OAuth2 Password Grant)

| Field | Value |
|-------|-------|
| Token URL | `https://soilscouts.fi/api/v1/auth/login/` |
| Refresh URL | `https://soilscouts.fi/api/v1/auth/token/refresh/` |

> SoilScout uses a non-standard JWT login endpoint rather than a standard OAuth2 token
> endpoint. The platform handles this automatically — the Refresh URL must be set separately
> because SoilScout uses a different path for token refresh.

---

### Credential fields (auth param schema)

Add these fields manually using the **+ Add credential field** button. Tenants will fill these
in when connecting their account.

| key | label | type | required |
|-----|-------|------|----------|
| `username` | `SoilScout Username` | `text` | yes |
| `password` | `SoilScout Password` | `password` | yes |

---

### Discovery endpoint

SoilScout's `/devices/` endpoint returns a flat array of all devices on the account.

| Field | Value |
|-------|-------|
| Path | `/devices/` |
| Method | `GET` |
| Device ID JSONPath | `$[*].id` |
| Device name JSONPath | `$[*].name` |

> Enter JSONPath expressions without quotes — type `$[*].id`, not `"$[*].id"`.

**Example response:**
```json
[
  { "id": 123, "name": "Field A — North", "device_type": "hydra", ... },
  { "id": 124, "name": "Field A — South", "device_type": "hydra", ... }
]
```

---

### Detail endpoint

`GET /devices/{id}/?with_details` returns the full device object including a
`last_measurement` block with all current readings. This avoids the need for time-range
parameters that the platform doesn't currently support.

| Field | Value |
|-------|-------|
| Path template | `/devices/{device_id}/?with_details` |
| Method | `GET` |

**Example response (abbreviated):**
```json
{
  "id": 123,
  "name": "Field A — North",
  "last_measurement": {
    "timestamp": "2025-09-12T08:30:00Z",
    "moisture": 0.27,
    "temperature": 18.4,
    "conductivity": 0.12,
    "salinity": 0.08,
    "dielectricity": 22.1,
    "water_balance": 0.15
  }
}
```

---

### Available streams

Add each stream using the **+ Add stream** button. Enter JSONPath expressions without quotes.

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `moisture` | `Soil Moisture` | `m³/m³` | numeric | `$.last_measurement.moisture` |
| `temperature` | `Soil Temperature` | `°C` | numeric | `$.last_measurement.temperature` |
| `salinity` | `Salinity` | `g/L` | numeric | `$.last_measurement.salinity` |
| `conductivity` | `Electrical Conductivity` | `dS/m` | numeric | `$.last_measurement.conductivity` |
| `dielectricity` | `Dielectricity` | _(blank)_ | numeric | `$.last_measurement.dielectricity` |
| `water_balance` | `Water Balance` | _(blank)_ | numeric | `$.last_measurement.water_balance` |

> **Optional stream — Oxygen:** Available on devices running firmware v1.62+.
> Add it as a separate stream if tenants have oxygen-capable sensors:
> key `oxygen`, label `Oxygen`, unit `%`, JSONPath `$.last_measurement.oxygen`

---

## Tenant setup (what tenants do)

Once the provider is registered:

1. Tenant Admin navigates to **Data Sources → Add Data Source**
2. Selects **SoilScout** from the provider list
3. Enters their **SoilScout account username and password**
4. Clicks **Discover devices** — the platform calls `/devices/` with their credentials
5. Selects which devices to connect and assigns each to a site
6. Selects which streams to activate per device (moisture and temperature are typical defaults)
7. Clicks **Connect** — virtual device records are created and polling begins immediately

Tenants can adjust stream labels and units at any time from the device's Streams tab.

---

## Rate limits

SoilScout enforces **5 requests/second** per IP with a burst queue of 20.
At the default 900-second poll interval, each device generates well under 1 req/min,
so rate limits are not a concern for normal usage. If tenants connect very large numbers
of devices (100+), consider increasing the poll interval.

---

## Known differences from standard OAuth2

SoilScout does not use the standard OAuth2 token endpoint format:

| Standard OAuth2 | SoilScout |
|-----------------|-----------|
| Request field: `grant_type=password` | Not required — endpoint only accepts `{username, password}` |
| Response field: `access_token` | Returns `access` |
| Response field: `refresh_token` | Returns `refresh` |
| Single token endpoint for auth + refresh | Separate endpoints: `/auth/login/` and `/auth/token/refresh/` |

The Fieldmouse platform handles all of these differences automatically. No special
configuration is needed beyond setting the Token URL and Refresh URL as shown above.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| "Base URL must start with http://" on save | URL entered without protocol or with trailing slash | Enter exactly `https://soilscouts.fi/api/v1` — no trailing slash |
| "Token URL is required" on save | Token URL left blank with OAuth2 auth type selected | Enter `https://soilscouts.fi/api/v1/auth/login/` |
| Discovery returns 401 | Wrong username or password | Tenant re-enters credentials |
| Discovery returns 0 devices | Account has no devices, or wrong account | Verify SoilScout account has devices assigned |
| Poll status `auth_failure` | Access token expired and refresh failed | Tenant updates password if changed; platform will re-authenticate on next poll |
| `last_measurement` fields all null | Device offline or not yet reported | Check device status in SoilScout dashboard |
| Readings stop updating | Device firmware or SoilScout API change | Check SoilScout release notes; update JSONPath expressions if field names changed |
