"""Formula evaluators for derived streams (Sprint 27).

Pure functions that take source readings + params and produce (timestamp, value)
output tuples. The dispatch layer (apps.readings.derived_dispatch) handles
storage, idempotency, and Celery wiring — these evaluators are deterministic
inputs-to-outputs only.

Per the Phase B kickoff decisions (2026-05-28):
  - cross-device alignment for `sum` / `difference` buckets to the nearest
    minute; the output reading is stamped at the bucket boundary.
  - `delta` with no `max_gap_minutes` does not suppress on gaps.
  - the output reading inherits worst-input quality (Sprint 28 wires this
    through; this module exposes the inherited quality via the return tuple).

Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

# Worst-input quality propagation: any input quality other than measured
# downgrades the output. Ordering captures the worst-input rule.
_QUALITY_RANK = {'measured': 0, 'estimated': 1, 'substituted': 2, 'gap': 3}
_QUALITY_BY_RANK = {v: k for k, v in _QUALITY_RANK.items()}


def _worst_quality(qualities: Iterable[str]) -> str:
    """Return the worst-quality value from an iterable; defaults to 'measured'."""
    worst = 0
    for q in qualities:
        worst = max(worst, _QUALITY_RANK.get(q, 0))
    return _QUALITY_BY_RANK[worst]


@dataclass(frozen=True)
class SourceReading:
    """Minimal reading shape an evaluator consumes — decoupled from ORM models."""
    stream_id: int
    timestamp: datetime
    value: float
    quality: str = 'measured'


@dataclass(frozen=True)
class DerivedOutput:
    """One output reading produced by an evaluator."""
    timestamp: datetime
    value: float
    quality: str = 'measured'


# ---------------------------------------------------------------------------
# Single-source: delta
# ---------------------------------------------------------------------------

def evaluate_delta(
    new_reading: SourceReading,
    previous_reading: SourceReading | None,
    *,
    max_gap_minutes: int | None = None,
) -> DerivedOutput | None:
    """Return the delta between `new_reading` and `previous_reading`.

    Returns None when:
      - There is no previous reading (first reading on a derived stream).
      - The computed delta is negative (counter reset — dropped).
      - The gap between readings exceeds `max_gap_minutes` (if set).

    The output is stamped at `new_reading.timestamp` and inherits worst-input
    quality from both readings.
    """
    if previous_reading is None:
        return None
    if max_gap_minutes is not None:
        gap = new_reading.timestamp - previous_reading.timestamp
        if gap > timedelta(minutes=max_gap_minutes):
            return None
    delta = new_reading.value - previous_reading.value
    if delta < 0:
        return None
    return DerivedOutput(
        timestamp=new_reading.timestamp,
        value=delta,
        quality=_worst_quality([new_reading.quality, previous_reading.quality]),
    )


# ---------------------------------------------------------------------------
# Single-source: scale
# ---------------------------------------------------------------------------

def evaluate_scale(
    reading: SourceReading,
    *,
    factor: float,
) -> DerivedOutput:
    """Return `reading.value * factor`, stamped at `reading.timestamp`."""
    return DerivedOutput(
        timestamp=reading.timestamp,
        value=reading.value * factor,
        quality=reading.quality,
    )


# ---------------------------------------------------------------------------
# Single-source: window_min / window_max / window_avg
# ---------------------------------------------------------------------------

def _floor_to_minute(ts: datetime) -> datetime:
    """Round a timestamp down to the nearest whole minute."""
    return ts.replace(second=0, microsecond=0)


def evaluate_window(
    readings_in_window: Sequence[SourceReading],
    *,
    aggregate: str,
    window_end: datetime,
) -> DerivedOutput | None:
    """Aggregate `readings_in_window` using `aggregate` (`min` / `max` / `avg`).

    `readings_in_window` is expected to be the readings whose timestamps fall
    inside the window ending at `window_end`. The output reading is stamped at
    `window_end` and inherits worst-input quality. Returns None on empty input.
    """
    if not readings_in_window:
        return None
    values = [r.value for r in readings_in_window]
    if aggregate == 'min':
        value = min(values)
    elif aggregate == 'max':
        value = max(values)
    elif aggregate == 'avg':
        value = sum(values) / len(values)
    else:
        raise ValueError(f'unknown windowed aggregate: {aggregate!r}')
    return DerivedOutput(
        timestamp=window_end,
        value=value,
        quality=_worst_quality(r.quality for r in readings_in_window),
    )


# ---------------------------------------------------------------------------
# Cross-source: sum / difference
# ---------------------------------------------------------------------------

def _bucket_minute(ts: datetime) -> datetime:
    """Round a timestamp down to the nearest whole minute (UTC-stable)."""
    return _floor_to_minute(ts)


def _group_by_minute_bucket(
    readings_by_stream: dict[int, Iterable[SourceReading]],
) -> dict[datetime, dict[int, SourceReading]]:
    """Group readings by minute bucket, preserving the latest reading per stream per bucket."""
    grouped: dict[datetime, dict[int, SourceReading]] = defaultdict(dict)
    for stream_id, readings in readings_by_stream.items():
        for r in readings:
            bucket = _bucket_minute(r.timestamp)
            # Keep the latest reading within the same bucket for this stream.
            existing = grouped[bucket].get(stream_id)
            if existing is None or r.timestamp >= existing.timestamp:
                grouped[bucket][stream_id] = r
    return grouped


def evaluate_sum(
    readings_by_stream: dict[int, Iterable[SourceReading]],
) -> list[DerivedOutput]:
    """Σ source streams at the same minute bucket.

    Only buckets where *every* source stream has a reading produce output.
    Output timestamp is the bucket boundary. Quality is the worst-input across
    the contributing readings in that bucket.
    """
    if not readings_by_stream:
        return []
    expected_streams = set(readings_by_stream.keys())
    outputs: list[DerivedOutput] = []
    grouped = _group_by_minute_bucket(readings_by_stream)
    for bucket in sorted(grouped):
        readings_at_bucket = grouped[bucket]
        if set(readings_at_bucket.keys()) != expected_streams:
            continue
        total = sum(r.value for r in readings_at_bucket.values())
        outputs.append(DerivedOutput(
            timestamp=bucket,
            value=total,
            quality=_worst_quality(r.quality for r in readings_at_bucket.values()),
        ))
    return outputs


def evaluate_difference(
    source_a: Iterable[SourceReading],
    source_b: Iterable[SourceReading],
    *,
    source_a_id: int,
    source_b_id: int,
) -> list[DerivedOutput]:
    """A − B at the same minute bucket. Output stamped at bucket boundary."""
    grouped = _group_by_minute_bucket({source_a_id: source_a, source_b_id: source_b})
    outputs: list[DerivedOutput] = []
    for bucket in sorted(grouped):
        readings_at_bucket = grouped[bucket]
        if source_a_id not in readings_at_bucket or source_b_id not in readings_at_bucket:
            continue
        a = readings_at_bucket[source_a_id]
        b = readings_at_bucket[source_b_id]
        outputs.append(DerivedOutput(
            timestamp=bucket,
            value=a.value - b.value,
            quality=_worst_quality([a.quality, b.quality]),
        ))
    return outputs
