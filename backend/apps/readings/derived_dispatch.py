"""Dispatch + ORM glue for derived-stream evaluation (Sprint 27).

The pure-function evaluators live in ``derived.py``. This module:
  - Loads source ``StreamReading``s from the database into ``SourceReading``
    dataclasses the evaluators consume.
  - Calls the right evaluator for each formula.
  - Upserts the output ``StreamReading`` rows on ``(stream_id, timestamp)``
    so re-running produces the same end state (idempotency).
  - Maintains ``DerivedStreamSourceIndex`` on ``DerivedStream`` save / delete /
    M2M changes via Django signals.
  - Provides ``get_or_create_site_composite_device`` for cross-device
    derived streams.

Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete
from django.dispatch import receiver

from .derived import (
    SourceReading,
    evaluate_delta,
    evaluate_difference,
    evaluate_scale,
    evaluate_sum,
    evaluate_window,
)
from .models import DerivedStream, DerivedStreamSourceIndex, Stream, StreamReading

logger = logging.getLogger(__name__)

WINDOW_FORMULAS = {DerivedStream.Formula.WINDOW_MIN, DerivedStream.Formula.WINDOW_MAX}


# ---------------------------------------------------------------------------
# Source-Stream -> Derived index maintenance
# ---------------------------------------------------------------------------

def _rebuild_index_for(derived_stream: DerivedStream) -> None:
    """Drop and recreate DerivedStreamSourceIndex rows for this derived stream."""
    DerivedStreamSourceIndex.objects.filter(derived_stream=derived_stream).delete()
    source_ids = list(derived_stream.source_streams.values_list('pk', flat=True))
    DerivedStreamSourceIndex.objects.bulk_create([
        DerivedStreamSourceIndex(derived_stream=derived_stream, source_stream_id=sid)
        for sid in source_ids
    ])


@receiver(m2m_changed, sender=DerivedStream.source_streams.through)
def _on_source_streams_changed(sender, instance, action, **kwargs):
    """Rebuild the source index whenever a derived stream's sources change."""
    if action in ('post_add', 'post_remove', 'post_clear'):
        _rebuild_index_for(instance)


@receiver(post_delete, sender=DerivedStream)
def _on_derived_stream_deleted(sender, instance, **kwargs):
    """Remove index entries for a deleted derived stream (CASCADE also handles this)."""
    DerivedStreamSourceIndex.objects.filter(derived_stream_id=instance.pk).delete()


# ---------------------------------------------------------------------------
# Per-formula evaluation glue
# ---------------------------------------------------------------------------

def _reading_to_source(r: StreamReading) -> SourceReading:
    """Convert an ORM StreamReading to the dataclass the evaluators consume."""
    quality = getattr(r, 'quality', 'measured') or 'measured'
    try:
        value = float(r.value)
    except (TypeError, ValueError):
        # Non-numeric values (boolean / string streams) can't be evaluated;
        # skip rather than crash.
        value = float('nan')
    return SourceReading(stream_id=r.stream_id, timestamp=r.timestamp, value=value, quality=quality)


def _latest_reading(stream_id: int) -> StreamReading | None:
    """Latest StreamReading on a stream, or None."""
    return (
        StreamReading.objects
        .filter(stream_id=stream_id)
        .order_by('-timestamp')
        .first()
    )


def _previous_reading_before(stream_id: int, ts) -> StreamReading | None:
    """Most recent StreamReading on `stream_id` strictly before `ts`."""
    return (
        StreamReading.objects
        .filter(stream_id=stream_id, timestamp__lt=ts)
        .order_by('-timestamp')
        .first()
    )


def _readings_in_window(stream_id: int, window_end, window_minutes: int) -> list[StreamReading]:
    """Readings on `stream_id` within the closed window (window_end − window_minutes, window_end]."""
    window_start = window_end - timedelta(minutes=window_minutes)
    return list(
        StreamReading.objects
        .filter(stream_id=stream_id, timestamp__gt=window_start, timestamp__lte=window_end)
        .order_by('timestamp')
    )


def _upsert_output(stream: Stream, timestamp, value, quality: str = 'measured') -> None:
    """Idempotent write of a derived StreamReading on (stream, timestamp).

    Uses update_or_create so re-running on the same inputs produces identical
    end state — required by the acceptance criterion. Inherits worst-input
    quality from the evaluator (Sprint 28).
    """
    StreamReading.objects.update_or_create(
        stream=stream,
        timestamp=timestamp,
        defaults={'value': value, 'quality': quality},
    )


