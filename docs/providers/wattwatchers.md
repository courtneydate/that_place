# Watt Watchers Provider Configuration

Watt Watchers manufactures energy monitoring devices that measure real and reactive power,
voltage, current, and frequency across multiple circuits. Devices communicate via cellular
and report to the Watt Watchers cloud platform.

- **API base:** `https://api-v3.wattwatchers.com.au`
- **API version:** v3 — verified during setup March 2026
- **API docs:** https://docs.wattwatchers.com.au/api/v3/

---

## Registration values

Enter these in **FM Admin → API Provider Library → New Provider**.

### Basic info

| Field | Value |
|-------|-------|
| Name | `Watt Watchers` |
| Slug | `wattwatchers` |
| Description | `Watt Watchers multi-channel energy monitors. Measures real power, reactive power, voltage, current, and AC frequency per circuit.` |
| Base URL | `https://api-v3.wattwatchers.com.au` |
| Auth type | `Bearer Token` |
| Poll interval | `300` (5 minutes) |
| Max requests/sec | `3` |

> **Base URL must not have a trailing slash.** Enter `https://api-v3.wattwatchers.com.au` exactly.

> **Max requests/sec:** Watt Watchers enforces `floor(device_count / 3)` TPS per API key.
> A value of `3` is safe for most tenants. For accounts with 30+ devices you may increase
> this proportionally; for very large fleets, leave it blank and monitor the
> `X-RateLimit-TpsRemaining` header in logs.

---

### Auth (Bearer Token)

Watt Watchers uses a **long-lived static API key** — no OAuth2, no expiry. API keys are
issued by Watt Watchers support or retrieved from the Fleet Management app
(Profile → API Key). They begin with `key_`.

Token URL, Refresh URL: **leave blank** — not applicable for Bearer Token auth.

---

### Credential fields (auth param schema)

Add this single field using the **+ Add credential field** button:

| key | label | type | required |
|-----|-------|------|----------|
| `token` | `Watt Watchers API Key` | `password` | yes |

> The key name must be exactly `token` — the platform's Bearer Token auth handler
> reads `credentials["token"]` and sends it as `Authorization: Bearer <token>`.

---

### Discovery endpoint

`GET /devices` returns a flat JSON array of device serial number strings. No pagination.

| Field | Value |
|-------|-------|
| Path | `/devices` |
| Method | `GET` |
| Device ID JSONPath | `$[*]` |
| Device name JSONPath | _(leave blank)_ |

> **No device names from discovery.** The `/devices` endpoint returns only IDs
> (e.g. `["D123456789012", "D234567890123"]`). Each discovered device will display
> its serial number as its name in the connection wizard. Tenants can rename virtual
> devices from the device settings page after connecting.

**Example response:**
```json
["D123456789012", "D234567890123", "D345678901234"]
```

---

### Detail endpoint

`GET /short-energy/{device_id}/latest` returns the device's most recent 30-second energy
record as a single-element JSON array. Using `convert[energy]=kW` changes the energy fields
from raw Joules to kW, making readings directly usable on dashboards.

| Field | Value |
|-------|-------|
| Path template | `/short-energy/{device_id}/latest?convert[energy]=kW` |
| Method | `GET` |

> **Why short energy, not long energy?** Short energy `/latest` gives near-real-time
> instantaneous readings (updated every 30 seconds) including voltage and current, which
> are not available in the long energy endpoint. Long energy is better for billing and
> historical analytics but is not suitable as a "current reading" endpoint.

> **`convert[energy]=kW` changes field names.** When this parameter is present,
> `eReal` becomes `pRealKw` and `eReactive` becomes `pReactiveKw` — the JSONPath
> expressions below rely on these converted names.

