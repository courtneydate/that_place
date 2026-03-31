# Davis WeatherLink v2 Provider Configuration

Davis Instruments manufactures professional weather stations that measure temperature,
humidity, wind speed and direction, barometric pressure, rainfall, solar radiation,
UV index, and more. Stations upload to the WeatherLink cloud platform via WeatherLink
Live, WeatherLink Console, or legacy IP/cellular loggers.

- **API base:** `https://api.weatherlink.com/v2`
- **API version:** v2
- **API docs:** https://weatherlink.github.io/v2-api/
- **Sensor catalog:** `GET /sensor-catalog` — download and cache; >2 MB, changes infrequently

> **Note:** WeatherLink v2 uses a dual-credential auth pattern (API Key + API Secret)
> that requires the `dual_api_key` auth type. See auth section below.

---

## Registration values

Enter these in **FM Admin → API Provider Library → New Provider**.

### Basic info

| Field | Value |
|-------|-------|
| Name | `Davis WeatherLink` |
| Slug | `davis-weatherlink` |
| Description | `Davis Instruments professional weather stations. Measures temperature, humidity, wind, barometric pressure, rainfall, solar radiation, and UV index via the WeatherLink cloud platform.` |
| Base URL | `https://api.weatherlink.com/v2` |
| Auth type | `Dual API Key` |
| Poll interval | `300` (5 minutes) |
| Max requests/sec | `10` |

> **Base URL must not have a trailing slash.**

> **Rate limits:** WeatherLink enforces 1,000 calls/hour and 10 calls/second per API key.
> At a 300-second poll interval, a 10-station account generates ~0.03 req/sec — well
> within limits. Very large accounts (100+ stations at short intervals) should increase
> the poll interval.

---

### Auth (Dual API Key)

WeatherLink v2 uses two credentials together on every request:

| Credential | How it's sent |
|------------|--------------|
| API Key | Query parameter: `?api-key=<key>` |
| API Secret | HTTP header: `X-Api-Secret: <secret>` |

Both credentials are required for every API call. There is no token exchange — this
is a static dual-credential scheme with no expiry.

**Obtaining credentials:**
1. Log into https://www.weatherlink.com
2. Go to Account → WeatherLink API
3. Click **Generate v2 Key** — this creates both the API Key and API Secret
4. Copy both immediately — the API Secret is only shown once
5. If the secret is lost, click **Generate** again; this invalidates the previous secret

> **Token URL, Refresh URL:** Leave blank — not applicable.

---

### Credential fields (auth param schema)

Add both fields using the **+ Add credential field** button:

| key | label | type | required | sent as |
|-----|-------|------|----------|---------|
| `api_key` | `WeatherLink API Key` | `text` | yes | Query param `api-key` |
| `api_secret` | `WeatherLink API Secret` | `password` | yes | Header `X-Api-Secret` |

> The `dual_api_key` auth handler reads `credentials["api_key"]` and appends
> `?api-key=<value>` to every request URL, and reads `credentials["api_secret"]`
> and adds it as the `X-Api-Secret` header.

---

### Poll interval and rate limits

| Field | Value |
|-------|-------|
| Poll interval | `300` (5 minutes) |
| Max requests/sec | `10` |

> WeatherLink enforces 1,000 API calls/hour and 10 calls/second per API key.
> These limits apply across all stations on one API key.

---

### Discovery endpoint

`GET /stations` returns an object containing a `stations` array. Each entry includes
the station ID and name.

| Field | Value |
|-------|-------|
| Path | `/stations` |
| Method | `GET` |
| Device ID JSONPath | `$.stations[*].station_id` |
| Device name JSONPath | `$.stations[*].station_name` |

**Example response:**
```json
{
  "stations": [
    {
      "station_id": 96551,
      "station_name": "Farm North",
      "gateway_id": 7000002,
      "gateway_id_hex": "001D0A000C0071B8",
      "product_number": "6555",
      "username": "user@example.com",
      "time_zone": "Australia/Brisbane",
      "city": "Brisbane",
      "country": "AU",
      "latitude": -27.47,
      "longitude": 153.02,
      "elevation": 27
    }
  ],
  "generated_at": 1711234567
}
```

> **Discovery returns names.** Unlike Watt Watchers, WeatherLink includes station names
> in discovery. Each discovered station will display its WeatherLink name in the
> connection wizard. Tenants can rename virtual devices after connecting if needed.

---

### Device detail endpoint

`GET /stations/{station_id}` returns full station metadata. This endpoint is called
once after discovery to confirm the station configuration — it is not used for polling.

| Field | Value |
|-------|-------|
| Path template | `/stations/{device_id}` |
| Method | `GET` |
| Name JSONPath | `$.stations[0].station_name` |

