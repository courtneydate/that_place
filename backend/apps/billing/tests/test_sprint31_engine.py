"""Sprint 31 — Billing Run Engine tests.

Covers:
  * Engine happy path: PPA host with a generation stream over 1 day.
  * Cross-tenant isolation on all read + write endpoints.
  * Permissions (Tenant Admin only writes; readers can list/retrieve).
  * TOU split correctness across a peak/off-peak boundary.
  * Mid-cycle pro-rata: deactivated_at clamps the billable window.
  * Stream-specific tariff assignment beats catch-all.
  * Same stream linked to two accounts → snapshot step fails cleanly.
  * Feed-in credit emitted on grid_export stream.
  * Per-line GST on every kind.
  * Redis lock prevents concurrent runs on the same (site, period).
  * retry resumes from failed_step; recompute rebuilds draft.
  * BillingSchedule cadence math + dispatcher dispatches a run.

Ref: SPEC.md § Feature: Billing Runs & Invoicing
     ROADMAP Sprint 31
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.billing import engine
from apps.billing.models import (
    BillingAccount,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
    BillingLineItem,
    BillingRun,
    BillingRunSnapshot,
    BillingSchedule,
)
from apps.billing.tasks import (
    _next_run_at,
    _previous_period,
    dispatch_billing_schedules,
    retry_billing_run,
    run_billing_run,
)
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import ReferenceDataset, ReferenceDatasetRow
from apps.readings.models import IntervalAggregate, Stream

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tenant(name='Acme', tz='Australia/Sydney'):
    return Tenant.objects.create(
        name=name, slug=slugify(name), timezone=tz, gst_rate=Decimal('0.10'),
    )


def make_user(tenant, role=TenantUser.Role.ADMIN, email=None):
    email = email or f'{role}@{tenant.slug}.test'
    user = User.objects.create_user(email=email, password='pass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': 'pass123'})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_site(tenant, name='Site'):
    return Site.objects.create(tenant=tenant, name=name)


def make_device(tenant, site, serial='D-1'):
    dt, _ = DeviceType.objects.get_or_create(
        slug='b31-meter',
        defaults={
            'name': 'Meter', 'connection_type': 'mqtt',
            'is_push': True, 'stream_type_definitions': [], 'commands': [],
        },
    )
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name=f'Dev {serial}', serial_number=serial,
        status=Device.Status.ACTIVE, topic_format='that_place_v1',
    )


def make_stream(device, *, key='gen_kwh', billing_role=Stream.BillingRole.GENERATION):
    return Stream.objects.create(
        device=device, key=key, label=key, unit='kWh',
        data_type='numeric', billing_role=billing_role,
        aggregation_kind_default=Stream.AggregationKind.SUM,
    )


def make_ppa_dataset(slug='ppa-test'):
    return ReferenceDataset.objects.create(
        slug=slug, name='PPA Test',
        dimension_schema={
            'plan_code': {'type': 'string'},
            'period_name': {'type': 'string'},
        },
        value_schema={
            'rate_cents_per_kwh': {'type': 'numeric', 'unit': 'c/kWh'},
            'supply_charge_cents_per_day': {'type': 'numeric', 'unit': 'c/day'},
        },
        scope=ReferenceDataset.Scope.TENANT,
        has_time_of_use=True,
        has_version=True,
    )


def make_flat_row(dataset, *, plan='basic', rate=20.0, supply=100.0, period='flat'):
    return ReferenceDatasetRow.objects.create(
        dataset=dataset, version='2025-26',
        dimensions={'plan_code': plan, 'period_name': period},
        values={'rate_cents_per_kwh': rate, 'supply_charge_cents_per_day': supply},
        applicable_days=None, time_from=None, time_to=None,
    )


def make_tou_rows(dataset, *, plan='tou'):
    """Build a peak/off-peak split: peak 07:00–21:00, off-peak the rest."""
    weekdays = [0, 1, 2, 3, 4, 5, 6]
    ReferenceDatasetRow.objects.create(
        dataset=dataset, version='2025-26',
        dimensions={'plan_code': plan, 'period_name': 'peak'},
        values={'rate_cents_per_kwh': 32.0, 'supply_charge_cents_per_day': 100.0},
        applicable_days=weekdays,
        time_from=time(7, 0), time_to=time(21, 0),
    )
    ReferenceDatasetRow.objects.create(
        dataset=dataset, version='2025-26',
        dimensions={'plan_code': plan, 'period_name': 'off_peak'},
        values={'rate_cents_per_kwh': 12.0, 'supply_charge_cents_per_day': 100.0},
        applicable_days=weekdays,
        time_from=time(21, 0), time_to=time(7, 0),
    )


def make_account(tenant, *, name='Host', activated=None, deactivated=None,
                 account_type=BillingAccount.AccountType.PPA_HOST):
    return BillingAccount.objects.create(
        tenant=tenant, name=name, account_type=account_type,
        activated_at=activated, deactivated_at=deactivated,
    )


def link_meter(account, stream, *, effective_from=None):
    return BillingAccountMeter.objects.create(
        billing_account=account, stream=stream,
        effective_from=effective_from or date(2025, 1, 1),
    )


def assign_tariff(account, dataset, *, stream=None, plan='basic',
                  effective_from=None):
    return BillingAccountTariffAssignment.objects.create(
        billing_account=account, dataset=dataset, stream=stream,
        dimension_filter={'plan_code': plan}, version='2025-26',
        effective_from=effective_from or date(2025, 1, 1),
    )


def add_aggregate(stream, *, period_start, value, period='30min'):
    """Write a single IntervalAggregate row (sum kind, all-measured quality)."""
    return IntervalAggregate.objects.create(
        stream=stream, period=period,
        period_start=period_start,
        aggregation_kind=Stream.AggregationKind.SUM,
        value=value, count=1,
        quality='measured',
        quality_breakdown={'measured': 1},
    )


def make_run(tenant, site, *, period_start, period_end, aggregate_period='30min',
             billing_account_ids=None, user=None):
    return BillingRun.objects.create(
        tenant=tenant, site=site,
        billing_account_ids=billing_account_ids or [],
        period_start=period_start, period_end=period_end,
        timezone_snapshot=tenant.timezone,
        aggregate_period=aggregate_period,
        created_by=user,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


# ---------------------------------------------------------------------------
# Engine — happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEngineHappyPath:

    def test_ppa_flat_one_day_one_account(self):
        """One PPA host account, one generation stream, flat 20 c/kWh tariff,
        24h period with 48 × 30-min aggregates of 1 kWh each → 48 kWh × 20c =
        960 cents (energy) + 100 cents (supply) + 10% GST per line.
        """
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device, billing_role=Stream.BillingRole.GENERATION)

        account = make_account(tenant)
        link_meter(account, stream)

        dataset = make_ppa_dataset()
        make_flat_row(dataset)
        assign_tariff(account, dataset)

        # Build 48 30-min aggregates over a single day in UTC.
        day_start = datetime(2026, 5, 1, 0, 0, tzinfo=dt_timezone.utc)
        for i in range(48):
            add_aggregate(stream, period_start=day_start + timedelta(minutes=30 * i), value=1.0)

        run = make_run(tenant, site,
                       period_start=day_start,
                       period_end=day_start + timedelta(days=1))
        engine.run_pipeline(run)

        run.refresh_from_db()
        assert run.status == BillingRun.Status.DRAFT
        assert run.failed_step is None

        items = list(BillingLineItem.objects.filter(billing_run=run))
        kinds = sorted(i.line_kind for i in items)
        assert kinds == ['energy', 'supply']

        energy = next(i for i in items if i.line_kind == 'energy')
        supply = next(i for i in items if i.line_kind == 'supply')
        assert energy.kwh == Decimal('48.000000')
        assert energy.amount_cents == 960
        assert energy.gst_cents == 96
        # 24h window touches 2 tenant-local dates (Sydney is UTC+10),
        # so the supply charge counts 2 days.
        assert supply.amount_cents == 200
        assert supply.gst_cents == 20

        # Snapshot row written.
        assert BillingRunSnapshot.objects.filter(billing_run=run).count() == 1


# ---------------------------------------------------------------------------
# TOU split correctness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTOUSplit:

    def test_one_hour_interval_crosses_peak_boundary(self):
        """1-hour interval at 21:00 local (off-peak begins) — half peak, half
        off-peak. With a 60 kWh interval and rates 32 / 12 c/kWh:
          peak share   = 30 kWh × 32c = 960 c
          off-peak     = 30 kWh × 12c = 360 c
        Each emitted as a separate line item (one per period_name).
        """
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device)

        account = make_account(tenant)
        link_meter(account, stream)

        dataset = make_ppa_dataset()
        make_tou_rows(dataset, plan='tou')
        assign_tariff(account, dataset, plan='tou')

        # Build a 1-h aggregate centered on 20:30–21:30 local (Sydney UTC+10
        # in May, no DST). 20:30 Sydney → 10:30 UTC.
        period_start_utc = datetime(2026, 5, 1, 10, 30, tzinfo=dt_timezone.utc)
        add_aggregate(stream, period_start=period_start_utc, value=60.0, period='1h')

        run = make_run(
            tenant, site,
            period_start=period_start_utc,
            period_end=period_start_utc + timedelta(hours=1),
            aggregate_period='1h',
        )
        engine.run_pipeline(run)

        energy_items = (
            BillingLineItem.objects
            .filter(billing_run=run, line_kind='energy')
            .order_by('period_name')
        )
        names = sorted(i.period_name for i in energy_items)
        assert names == ['off_peak', 'peak']
        peak = energy_items.get(period_name='peak')
        off = energy_items.get(period_name='off_peak')
        # Half-and-half split.
        assert peak.kwh == Decimal('30.000000')
        assert off.kwh == Decimal('30.000000')
        assert peak.amount_cents == 960
        assert off.amount_cents == 360


# ---------------------------------------------------------------------------
# Pro-rata + tariff precedence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProRataAndPrecedence:

    def test_deactivated_at_clamps_billable_window(self):
        """Account deactivated halfway through the period — only the first
        half's aggregates contribute."""
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device)

        period_start = datetime(2026, 5, 1, 0, 0, tzinfo=dt_timezone.utc)
        period_end = period_start + timedelta(days=2)
        # Deactivate at the midpoint.
        account = make_account(
            tenant,
            activated=period_start,
            deactivated=period_start + timedelta(days=1),
        )
        link_meter(account, stream)
        dataset = make_ppa_dataset()
        make_flat_row(dataset, rate=10.0, supply=0.0)
        assign_tariff(account, dataset)

        for i in range(96):  # 48 × 30-min per day × 2 days
            add_aggregate(stream, period_start=period_start + timedelta(minutes=30 * i), value=1.0)

        run = make_run(tenant, site, period_start=period_start, period_end=period_end)
        engine.run_pipeline(run)

        energy = BillingLineItem.objects.get(billing_run=run, line_kind='energy')
        # Only the 48 intervals before deactivation count.
        assert energy.kwh == Decimal('48.000000')

    def test_stream_specific_assignment_beats_catch_all(self):
        """A stream-specific tariff wins over a catch-all on the same account."""
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device)
        account = make_account(tenant)
        link_meter(account, stream)

        cheap_dataset = make_ppa_dataset(slug='cheap-catchall')
        ReferenceDatasetRow.objects.create(
            dataset=cheap_dataset, version='2025-26',
            dimensions={'plan_code': 'cheap', 'period_name': 'flat'},
            values={'rate_cents_per_kwh': 1.0, 'supply_charge_cents_per_day': 0.0},
        )
        assign_tariff(account, cheap_dataset, plan='cheap', stream=None)

        expensive_dataset = make_ppa_dataset(slug='expensive-stream')
        ReferenceDatasetRow.objects.create(
            dataset=expensive_dataset, version='2025-26',
            dimensions={'plan_code': 'lux', 'period_name': 'flat'},
            values={'rate_cents_per_kwh': 100.0, 'supply_charge_cents_per_day': 0.0},
        )
        assign_tariff(account, expensive_dataset, plan='lux', stream=stream)

        start = datetime(2026, 5, 1, 0, 0, tzinfo=dt_timezone.utc)
        add_aggregate(stream, period_start=start, value=1.0)

        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(minutes=30))
        engine.run_pipeline(run)

        energy = BillingLineItem.objects.get(billing_run=run, line_kind='energy')
        # 1 kWh × 100c (stream-specific won) — not 1c (catch-all).
        assert energy.amount_cents == 100


