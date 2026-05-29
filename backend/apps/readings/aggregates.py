"""Interval aggregation engine — period alignment + aggregator core (Sprint 28).

Periods are clock-aligned in UTC. The aggregator is split into two layers:

* ``clock_align`` / ``period_end`` — pure functions over timestamps. Trivially
  unit-testable; no ORM dependency.
* ``compute_aggregate`` — pulls source ``StreamReading`` rows from the ORM,
  rolls them up by ``aggregation_kind``, builds the quality breakdown +
  derived quality, and ``update_or_create``s the ``IntervalAggregate`` row.
  Idempotent on ``(stream, period, period_start, aggregation_kind)``.

Ref: SPEC.md § Feature: Interval Aggregation Engine; § Feature: Data Quality
Flags; ROADMAP Sprint 28
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import IntervalAggregate, Stream, StreamReading

logger = logging.getLogger(__name__)

# Worst-input quality propagation (matches apps.readings.derived semantics).
_QUALITY_RANK = {'measured': 0, 'estimated': 1, 'substituted': 2, 'gap': 3}
_QUALITY_BY_RANK = {v: k for k, v in _QUALITY_RANK.items()}


def _worst_quality(qualities: Iterable[str]) -> str:
    """Return the worst-quality value from an iterable; defaults to 'measured'."""
    worst = 0
    for q in qualities:
        worst = max(worst, _QUALITY_RANK.get(q, 0))
    return _QUALITY_BY_RANK[worst]


# ---------------------------------------------------------------------------
# Period alignment — pure functions
# ---------------------------------------------------------------------------

_PERIOD_MINUTES = {
    IntervalAggregate.Period.MIN_5: 5,
    IntervalAggregate.Period.MIN_30: 30,
    IntervalAggregate.Period.HOUR: 60,
    IntervalAggregate.Period.DAY: 60 * 24,
}


def clock_align(ts: datetime, period: str) -> datetime:
    """Return the UTC-aligned period_start that contains ``ts``.

    Buckets:
      5min  → 00:00 / 00:05 / 00:10 / …
      30min → 00:00 / 00:30 / …
      1h    → top of the hour
      1d    → 00:00:00 UTC
      1mo   → first of the month, 00:00:00 UTC
    """
    if ts.tzinfo is None:
        raise ValueError('clock_align requires a timezone-aware datetime')
    ts_utc = ts.astimezone(timezone.utc)
    if period == IntervalAggregate.Period.MONTH:
        return ts_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == IntervalAggregate.Period.DAY:
        return ts_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = _PERIOD_MINUTES.get(period)
    if minutes is None:
        raise ValueError(f'unknown period: {period!r}')
    base = ts_utc.replace(second=0, microsecond=0)
    aligned_minute = (base.minute // minutes) * minutes
    return base.replace(minute=aligned_minute)


def period_end(period_start: datetime, period: str) -> datetime:
    """Return the exclusive upper bound of the bucket starting at ``period_start``."""
    if period == IntervalAggregate.Period.MONTH:
        if period_start.month == 12:
            return period_start.replace(year=period_start.year + 1, month=1)
        return period_start.replace(month=period_start.month + 1)
    minutes = _PERIOD_MINUTES.get(period)
    if minutes is None:
        raise ValueError(f'unknown period: {period!r}')
    return period_start + timedelta(minutes=minutes)


def previous_period_start(now: datetime, period: str) -> datetime:
    """Return the most-recently-completed bucket's start time, given ``now``."""
    current = clock_align(now, period)
    # ``current`` is the in-progress bucket; the previous one is the completed
    # bucket. For 5-min at 10:12 → current=10:10, previous=10:05.
    if period == IntervalAggregate.Period.MONTH:
        if current.month == 1:
            return current.replace(year=current.year - 1, month=12)
        return current.replace(month=current.month - 1)
    minutes = _PERIOD_MINUTES.get(period)
    if minutes is None:
        raise ValueError(f'unknown period: {period!r}')
    return current - timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Aggregation kernels
# ---------------------------------------------------------------------------

def _aggregate_values(values: list[float], kind: str) -> float | None:
    """Roll up a list of numeric values by ``kind``. Returns None on empty input."""
    if not values:
        return None
    if kind == Stream.AggregationKind.SUM:
        return sum(values)
    if kind == Stream.AggregationKind.MEAN:
        return sum(values) / len(values)
    if kind == Stream.AggregationKind.MIN:
        return min(values)
    if kind == Stream.AggregationKind.MAX:
        return max(values)
    if kind == Stream.AggregationKind.LAST:
        # values come from the DB ordered by timestamp ASC, so last is the
        # most recent reading in the bucket.
        return values[-1]
    raise ValueError(f'unknown aggregation kind: {kind!r}')


def _coerce_numeric(raw_value) -> float | None:
    """Coerce a JSON value to a float, or None if not numeric."""
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Compute + upsert
# ---------------------------------------------------------------------------

def compute_aggregate(stream: Stream, period: str, period_start: datetime, kind: str) -> IntervalAggregate:
    """Compute one ``IntervalAggregate`` for (stream, period, period_start, kind).

    Upserts on the unique key — re-running with the same inputs produces the
    same end state. A period with zero readings becomes a gap row
    (``count=0, value=None, quality=gap``).
    """
    bucket_end = period_end(period_start, period)
    readings = list(
        StreamReading.objects
        .filter(stream=stream, timestamp__gte=period_start, timestamp__lt=bucket_end)
        .order_by('timestamp')
        .values('value', 'quality')
    )

    if not readings:
        return _upsert_aggregate(
            stream=stream,
            period=period,
            period_start=period_start,
            kind=kind,
            value=None,
            count=0,
            quality=StreamReading.Quality.GAP,
            quality_breakdown={},
        )

    numeric_values: list[float] = []
    qualities: list[str] = []
    breakdown: Counter[str] = Counter()
    for r in readings:
        v = _coerce_numeric(r['value'])
        if v is not None:
            numeric_values.append(v)
        qualities.append(r['quality'])
        breakdown[r['quality']] += 1

    value = _aggregate_values(numeric_values, kind)
    return _upsert_aggregate(
        stream=stream,
        period=period,
        period_start=period_start,
        kind=kind,
        value=value,
        count=len(readings),
        quality=_worst_quality(qualities),
        quality_breakdown=dict(breakdown),
    )


def _upsert_aggregate(
    *, stream, period, period_start, kind, value, count, quality, quality_breakdown,
) -> IntervalAggregate:
    obj, _ = IntervalAggregate.objects.update_or_create(
        stream=stream,
        period=period,
        period_start=period_start,
        aggregation_kind=kind,
        defaults={
            'value': value,
            'count': count,
            'quality': quality,
            'quality_breakdown': quality_breakdown,
        },
    )
    return obj
