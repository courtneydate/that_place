"""Phase B2 sign-off smoke checks — repeatable.

Drives an end-to-end PPA billing round trip against the running stack
(Postgres + Redis + MinIO): build account + tariff + meter + interval
aggregates → run the engine to draft → finalize (PDF to object storage, email
delivery) → confirm a signed download URL → void with notification. Also
exercises the BillingSchedule dispatcher and cross-tenant isolation.

    docker-compose run --rm --no-deps backend python manage.py smoke_b2

Celery is forced into eager mode so the finalize / void sub-tasks (normally
dispatched with .delay()) run inline; email uses the in-memory backend so
delivery can be asserted. Every scenario runs inside a rolled-back savepoint —
no data persists. (PDF objects written to MinIO are harmless and overwrite on
re-run.)

Covers the ROADMAP Phase B2 sign-off checklist (manual smoke tests):
  * end-to-end PPA: account → tariff → run → finalize → invoice + signed URL
  * void a finalized run → void-notification emails
  * BillingSchedule dispatcher fires when next_run_at has passed
  * cross-tenant isolation across billing endpoints
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.billing import engine
from apps.billing.models import (
    BillingAccount,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
    BillingInvoice,
    BillingLineItem,
    BillingRun,
    BillingSchedule,
)
from apps.billing.tasks import dispatch_billing_schedules
from apps.feeds.models import ReferenceDataset, ReferenceDatasetRow
from apps.readings.models import IntervalAggregate, Stream
from config.celery import app as celery_app

from ._smoke_util import (
    Reporter,
    auth_client,
    disable_mqtt_provisioning,
    make_admin,
    make_device,
    make_site,
    make_stream,
    make_tenant,
    scenario,
)

TS = datetime(2026, 5, 1, 10, 0, tzinfo=dt_timezone.utc)


# ---------------------------------------------------------------------------
# Billing builders (match the sprint test-suite patterns)
# ---------------------------------------------------------------------------

def make_flat_dataset(slug, *, rate, supply=0.0, plan='basic'):
    ds = ReferenceDataset.objects.create(
        slug=slug, name=slug,
        dimension_schema={'plan_code': {'type': 'string'},
                          'period_name': {'type': 'string'}},
        value_schema={'rate_cents_per_kwh': {'type': 'numeric', 'unit': 'c/kWh'},
                      'supply_charge_cents_per_day': {'type': 'numeric', 'unit': 'c/day'}},
        scope=ReferenceDataset.Scope.TENANT,
        has_time_of_use=True, has_version=True,
    )
    ReferenceDatasetRow.objects.create(
        dataset=ds, version='2025-26',
        dimensions={'plan_code': plan, 'period_name': 'flat'},
        values={'rate_cents_per_kwh': rate, 'supply_charge_cents_per_day': supply},
        applicable_days=None, time_from=None, time_to=None,
    )
    return ds


def make_account(tenant, *, name, account_type=BillingAccount.AccountType.PPA_HOST,
                 recipients=None):
    return BillingAccount.objects.create(
        tenant=tenant, name=name, account_type=account_type,
        invoice_email_recipients=recipients or [],
    )


def link_meter(account, stream):
    return BillingAccountMeter.objects.create(
        billing_account=account, stream=stream, effective_from=date(2025, 1, 1),
    )


def assign_tariff(account, dataset, *, plan='basic', applies_to_role=''):
    return BillingAccountTariffAssignment.objects.create(
        billing_account=account, dataset=dataset, stream=None,
        dimension_filter={'plan_code': plan}, version='2025-26',
        applies_to_role=applies_to_role, effective_from=date(2025, 1, 1),
    )


def add_aggregate(stream, *, period_start, value, period='30min'):
    return IntervalAggregate.objects.create(
        stream=stream, period=period, period_start=period_start,
        aggregation_kind=Stream.AggregationKind.SUM,
        value=value, count=1, quality='measured',
        quality_breakdown={'measured': 1},
    )


class Command(BaseCommand):
    help = 'Run the Phase B2 sign-off smoke checks (repeatable, non-destructive).'

    def handle(self, *args, **options):
        reporter = Reporter(self.stdout, self.style)
        disable_mqtt_provisioning()
        # Run finalize/void sub-tasks inline; capture email in memory.
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

        self.stdout.write(self.style.MIGRATE_HEADING('Phase B2 sign-off smoke checks'))

        class _RollbackAll(Exception):
            pass

        try:
            with transaction.atomic():
                self._ppa_end_to_end(reporter)
                self._schedule_dispatch(reporter)
                raise _RollbackAll
        except _RollbackAll:
            pass

        reporter.summarize()
        if reporter.fail_count:
            raise CommandError(f'{reporter.fail_count} B2 check(s) failed.')

    # -- end-to-end PPA ------------------------------------------------------

    def _ppa_end_to_end(self, reporter):
        with scenario(reporter, 'end-to-end PPA: run → finalize → invoice → void'):
            tenant = make_tenant(
                gst_rate=Decimal('0.10'),
                invoice_number_format='INV-{YYYY}-{seq:04d}',
            )
            site = make_site(tenant)
            admin = make_admin(tenant)
            client = auth_client(admin)

            gen_dev = make_device(tenant, site, 'B2-GEN')
            gen = make_stream(gen_dev, key='generation',
                              billing_role=Stream.BillingRole.GENERATION)
            account = make_account(
                tenant, name='PPA Host Co',
                recipients=['billing@ppa-host.test'],
            )
            link_meter(account, gen)
            ds = make_flat_dataset('ppa-gen-rate', rate=20.0, supply=100.0)
            assign_tariff(account, ds)

            # 4 × 30-min intervals of 10 kWh = 40 kWh @ 20 c/kWh = 800 c energy.
            for i in range(4):
                add_aggregate(gen, period_start=TS + timedelta(minutes=30 * i), value=10.0)

            run = BillingRun.objects.create(
                tenant=tenant, site=site, billing_account_ids=[],
                period_start=TS, period_end=TS + timedelta(hours=2),
                timezone_snapshot=tenant.timezone, aggregate_period='30min',
            )
            engine.run_pipeline(run)
            run.refresh_from_db()
            reporter.check('engine reaches draft', run.status == BillingRun.Status.DRAFT,
                           run.status)

            energy = BillingLineItem.objects.filter(
                billing_run=run, line_kind='energy',
            ).first()
            reporter.check('energy line present', energy is not None)
            if energy:
                reporter.check('energy kWh = 40', energy.kwh == Decimal('40.000000'),
                               str(energy.kwh))
                reporter.check('energy rate = 20 c/kWh',
                               energy.rate_cents_per_kwh == Decimal('20.000000'),
                               str(energy.rate_cents_per_kwh))
                reporter.check('energy amount = 800 c', energy.amount_cents == 800,
                               str(energy.amount_cents))
                reporter.check('energy GST = 80 c (10%)', energy.gst_cents == 80,
                               str(energy.gst_cents))

            # Finalize via the real API endpoint (dispatches inline under eager).
            mail.outbox = []
            resp = client.post(f'/api/v1/billing-runs/{run.id}/finalize/', {}, format='json')
            reporter.check('finalize accepted (202)', resp.status_code == 202,
                           f'status {resp.status_code}')
            run.refresh_from_db()
            reporter.check('run finalized', run.status == BillingRun.Status.FINALIZED,
                           run.status)

            invoices = list(BillingInvoice.objects.filter(billing_run=run))
            reporter.check('one invoice per account', len(invoices) == 1,
                           f'{len(invoices)} invoices')
            invoice = invoices[0] if invoices else None
            if invoice:
                reporter.check('invoice number allocated',
                               bool(invoice.invoice_number), invoice.invoice_number)
                reporter.check('PDF written to object storage',
                               bool(invoice.pdf_object_key), invoice.pdf_object_key or '—')
                # Totals are internally consistent with the line items.
                items = BillingLineItem.objects.filter(billing_run=run, billing_account=account)
                sub = sum(i.amount_cents for i in items)
                gst = sum(i.gst_cents for i in items)
                reporter.check('invoice subtotal = Σ line amounts',
                               invoice.subtotal_cents == sub,
                               f'{invoice.subtotal_cents} vs {sub}')
                reporter.check('invoice GST = Σ line GST',
                               invoice.gst_cents == gst, f'{invoice.gst_cents} vs {gst}')
                reporter.check('invoice total = subtotal + GST',
                               invoice.total_cents == sub + gst,
                               f'{invoice.total_cents} vs {sub + gst}')
                reporter.check('invoice marked delivered',
                               invoice.status == BillingInvoice.Status.DELIVERED,
                               invoice.status)

            reporter.check('finalize sent ≥1 invoice email',
                           len(getattr(mail, 'outbox', [])) >= 1,
                           f'{len(getattr(mail, "outbox", []))} sent')

            # Signed download URL via the API, then fetch it to confirm it works.
            if invoice:
                r = client.get(f'/api/v1/invoices/{invoice.id}/pdf/')
                url = (r.json().get('url') if r.status_code == 200 else '') or ''
                reporter.check('signed PDF URL issued (200)',
                               r.status_code == 200 and bool(url),
                               f'status {r.status_code}')
                if url:
                    self._fetch_signed_url(reporter, url)

            # Void the finalized run — expect a void-notification email.
            if invoice:
                mail.outbox = []
                resp = client.post(f'/api/v1/billing-runs/{run.id}/void/',
                                   {'silent_void': False, 'reason': 'smoke test'},
                                   format='json')
                reporter.check('void accepted', resp.status_code in (200, 202),
                               f'status {resp.status_code}')
                run.refresh_from_db()
                invoice.refresh_from_db()
                reporter.check('run voided', run.status == BillingRun.Status.VOIDED,
                               run.status)
                reporter.check('invoice voided',
                               invoice.status == BillingInvoice.Status.VOID, invoice.status)
                reporter.check('void-notification email sent',
                               len(getattr(mail, 'outbox', [])) >= 1,
                               f'{len(getattr(mail, "outbox", []))} sent')

            # Cross-tenant isolation on the created records.
            other = make_tenant(name='Other Co')
            other_admin = make_admin(other, email='other-admin@example.test')
            oc = auth_client(other_admin)
            probes = [
                ('billing run', f'/api/v1/billing-runs/{run.id}/'),
                ('billing account', f'/api/v1/billing-accounts/{account.id}/'),
            ]
            if invoice:
                probes.append(('invoice', f'/api/v1/invoices/{invoice.id}/'))
            all_404 = True
            for label, path in probes:
                got = oc.get(path).status_code
                if got != 404:
                    all_404 = False
                    reporter.check(f'cross-tenant {label} blocked (404)', False,
                                   f'status {got}')
            reporter.check('cross-tenant billing endpoints all return 404', all_404)

    def _fetch_signed_url(self, reporter, url):
        try:
            import requests
            resp = requests.get(url, timeout=10)
            ok = resp.status_code == 200 and resp.content[:4] == b'%PDF'
            reporter.check('signed URL downloads a valid PDF', ok,
                           f'status {resp.status_code}, magic {resp.content[:4]!r}')
        except Exception as exc:  # noqa: BLE001
            reporter.skip('signed URL download', f'could not fetch: {exc!r}')

    # -- billing schedule dispatch ------------------------------------------

    def _schedule_dispatch(self, reporter):
        with scenario(reporter, 'BillingSchedule dispatcher fires when due'):
            tenant = make_tenant()
            site = make_site(tenant)

            schedule = BillingSchedule.objects.create(
                tenant=tenant, name='Monthly', site=site,
                billing_account_ids=[], aggregate_period='30min',
                cadence=BillingSchedule.Cadence.MONTHLY_CALENDAR,
                period_offset_days=0, auto_finalize=False, is_active=True,
                next_run_at=timezone.now() - timedelta(minutes=1),
            )
            before = BillingRun.objects.filter(tenant=tenant, site=site).count()
            dispatch_billing_schedules()
            after = BillingRun.objects.filter(tenant=tenant, site=site).count()
            reporter.check('dispatcher created a BillingRun', after == before + 1,
                           f'{before} → {after}')

            schedule.refresh_from_db()
            reporter.check('next_run_at advanced into the future',
                           schedule.next_run_at > timezone.now())