def _evaluate_for_trigger(derived: DerivedStream, trigger_stream_id: int) -> int:
    """Run one derived stream's evaluator and write the output.

    `trigger_stream_id` is the source stream whose new reading caused this
    evaluation. Returns the number of output rows written.
    """
    formula = derived.formula
    params = derived.params or {}
    sources = list(derived.source_streams.all())

    if formula == DerivedStream.Formula.DELTA:
        # Single-source — evaluate against the most recent reading on the trigger.
        new = _latest_reading(trigger_stream_id)
        if new is None:
            return 0
        prev = _previous_reading_before(trigger_stream_id, new.timestamp)
        out = evaluate_delta(
            _reading_to_source(new),
            previous_reading=_reading_to_source(prev) if prev else None,
            max_gap_minutes=params.get('max_gap_minutes'),
        )
        if out is None:
            return 0
        _upsert_output(derived.stream, out.timestamp, out.value, out.quality)
        return 1

    if formula == DerivedStream.Formula.SCALE:
        new = _latest_reading(trigger_stream_id)
        if new is None:
            return 0
        out = evaluate_scale(_reading_to_source(new), factor=float(params.get('factor', 1.0)))
        _upsert_output(derived.stream, out.timestamp, out.value, out.quality)
        return 1

    if formula in WINDOW_FORMULAS:
        new = _latest_reading(trigger_stream_id)
        if new is None:
            return 0
        window_minutes = int(params.get('window_minutes', 5))
        window_readings = _readings_in_window(trigger_stream_id, new.timestamp, window_minutes)
        aggregate = 'min' if formula == DerivedStream.Formula.WINDOW_MIN else 'max'
        out = evaluate_window(
            [_reading_to_source(r) for r in window_readings],
            aggregate=aggregate,
            window_end=new.timestamp,
        )
        if out is None:
            return 0
        _upsert_output(derived.stream, out.timestamp, out.value, out.quality)
        return 1

    if formula == DerivedStream.Formula.SUM:
        # Cross-source: pull the most recent reading per source within the
        # trigger's minute bucket. Emit only if every source has one.
        trigger_reading = _latest_reading(trigger_stream_id)
        if trigger_reading is None or not sources:
            return 0
        bucket = trigger_reading.timestamp.replace(second=0, microsecond=0)
        bucket_end = bucket + timedelta(minutes=1)
        per_stream = {
            s.pk: list(
                StreamReading.objects
                .filter(stream_id=s.pk, timestamp__gte=bucket, timestamp__lt=bucket_end)
                .order_by('-timestamp')[:1]
            )
            for s in sources
        }
        readings_by_stream = {
            sid: [_reading_to_source(r) for r in rs]
            for sid, rs in per_stream.items()
            if rs
        }
        if set(readings_by_stream.keys()) != {s.pk for s in sources}:
            return 0
        outputs = evaluate_sum(readings_by_stream)
        for o in outputs:
            _upsert_output(derived.stream, o.timestamp, o.value, o.quality)
        return len(outputs)

    if formula == DerivedStream.Formula.DIFFERENCE:
        if len(sources) < 2:
            return 0
        # source_a/source_b ids may be pinned in params; default to source-stream order.
        source_a_id = params.get('source_a_id') or sources[0].pk
        source_b_id = params.get('source_b_id') or sources[1].pk
        trigger_reading = _latest_reading(trigger_stream_id)
        if trigger_reading is None:
            return 0
        bucket = trigger_reading.timestamp.replace(second=0, microsecond=0)
        bucket_end = bucket + timedelta(minutes=1)
        a = list(
            StreamReading.objects
            .filter(stream_id=source_a_id, timestamp__gte=bucket, timestamp__lt=bucket_end)
            .order_by('-timestamp')[:1]
        )
        b = list(
            StreamReading.objects
            .filter(stream_id=source_b_id, timestamp__gte=bucket, timestamp__lt=bucket_end)
            .order_by('-timestamp')[:1]
        )
        if not a or not b:
            return 0
        outputs = evaluate_difference(
            [_reading_to_source(r) for r in a],
            [_reading_to_source(r) for r in b],
            source_a_id=source_a_id,
            source_b_id=source_b_id,
        )
        for o in outputs:
            _upsert_output(derived.stream, o.timestamp, o.value, o.quality)
        return len(outputs)

    logger.warning('Unknown derived formula %r — skipping', formula)
    return 0


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@shared_task(name='readings.dispatch_stream_derived_evaluation')
def dispatch_stream_derived_evaluation(source_stream_id: int) -> None:
    """Look up active derived streams sourced from this stream and dispatch each."""
    derived_ids = list(
        DerivedStreamSourceIndex.objects
        .filter(source_stream_id=source_stream_id, derived_stream__is_active=True)
        .values_list('derived_stream_id', flat=True)
    )
    for derived_id in derived_ids:
        evaluate_derived_stream.delay(derived_id, source_stream_id)


