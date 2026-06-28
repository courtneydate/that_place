# Derived Streams & Aggregation — Technical Reference

Covers how `aggregation_kind` is selected, how each derived stream formula
works, and how these feed into the billing engine.

---

## Aggregation kind

### Two separate settings — easy to confuse

**1. `Stream.aggregation_kind_default` — set per stream**

Configured on each Stream record (Streams tab on the device detail page).
Tells the background `maintain_interval_aggregates` Celery beat task what kind
of aggregate to continuously produce for that stream.

| Kind | Formula | Use for |
|---|---|---|
| `sum` | Sum of all readings in the bucket | **Energy (kWh)** — interval total is what gets billed |
| `mean` | Average of readings in the bucket | Power (kW), voltage, temperature — instantaneous values |
| `min` | Lowest reading in the bucket | Monitoring / alerting |
| `max` | Highest reading in the bucket | Monitoring / alerting |
| `last` | Final reading in the bucket | Cumulative counters (odometer-style registers) |

> **Default is `mean` when a stream is auto-discovered.** This is correct for
> most sensor data but wrong for energy streams. Any stream used in billing
> must have `aggregation_kind_default = sum`.

**2. The billing engine hardcodes `aggregation_kind = 'sum'`**

In `step_snapshot` (apps/billing/engine.py) the engine always queries:

```python
IntervalAggregate.objects.filter(
    stream_id=stream_id,
    period=period,
    aggregation_kind='sum',   # hardcoded
    ...
)
```

**If a stream's `aggregation_kind_default` is not `sum`, no sum aggregates
exist and the billing run computes $0 for that stream.**

### What to do for every billed stream

1. Device detail → **Streams tab** → find the stream (e.g. `generation_kwh`)
2. Set `aggregation_kind_default` to **Sum (energy)**
3. Backfill historical sum aggregates retroactively:

```bash
docker compose exec backend python manage.py shell -c "
from apps.readings.aggregate_tasks import backfill_aggregates
from apps.readings.models import Stream
s = Stream.objects.get(id=YOUR_STREAM_ID)
backfill_aggregates.delay(s.id)
"
```

---

## Derived stream formulas

Derived streams are virtual streams computed from one or more source streams.
They write `StreamReading` records identically to a real device, so they flow
into aggregates and billing without special handling.

Configured under: Device detail → Streams tab → **New derived stream**

---

### `delta` — interval energy from a cumulative counter

**Use case:** Your meter reports a rising cumulative kWh total (like a physical
meter display). `delta` converts it into interval consumption.

```
output = current_reading.value − previous_reading.value
```

**Guards (returns no output when):**
- First reading — no previous to compare against
- Result is **negative** — counter reset (meter replaced or rolled over)
- Gap between readings exceeds `max_gap_minutes` — prevents a large spurious
  spike after a comms outage

**Quality:** inherits the worst quality of the two input readings.

**Example:**

```
09:00  cumulative = 10,000 kWh    →  (no output — first reading)
09:30  cumulative = 10,012 kWh    →  delta = 12 kWh  (stamped at 09:30)
10:00  cumulative = 10,025 kWh    →  delta = 13 kWh  (stamped at 10:00)
10:30  cumulative = 10,040 kWh    →  delta = 15 kWh  (stamped at 10:30)
```

**For billing:** set `aggregation_kind_default = sum` on the delta stream
(not the raw cumulative stream). The delta values are already interval energy;
summing them gives total kWh for the period.

---

### `scale` — unit conversion or coefficient

**Use case:** A pulse counter reports in pulses; multiply by a factor to get
litres, kWh, cubic metres, etc.

```
output = reading.value × factor
```

**Example:** Water meter reports 500 pulses; factor = 0.002 m³/pulse → 1.0 m³

Quality passes through unchanged.

---

### `sum` — add multiple streams together

**Use case:** Combine three phase meters into total three-phase energy; add the
output of two inverters; total energy across multiple sub-meters.

```
output = stream_A.value + stream_B.value + ...   (at the same minute bucket)
```

**Alignment:** readings from different devices are bucketed to the nearest
minute. Only buckets where **every** source stream has a reading produce output
— if one stream is missing at a given minute, that minute is skipped entirely.