---

### Measurement endpoint — Current conditions (recommended)

`GET /current/{station_id}` returns the most recent sensor readings for a station.
No time parameters required. Best for live dashboards.

| Field | Value |
|-------|-------|
| Path template | `/current/{device_id}` |
| Method | `GET` |
| Time parameters | None |

> **Subscription affects data granularity:**
> - Pro+: Most recent record
> - Pro: Most recent 5-minute record
> - Basic: Most recent 15-minute record

**Example response (WeatherLink Live — ISS sensor, data_structure_type 10):**
```json
{
  "station_id": 96551,
  "sensors": [
    {
      "lsid": 3456789,
      "sensor_type": 43,
      "data_structure_type": 10,
      "data": [
        {
          "ts": 1711234567,
          "temp": 72.5,
          "hum": 58.3,
          "dew_point": 56.1,
          "wind_speed": 8.2,
          "wind_dir": 245,
          "wind_gust": 14.1,
          "wind_gust_dir": 250,
          "bar": 29.92,
          "bar_trend": 0.01,
          "rain_rate": 0.0,
          "rainfall_last_15_min": 0.0,
          "rainfall_day": 0.12,
          "solar_rad": 543,
          "uv_index": 4.2
        }
      ]
    }
  ],
  "generated_at": 1711234580
}
```

> **Sensor nesting.** All readings are wrapped in `sensors[].data[]`. The
> `data_structure_type` field identifies the sensor record format.
> Type 10 = WeatherLink Live ISS current conditions (most common setup).
> See the [sensor catalog](https://api.weatherlink.com/v2/sensor-catalog) for all types.

> **Temperature in °F.** All WeatherLink v2 API temperature values are in Fahrenheit.
> Configure stream units as `°F` or apply conversion at the dashboard level.

---

### Measurement endpoint — Historic (optional)

`GET /historic/{station_id}?start-timestamp={from_unix}&end-timestamp={to_unix}` returns
archived readings over a time window. Requires Pro or Pro+ subscription.

| Field | Value |
|-------|-------|
| Path template | `/historic/{device_id}` |
| Method | `GET` |
| Time parameters | `start-timestamp` (Unix), `end-timestamp` (Unix) |
| Max window | 86,400 seconds (24 hours) |

> **Use current endpoint for real-time monitoring.** Historic is best for backfill
> or compliance use cases, not for live dashboards.

---

### Available streams

Add each stream using the **+ Add stream** button. All JSONPath expressions navigate
the `sensors` array using a filter on `data_structure_type` to target the correct sensor.

> **These JSONPaths target data_structure_type 10** (WeatherLink Live ISS current
> conditions — the most common Davis setup). If your station uses a different sensor
> type, check the sensor catalog and adjust the filter value accordingly.

#### Temperature and humidity

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `temperature` | `Temperature` | `°F` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].temp` |
| `humidity` | `Humidity` | `%` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].hum` |
| `dew_point` | `Dew Point` | `°F` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].dew_point` |

#### Wind

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `wind_speed` | `Wind Speed` | `mph` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].wind_speed` |
| `wind_dir` | `Wind Direction` | `°` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].wind_dir` |
| `wind_gust` | `Wind Gust` | `mph` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].wind_gust` |

#### Pressure

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `pressure` | `Barometric Pressure` | `inHg` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].bar` |

#### Rainfall

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `rain_rate` | `Rain Rate` | `in/hr` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].rain_rate` |
| `rainfall_day` | `Rainfall Today` | `in` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].rainfall_day` |
| `rainfall_15min` | `Rainfall (15 min)` | `in` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].rainfall_last_15_min` |

