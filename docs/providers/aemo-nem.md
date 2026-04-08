# AEMO NEM Market Data

The Australian Energy Market Operator (AEMO) publishes live wholesale electricity prices
for the National Electricity Market (NEM) via a public REST API. Prices update every
5 minutes and cover all five NEM regions. No authentication or API key is required.

This is a **system-level data feed** — unlike device providers (SoilScout, Watt Watchers),
AEMO is registered once at the platform level, not per-tenant. Spot prices are stored
centrally and made available to all tenants for rule evaluation and cost calculations.

- **API base:** `https://visualisations.aemo.com.au/aemo/apps/api/report`
- **API version:** No versioning — endpoint has been stable since 2023
- **Auth:** None — public endpoint, no key required
- **Update frequency:** Every 5 minutes (aligned to NEM dispatch intervals)
- **AEMO dashboard:** https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-data-nemweb

> **Domain note:** The main AEMO website (`aemo.com.au`) blocks automated requests with HTTP 403.
> Always use `visualisations.aemo.com.au` — this is the data visualisation subdomain that
> serves the API and does not enforce the same restrictions.

---

## Regions covered

| Region ID | State(s) |
|-----------|----------|
| `NSW1` | New South Wales + ACT |
| `QLD1` | Queensland |
| `SA1` | South Australia |
| `TAS1` | Tasmania |
| `VIC1` | Victoria |

Western Australia (AEMO-operated SWIS) and the NT are **not** part of the NEM and are not
included in this feed.

---

## Endpoint

### Current NEM summary

```
GET https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY
```

Returns the current 5-minute dispatch interval data for all five regions in a single
response. No query parameters required.

**Full response structure:**

```json
{
  "ELEC_NEM_SUMMARY": [
    {
      "SETTLEMENTDATE": "2026-04-08T10:35:00",
      "REGIONID": "NSW1",
      "PRICE": 20.51022,
      "PRICE_STATUS": "FIRM",
      "APCFLAG": 0.0,
      "MARKETSUSPENDEDFLAG": 0.0,
      "TOTALDEMAND": 6603.05,
      "NETINTERCHANGE": -281.68,
      "SCHEDULEDGENERATION": 2785.64278,
      "SEMISCHEDULEDGENERATION": 3514.07722,
      "INTERCONNECTORFLOWS": "[{\"name\":\"N-Q-MNSP1\",\"value\":...}]"
    }
  ],
  "ELEC_NEM_SUMMARY_PRICES": [
    {
      "REGIONID": "NSW1",
      "RRP": 20.89856,
      "RAISEREGRRP": 4.97,
      "LOWERREGRRP": 1.0,
      "RAISE1SECRRP": 0.01,
      "RAISE6SECRRP": 0.04,
      "RAISE60SECRRP": 0.03,
      "RAISE5MINRRP": 0.01,
      "LOWER1SECRRP": 0.0,
      "LOWER6SECRRP": 0.01,
      "LOWER60SECRRP": 0.01,
      "LOWER5MINRRP": 0.02
    }
  ],
  "ELEC_NEM_SUMMARY_MARKET_NOTICE": [
    {
      "NOTICEID": 140958,
      "EFFECTIVEDATE": "2026-04-08T10:03:48",
      "EXTERNALREFERENCE": "string",
      "TYPEID": "NON-CONFORMANCE",
      "REASON": "string"
    }
  ]
}
```

Each top-level array contains **one entry per NEM region** (5 total), ordered by region ID.

---

## Field reference

### `ELEC_NEM_SUMMARY` — regional dispatch snapshot

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `SETTLEMENTDATE` | datetime | — | Settlement interval end time (AEST, no timezone suffix) |
| `REGIONID` | string | — | NEM region: `NSW1`, `QLD1`, `SA1`, `TAS1`, `VIC1` |
| `PRICE` | float | $/MWh | Dispatch price for the interval (see note on `RRP` vs `PRICE` below) |
| `PRICE_STATUS` | string | — | `FIRM` = final; `PRELIMINARY` = subject to revision |
| `APCFLAG` | float | — | `1.0` if Administered Price Cap is active in this region |
| `MARKETSUSPENDEDFLAG` | float | — | `1.0` if the market is suspended (rare emergency condition) |
| `TOTALDEMAND` | float | MW | Total regional electricity demand |
| `NETINTERCHANGE` | float | MW | Net flow across all interconnectors (negative = net export) |
| `SCHEDULEDGENERATION` | float | MW | Scheduled (dispatchable) generation |
| `SEMISCHEDULEDGENERATION` | float | MW | Semi-scheduled generation (wind, utility solar) |
| `INTERCONNECTORFLOWS` | string | MW | JSON-encoded array of individual interconnector flows |

