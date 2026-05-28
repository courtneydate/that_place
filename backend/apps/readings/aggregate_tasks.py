"""Celery tasks for the interval aggregation engine (Sprint 28).

Two paths:

  * ``maintain_interval_aggregates`` — beat task. Runs on a 60-second cadence
    and writes any newly-completed bucket for every active stream using
    ``Stream.aggregation_kind_default``. Idempotent on the unique key so
    re-runs are no-ops.
  * ``backfill_aggregates`` — on-demand. Given a stream, period, kind, and
    date range, walks every bucket between the aligned endpoints and upserts
    each one. Used by the read API's backfill endpoint when an operator wants
    historical aggregates or an extra kind.

The aggregator itself lives in ``aggregates.py`` — these tasks are thin
orchestration around it.

Ref: SPEC.md § Feature: Interval Aggregation Engine; ROADMAP Sprint 28
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .aggregates import clock_align, compute_aggregate, period_end, previous_period_start
from .models import IntervalAggregate, Stream

logger = logging.getLogger(__name__)

ALL_PERIODS = [
    IntervalAggregate.Period.MIN_5,
    IntervalAggregate.Period.MIN_30,
    IntervalAggregate.Period.HOUR,
    IntervalAggregate.Period.DAY,
    IntervalAggregate.Period.MONTH,
]


@shared_task(name='readings.maintain_interval_aggregates')
def maintain_interval_aggregates() -> int:
    """Write any newly-completed aggregates for every active stream.

    Run on a 60-second cadence. Cheap because update_or_create is idempotent —
    re-running on a bucket that's already current is a no-op write. Only
    completed buckets (period_start strictly in the past) are touched; the
    in-progress bucket waits for the next beat tick after it closes.
    """
    now = timezone.now()
    streams = Stream.objects.filter(
        device__status='active',
    ).only('id', 'aggregation_kind_default')

    written = 0
    for stream in streams.iterator():
        kind = stream.aggregation_kind_default
        for period in ALL_PERIODS:
            try:
                target = previous_period_start(now, period)
                compute_aggregate(stream, period, target, kind)
                written += 1
            except Exception:  # noqa: BLE001 — beat task must keep going
                logger.exception(
                    'maintain_interval_aggregates failed for stream=%d period=%s',
                    stream.pk, period,
                )
    return written


@shared_task(name='readings.backfill_aggregates')
def backfill_aggregates(
    stream_id: int,
    period: str,
    date_from_iso: str,
    date_to_iso: str,
    kinds: list[str] | None = None,
) -> int:
    """Recompute all aggregates of ``period`` for ``stream`` in ``[from, to)``.

    Aligns endpoints to the period boundary so partial first/last buckets are
    included. Upserts each (stream, period, period_start, kind) row. Idempotent.

    ``kinds`` defaults to ``[Stream.aggregation_kind_default]``; pass a list to
    compute extra kinds in one pass.
    """
    try:
        stream = Stream.objects.get(pk=stream_id)
    except Stream.DoesNotExist:
        logger.warning('backfill_aggregates: stream %d not found', stream_id)
        return 0

    date_from = parse_datetime(date_from_iso)
    date_to = parse_datetime(date_to_iso)
    if date_from is None or date_to is None or date_from >= date_to:
        raise ValueError(
            f'backfill_aggregates: invalid range {date_from_iso!r} → {date_to_iso!r}'
        )

    if not kinds:
        kinds = [stream.aggregation_kind_default]

    aligned_start = clock_align(date_from, period)
    cursor = aligned_start
    written = 0
    while cursor < date_to:
        for kind in kinds:
            compute_aggregate(stream, period, cursor, kind)
            written += 1
        cursor = period_end(cursor, period)
        # Defensive: avoid infinite loops on a misconfigured period.
        if cursor <= aligned_start:
            break
        if cursor - aligned_start > timedelta(days=366 * 5):
            # 5-year cap matches the longest realistic backfill window.
            break
    return written