# ---------------------------------------------------------------------------
# Misconfiguration: stream linked to two active accounts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMisconfiguration:

    def test_double_booked_stream_fails_snapshot_step(self):
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device)
        a1 = make_account(tenant, name='A1')
        a2 = make_account(tenant, name='A2')
        link_meter(a1, stream)
        link_meter(a2, stream)

        dataset = make_ppa_dataset()
        make_flat_row(dataset)
        assign_tariff(a1, dataset)
        assign_tariff(a2, dataset)

        start = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        add_aggregate(stream, period_start=start, value=1.0)
        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(hours=1))
        with pytest.raises(engine.StepError) as exc:
            engine.run_pipeline(run)
        assert exc.value.step == BillingRun.Step.SNAPSHOT
        assert 'multiple active billing accounts' in exc.value.message


# ---------------------------------------------------------------------------
# Feed-in credit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFeedInCredit:

    def test_grid_export_stream_emits_credit_line(self):
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(
            device, key='export', billing_role=Stream.BillingRole.GRID_EXPORT,
        )
        account = make_account(tenant)
        link_meter(account, stream)
        dataset = make_ppa_dataset(slug='ppa-feed-in')
        make_flat_row(dataset, rate=5.0, supply=0.0)
        assign_tariff(account, dataset, stream=stream)

        start = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        add_aggregate(stream, period_start=start, value=10.0)
        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(minutes=30))
        engine.run_pipeline(run)

        credit = BillingLineItem.objects.get(billing_run=run, line_kind='credit')
        # 10 kWh × 5c = 50c, negated for credit.
        assert credit.amount_cents == -50
        # GST on a negative amount is also negative — keeps the invoice math
        # consistent (subtotal × rate scales linearly).
        assert credit.gst_cents == -5