### `ELEC_NEM_SUMMARY_PRICES` — ancillary services pricing

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `REGIONID` | string | — | NEM region |
| `RRP` | float | $/MWh | Regional Reference Price (same interval as summary) |
| `RAISEREGRRP` | float | $/MWh | Regulation raise price (frequency control, upward) |
| `LOWERREGRRP` | float | $/MWh | Regulation lower price (frequency control, downward) |
| `RAISE1SECRRP` | float | $/MWh | Fast raise — 1-second response |
| `RAISE6SECRRP` | float | $/MWh | Fast raise — 6-second response |
| `RAISE60SECRRP` | float | $/MWh | Raise — 60-second response |
| `RAISE5MINRRP` | float | $/MWh | Raise — 5-minute response |
| `LOWER1SECRRP` | float | $/MWh | Fast lower — 1-second response |
| `LOWER6SECRRP` | float | $/MWh | Fast lower — 6-second response |
| `LOWER60SECRRP` | float | $/MWh | Lower — 60-second response |
| `LOWER5MINRRP` | float | $/MWh | Lower — 5-minute response |

### `ELEC_NEM_SUMMARY_MARKET_NOTICE` — operational notices

| Field | Type | Description |
|-------|------|-------------|
| `NOTICEID` | float | Unique notice identifier |
| `EFFECTIVEDATE` | datetime | When the notice came into effect |
| `EXTERNALREFERENCE` | string | External document or reference number |
| `TYPEID` | string | Notice category (see common types below) |
| `REASON` | string | Human-readable explanation |

**Common `TYPEID` values:**

| Value | Meaning |
|-------|---------|
| `NON-CONFORMANCE` | A generator is not following dispatch instructions |
| `PRICES UNCHANGED` | Price review completed — interval price confirmed |
| `PRICES SUBJECT TO REVIEW` | A price review is in progress for a recent interval |
| `RESERVE NOTICE` | Reserve adequacy advisory |
| `MARKET SYSTEMS` | AEMO system maintenance affecting market operations |

---

## `PRICE` vs `RRP`

The response contains prices in two places. They will usually be equal but can differ:

| Field | Location | Notes |
|-------|----------|-------|
| `PRICE` | `ELEC_NEM_SUMMARY` | Dispatch price as calculated; may be preliminary |
| `RRP` | `ELEC_NEM_SUMMARY_PRICES` | Regional Reference Price — the official settlement value |

**Use `RRP` from `ELEC_NEM_SUMMARY_PRICES`** for storage and rule evaluation. It is the
value that energy contracts settle against. When `PRICE_STATUS` is `PRELIMINARY`, the
`RRP` may be revised in a subsequent interval; store both the value and the status.

---

## Unit conversions

AEMO publishes prices in **$/MWh**. Consumer-facing and rule-evaluation contexts typically
use **$/kWh** or **cents/kWh**:

| From | To | Operation |
|------|----|-----------|
| $/MWh | $/kWh | divide by 1,000 |
| $/MWh | cents/kWh | divide by 10 |

**Example:** `RRP = 89.40 $/MWh` → `0.0894 $/kWh` → `8.94 c/kWh`

**Price floor and cap:** NEM prices are bounded by the Market Price Cap (currently **$16,600/MWh**)
and the Market Floor Price (currently **−$1,000/MWh**). Negative prices are real and common
during high renewable generation periods. Treat them as valid values, not errors.

---

## Poll configuration