**Example response (3-channel device):**
```json
[
  {
    "timestamp": 1711234567,
    "duration": 30,
    "frequency": 49.98,
    "pRealKw": [3.21, -1.05, 0.84],
    "pReactiveKw": [0.12, -0.08, 0.03],
    "vRMS": [239.4, 239.6, 239.5],
    "iRMS": [14.2, 4.6, 3.8]
  }
]
```

> **Array structure:** Every measurement field is an array with one element per channel.
> `pRealKw[0]` = channel 1, `pRealKw[1]` = channel 2, etc. (0-indexed).
> The `frequency` field is device-wide (a scalar, not an array).

> **`204 No Content`:** If the device has never sent data, the API returns HTTP 204
> (no body). The poller will log a JSON decode error for that device until it first
> reports. This is expected for newly provisioned devices.

---

### Available streams

Add each stream using the **+ Add stream** button. Enter JSONPath expressions without quotes.

All streams reference `$[0]` because the `/latest` endpoint wraps its single record in an array.

#### Power (kW) — per channel

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `power_c1` | `Power — Ch 1` | `kW` | `numeric` | `$[0].pRealKw[0]` |
| `power_c2` | `Power — Ch 2` | `kW` | `numeric` | `$[0].pRealKw[1]` |
| `power_c3` | `Power — Ch 3` | `kW` | `numeric` | `$[0].pRealKw[2]` |

#### Voltage (V) — per channel

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `voltage_c1` | `Voltage — Ch 1` | `V` | `numeric` | `$[0].vRMS[0]` |
| `voltage_c2` | `Voltage — Ch 2` | `V` | `numeric` | `$[0].vRMS[1]` |
| `voltage_c3` | `Voltage — Ch 3` | `V` | `numeric` | `$[0].vRMS[2]` |

#### Current (A) — per channel

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `current_c1` | `Current — Ch 1` | `A` | `numeric` | `$[0].iRMS[0]` |
| `current_c2` | `Current — Ch 2` | `A` | `numeric` | `$[0].iRMS[1]` |
| `current_c3` | `Current — Ch 3` | `A` | `numeric` | `$[0].iRMS[2]` |

#### Reactive power (kVAr) — per channel (optional)

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `reactive_c1` | `Reactive Power — Ch 1` | `kVAr` | `numeric` | `$[0].pReactiveKw[0]` |
| `reactive_c2` | `Reactive Power — Ch 2` | `kVAr` | `numeric` | `$[0].pReactiveKw[1]` |
| `reactive_c3` | `Reactive Power — Ch 3` | `kVAr` | `numeric` | `$[0].pReactiveKw[2]` |

#### Device-wide

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `frequency` | `Frequency` | `Hz` | `numeric` | `$[0].frequency` |

---

### 6-channel devices

Watt Watchers 6M and 6M-series devices have 6 channels. Add the following additional streams:

| key | label | unit | JSONPath |
|-----|-------|------|----------|
| `power_c4` | `Power — Ch 4` | `kW` | `$[0].pRealKw[3]` |
| `power_c5` | `Power — Ch 5` | `kW` | `$[0].pRealKw[4]` |
| `power_c6` | `Power — Ch 6` | `kW` | `$[0].pRealKw[5]` |
| `voltage_c4` | `Voltage — Ch 4` | `V` | `$[0].vRMS[3]` |
| `voltage_c5` | `Voltage — Ch 5` | `V` | `$[0].vRMS[4]` |
| `voltage_c6` | `Voltage — Ch 6` | `V` | `$[0].vRMS[5]` |
| `current_c4` | `Current — Ch 4` | `A` | `$[0].iRMS[3]` |
| `current_c5` | `Current — Ch 5` | `A` | `$[0].iRMS[4]` |
| `current_c6` | `Current — Ch 6` | `A` | `$[0].iRMS[5]` |

> **Selecting streams with the wrong channel count:** If a tenant activates `power_c4`
> on a 3-channel device, the JSONPath `$[0].pRealKw[3]` will return no match and no
> reading will be stored. This is harmless but the stream will show no data.