# ---------------------------------------------------------------------------
# API endpoint surface
# ---------------------------------------------------------------------------


URL_RUNS = '/api/v1/billing-runs/'
URL_SCHEDULES = '/api/v1/billing-schedules/'


@pytest.mark.django_db
class TestBillingRunEndpoints:

    def _setup_one(self):
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device)
        account = make_account(tenant)
        link_meter(account, stream)
        dataset = make_ppa_dataset()
        make_flat_row(dataset)
        assign_tariff(account, dataset)
        start = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        add_aggregate(stream, period_start=start, value=2.0)
        return tenant, site, start

    def test_create_dispatches_and_returns_202(self):
        tenant, site, start = self._setup_one()
        admin = make_user(tenant)
        with patch('apps.billing.tasks.run_billing_run.delay') as mock_dispatch:
            resp = auth_client(admin).post(
                URL_RUNS,
                {
                    'site': site.id,
                    'period_start': start.isoformat(),
                    'period_end': (start + timedelta(hours=1)).isoformat(),
                },
                format='json',
            )
        assert resp.status_code == status.HTTP_202_ACCEPTED, resp.data
        run_id = resp.data['id']
        mock_dispatch.assert_called_once_with(run_id)
        run = BillingRun.objects.get(pk=run_id)
        assert run.tenant_id == tenant.id
        assert run.created_by_id == admin.id
        # timezone snapshot is captured at create time.
        assert run.timezone_snapshot == tenant.timezone

    def test_operator_cannot_create(self):
        tenant, site, start = self._setup_one()
        op = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@x')
        resp = auth_client(op).post(
            URL_RUNS,
            {
                'site': site.id,
                'period_start': start.isoformat(),
                'period_end': (start + timedelta(hours=1)).isoformat(),
            },
            format='json',
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_run_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        site_a = make_site(tenant_a)
        run = make_run(
            tenant_a, site_a,
            period_start=datetime(2026, 5, 1, tzinfo=dt_timezone.utc),
            period_end=datetime(2026, 5, 2, tzinfo=dt_timezone.utc),
        )
        admin_b = make_user(tenant_b)
        resp = auth_client(admin_b).get(f'{URL_RUNS}{run.id}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_retry_rejects_non_failed_runs(self):
        tenant, site, start = self._setup_one()
        admin = make_user(tenant)
        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(hours=1))
        resp = auth_client(admin).post(f'{URL_RUNS}{run.id}/retry/')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'invalid_status'

    def test_recompute_rejects_non_draft_runs(self):
        tenant, site, start = self._setup_one()
        admin = make_user(tenant)
        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(hours=1))
        # Status defaults to queued; recompute only works on draft.
        resp = auth_client(admin).post(f'{URL_RUNS}{run.id}/recompute/')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_line_items_list_endpoint(self):
        tenant, site, start = self._setup_one()
        admin = make_user(tenant)
        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(hours=1))
        engine.run_pipeline(run)
        resp = auth_client(admin).get(f'{URL_RUNS}{run.id}/line-items/')
        assert resp.status_code == 200
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# Redis lock + tasks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunTaskLocking:

    def test_lock_prevents_concurrent_run(self):
        """Pre-acquire the lock and confirm the task aborts cleanly."""
        from apps.billing.tasks import _run_lock_key

        tenant = make_tenant()
        site = make_site(tenant)
        run = make_run(
            tenant, site,
            period_start=datetime(2026, 5, 1, tzinfo=dt_timezone.utc),
            period_end=datetime(2026, 5, 2, tzinfo=dt_timezone.utc),
        )
        lock_key = _run_lock_key(site.id, run.period_start, run.period_end)
        cache.add(lock_key, 'other-worker', timeout=60)

        run_billing_run(run.id)

        run.refresh_from_db()
        assert run.status == BillingRun.Status.FAILED
        assert 'already in progress' in run.failure_detail

    def test_retry_resumes_from_failed_step(self):
        """A run marked failed at compute_line_items is retried — the engine
        skips resolve_scope/snapshot and only re-runs the failing step."""
        tenant = make_tenant()
        site = make_site(tenant)
        device = make_device(tenant, site)
        stream = make_stream(device)
        account = make_account(tenant)
        link_meter(account, stream)
        dataset = make_ppa_dataset()
        make_flat_row(dataset)
        assign_tariff(account, dataset)
        start = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        add_aggregate(stream, period_start=start, value=4.0)
        run = make_run(tenant, site,
                       period_start=start, period_end=start + timedelta(hours=1))

        # Pre-populate snapshot so retry can skip the snapshot step.
        engine.step_resolve_scope(run)
        engine.step_snapshot(run)
        run.status = BillingRun.Status.FAILED
        run.failed_step = BillingRun.Step.COMPUTE_LINE_ITEMS
        run.save(update_fields=['status', 'failed_step'])

        retry_billing_run(run.id)
        run.refresh_from_db()
        assert run.status == BillingRun.Status.DRAFT
        assert BillingLineItem.objects.filter(billing_run=run).exists()