@shared_task(name='readings.evaluate_derived_stream')
def evaluate_derived_stream(derived_stream_id: int, trigger_stream_id: int) -> int:
    """Evaluate one derived stream and write the resulting StreamReading."""
    try:
        derived = (
            DerivedStream.objects
            .select_related('stream')
            .prefetch_related('source_streams')
            .get(pk=derived_stream_id, is_active=True)
        )
    except DerivedStream.DoesNotExist:
        return 0
    with transaction.atomic():
        return _evaluate_for_trigger(derived, trigger_stream_id)


# ---------------------------------------------------------------------------
# Backfill — pull a date range of source readings and recompute outputs
# ---------------------------------------------------------------------------

@shared_task(name='readings.backfill_derived_stream')
def backfill_derived_stream(derived_stream_id: int, date_from_iso: str, date_to_iso: str) -> int:
    """Recompute a derived stream over a date range. Idempotent upsert per timestamp.

    Walks the trigger-stream readings inside the window in chronological order
    and runs the per-trigger evaluator for each one. Derived readings outside
    the window are untouched.
    """
    from django.utils.dateparse import parse_datetime

    derived = (
        DerivedStream.objects
        .select_related('stream')
        .prefetch_related('source_streams')
        .get(pk=derived_stream_id)
    )
    date_from = parse_datetime(date_from_iso)
    date_to = parse_datetime(date_to_iso)
    if date_from is None or date_to is None:
        raise ValueError(f'invalid ISO datetimes: {date_from_iso!r}, {date_to_iso!r}')

    # For single-source formulas the trigger is the only source. For sum /
    # difference, every source acts as a trigger (each readings drives a
    # re-evaluation of its minute bucket).
    trigger_stream_ids = [s.pk for s in derived.source_streams.all()]
    if not trigger_stream_ids:
        return 0

    total = 0
    for trigger_stream_id in trigger_stream_ids:
        readings = (
            StreamReading.objects
            .filter(
                stream_id=trigger_stream_id,
                timestamp__gte=date_from,
                timestamp__lte=date_to,
            )
            .order_by('timestamp')
        )
        for reading in readings:
            # Re-use the same per-trigger evaluator. It will pick up the
            # latest reading on the trigger stream, which during a historical
            # walk would skip past older readings. We need the historical
            # reading itself to drive the evaluator, so we call the evaluators
            # directly here for a single specific reading.
            total += _evaluate_for_trigger_at_reading(derived, reading)
    return total