| Setting | Value | Reason |
|---------|-------|--------|
| Poll interval | `300` seconds (5 minutes) | AEMO publishes one dispatch interval per 5 minutes; polling faster returns stale data |
| Celery task | `tasks.fetch_aemo_spot_prices` | Async — must not run in the ingestion path |
| Retry on failure | Yes — up to 3 attempts with 30-second backoff | AEMO occasionally returns 503 during peak load |
| Stale threshold | `900` seconds (3 intervals) | Alert if no successful fetch within 15 minutes |

> **Do not poll more frequently than every 5 minutes.** The endpoint serves the same
> data within a dispatch interval — extra requests waste bandwidth and may trigger
> AEMO's informal rate limits, which are not documented but have been observed.

---

## Celery task outline

```python
@shared_task(bind=True, max_retries=3)
def fetch_aemo_spot_prices(self):
    """Fetch current NEM spot prices from AEMO and store per region."""
    url = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise self.retry(exc=exc, countdown=30)

    prices = {row["REGIONID"]: row for row in data["ELEC_NEM_SUMMARY_PRICES"]}
    statuses = {row["REGIONID"]: row["PRICE_STATUS"] for row in data["ELEC_NEM_SUMMARY"]}
    settlement_date = data["ELEC_NEM_SUMMARY"][0]["SETTLEMENTDATE"]

    for region_id, price_row in prices.items():
        NEMSpotPrice.objects.update_or_create(
            region=region_id,
            settlement_date=settlement_date,
            defaults={
                "rrp": price_row["RRP"],
                "price_status": statuses.get(region_id, "FIRM"),
                "raise_reg_rrp": price_row["RAISEREGRRP"],
                "lower_reg_rrp": price_row["LOWERREGRRP"],
            },
        )
```

---

## Data availability and history

| Data type | Availability |
|-----------|-------------|
| Current dispatch interval | Live via `ELEC_NEM_SUMMARY` — always the most recent 5-minute interval |
| Historical dispatch prices | Via NEMWeb file downloads (`DISPATCHPRICE` CSV files) — not this API |
| 30-minute trading prices | Derived from 6 dispatch intervals — not directly in this endpoint |
| Predispatch (forecast) | Separate AEMO endpoint — not covered here |

For historical backfill, AEMO publishes `DISPATCHPRICE` ZIP archives on NEMWeb at:
```
https://nemweb.com.au/Reports/Current/DispatchIS_Reports/
```
These are CSV files inside ZIP archives, published every 5 minutes and retained for
approximately 3 months in the `Current` folder. Older data is in the `Archive` folder.

---

## Market price boundaries

| Boundary | Value (2025–26) | Trigger |
|----------|-----------------|---------|
| Market Price Cap (MPC) | $16,600/MWh | `APCFLAG = 0` normally; cap activated during shortage events |
| Administered Price Cap (APC) | $300/MWh | Applied when cumulative prices exceed the APC threshold; `APCFLAG = 1.0` |
| Market Floor Price | −$1,000/MWh | Negative prices are valid — store them as-is |
| APC Threshold | $1,359,100 over 7 days | Once exceeded, APC applies until the cumulative sum resets |

> **APCFLAG handling:** When `APCFLAG = 1.0`, the `RRP` is capped at $300/MWh regardless
> of what the dispatch algorithm would have produced. Rules using spot price as a trigger
> should treat the APC as a "market stress" signal and may need separate logic.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| HTTP 403 from `aemo.com.au` | Main AEMO domain blocks automated requests | Switch to `visualisations.aemo.com.au` |
| HTTP 503 intermittently | AEMO infrastructure load during dispatch interval | Retry with 30-second backoff — resolves within 1–2 minutes |
| `SETTLEMENTDATE` not advancing | Stale data being cached upstream | AEMO sometimes serves a cached response for ~30 seconds mid-interval; retry is safe |
| `PRICE_STATUS = "PRELIMINARY"` | Price review in progress | Store the price and status; the next interval will confirm or revise |
| Negative `RRP` | High renewables + low demand — valid market condition | Do not treat as an error; rules may want to trigger at or below 0 $/MWh |
| `MARKETSUSPENDEDFLAG = 1.0` | AEMO has suspended the market (rare emergency) | Stop rule evaluation based on spot price; use last known firm price or a fallback value |
| `APCFLAG = 1.0` | Administered Price Cap is active | Log the condition; notify tenant admins if rules depend on spot price signals |