**Cross-device:** streams can come from different devices. The output lives on
an auto-created virtual "Site Composite" device.

**Quality:** worst quality of all inputs at that bucket.

---

### `difference` — subtract one stream from another

**Use case:** Consumption from solar = generation − grid export. Net import =
grid import − grid export. Any A minus B calculation.

```
output = stream_A.value − stream_B.value   (at the same minute bucket)
```

The result can be negative (e.g. a net export situation is a negative net
import). Both streams must have a reading at the same minute for output to be
produced. Same minute-bucket alignment as `sum`.

**Quality:** worst quality of the two inputs.

---

### `window_min` / `window_max` — rolling window extremes

**Use case:** Minimum or maximum value seen across a rolling time window.
Used for monitoring (e.g. "lowest voltage in the last 15 minutes") and as the
primitive behind windowed aggregate rule conditions.

```
window_min = min(all readings within the window ending now)
window_max = max(all readings within the window ending now)
```

Output is stamped at the window end boundary. Returns nothing if no readings
fall within the window.

**Quality:** worst quality of all readings in the window.

---

## How derived streams connect to billing

For billing the most important formula is **`delta`**, because most commercial
meters report a cumulative kWh total rather than interval energy directly.

### Full pipeline for a cumulative meter

```
Device sends cumulative kWh readings
        │
        ▼
StreamReading  (cumulative kWh — raw, aggregation_kind_default = last)
        │
        ▼  DerivedStream — formula: delta, max_gap_minutes = 65
        │
        ▼
StreamReading  (interval kWh — derived, aggregation_kind_default = sum)
        │
        ▼  maintain_interval_aggregates beat task
        │
        ▼
IntervalAggregate  (sum, 30 min)
        │
        ▼  billing engine step_snapshot
        │
        ▼
BillingRunSnapshot.computed_kwh  →  invoice line item
```

### Why the raw stream uses `last` and the delta uses `sum`

| Stream | Kind | Reason |
|---|---|---|
| Raw cumulative | `last` | The register value at the end of the bucket is the correct snapshot of the counter |
| Delta (interval) | `sum` | Each delta value IS the interval energy; summing them gives total kWh for the run |

### Example: one month of generation

```
Delta stream produces one 30-min reading every interval.
Aggregation (sum, 30 min) stores each interval's kWh.

Billing run fetches all 30-min sum aggregates in the period:
  1,488 intervals × average 5 kWh = 7,440 kWh total

Tariff: 20 c/kWh flat
Energy line: 7,440 × $0.20 = $1,488.00 + $148.80 GST

Supply: 31 days × $1.00/day = $31.00 + $3.10 GST

Invoice total: $1,670.90 incl. GST
```

### TOU splitting

When a tariff has time-of-use periods (peak / off-peak), the engine splits
each 30-minute interval at the boundary rather than applying a weighted mean.
A 30-minute interval that straddles 21:00 (peak→off-peak) is split exactly:

```
20:45–21:00  =  15 min  =  50% of interval kWh  →  peak rate    (e.g. 32 c/kWh)
21:00–21:15  =  15 min  =  50% of interval kWh  →  off-peak rate (e.g. 12 c/kWh)
```

All peak-segment kWh across the month accumulate into one peak energy line
item; all off-peak kWh into one off-peak line item.

---

## Common misconfiguration checklist

| Symptom | Cause | Fix |
|---|---|---|
| Billing run produces $0 energy | Stream `aggregation_kind_default` is not `sum` | Change to Sum, run backfill |
| Billing run produces $0 energy | No `IntervalAggregate` rows exist yet | Backfill or wait for beat task |
| Delta stream produces no output | Meter sending cumulative values but `max_gap_minutes` too tight | Increase `max_gap_minutes` or check comms |
| Delta stream shows spikes | Counter reset not caught | Check for negative-delta guard; verify meter was not replaced |
| Sum/difference stream skips minutes | Source streams don't report at the same time | Check device poll intervals are aligned |
| Billing run fails at compute_line_items | No tariff assignment resolves for the stream | Check BillingAccountTariffAssignment dimension filter — use Preview to verify |