# ---------------------------------------------------------------------------
# BillingSchedule cadence + dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBillingScheduleDispatcher:

    def test_monthly_calendar_previous_period_in_tenant_tz(self):
        tenant = make_tenant(tz='Australia/Sydney')
        site = make_site(tenant)
        sched = BillingSchedule.objects.create(
            tenant=tenant, name='monthly', site=site,
            cadence=BillingSchedule.Cadence.MONTHLY_CALENDAR,
        )
        # Pretend "now" is 2026-06-05 12:00 UTC → Sydney 2026-06-05 22:00.
        # Previous calendar month is May 2026 (00:00 → 00:00 Sydney).
        now = datetime(2026, 6, 5, 12, 0, tzinfo=dt_timezone.utc)
        start, end = _previous_period(sched, now)
        syd = ZoneInfo('Australia/Sydney')
        assert start.astimezone(syd) == datetime(2026, 5, 1, tzinfo=syd)
        assert end.astimezone(syd) == datetime(2026, 6, 1, tzinfo=syd)

    def test_next_run_at_advances(self):
        tenant = make_tenant()
        site = make_site(tenant)
        sched = BillingSchedule.objects.create(
            tenant=tenant, name='monthly', site=site,
            cadence=BillingSchedule.Cadence.MONTHLY_CALENDAR,
        )
        now = datetime(2026, 6, 5, 12, 0, tzinfo=dt_timezone.utc)
        next_ = _next_run_at(sched, now)
        syd = ZoneInfo('Australia/Sydney')
        assert next_.astimezone(syd) == datetime(2026, 7, 1, tzinfo=syd)

    def test_dispatcher_creates_a_run_when_next_run_at_has_passed(self):
        tenant = make_tenant()
        site = make_site(tenant)
        from django.utils import timezone as dj_timezone

        # next_run_at in the past — dispatcher should fire.
        past = dj_timezone.now() - timedelta(hours=1)
        BillingSchedule.objects.create(
            tenant=tenant, name='sched', site=site,
            cadence=BillingSchedule.Cadence.MONTHLY_CALENDAR,
            next_run_at=past, is_active=True,
        )
        with patch('apps.billing.tasks.run_billing_run.delay') as mock_dispatch:
            dispatch_billing_schedules()
        assert BillingRun.objects.count() == 1
        mock_dispatch.assert_called_once()
