"""Celery tasks for the billing engine — Sprint 31.

billing.run_billing_run — main entry point. Acquires the per-(site, period)
    Redis lock, walks the engine steps, releases the lock. On failure marks
    the run failed and records the failed_step / failure_detail.

billing.retry_billing_run — refuses unless status=failed; resumes from
    failed_step.

billing.dispatch_billing_schedules — beat task fired every minute by
    Celery beat; finds active BillingSchedules whose next_run_at has
    passed and creates + dispatches a BillingRun for the previous full
    cadence period (offset by period_offset_days).

Per Sprint 31: only one in-flight run per (site, period_start, period_end).
Redis SET NX with TTL guards against concurrent dispatches; the lock is
released in the task's finally block.

Ref: SPEC.md § Feature: Billing Runs & Invoicing
     ROADMAP Sprint 31
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


# Lock TTL covers the worst-case run duration; the task releases the lock
# explicitly so this only matters when a worker crashes mid-run.
RUN_LOCK_TTL_SECONDS = 60 * 60  # 1 hour

# Beat dispatcher safety: how far behind a scheduled run can be before the
# dispatcher skips it (avoid retroactive runs after a long outage).
SCHEDULE_LATE_TOLERANCE = timedelta(days=7)


def _run_lock_key(site_id: int, period_start, period_end) -> str:
    """Redis key for the per-(site, period) BillingRun lock."""
    return f'billing:run:lock:{site_id}:{period_start.isoformat()}:{period_end.isoformat()}'


# ---------------------------------------------------------------------------
# Main run task
# ---------------------------------------------------------------------------

@shared_task(name='billing.run_billing_run', max_retries=0)
def run_billing_run(billing_run_id: int) -> None:
    """Execute the billing engine for a single BillingRun.

    Acquires the per-(site, period) Redis lock via SET NX. Two simultaneous
    dispatches for the same run won't both execute the pipeline.

    On any step failure, marks the run failed and records the failed_step
    + failure_detail. The Redis lock is always released in `finally`.
    """
    from .models import BillingRun

    try:
        billing_run = BillingRun.objects.select_related('tenant', 'site').get(
            pk=billing_run_id,
        )
    except BillingRun.DoesNotExist:
        logger.warning('BillingRun %d not found — task aborted.', billing_run_id)
        return

    lock_key = _run_lock_key(
        billing_run.site_id, billing_run.period_start, billing_run.period_end,
    )
    acquired = cache.add(lock_key, str(billing_run_id), timeout=RUN_LOCK_TTL_SECONDS)
    if not acquired:
        logger.warning(
            'BillingRun %d skipped — lock %s held by another worker.',
            billing_run_id, lock_key,
        )
        # Re-mark the run failed so the user can investigate (rather than
        # leaving it stuck in queued/computing).
        billing_run.status = BillingRun.Status.FAILED
        billing_run.failure_detail = (
            'Another billing run for the same (site, period) is already in '
            'progress. Retry once it completes.'
        )
        billing_run.save(update_fields=['status', 'failure_detail'])
        return

    try:
        _execute(billing_run, from_step=None)
    finally:
        cache.delete(lock_key)


# ---------------------------------------------------------------------------
# Retry task
# ---------------------------------------------------------------------------

@shared_task(name='billing.retry_billing_run', max_retries=0)
def retry_billing_run(billing_run_id: int) -> None:
    """Resume a failed BillingRun from its failed_step.

    No-op if the run isn't in status=failed (the endpoint validates this
    too; this guard is for late-arriving retries after a manual
    intervention).
    """
    from .models import BillingRun

    try:
        billing_run = BillingRun.objects.select_related('tenant', 'site').get(
            pk=billing_run_id,
        )
    except BillingRun.DoesNotExist:
        logger.warning('BillingRun %d not found — retry aborted.', billing_run_id)
        return

    if billing_run.status != BillingRun.Status.FAILED:
        logger.warning(
            'BillingRun %d retry skipped — status=%s (only failed runs can be retried).',
            billing_run_id, billing_run.status,
        )
        return

    from_step = billing_run.failed_step  # may be None — falls back to start
    lock_key = _run_lock_key(
        billing_run.site_id, billing_run.period_start, billing_run.period_end,
    )
    acquired = cache.add(lock_key, str(billing_run_id), timeout=RUN_LOCK_TTL_SECONDS)
    if not acquired:
        logger.warning(
            'BillingRun %d retry skipped — lock %s held.', billing_run_id, lock_key,
        )
        return

    try:
        _execute(billing_run, from_step=from_step)
    finally:
        cache.delete(lock_key)


# ---------------------------------------------------------------------------
# Shared executor
# ---------------------------------------------------------------------------

def _execute(billing_run, from_step) -> None:
    """Run the engine pipeline and translate StepError into BillingRun state."""
    from .engine import StepError, run_pipeline
    from .models import BillingRun

    # Mark as computing so dashboards see progress (only when starting fresh).
    if from_step in (None, BillingRun.Step.RESOLVE_SCOPE):
        billing_run.status = BillingRun.Status.COMPUTING
        billing_run.failed_step = None
        billing_run.failure_detail = ''
        billing_run.save(update_fields=['status', 'failed_step', 'failure_detail'])

    try:
        run_pipeline(billing_run, from_step=from_step)
    except StepError as exc:
        logger.exception(
            'BillingRun %d failed at step %s', billing_run.id, exc.step,
        )
        billing_run.status = BillingRun.Status.FAILED
        billing_run.failed_step = exc.step
        billing_run.failure_detail = exc.message[:5000]
        billing_run.save(update_fields=['status', 'failed_step', 'failure_detail'])
    else:
        logger.info('BillingRun %d completed', billing_run.id)


# ---------------------------------------------------------------------------
# Schedule beat dispatcher
# ---------------------------------------------------------------------------

@shared_task(name='billing.dispatch_billing_schedules')
def dispatch_billing_schedules() -> None:
    """Beat task: dispatch BillingRuns for any schedules that are due.

    A schedule is due when next_run_at has passed and no more than
    SCHEDULE_LATE_TOLERANCE in arrears (avoid retroactive backfill after a
    long outage — the operator should intervene manually).

    On a successful dispatch, advances next_run_at to the next cadence
    boundary.
    """
    from .models import BillingRun, BillingSchedule

    now = timezone.now()
    cutoff = now - SCHEDULE_LATE_TOLERANCE
    due_schedules = (
        BillingSchedule.objects
        .filter(is_active=True, next_run_at__lte=now, next_run_at__gte=cutoff)
        .select_related('tenant', 'site')
    )

    for schedule in due_schedules:
        period_start, period_end = _previous_period(schedule, now)
        if period_end <= period_start:
            logger.warning(
                'BillingSchedule %d skipped — invalid window %s→%s',
                schedule.id, period_start, period_end,
            )
            continue

        # Skip if a run already exists for this schedule's period (idempotent
        # against re-dispatching the same period after a worker restart).
        already = BillingRun.objects.filter(
            tenant=schedule.tenant,
            site=schedule.site,
            period_start=period_start,
            period_end=period_end,
        ).exists()
        if already:
            schedule.next_run_at = _next_run_at(schedule, now)
            schedule.save(update_fields=['next_run_at'])
            continue

        run = BillingRun.objects.create(
            tenant=schedule.tenant,
            site=schedule.site,
            billing_account_ids=list(schedule.billing_account_ids or []),
            period_start=period_start,
            period_end=period_end,
            timezone_snapshot=schedule.tenant.timezone or 'Australia/Sydney',
            aggregate_period=schedule.aggregate_period,
            created_by=None,
        )
        run_billing_run.delay(run.id)

        schedule.last_run_at = now
        schedule.next_run_at = _next_run_at(schedule, now)
        schedule.save(update_fields=['last_run_at', 'next_run_at'])
        logger.info(
            'BillingSchedule %d dispatched BillingRun %d (period %s → %s)',
            schedule.id, run.id, period_start, period_end,
        )


# ---------------------------------------------------------------------------
# Schedule cadence helpers
# ---------------------------------------------------------------------------

def _previous_period(schedule, now):
    """Return (period_start_utc, period_end_utc) for the previous full cadence.

    monthly_calendar: the previous calendar month, anchored at 00:00 tenant tz.
    monthly_anchor:   from anchor_day of N-1 months ago to anchor_day of N months ago.
    quarterly:        the previous calendar quarter (Jan–Mar, Apr–Jun, …).
    custom_cron:      best-effort previous occurrence; v1 falls back to
                      monthly_calendar — the cron expression is reserved for
                      a follow-up sprint with `croniter`.
    """
    tz = ZoneInfo(schedule.tenant.timezone or 'Australia/Sydney')
    now_local = now.astimezone(tz)

    cadence = schedule.cadence
    if cadence == schedule.Cadence.MONTHLY_CALENDAR:
        first_of_this_month = now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        first_of_prev_month = _add_months(first_of_this_month, -1)
        return first_of_prev_month.astimezone(ZoneInfo('UTC')), first_of_this_month.astimezone(ZoneInfo('UTC'))

    if cadence == schedule.Cadence.MONTHLY_ANCHOR:
        anchor = schedule.anchor_day or 1
        anchor_this = _safe_replace_day(now_local, anchor).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        if anchor_this > now_local:
            # The anchor for this month hasn't happened yet — previous period
            # ends at the prior month's anchor.
            period_end = _safe_replace_day(_add_months(now_local, -1), anchor).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
        else:
            period_end = anchor_this
        period_start = _safe_replace_day(_add_months(period_end, -1), anchor).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        return period_start.astimezone(ZoneInfo('UTC')), period_end.astimezone(ZoneInfo('UTC'))

    if cadence == schedule.Cadence.QUARTERLY:
        quarter_index = (now_local.month - 1) // 3
        first_of_this_quarter = now_local.replace(
            month=quarter_index * 3 + 1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
        first_of_prev_quarter = _add_months(first_of_this_quarter, -3)
        return (
            first_of_prev_quarter.astimezone(ZoneInfo('UTC')),
            first_of_this_quarter.astimezone(ZoneInfo('UTC')),
        )

    # custom_cron — best-effort monthly fallback for v1.
    return _previous_period_monthly_fallback(now_local)


def _previous_period_monthly_fallback(now_local):
    first_of_this_month = now_local.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    first_of_prev_month = _add_months(first_of_this_month, -1)
    return (
        first_of_prev_month.astimezone(ZoneInfo('UTC')),
        first_of_this_month.astimezone(ZoneInfo('UTC')),
    )


def _next_run_at(schedule, now):
    """Return the next next_run_at for a schedule after a successful dispatch."""
    tz = ZoneInfo(schedule.tenant.timezone or 'Australia/Sydney')
    now_local = now.astimezone(tz)
    cadence = schedule.cadence
    offset = timedelta(days=schedule.period_offset_days or 0)

    if cadence == schedule.Cadence.MONTHLY_CALENDAR:
        # First of next month, plus offset, in tenant tz.
        first_next = _add_months(
            now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            1,
        )
        return (first_next + offset).astimezone(ZoneInfo('UTC'))

    if cadence == schedule.Cadence.MONTHLY_ANCHOR:
        anchor = schedule.anchor_day or 1
        anchor_next = _safe_replace_day(_add_months(now_local, 1), anchor).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        return (anchor_next + offset).astimezone(ZoneInfo('UTC'))

    if cadence == schedule.Cadence.QUARTERLY:
        quarter_index = (now_local.month - 1) // 3
        first_next = _add_months(
            now_local.replace(
                month=quarter_index * 3 + 1, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            ),
            3,
        )
        return (first_next + offset).astimezone(ZoneInfo('UTC'))

    # custom_cron — fall back to monthly calendar in v1.
    first_next = _add_months(
        now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        1,
    )
    return (first_next + offset).astimezone(ZoneInfo('UTC'))


def _add_months(dt: datetime, months: int) -> datetime:
    """Add ``months`` months to ``dt``, capping the day at the new month's last."""
    new_month_idx = dt.month - 1 + months
    new_year = dt.year + new_month_idx // 12
    new_month = new_month_idx % 12 + 1
    day = min(dt.day, _days_in_month(new_year, new_month))
    return dt.replace(year=new_year, month=new_month, day=day)


def _safe_replace_day(dt: datetime, day: int) -> datetime:
    """Replace the day-of-month, clamping to the month's last day."""
    return dt.replace(day=min(day, _days_in_month(dt.year, dt.month)))


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in (year, month)."""
    import calendar

    return calendar.monthrange(year, month)[1]
