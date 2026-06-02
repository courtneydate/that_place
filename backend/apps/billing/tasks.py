"""Celery tasks for the billing engine — Sprint 31 + Sprint 32.

billing.run_billing_run — main entry point. Acquires the per-(site, period)
    Redis lock, walks the engine steps, releases the lock. On failure marks
    the run failed and records the failed_step / failure_detail.

billing.retry_billing_run — refuses unless status=failed; resumes from
    failed_step.

billing.dispatch_billing_schedules — beat task fired every minute by
    Celery beat; finds active BillingSchedules whose next_run_at has
    passed and creates + dispatches a BillingRun for the previous full
    cadence period (offset by period_offset_days). When BillingSchedule
    .auto_finalize is True, finalize_billing_run is dispatched once the
    run reaches status=draft.

billing.finalize_billing_run — Sprint 32. Locks the run + line items +
    snapshot immutable, creates one BillingInvoice per account (atomic
    invoice number + PDF render + upload), then dispatches one
    send_invoice_email task per invoice.

billing.send_invoice_email — Sprint 32. Sends the invoice email to all
    recipients with PDF attached + a 14-day signed download URL. Updates
    BillingInvoice.delivery_status.

billing.send_void_notification_email — Sprint 32. Sends a void-notification
    email per delivered invoice when a run is voided without silent_void.

Per Sprint 31: only one in-flight run per (site, period_start, period_end).
Redis SET NX with TTL guards against concurrent dispatches; the lock is
released in the task's finally block.

Ref: SPEC.md § Feature: Billing Runs & Invoicing
     ROADMAP Sprint 31, Sprint 32
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import boto3
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, send_mail
from django.utils import timezone

from .invoice_renderer import generate_pdf_signed_url, render_and_upload_pdf

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
        if schedule.auto_finalize:
            # Dispatch finalize after the run task completes. The finalize
            # task itself guards on status=draft, so it will no-op if the
            # run fails.
            finalize_billing_run.apply_async(
                args=[run.id, None],
                countdown=5,
                # Give the run task time to reach draft; finalize will
                # retry up to 3× with 30 s delay if the run isn't draft yet.
            )

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


# ---------------------------------------------------------------------------
# Sprint 32 — Finalize + invoice email delivery
# ---------------------------------------------------------------------------

# 14-day signed URL for email links.
EMAIL_SIGNED_URL_EXPIRY = 14 * 24 * 60 * 60  # 1 209 600 seconds


@shared_task(
    name='billing.finalize_billing_run',
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def finalize_billing_run(self, billing_run_id: int, finalized_by_user_id) -> None:
    """Lock a draft BillingRun and create + dispatch invoices.

    Steps (all in one DB transaction):
      1. Verify run.status == draft; re-queue with countdown if not (run
         may still be computing when auto_finalize dispatches early).
      2. Lock the run row (select_for_update).
      3. Create BillingInvoice per account: allocate invoice number, sum
         line items, write record.
      4. Render + upload PDF per invoice.
      5. Mark run status=finalized, finalized_at, finalized_by.

    Then (outside the transaction) dispatch one send_invoice_email per invoice.
    """
    from django.db import transaction
    from django.utils import timezone

    from .models import BillingAccount, BillingInvoice, BillingLineItem, BillingRun

    try:
        run = BillingRun.objects.select_related('tenant', 'site').get(pk=billing_run_id)
    except BillingRun.DoesNotExist:
        logger.warning('finalize_billing_run: BillingRun %d not found', billing_run_id)
        return

    if run.status not in (BillingRun.Status.DRAFT, BillingRun.Status.REVIEW):
        if run.status == BillingRun.Status.COMPUTING and self.request.retries < self.max_retries:
            # Still computing — retry after delay.
            raise self.retry(
                exc=RuntimeError(f'BillingRun {billing_run_id} still computing'),
            )
        logger.warning(
            'finalize_billing_run: BillingRun %d has status=%s — skipping',
            billing_run_id, run.status,
        )
        return

    finalized_by = None
    if finalized_by_user_id is not None:
        from apps.accounts.models import User
        try:
            finalized_by = User.objects.get(pk=finalized_by_user_id)
        except User.DoesNotExist:
            pass

    tenant = run.tenant
    line_items_by_account = {}

    with transaction.atomic():
        # Lock the run row.
        run = BillingRun.objects.select_for_update().get(pk=billing_run_id)
        if run.status not in (BillingRun.Status.DRAFT, BillingRun.Status.REVIEW):
            logger.warning(
                'finalize_billing_run: BillingRun %d status changed under lock — abort',
                billing_run_id,
            )
            return

        # Collect accounts involved in this run.
        account_ids = list(
            BillingLineItem.objects
            .filter(billing_run=run)
            .values_list('billing_account_id', flat=True)
            .distinct()
        )
        accounts = {
            a.id: a
            for a in BillingAccount.objects.filter(id__in=account_ids)
        }

        created_invoices = []
        for account_id, account in accounts.items():
            items = list(
                BillingLineItem.objects
                .select_related('stream')
                .filter(billing_run=run, billing_account_id=account_id)
            )
            subtotal = sum(i.amount_cents for i in items)
            gst = sum(i.gst_cents for i in items)

            invoice_number = _allocate_number(tenant)

            invoice = BillingInvoice(
                billing_run=run,
                billing_account=account,
                invoice_number=invoice_number,
                period_start=run.period_start,
                period_end=run.period_end,
                subtotal_cents=subtotal,
                gst_cents=gst,
                total_cents=subtotal + gst,
                status=BillingInvoice.Status.DRAFT,
                delivery_status=BillingInvoice.DeliveryStatus.PENDING,
            )
            invoice.save()
            created_invoices.append(invoice)
            line_items_by_account[invoice.id] = items

        # Mark run finalized.
        run.status = BillingRun.Status.FINALIZED
        run.finalized_at = timezone.now()
        run.finalized_by = finalized_by
        run.save(update_fields=['status', 'finalized_at', 'finalized_by'])

    # Outside the transaction: render PDFs + dispatch email tasks.
    # PDF rendering is slow (WeasyPrint) — don't hold the DB lock.
    for invoice in created_invoices:
        items = line_items_by_account[invoice.id]
        account = accounts[invoice.billing_account_id]
        try:
            render_and_upload_pdf(invoice, run, account, items, tenant)
            invoice.save(update_fields=['pdf_object_key'])
        except Exception:
            logger.exception(
                'finalize_billing_run: PDF render/upload failed for invoice %d (%s)',
                invoice.id, invoice.invoice_number,
            )
            # Continue — invoice still gets created and emailed; the PDF
            # attachment will be missing but the signed URL will point to the
            # placeholder. Operator can manually resend once fixed.

        if account.invoice_email_recipients:
            send_invoice_email.delay(invoice.id)
        else:
            logger.info(
                'Invoice %s (%s) has no recipients — skipping email.',
                invoice.invoice_number, account.name,
            )

    logger.info(
        'finalize_billing_run: BillingRun %d finalized; %d invoices created',
        billing_run_id, len(created_invoices),
    )


def _allocate_number(tenant) -> str:
    """Thin wrapper so finalize_billing_run can call allocate_invoice_number."""
    from .invoice_renderer import allocate_invoice_number  # noqa: PLC0415
    return allocate_invoice_number(tenant)


@shared_task(
    name='billing.send_invoice_email',
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def send_invoice_email(self, invoice_id: int) -> None:
    """Email a BillingInvoice to all its account recipients.

    Attaches the PDF if pdf_object_key is set; always includes a 14-day
    signed download URL. Updates delivery_status and delivered_at.
    """
    from django.utils import timezone

    from .models import BillingInvoice

    try:
        invoice = BillingInvoice.objects.select_related(
            'billing_account', 'billing_run__tenant',
        ).get(pk=invoice_id)
    except BillingInvoice.DoesNotExist:
        logger.warning('send_invoice_email: invoice %d not found', invoice_id)
        return

    account = invoice.billing_account
    recipients = list(account.invoice_email_recipients or [])
    if not recipients:
        logger.info('send_invoice_email: no recipients for invoice %d', invoice_id)
        return

    tenant = invoice.billing_run.tenant
    subject = (
        f'Tax Invoice {invoice.invoice_number} — '
        f'{invoice.period_start.strftime("%b %Y")}'
    )

    # Build a 14-day signed URL (present even if PDF upload failed).
    signed_url = ''
    if invoice.pdf_object_key:
        try:
            signed_url = generate_pdf_signed_url(
                invoice.pdf_object_key,
                expiry_seconds=EMAIL_SIGNED_URL_EXPIRY,
            )
        except Exception:
            logger.exception(
                'send_invoice_email: failed to generate signed URL for invoice %d',
                invoice_id,
            )

    body = (
        f'Dear {account.name},\n\n'
        f'Please find attached your tax invoice {invoice.invoice_number} '
        f'for the billing period '
        f'{invoice.period_start.strftime("%d %b %Y")} to '
        f'{invoice.period_end.strftime("%d %b %Y")}.\n\n'
        f'Invoice total: ${invoice.total_cents / 100:,.2f} (incl. GST)\n\n'
    )
    if signed_url:
        body += (
            f'Download your invoice (valid for 14 days):\n{signed_url}\n\n'
        )
    body += (
        f'If you have any questions about this invoice, please contact us.\n\n'
        f'Regards,\n{tenant.name}'
    )

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )

    # Attach PDF bytes if available.
    if invoice.pdf_object_key:
        try:
            client = boto3.client(
                's3',
                aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None),
            )
            response = client.get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=invoice.pdf_object_key,
            )
            pdf_bytes = response['Body'].read()
            email.attach(
                f'{invoice.invoice_number}.pdf',
                pdf_bytes,
                'application/pdf',
            )
        except Exception:
            logger.exception(
                'send_invoice_email: could not fetch PDF for attachment (invoice %d)',
                invoice_id,
            )

    try:
        email.send(fail_silently=False)
        invoice.delivery_status = BillingInvoice.DeliveryStatus.SENT
        invoice.status = BillingInvoice.Status.DELIVERED
        invoice.delivered_at = timezone.now()
        invoice.save(update_fields=['delivery_status', 'status', 'delivered_at'])
        logger.info(
            'send_invoice_email: sent invoice %s to %s',
            invoice.invoice_number, recipients,
        )
    except Exception as exc:
        logger.error(
            'send_invoice_email: failed for invoice %d — %s', invoice_id, exc,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        invoice.delivery_status = BillingInvoice.DeliveryStatus.FAILED
        invoice.save(update_fields=['delivery_status'])


@shared_task(
    name='billing.send_void_notification_email',
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def send_void_notification_email(self, invoice_id: int) -> None:
    """Notify invoice recipients that the run has been voided.

    Only fired for invoices that were status=delivered at void time.
    """
    from .models import BillingInvoice

    try:
        invoice = BillingInvoice.objects.select_related(
            'billing_account', 'billing_run__tenant',
        ).get(pk=invoice_id)
    except BillingInvoice.DoesNotExist:
        logger.warning('send_void_notification_email: invoice %d not found', invoice_id)
        return

    account = invoice.billing_account
    recipients = list(account.invoice_email_recipients or [])
    if not recipients:
        return

    tenant = invoice.billing_run.tenant
    run = invoice.billing_run
    reason_note = f'\n\nReason: {run.void_reason}' if run.void_reason else ''

    subject = f'VOID NOTICE — Invoice {invoice.invoice_number}'
    body = (
        f'Dear {account.name},\n\n'
        f'Invoice {invoice.invoice_number} for the billing period '
        f'{invoice.period_start.strftime("%d %b %Y")} to '
        f'{invoice.period_end.strftime("%d %b %Y")} has been voided and '
        f'is no longer payable.{reason_note}\n\n'
        f'A revised invoice will be issued if applicable. Please contact '
        f'us if you have any questions.\n\n'
        f'Regards,\n{tenant.name}'
    )

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        logger.info(
            'send_void_notification_email: sent for invoice %s to %s',
            invoice.invoice_number, recipients,
        )
    except Exception as exc:
        logger.error(
            'send_void_notification_email: failed for invoice %d — %s', invoice_id, exc,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