#### Solar and UV

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `solar_rad` | `Solar Radiation` | `W/m²` | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].solar_rad` |
| `uv_index` | `UV Index` | _(blank)_ | `numeric` | `$.sensors[?(@.data_structure_type==10)].data[0].uv_index` |

---

### AirLink sensor (air quality — optional)

AirLink sensors report as `data_structure_type 16`. Add these streams only if the
station has an AirLink sensor attached.

| key | label | unit | data type | JSONPath |
|-----|-------|------|-----------|----------|
| `pm_1` | `PM 1.0` | `µg/m³` | `numeric` | `$.sensors[?(@.data_structure_type==16)].data[0].pm_1` |
| `pm_2p5` | `PM 2.5` | `µg/m³` | `numeric` | `$.sensors[?(@.data_structure_type==16)].data[0].pm_2p5` |
| `pm_10` | `PM 10` | `µg/m³` | `numeric` | `$.sensors[?(@.data_structure_type==16)].data[0].pm_10` |
| `aqi` | `AQI (NowCast PM 2.5)` | _(blank)_ | `numeric` | `$.sensors[?(@.data_structure_type==16)].data[0].aqi_val` |

---

## Tenant setup (what tenants do)

Once the provider is registered:

1. Tenant Admin navigates to **Data Sources → Add Data Source**
2. Selects **Davis WeatherLink** from the provider list
3. Enters their **API Key** and **API Secret** from their WeatherLink account
4. Clicks **Discover stations** — the platform calls `GET /stations`
5. Selects which stations to connect and assigns each to a site
   - Station names are provided by WeatherLink — no manual renaming needed unless desired
6. Selects which streams to activate per station
   - Standard weather: activate `temperature`, `humidity`, `wind_speed`, `wind_dir`, `pressure`, `rainfall_day`
   - Add `solar_rad` and `uv_index` if relevant
   - Add AirLink streams only if the station has an AirLink sensor
7. Clicks **Connect** — virtual device records are created and polling begins

---

## Understanding sensor types

WeatherLink stations report multiple sensor types in a single response. The platform
uses `data_structure_type` in JSONPath filters to target the right sensor.

| data_structure_type | Sensor | Platform use |
|--------------------|--------|-------------|
| 10 | WeatherLink Live — ISS (Integrated Sensor Suite) | Primary weather streams |
| 12 | WeatherLink Live — health | Not used (device diagnostics only) |
| 16 | AirLink — current conditions | Air quality streams (optional) |
| 23 | WeatherLink Console — ISS | Use instead of type 10 for Console stations |

> **Identify your type before configuring streams.** Connect the station, fetch one
> raw reading from `GET /current/{station_id}` (use Postman or curl), and check which
> `data_structure_type` values appear. Use that value in the JSONPath filter.

---

## Rate limits

| Metric | Limit |
|--------|-------|
| Calls per hour | 1,000 per API key |
| Calls per second | 10 per API key |

At a 5-minute (300 s) poll interval, a 10-station account uses ~720 calls/day
(~30/hour). Rate limiting is only a concern for accounts with 30+ stations polling
at 60-second intervals or shorter.

If 1,000 calls/hour is insufficient, contact Davis via the
[WeatherLink Developers Discord](https://discord.gg/weatherlink) to request a higher limit.

---

## Known differences from standard patterns

| Topic | Detail |
|-------|--------|
| Dual credentials | Every request requires both an API Key (query param) and an API Secret (header). This is not a standard Bearer Token or OAuth2 pattern — it requires the `dual_api_key` auth type. |
| Sensor nesting | Readings are not at the root of the response. All values are inside `sensors[].data[]`. JSONPath filter expressions on `data_structure_type` are required. |
| Temperature in °F | All temperature values are Fahrenheit. No conversion parameter exists in the API — convert at the dashboard widget level if Celsius display is needed. |
| Rainfall is a period total | `rainfall_day` is the accumulated total since midnight local time, not a rate. Use `rain_rate` for instantaneous rate. |
| Station ID is an integer | WeatherLink station IDs are integers (e.g. `96551`), not strings. The discovery JSONPath `$.stations[*].station_id` returns integers — ensure the platform treats them as strings internally. |
| Pro subscription required | Historic data requires a Pro or Pro+ WeatherLink subscription. Current conditions work on Basic. |
| Sensor catalog | The `/sensor-catalog` endpoint (>2 MB) maps all sensor types to their fields. Cache it locally — it changes infrequently. Not needed for routine polling but essential for diagnosing unexpected empty fields. |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| All requests return 401 | Missing `X-Api-Secret` header, or key/secret mismatch | Verify both credentials; check that `api_key` is in the URL and `api_secret` is in the header |
| Discovery returns 0 stations | API key has no stations associated | Verify the key was generated from the correct WeatherLink account; confirm stations are visible at weatherlink.com |
| `sensors` array empty in response | Station offline or never uploaded | Check station status on weatherlink.com; verify station firmware and connectivity |
| All stream values null | Wrong `data_structure_type` in JSONPath filter | Fetch a raw `/current/{id}` response and check which `data_structure_type` values are present; update JSONPath filters |
| `temperature` shows values >100 | Expected — temperature is in °F | Relabel the stream unit as `°F` or apply Celsius conversion on the dashboard |
| Rainfall stream flat-lines | `rainfall_day` resets at midnight | Expected behaviour — the value is a daily accumulation, not a continuous sensor |
| 429 Too Many Requests | 1,000 call/hour limit exceeded | Increase poll interval; or contact Davis to raise the limit |
| AirLink streams show no data | Station has no AirLink sensor, or wrong data_structure_type | Confirm AirLink is attached to the station; check for `data_structure_type: 16` in a raw response |