def _evaluate_for_trigger_at_reading(derived: DerivedStream, trigger_reading: StreamReading) -> int:
    """Per-reading variant of the dispatch evaluator used by backfill.

    Differs from `_evaluate_for_trigger` only in that it uses the supplied
    `trigger_reading` rather than the latest reading on the stream — so a
    historical walk evaluates against the values that existed *at* that
    timestamp.
    """
    formula = derived.formula
    params = derived.params or {}
    sources = list(derived.source_streams.all())

    if formula == DerivedStream.Formula.DELTA:
        prev = _previous_reading_before(trigger_reading.stream_id, trigger_reading.timestamp)
        out = evaluate_delta(
            _reading_to_source(trigger_reading),
            previous_reading=_reading_to_source(prev) if prev else None,
            max_gap_minutes=params.get('max_gap_minutes'),
        )
        if out is None:
            return 0
        _upsert_output(derived.stream, out.timestamp, out.value, out.quality)
        return 1

    if formula == DerivedStream.Formula.SCALE:
        out = evaluate_scale(_reading_to_source(trigger_reading), factor=float(params.get('factor', 1.0)))
        _upsert_output(derived.stream, out.timestamp, out.value, out.quality)
        return 1

    if formula in WINDOW_FORMULAS:
        window_minutes = int(params.get('window_minutes', 5))
        readings = _readings_in_window(trigger_reading.stream_id, trigger_reading.timestamp, window_minutes)
        aggregate = 'min' if formula == DerivedStream.Formula.WINDOW_MIN else 'max'
        out = evaluate_window(
            [_reading_to_source(r) for r in readings],
            aggregate=aggregate,
            window_end=trigger_reading.timestamp,
        )
        if out is None:
            return 0
        _upsert_output(derived.stream, out.timestamp, out.value, out.quality)
        return 1

    if formula == DerivedStream.Formula.SUM:
        bucket = trigger_reading.timestamp.replace(second=0, microsecond=0)
        bucket_end = bucket + timedelta(minutes=1)
        per_stream = {
            s.pk: list(
                StreamReading.objects
                .filter(stream_id=s.pk, timestamp__gte=bucket, timestamp__lt=bucket_end)
                .order_by('-timestamp')[:1]
            )
            for s in sources
        }
        readings_by_stream = {
            sid: [_reading_to_source(r) for r in rs]
            for sid, rs in per_stream.items()
            if rs
        }
        if set(readings_by_stream.keys()) != {s.pk for s in sources}:
            return 0
        outputs = evaluate_sum(readings_by_stream)
        for o in outputs:
            _upsert_output(derived.stream, o.timestamp, o.value, o.quality)
        return len(outputs)

    if formula == DerivedStream.Formula.DIFFERENCE:
        if len(sources) < 2:
            return 0
        source_a_id = params.get('source_a_id') or sources[0].pk
        source_b_id = params.get('source_b_id') or sources[1].pk
        bucket = trigger_reading.timestamp.replace(second=0, microsecond=0)
        bucket_end = bucket + timedelta(minutes=1)
        a = list(
            StreamReading.objects
            .filter(stream_id=source_a_id, timestamp__gte=bucket, timestamp__lt=bucket_end)
            .order_by('-timestamp')[:1]
        )
        b = list(
            StreamReading.objects
            .filter(stream_id=source_b_id, timestamp__gte=bucket, timestamp__lt=bucket_end)
            .order_by('-timestamp')[:1]
        )
        if not a or not b:
            return 0
        outputs = evaluate_difference(
            [_reading_to_source(r) for r in a],
            [_reading_to_source(r) for r in b],
            source_a_id=source_a_id,
            source_b_id=source_b_id,
        )
        for o in outputs:
            _upsert_output(derived.stream, o.timestamp, o.value, o.quality)
        return len(outputs)

    return 0


# ---------------------------------------------------------------------------
# Unique constraint on (stream, timestamp) for derived idempotency
# ---------------------------------------------------------------------------
# Note: StreamReading currently lacks a unique constraint on (stream, timestamp);
# the existing ingestion path tolerates duplicates. For derived streams, the
# update_or_create above is the idempotency primitive (race-safe enough for
# Celery's one-task-at-a-time-per-derived-stream pattern; under genuine
# concurrent triggers Sprint 28's aggregation engine will be the source of
# truth and this race window narrows further).


# ---------------------------------------------------------------------------
# Site composite host (cross-device derived streams)
# ---------------------------------------------------------------------------

SITE_COMPOSITE_SLUG = 'site-composite'


def get_or_create_site_composite_device(site):
    """Return the per-site virtual Device that hosts cross-device derived streams.

    Created on first call with `is_virtual=True`, `status=active`, no MQTT
    credentials, using the platform-seeded ``Site Composite`` DeviceType. The
    serial number is deterministic per site (`SITE-COMPOSITE-<site_id>`) so
    repeated calls are idempotent.

    Ref: SPEC.md § Feature: Derived / Computed Streams — cross-device hosting
    """
    from apps.devices.models import Device, DeviceType

    device_type = DeviceType.objects.get(slug=SITE_COMPOSITE_SLUG)
    device, _ = Device.objects.get_or_create(
        tenant=site.tenant,
        site=site,
        device_type=device_type,
        is_virtual=True,
        defaults={
            'name': f'Site Composite — {site.name}',
            'serial_number': f'SITE-COMPOSITE-{site.pk}',
            'status': Device.Status.ACTIVE,
        },
    )
    return device


def sources_span_multiple_devices(source_streams) -> bool:
    """Return True if the given source streams come from more than one device."""
    device_ids = {s.device_id for s in source_streams}
    return len(device_ids) > 1


# Touch the signal receivers so import-time registration occurs even when the
# module is imported lazily.
_signal_anchor = (_on_source_streams_changed, _on_derived_stream_deleted)
