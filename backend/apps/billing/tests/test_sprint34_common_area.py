"""Sprint 34 — Common-area apportionment & reconciliation tests.

Covers the ``reconcile`` engine step and the common-area apportionment folded
into ``compute_line_items``:
  * pro_rata_consumption / equal_share / by_floor_area apportionment.
  * by_floor_area with a missing floor area → clean StepError.
  * internal account auto-created per common-area meter; source_account link.
  * reconciliation within tolerance (ok) and over tolerance (exceeded).
  * finalize gate: over-tolerance run blocked at review; force+note finalizes.
  * finalize force without a note is rejected at the API.
  * idempotent on rerun (same lines + report).
  * reconciliation endpoint: owner reads, cross-tenant 404, 404 for PPA runs.
  * PPA (non-hierarchical) runs write no reconciliation / common-area lines.

Ref: SPEC.md § Feature: Embedded-Network Billing (Reconciliation)
     ROADMAP Sprint 34
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

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
    ReconciliationReport,
)
from apps.billing.tasks import finalize_billing_run
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import ReferenceDataset, ReferenceDatasetRow
from apps.metering.models import MeterProfile
from apps.readings.models import IntervalAggregate, Stream

TS = datetime(2026, 5, 1, 10, 0, tzinfo=dt_timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


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


def make_site(tenant, *, method=Site.CommonAreaApportionmentMethod.PRO_RATA_CONSUMPTION,
              tol='1.5', name='EN Site'):
    return Site.objects.create(
        tenant=tenant, name=name, is_hierarchical=True,
        reconciliation_tolerance_percent=Decimal(tol),
        common_area_apportionment_method=method,
    )


def make_device(tenant, site, serial):
    dt, _ = DeviceType.objects.get_or_create(
        slug='b34-meter',
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


def make_stream(device, *, key, billing_role):
    return Stream.objects.create(
        device=device, key=key, label=key, unit='kWh',
        data_type='numeric', billing_role=billing_role,
        aggregation_kind_default=Stream.AggregationKind.SUM,
    )


def make_meter(device, role, *, parent=None):
    return MeterProfile.objects.create(
        tenant=device.tenant, device=device, meter_role=role, parent_meter=parent,
    )


def make_account(tenant, *, name, floor_area=None):
    return BillingAccount.objects.create(
        tenant=tenant, name=name, account_type=BillingAccount.AccountType.EN_TENANT,
        floor_area_sqm=floor_area,
    )


def link_meter(account, stream):
    return BillingAccountMeter.objects.create(
        billing_account=account, stream=stream, effective_from=date(2025, 1, 1),
    )


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


def assign_grid_tariff(account, dataset, *, plan='basic'):
    return BillingAccountTariffAssignment.objects.create(
        billing_account=account, dataset=dataset, stream=None,
        dimension_filter={'plan_code': plan}, version='2025-26',
        applies_to_role=Stream.BillingRole.CONSUMPTION,
        effective_from=date(2025, 1, 1),
    )


def add_aggregate(stream, *, value, period_start=TS, period='30min'):
    return IntervalAggregate.objects.create(
        stream=stream, period=period, period_start=period_start,
        aggregation_kind=Stream.AggregationKind.SUM,
        value=value, count=1, quality='measured',
        quality_breakdown={'measured': 1},
    )


def make_run(tenant, site):
    return BillingRun.objects.create(
        tenant=tenant, site=site, billing_account_ids=[],
        period_start=TS, period_end=TS + timedelta(minutes=30),
        timezone_snapshot=tenant.timezone, aggregate_period='30min',
    )


def _ca_lines(run):
    return list(
        BillingLineItem.objects.filter(billing_run=run, line_kind='common_area_share')
        .select_related('billing_account', 'source_account')
    )


# ---------------------------------------------------------------------------
# Scenario builder: 1 gate + N children + 1 common-area meter
# ---------------------------------------------------------------------------

def _hierarchical_site(*, method=Site.CommonAreaApportionmentMethod.PRO_RATA_CONSUMPTION,
                       tol='1.5', gate_import=12.0, generation=0.0, gate_export=0.0,
                       common_area=2.0, children_spec=((6.0, None), (4.0, None)),
                       grid_rate=30.0):
    """Build a hierarchical scenario and return (tenant, site, run, [child accounts]).

    children_spec: iterable of (import_kwh, floor_area).
    """
    tenant = make_tenant()
    site = make_site(tenant, method=method, tol=tol)
    grid_ds = make_flat_dataset('grid-rate', rate=grid_rate)

    # Gate meter (import + export streams).
    gate_dev = make_device(tenant, site, 'GATE')
    make_meter(gate_dev, MeterProfile.MeterRole.GATE)
    g_imp = make_stream(gate_dev, key='g_imp', billing_role=Stream.BillingRole.GRID_IMPORT)
    add_aggregate(g_imp, value=gate_import)
    if gate_export:
        g_exp = make_stream(gate_dev, key='g_exp', billing_role=Stream.BillingRole.GRID_EXPORT)
        add_aggregate(g_exp, value=gate_export)

    # Generation (optional).
    if generation:
        gen_dev = make_device(tenant, site, 'GEN')
        make_meter(gen_dev, MeterProfile.MeterRole.GENERATION)
        gen = make_stream(gen_dev, key='gen', billing_role=Stream.BillingRole.GENERATION)
        add_aggregate(gen, value=generation)

    # Common-area meter.
    if common_area:
        ca_dev = make_device(tenant, site, 'CA')
        make_meter(ca_dev, MeterProfile.MeterRole.COMMON_AREA, parent=gate_dev)
        ca_stream = make_stream(ca_dev, key='ca', billing_role=Stream.BillingRole.CONSUMPTION)
        add_aggregate(ca_stream, value=common_area)

    # Children.
    accounts = []
    for i, (imp, area) in enumerate(children_spec):
        dev = make_device(tenant, site, f'CH{i}')
        make_meter(dev, MeterProfile.MeterRole.CHILD, parent=gate_dev)
        imp_stream = make_stream(dev, key=f'imp{i}', billing_role=Stream.BillingRole.GRID_IMPORT)
        add_aggregate(imp_stream, value=imp)
        acct = make_account(tenant, name=f'Tenant {i}', floor_area=area)
        link_meter(acct, imp_stream)
        assign_grid_tariff(acct, grid_ds)
        accounts.append(acct)

    run = make_run(tenant, site)
    return tenant, site, run, accounts


# ---------------------------------------------------------------------------
# Common-area apportionment
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestApportionment:

    def test_pro_rata_by_consumption(self):
        # common-area 10; imports 6/4 → shares 6/4.
        tenant, site, run, (a, b) = _hierarchical_site(
            common_area=10.0, children_spec=((6.0, None), (4.0, None)),
        )
        engine.run_pipeline(run)
        lines = {li.billing_account_id: li for li in _ca_lines(run)}
        assert lines[a.id].kwh == Decimal('6.000000')
        assert lines[b.id].kwh == Decimal('4.000000')
        # Costed at the child grid rate (30 c/kWh).
        assert lines[a.id].rate_cents_per_kwh == Decimal('30.000000')
        assert lines[a.id].amount_cents == 180  # 6 × 30
        assert lines[a.id].gst_cents == 18
        assert lines[b.id].amount_cents == 120  # 4 × 30

    def test_equal_share(self):
        tenant, site, run, (a, b) = _hierarchical_site(
            method=Site.CommonAreaApportionmentMethod.EQUAL_SHARE,
            common_area=10.0, children_spec=((6.0, None), (4.0, None)),
        )
        engine.run_pipeline(run)
        lines = {li.billing_account_id: li for li in _ca_lines(run)}
        assert lines[a.id].kwh == Decimal('5.000000')
        assert lines[b.id].kwh == Decimal('5.000000')

    def test_by_floor_area(self):
        tenant, site, run, (a, b) = _hierarchical_site(
            method=Site.CommonAreaApportionmentMethod.BY_FLOOR_AREA,
            common_area=10.0,
            children_spec=((6.0, Decimal('100')), (4.0, Decimal('300'))),
        )
        engine.run_pipeline(run)
        lines = {li.billing_account_id: li for li in _ca_lines(run)}
        # 100:300 → 2.5 / 7.5 of 10.
        assert lines[a.id].kwh == Decimal('2.500000')
        assert lines[b.id].kwh == Decimal('7.500000')

    def test_by_floor_area_missing_area_raises(self):
        tenant, site, run, accounts = _hierarchical_site(
            method=Site.CommonAreaApportionmentMethod.BY_FLOOR_AREA,
            common_area=10.0,
            children_spec=((6.0, Decimal('100')), (4.0, None)),  # one missing area
        )
        # run_pipeline raises StepError; the task layer maps it to status=failed.
        with pytest.raises(engine.StepError) as exc:
            engine.run_pipeline(run)
        assert exc.value.step == BillingRun.Step.COMPUTE_LINE_ITEMS
        assert 'floor_area_sqm' in str(exc.value)

    def test_shares_sum_to_common_area_exactly(self):
        # 10 across three equal importers → 3.333333 ×2 + 3.333334.
        tenant, site, run, accounts = _hierarchical_site(
            common_area=10.0,
            children_spec=((4.0, None), (4.0, None), (4.0, None)),
        )
        engine.run_pipeline(run)
        kwh = sorted(li.kwh for li in _ca_lines(run))
        assert sum(kwh) == Decimal('10.000000')
        assert kwh == [Decimal('3.333333'), Decimal('3.333333'), Decimal('3.333334')]

    def test_internal_account_auto_created_and_linked(self):
        tenant, site, run, (a, b) = _hierarchical_site(common_area=10.0)
        engine.run_pipeline(run)
        internal = BillingAccount.objects.get(
            tenant=tenant, account_type=BillingAccount.AccountType.INTERNAL,
        )
        for li in _ca_lines(run):
            assert li.source_account_id == internal.id

    def test_idempotent_on_rerun(self):
        tenant, site, run, (a, b) = _hierarchical_site(common_area=10.0)
        engine.run_pipeline(run)
        first = {li.billing_account_id: li.kwh for li in _ca_lines(run)}
        internal_count_1 = BillingAccount.objects.filter(
            tenant=tenant, account_type=BillingAccount.AccountType.INTERNAL,
        ).count()
        engine.run_pipeline(run)
        second = {li.billing_account_id: li.kwh for li in _ca_lines(run)}
        internal_count_2 = BillingAccount.objects.filter(
            tenant=tenant, account_type=BillingAccount.AccountType.INTERNAL,
        ).count()
        assert first == second
        assert internal_count_1 == internal_count_2 == 1  # not duplicated


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReconciliation:

    def test_within_tolerance(self):
        # input = gate_import 12; output = child 10 + common 2 = 12 → losses 0.
        tenant, site, run, accounts = _hierarchical_site(
            gate_import=12.0, common_area=2.0,
            children_spec=((6.0, None), (4.0, None)),
        )
        engine.run_pipeline(run)
        report = ReconciliationReport.objects.get(billing_run=run)
        assert report.computed_losses_kwh == Decimal('0.000000')
        assert report.variance_percent == Decimal('0.0000')
        assert report.within_tolerance is True
        assert report.status == ReconciliationReport.ReconStatus.OK
        assert report.child_grid_import_total_kwh == Decimal('10.000000')
        assert report.common_area_total_kwh == Decimal('2.000000')

    def test_over_tolerance_flags_exceeded(self):
        # input 12; output = child 6 + common 0 = 6 → losses 6 → 50%.
        tenant, site, run, accounts = _hierarchical_site(
            gate_import=12.0, common_area=0.0,
            children_spec=((6.0, None),),
        )
        engine.run_pipeline(run)
        report = ReconciliationReport.objects.get(billing_run=run)
        assert report.variance_percent == Decimal('50.0000')
        assert report.within_tolerance is False
        assert report.status == ReconciliationReport.ReconStatus.EXCEEDED
        # Draft status is unchanged by reconcile — the gate is at finalize.
        run.refresh_from_db()
        assert run.status == BillingRun.Status.DRAFT


# ---------------------------------------------------------------------------
# Finalize gate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFinalizeGate:

    def _over_tolerance_run(self):
        tenant, site, run, accounts = _hierarchical_site(
            gate_import=12.0, common_area=0.0, children_spec=((6.0, None),),
        )
        engine.run_pipeline(run)
        return tenant, run

    def test_over_tolerance_blocks_finalize_at_review(self):
        tenant, run = self._over_tolerance_run()
        finalize_billing_run(run.id, None)  # non-force
        run.refresh_from_db()
        assert run.status == BillingRun.Status.REVIEW
        assert 'variance' in run.failure_detail.lower()
        from apps.billing.models import BillingInvoice
        assert BillingInvoice.objects.filter(billing_run=run).count() == 0

    def test_force_finalize_with_note_proceeds(self):
        tenant, run = self._over_tolerance_run()
        finalize_billing_run(run.id, None, force=True, note='Metering fault acknowledged')
        run.refresh_from_db()
        assert run.status == BillingRun.Status.FINALIZED
        assert run.notes == 'Metering fault acknowledged'
        from apps.billing.models import BillingInvoice
        assert BillingInvoice.objects.filter(billing_run=run).exists()

    def test_finalize_api_force_without_note_rejected(self):
        tenant, run = self._over_tolerance_run()
        admin = make_user(tenant)
        resp = auth_client(admin).post(
            f'/api/v1/billing-runs/{run.id}/finalize/',
            {'force': True}, format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'note_required'


# ---------------------------------------------------------------------------
# Reconciliation endpoint + isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReconciliationEndpoint:

    def test_owner_reads_report(self):
        tenant, site, run, accounts = _hierarchical_site()
        engine.run_pipeline(run)
        admin = make_user(tenant)
        resp = auth_client(admin).get(f'/api/v1/billing-runs/{run.id}/reconciliation/')
        assert resp.status_code == 200
        assert 'variance_percent' in resp.data
        assert resp.data['within_tolerance'] is True

    def test_cross_tenant_404(self):
        tenant, site, run, accounts = _hierarchical_site()
        engine.run_pipeline(run)
        other = make_tenant(name='Other')
        other_admin = make_user(other, email='x@other.test')
        resp = auth_client(other_admin).get(
            f'/api/v1/billing-runs/{run.id}/reconciliation/',
        )
        assert resp.status_code == 404

    def test_ppa_run_has_no_report_or_common_area(self):
        # Non-hierarchical: no reconciliation, no common-area lines.
        tenant = make_tenant()
        site = Site.objects.create(tenant=tenant, name='PPA', is_hierarchical=False)
        dev = make_device(tenant, site, 'PPA-GEN')
        gen = make_stream(dev, key='gen', billing_role=Stream.BillingRole.GENERATION)
        add_aggregate(gen, value=10.0)
        acct = BillingAccount.objects.create(
            tenant=tenant, name='Host', account_type=BillingAccount.AccountType.PPA_HOST,
        )
        link_meter(acct, gen)
        ds = make_flat_dataset('gen-rate', rate=20.0)
        BillingAccountTariffAssignment.objects.create(
            billing_account=acct, dataset=ds, stream=None,
            dimension_filter={'plan_code': 'basic'}, version='2025-26',
            applies_to_role='', effective_from=date(2025, 1, 1),
        )
        run = make_run(tenant, site)
        engine.run_pipeline(run)
        assert not ReconciliationReport.objects.filter(billing_run=run).exists()
        assert not _ca_lines(run)
        admin = make_user(tenant)
        resp = auth_client(admin).get(f'/api/v1/billing-runs/{run.id}/reconciliation/')
        assert resp.status_code == 404
