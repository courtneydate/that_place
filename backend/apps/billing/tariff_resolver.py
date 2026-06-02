"""Tariff resolution for the billing engine — Sprint 31.

Two responsibilities:

1. find_assignment(account, stream, on_date)
      Walk BillingAccountTariffAssignment to pick the right assignment for an
      (account, stream) pair on a given date. Stream-specific assignment wins
      over a catch-all (stream=None) assignment in the same effective window.

2. split_interval(assignment, interval_start_utc, interval_end_utc, tenant_tz)
      Walk an IntervalAggregate's UTC window minute-by-minute in tenant local
      time, group consecutive minutes by the TOU row that matches, and return
      (period_name, fraction, row) segments. The caller multiplies the
      fraction by the interval's total kWh and applies row.values['rate_*'].

Per Sprint 31 design decisions:
  - Stream-specific assignment wins over catch-all.
  - TOU boundaries are split — an interval that straddles peak/off_peak
    produces two segments, not one weighted-mean entry.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs / Billing Runs & Invoicing
     ROADMAP Sprint 31 design decisions
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class TariffResolutionError(Exception):
    """Raised when an account/stream cannot be resolved to a single tariff row."""


# ---------------------------------------------------------------------------
# Assignment resolution
# ---------------------------------------------------------------------------

def find_assignment(account, stream, on_date: date):
    """Return the active BillingAccountTariffAssignment for an (account, stream).

    Stream-specific (assignment.stream_id == stream.id) wins over a catch-all
    (assignment.stream_id is None) when both cover ``on_date``.

    Returns None when no assignment applies — the caller decides whether that
    is a hard error (energy line) or fine (e.g. grid_export with no feed-in
    tariff: caller skips emitting a credit line).

    Raises TariffResolutionError if multiple stream-specific OR multiple
    catch-all assignments overlap on ``on_date`` — a misconfiguration.
    """
    from .models import BillingAccountTariffAssignment

    candidates = list(
        BillingAccountTariffAssignment.objects.filter(
            billing_account=account,
            effective_from__lte=on_date,
        ).filter(
            models_or_null('effective_to__gte', on_date),
        )
    )

    stream_specific = [
        a for a in candidates if a.stream_id == stream.id
    ]
    catch_all = [
        a for a in candidates if a.stream_id is None
    ]

    if len(stream_specific) > 1:
        raise TariffResolutionError(
            f'Multiple stream-specific tariff assignments for account '
            f'{account.id}, stream {stream.id} on {on_date} '
            f'(ids={[a.id for a in stream_specific]}). Fix overlapping '
            'effective windows.'
        )
    if stream_specific:
        return stream_specific[0]

    if len(catch_all) > 1:
        raise TariffResolutionError(
            f'Multiple catch-all tariff assignments for account {account.id} '
            f'on {on_date} (ids={[a.id for a in catch_all]}). Fix overlapping '
            'effective windows.'
        )
    if catch_all:
        return catch_all[0]

    return None


def models_or_null(field_lookup: str, value):
    """Q(field__lookup=value) | Q(field__isnull=True). Helper for nullable-bound filters."""
    from django.db.models import Q

    field_name = field_lookup.split('__', 1)[0]
    return Q(**{field_lookup: value}) | Q(**{f'{field_name}__isnull': True})


# ---------------------------------------------------------------------------
# Row resolution at a specific moment
# ---------------------------------------------------------------------------

def candidate_rows(assignment, on_date: date):
    """Return the active rows for an assignment that are valid on ``on_date``.

    Filters by:
      - dataset_id
      - is_active=True
      - dimension_filter containment (case-insensitive equality per key)
      - version (pinned, or latest active when dataset.has_version)
      - valid_from / valid_to (nullable bounds)

    The TOU filter (applicable_days, time_from/time_to) is *not* applied here
    — that's the per-moment lookup done by row_at().
    """
    from apps.feeds.models import ReferenceDatasetRow
    from apps.feeds.resolution import (
        _dimensions_match,
        models_Q_valid_today,
    )

    qs = ReferenceDatasetRow.objects.filter(
        dataset_id=assignment.dataset_id,
        is_active=True,
    ).filter(models_Q_valid_today(on_date))

    if assignment.version:
        qs = qs.filter(version=assignment.version)
    elif assignment.dataset.has_version:
        latest = (
            qs.exclude(version__isnull=True)
            .exclude(version='')
            .order_by('-version')
            .values_list('version', flat=True)
            .first()
        )
        if latest is None:
            raise TariffResolutionError(
                f'Dataset "{assignment.dataset.slug}" has no active versioned rows.'
            )
        qs = qs.filter(version=latest)

    return [
        row for row in qs
        if _dimensions_match(row.dimensions, assignment.dimension_filter or {})
    ]


def row_at(assignment, rows: list, dt_local: datetime):
    """Pick the single candidate row that applies at ``dt_local`` (tenant tz).

    Filters ``rows`` by TOU (applicable_days / time_from / time_to). Returns
    the matching row or None when no row covers this moment (e.g. a TOU
    schedule with gaps — operator misconfiguration; caller decides whether
    to skip or raise).

    Raises TariffResolutionError if more than one row matches — overlapping
    TOU windows are a misconfiguration.
    """
    from apps.feeds.resolution import _tou_matches

    day = dt_local.weekday()
    t_now = dt_local.time().replace(second=0, microsecond=0)

    matching = [
        row for row in rows
        if _tou_matches(row, day, t_now)
    ]

    if len(matching) > 1:
        raise TariffResolutionError(
            f'Ambiguous TOU resolution at {dt_local.isoformat()}: '
            f'{len(matching)} rows match (ids={[r.id for r in matching]}).'
        )
    return matching[0] if matching else None


# ---------------------------------------------------------------------------
# Interval splitting at TOU boundaries
# ---------------------------------------------------------------------------

def split_interval(
    assignment,
    interval_start_utc: datetime,
    interval_end_utc: datetime,
    tenant_tz: str,
):
    """Split an interval at TOU boundaries against the assignment's tariff.

    Walks the interval minute-by-minute in tenant local time, groups
    consecutive minutes that resolve to the same ReferenceDatasetRow, and
    yields (row, fraction) segments. ``fraction`` sums to 1.0 across the
    yielded segments (modulo float epsilon).

    Caller uses each segment's row.values to derive period_name + rate.

    A minute that does not match any row (TOU gap) is dropped — its share of
    the interval is effectively unbilled. The caller decides whether to log
    or fail when the dropped fraction is non-trivial.

    Args:
        assignment:           BillingAccountTariffAssignment instance.
        interval_start_utc:   Aware UTC datetime.
        interval_end_utc:     Aware UTC datetime (exclusive).
        tenant_tz:            IANA timezone string.

    Yields:
        (row, fraction) tuples, in chronological order.
    """
    if interval_end_utc <= interval_start_utc:
        return

    tz = ZoneInfo(tenant_tz)
    start_local = interval_start_utc.astimezone(tz)
    end_local = interval_end_utc.astimezone(tz)

    # Cache candidate rows per tenant-local date (intervals < 24h almost
    # always sit on one date; multi-day intervals get one fetch per day).
    rows_by_date: dict[date, list] = {}

    def rows_for(local_date):
        if local_date not in rows_by_date:
            rows_by_date[local_date] = candidate_rows(assignment, local_date)
        return rows_by_date[local_date]

    total_minutes = max(int((end_local - start_local).total_seconds() // 60), 1)
    cursor = start_local
    seg_row = None
    seg_minutes = 0

    for _ in range(total_minutes):
        rows = rows_for(cursor.date())
        row = row_at(assignment, rows, cursor)
        if row is None:
            # Close out the current segment (if any) and skip this minute.
            if seg_row is not None and seg_minutes > 0:
                yield seg_row, Decimal(seg_minutes) / Decimal(total_minutes)
                seg_row = None
                seg_minutes = 0
        elif seg_row is None or row.id != seg_row.id:
            # New segment starts here.
            if seg_row is not None and seg_minutes > 0:
                yield seg_row, Decimal(seg_minutes) / Decimal(total_minutes)
            seg_row = row
            seg_minutes = 1
        else:
            seg_minutes += 1
        cursor = cursor + timedelta(minutes=1)

    if seg_row is not None and seg_minutes > 0:
        yield seg_row, Decimal(seg_minutes) / Decimal(total_minutes)


def derive_period_name(row) -> str:
    """Return a human-readable TOU period name for a row.

    Prefers ``period_name`` in dimensions, falls back to ``tariff_code`` or
    the row's id. Used to label BillingLineItem.period_name.
    """
    if not row:
        return ''
    dims = row.dimensions or {}
    return (
        dims.get('period_name')
        or dims.get('tariff_code')
        or f'row-{row.id}'
    )


def get_rate(row, key: str = 'rate_cents_per_kwh') -> Decimal | None:
    """Return a Decimal rate from a row's values dict, or None when absent."""
    if not row:
        return None
    raw = (row.values or {}).get(key)
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def get_supply_charge(row) -> Decimal | None:
    """Return the daily supply charge in cents, or None when absent.

    Recognises both the PPA-template key (``supply_charge_cents_per_day``) and
    the network-tariffs key (``daily_supply_charge_cents``).
    """
    if not row:
        return None
    values = row.values or {}
    raw = values.get('supply_charge_cents_per_day') or values.get('daily_supply_charge_cents')
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None