---

## Tenant setup (what tenants do)

Once the provider is registered:

1. Tenant Admin navigates to **Data Sources → Add Data Source**
2. Selects **Watt Watchers** from the provider list
3. Enters their **Watt Watchers API key** (starts with `key_`)
4. Clicks **Discover devices** — the platform calls `GET /devices` with their key
5. Selects which devices to connect and assigns each to a site
6. Selects which streams to activate per device
   - For a 3-channel device: activate `power_c1`–`c3`, `voltage_c1`–`c3`, `current_c1`–`c3`
   - For a 6-channel device: activate all 6 sets
   - `frequency` is device-wide — activate once per device
7. Clicks **Connect** — virtual device records are created and polling begins immediately

After connecting, tenants should:
- **Rename each virtual device** to match the circuit it monitors (e.g. "Main Switchboard", "Solar Inverter")
- **Relabel streams** to match the physical circuit of each channel (e.g. "Power — Ch 1" → "Grid Import") — do this from the device's Streams tab

---

## Understanding channel numbers

Watt Watchers channel numbers are assigned physically at installation and are fixed.
Channel 1 is the first CT clamp on the device. The Watt Watchers Fleet Management app
shows the `label` and `categoryLabel` configured for each channel — use that to map
channel numbers to circuit names before choosing which streams to activate and how to
label them in That Place.

---

## Rate limits

Watt Watchers enforces per-API-key rate limits that scale with the number of devices:

| Metric | Formula |
|--------|---------|
| Transactions/day (TPD) | `devices × ~3,456` (approx) |
| Transactions/second (TPS) | `floor(devices / 3)` |

At 300-second poll intervals, a 10-device account generates ~0.03 requests/second,
well under the ~3 TPS limit. Rate limiting is only a concern for accounts with a very
large number of devices being polled at a very short interval.

If polling is throttled, the provider returns HTTP 429 with a `Retry-After` header.
The platform will log this as a poll error and retry on the next scheduled poll cycle.

---

## Known differences from standard patterns

| Topic | Detail |
|-------|--------|
| Static API key | No OAuth2 flow — the key never expires unless manually revoked by Watt Watchers. If a tenant loses their key, they must obtain a new one and update the data source credentials. |
| Measurement arrays | All per-channel values are returned as arrays indexed from 0. A 3-channel device returns arrays of length 3; a 6-channel device length 6. JSONPath index must match the channel count. |
| Joules by default | Energy fields (`eReal`, `eReactive`) default to Joules, not kWh. The `convert[energy]=kW` parameter in the detail endpoint path converts them to kW and renames the fields. |
| `204 No Content` | A device with no data returns 204 (empty body), not `[]`. The poller will log a JSON parse error for that poll — this is expected for new devices. |
| Short energy retention | Short energy data is only available for the past 31 days. The `/latest` endpoint always works regardless of this window. |
| `timestamp` = period end | The `timestamp` field marks the **end** of the 30-second measurement window, not the start. |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Discovery returns 401 | Invalid or revoked API key | Tenant re-enters the key; verify it starts with `key_` |
| Discovery returns 0 devices | API key has no devices assigned | Contact Watt Watchers support to assign devices to the key |
| Device shows serial number as name | Expected — discovery returns only IDs | Tenant renames the virtual device after connecting |
| Stream shows no data | Channel index out of range for device model | Confirm device channel count in Watt Watchers Fleet Management; deactivate streams beyond the device's channel count |
| Poll status `error` with "JSON decode" | Device returned 204 (no data yet) | Wait for the device to report at least one reading; error will clear automatically |
| All streams flat-line after working | API key revoked or device offline | Check poll error message; if 401, tenant must obtain and re-enter a new API key |
| `frequency` showing no data | JSONPath `$[0].frequency` not matching | Confirm detail endpoint URL includes `?convert[energy]=kW`; check a raw API response for the field name |
