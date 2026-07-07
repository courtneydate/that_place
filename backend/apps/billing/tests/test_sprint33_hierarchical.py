"""Sprint 33 — Embedded-Network (hierarchical) solar allocation tests.

Covers the new ``allocate_solar`` engine step and the split-rate child invoice:
  * Single-gate / single-child happy path + two-leg invoice (solar + grid).
  * Multi-child pro-rata allocation by grid_import.
  * Allocation totals equal the solar pool exactly (no rounding leakage).
  * BESS discharge excluded from the solar pool.
  * Solar pool of zero produces no allocations.
  * gate_export > generation caps the pool at zero.
  * Mid-cycle child onboarding pro-rates per interval (window clamping).
  * Idempotent re-run (recompute) produces identical records.
  * Missing grid tariff fails compute_line_items cleanly.
  * allocations endpoint: owner reads, cross-tenant 404, empty for PPA.
  * PPA (non-hierarchical) runs write no allocations — Sprint 31 path intact.

Ref: SPEC.md § Feature: Embedded-Network Billing (Hierarchical Metering)
     ROADMAP Sprint 33
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
    SolarAllocationRecord,
)
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import ReferenceDataset, ReferenceDatasetRow
from apps.readings.models import IntervalAggregate, Stream

# ---------------------------------------------------------------------------
# Fixtures / helpers
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


def make_site(tenant, *, hierarchical=True, name='EN Site'):
    return Site.objects.create(tenant=tenant, name=name, is_hierarchical=hierarchical)


def make_device(tenant, site, serial):
    dt, _ = DeviceType.objects.get_or_create(
        slug='b33-meter',
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


def make_flat_dataset(slug, *, rate, supply=0.0, plan='basic'):
    """A single-row flat tariff dataset returning ``rate`` c/kWh."""
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


def make_account(tenant, *, name, account_type=BillingAccount.AccountType.EN_TENANT,
                 activated=None, deactivated=None):
    return BillingAccount.objects.create(
        tenant=tenant, name=name, account_type=account_type,
        activated_at=activated, deactivated_at=deactivated,
    )


def link_meter(account, stream, *, effective_from=None):
    return BillingAccountMeter.objects.create(
        billing_account=account, stream=stream,
        effective_from=effective_from or date(2025, 1, 1),
    )


def assign_tariff(account, dataset, *, stream=None, plan='basic', applies_to_role=''):
    return BillingAccountTariffAssignment.objects.create(
        billing_account=account, dataset=dataset, stream=stream,
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


def make_run(tenant, site, *, period_start, period_end, aggregate_period='30min'):
    return BillingRun.objects.create(
        tenant=tenant, site=site, billing_account_ids=[],
        period_start=period_start, period_end=period_end,
        timezone_snapshot=tenant.timezone, aggregate_period=aggregate_period,
    )


# A reusable interval start: Sydney is UTC+10 (no DST in May), 10:00 UTC =
# 20:00 local — keeps everything inside one tenant-local date.
TS = datetime(2026, 5, 1, 10, 0, tzinfo=dt_timezone.utc)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


def _energy_legs(run):
    """Return (solar_line, grid_line) by period-name suffix, either may be None."""
    items = BillingLineItem.objects.filter(billing_run=run, line_kind='energy')
    solar = next((i for i in items if '(solar)' in i.period_name), None)
    grid = next((i for i in items if '(grid)' in i.period_name), None)
    return solar, grid


# ---------------------------------------------------------------------------
# Happy path + two-leg invoice
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSingleChildHappyPath:

    def _scenario(self, *, generation, gate_export, child_import):
        tenant = make_tenant()
        site = make_site(tenant)

        gen_dev = make_device(tenant, site, 'GEN')
        gen = make_stream(gen_dev, key='gen', billing_role=Stream.BillingRole.GENERATION)
        gate_dev = make_device(tenant, site, 'GATE')
        export = make_stream(gate_dev, key='exp', billing_role=Stream.BillingRole.GRID_EXPORT)
        child_dev = make_device(tenant, site, 'CH1')
        imp = make_stream(child_dev, key='imp', billing_role=Stream.BillingRole.GRID_IMPORT)

        child = make_account(tenant, name='Tenant 1')
        link_meter(child, imp)

        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)
        assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
        assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)

        add_aggregate(gen, period_start=TS, value=generation)
        add_aggregate(export, period_start=TS, value=gate_export)
        add_aggregate(imp, period_start=TS, value=child_import)

        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)
        return run, child

    def test_pool_allocated_and_invoice_splits_two_legs(self):
        # gen 10 − export 4 = pool 6; child import 8 → solar 6, grid 2.
        run, child = self._scenario(generation=10.0, gate_export=4.0, child_import=8.0)
        run.refresh_from_db()
        assert run.status == BillingRun.Status.DRAFT

        rec = SolarAllocationRecord.objects.get(billing_run=run, billing_account=child)
        assert rec.allocated_kwh == Decimal('6.000000')
        assert rec.pool_kwh == Decimal('6.000000')
        assert rec.child_grid_import_kwh == Decimal('8.000000')
        assert rec.allocation_method == 'pro_rata_consumption'

        solar, grid = _energy_legs(run)
        assert solar is not None and grid is not None
        # Solar leg: 6 kWh × 10c = 60c.
        assert solar.kwh == Decimal('6.000000')
        assert solar.rate_cents_per_kwh == Decimal('10.000000')
        assert solar.amount_cents == 60
        assert solar.gst_cents == 6
        # Grid leg: remaining 2 kWh × 30c = 60c.
        assert grid.kwh == Decimal('2.000000')
        assert grid.rate_cents_per_kwh == Decimal('30.000000')
        assert grid.amount_cents == 60
        assert grid.gst_cents == 6

    def test_zero_pool_produces_no_allocation_only_grid_leg(self):
        # gen 0 → pool 0; no allocation, whole 8 kWh bills at grid rate.
        run, child = self._scenario(generation=0.0, gate_export=0.0, child_import=8.0)
        assert SolarAllocationRecord.objects.filter(billing_run=run).count() == 0
        solar, grid = _energy_legs(run)
        assert solar is None
        assert grid.kwh == Decimal('8.000000')
        assert grid.amount_cents == 240  # 8 × 30c

    def test_gate_export_exceeds_generation_caps_pool_at_zero(self):
        # gen 4 − export 10 = −6 → pool floored at 0; no allocation.
        run, child = self._scenario(generation=4.0, gate_export=10.0, child_import=8.0)
        assert SolarAllocationRecord.objects.filter(billing_run=run).count() == 0
        solar, grid = _energy_legs(run)
        assert solar is None
        assert grid.kwh == Decimal('8.000000')


# ---------------------------------------------------------------------------
# Multi-child pro-rata + exactness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMultiChildAllocation:

    def _two_children(self, *, generation, import_a, import_b):
        tenant = make_tenant()
        site = make_site(tenant)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)

        child_a = make_account(tenant, name='A')
        child_b = make_account(tenant, name='B')
        imp_a = make_stream(make_device(tenant, site, 'CA'), key='ia',
                            billing_role=Stream.BillingRole.GRID_IMPORT)
        imp_b = make_stream(make_device(tenant, site, 'CB'), key='ib',
                            billing_role=Stream.BillingRole.GRID_IMPORT)
        link_meter(child_a, imp_a)
        link_meter(child_b, imp_b)

        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)
        for child in (child_a, child_b):
            assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
            assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)

        add_aggregate(gen, period_start=TS, value=generation)
        add_aggregate(imp_a, period_start=TS, value=import_a)
        add_aggregate(imp_b, period_start=TS, value=import_b)

        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)
        return run, child_a, child_b

    def test_pro_rata_by_grid_import(self):
        # pool 8 (gen 8, no export); imports 6 / 4 → 4.8 / 3.2.
        run, child_a, child_b = self._two_children(generation=8.0, import_a=6.0, import_b=4.0)
        rec_a = SolarAllocationRecord.objects.get(billing_run=run, billing_account=child_a)
        rec_b = SolarAllocationRecord.objects.get(billing_run=run, billing_account=child_b)
        assert rec_a.allocated_kwh == Decimal('4.800000')
        assert rec_b.allocated_kwh == Decimal('3.200000')
        # Exactly the pool, no leakage.
        assert rec_a.allocated_kwh + rec_b.allocated_kwh == Decimal('8.000000')

    def test_allocation_sums_to_pool_exactly_with_awkward_division(self):
        # pool 10, three equal importers of 4 (total 12 ≥ pool) → 10/3 each.
        tenant = make_tenant()
        site = make_site(tenant)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)
        add_aggregate(gen, period_start=TS, value=10.0)

        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)
        children = []
        for i in range(3):
            child = make_account(tenant, name=f'C{i}')
            imp = make_stream(make_device(tenant, site, f'C{i}'), key=f'i{i}',
                              billing_role=Stream.BillingRole.GRID_IMPORT)
            link_meter(child, imp)
            assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
            assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)
            add_aggregate(imp, period_start=TS, value=4.0)
            children.append(child)

        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)

        recs = SolarAllocationRecord.objects.filter(billing_run=run)
        total = sum((r.allocated_kwh for r in recs), Decimal('0'))
        assert total == Decimal('10.000000')  # exact, no rounding leakage
        # Each child gets ~3.333333; one absorbs the +0.000001 remainder.
        values = sorted(r.allocated_kwh for r in recs)
        assert values == [Decimal('3.333333'), Decimal('3.333333'), Decimal('3.333334')]


# ---------------------------------------------------------------------------
# BESS exclusion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBessExclusion:

    def test_bess_discharge_not_counted_in_pool(self):
        tenant = make_tenant()
        site = make_site(tenant)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)
        bess = make_stream(make_device(tenant, site, 'BESS'), key='bd',
                           billing_role=Stream.BillingRole.BESS_DISCHARGE)
        child = make_account(tenant, name='A')
        imp = make_stream(make_device(tenant, site, 'CA'), key='ia',
                          billing_role=Stream.BillingRole.GRID_IMPORT)
        link_meter(child, imp)
        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)
        assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
        assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)

        add_aggregate(gen, period_start=TS, value=10.0)
        add_aggregate(bess, period_start=TS, value=5.0)   # must NOT inflate pool
        add_aggregate(imp, period_start=TS, value=10.0)

        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)

        rec = SolarAllocationRecord.objects.get(billing_run=run, billing_account=child)
        # Pool is generation only (10), not generation + bess_discharge (15).
        assert rec.pool_kwh == Decimal('10.000000')
        assert rec.allocated_kwh == Decimal('10.000000')

    def test_bess_charge_recorded_but_not_netted_from_grid_import(self):
        """BESS charge is recorded for comparison but plays no part in the
        allocation weight — a child's metered grid_import is used as-is, never
        reduced by bess_charge. (Battery economics are charge/discharge-time
        arbitrage, handled separately from solar allocation.)"""
        tenant = make_tenant()
        site = make_site(tenant)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)

        child_a = make_account(tenant, name='A')
        child_b = make_account(tenant, name='B')
        imp_a = make_stream(make_device(tenant, site, 'CA'), key='ia',
                            billing_role=Stream.BillingRole.GRID_IMPORT)
        imp_b = make_stream(make_device(tenant, site, 'CB'), key='ib',
                            billing_role=Stream.BillingRole.GRID_IMPORT)
        # Child A also has a battery that charged 4 kWh this interval — recorded,
        # but it must NOT reduce A's grid_import weight of 6.
        charge_a = make_stream(make_device(tenant, site, 'BESSA'), key='bc',
                               billing_role=Stream.BillingRole.BESS_CHARGE)
        link_meter(child_a, imp_a)
        link_meter(child_b, imp_b)
        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)
        for child in (child_a, child_b):
            assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
            assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)

        add_aggregate(gen, period_start=TS, value=8.0)
        add_aggregate(imp_a, period_start=TS, value=6.0)
        add_aggregate(charge_a, period_start=TS, value=4.0)  # recorded, ignored by allocation
        add_aggregate(imp_b, period_start=TS, value=4.0)

        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)

        # Weights are 6 / 4 (NOT 2 / 4 as if charge were netted out) → 4.8 / 3.2.
        rec_a = SolarAllocationRecord.objects.get(billing_run=run, billing_account=child_a)
        rec_b = SolarAllocationRecord.objects.get(billing_run=run, billing_account=child_b)
        assert rec_a.child_grid_import_kwh == Decimal('6.000000')
        assert rec_a.allocated_kwh == Decimal('4.800000')
        assert rec_b.allocated_kwh == Decimal('3.200000')


# ---------------------------------------------------------------------------
# Mid-cycle onboarding (per-interval window clamping)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMidCycleOnboarding:

    def test_child_activated_mid_period_only_gets_later_intervals(self):
        tenant = make_tenant()
        site = make_site(tenant)
        ts1 = TS
        ts2 = TS + timedelta(minutes=30)
        period_end = TS + timedelta(hours=1)

        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)
        add_aggregate(gen, period_start=ts1, value=10.0)
        add_aggregate(gen, period_start=ts2, value=10.0)

        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)

        child_a = make_account(tenant, name='A')          # active whole period
        child_b = make_account(tenant, name='B', activated=ts2)  # joins at interval 2
        imp_a = make_stream(make_device(tenant, site, 'CA'), key='ia',
                            billing_role=Stream.BillingRole.GRID_IMPORT)
        imp_b = make_stream(make_device(tenant, site, 'CB'), key='ib',
                            billing_role=Stream.BillingRole.GRID_IMPORT)
        link_meter(child_a, imp_a)
        link_meter(child_b, imp_b)
        for child in (child_a, child_b):
            assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
            assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)

        for ts in (ts1, ts2):
            add_aggregate(imp_a, period_start=ts, value=10.0)
            add_aggregate(imp_b, period_start=ts, value=10.0)

        run = make_run(tenant, site, period_start=TS, period_end=period_end)
        engine.run_pipeline(run)

        # Interval 1: only A active → A gets the whole pool (10), B nothing.
        i1 = SolarAllocationRecord.objects.filter(billing_run=run, interval_start=ts1)
        assert i1.count() == 1
        assert i1.get(billing_account=child_a).allocated_kwh == Decimal('10.000000')
        assert not i1.filter(billing_account=child_b).exists()

        # Interval 2: both active, equal import → 5 / 5.
        i2 = SolarAllocationRecord.objects.filter(billing_run=run, interval_start=ts2)
        assert i2.count() == 2
        assert i2.get(billing_account=child_a).allocated_kwh == Decimal('5.000000')
        assert i2.get(billing_account=child_b).allocated_kwh == Decimal('5.000000')


# ---------------------------------------------------------------------------
# Idempotency + missing-tariff failure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIdempotencyAndErrors:

    def _one_child_run(self, *, with_grid_tariff=True):
        tenant = make_tenant()
        site = make_site(tenant)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)
        child = make_account(tenant, name='A')
        imp = make_stream(make_device(tenant, site, 'CA'), key='ia',
                          billing_role=Stream.BillingRole.GRID_IMPORT)
        link_meter(child, imp)
        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
        if with_grid_tariff:
            grid_ds = make_flat_dataset('grid-rate', rate=30.0)
            assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)
        add_aggregate(gen, period_start=TS, value=6.0)
        add_aggregate(imp, period_start=TS, value=8.0)
        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        return run

    def test_rerun_is_idempotent(self):
        run = self._one_child_run()
        engine.run_pipeline(run)
        first = {
            (r.billing_account_id, r.interval_start): r.allocated_kwh
            for r in SolarAllocationRecord.objects.filter(billing_run=run)
        }
        # Re-run the whole pipeline (recompute) — identical end state.
        engine.run_pipeline(run)
        second = {
            (r.billing_account_id, r.interval_start): r.allocated_kwh
            for r in SolarAllocationRecord.objects.filter(billing_run=run)
        }
        assert first == second
        assert SolarAllocationRecord.objects.filter(billing_run=run).count() == 1

    def test_missing_grid_tariff_fails_compute_step(self):
        run = self._one_child_run(with_grid_tariff=False)
        with pytest.raises(engine.StepError) as exc:
            engine.run_pipeline(run)
        assert exc.value.step == BillingRun.Step.COMPUTE_LINE_ITEMS
        assert 'grid tariff' in exc.value.message


# ---------------------------------------------------------------------------
# allocations endpoint + PPA non-regression
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAllocationsEndpointAndPPA:

    def _hier_run(self, tenant):
        site = make_site(tenant)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)
        child = make_account(tenant, name='A')
        imp = make_stream(make_device(tenant, site, 'CA'), key='ia',
                          billing_role=Stream.BillingRole.GRID_IMPORT)
        link_meter(child, imp)
        solar_ds = make_flat_dataset('solar-rate', rate=10.0)
        grid_ds = make_flat_dataset('grid-rate', rate=30.0)
        assign_tariff(child, solar_ds, applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR)
        assign_tariff(child, grid_ds, applies_to_role=Stream.BillingRole.CONSUMPTION)
        add_aggregate(gen, period_start=TS, value=6.0)
        add_aggregate(imp, period_start=TS, value=8.0)
        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)
        return run

    def test_owner_can_read_allocations(self):
        tenant = make_tenant()
        run = self._hier_run(tenant)
        admin = make_user(tenant)
        resp = auth_client(admin).get(f'/api/v1/billing-runs/{run.id}/allocations/')
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]['allocated_kwh'] == '6.000000'
        assert resp.data[0]['pool_kwh'] == '6.000000'

    def test_cross_tenant_allocations_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        run_a = self._hier_run(tenant_a)
        admin_b = make_user(tenant_b)
        resp = auth_client(admin_b).get(f'/api/v1/billing-runs/{run_a.id}/allocations/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_ppa_run_writes_no_allocations(self):
        """A non-hierarchical PPA run skips allocate_solar entirely and bills the
        single-rate path (Sprint 31 behaviour intact)."""
        tenant = make_tenant()
        site = make_site(tenant, hierarchical=False)
        gen = make_stream(make_device(tenant, site, 'GEN'), key='gen',
                          billing_role=Stream.BillingRole.GENERATION)
        host = make_account(tenant, name='Host',
                            account_type=BillingAccount.AccountType.PPA_HOST)
        link_meter(host, gen)
        ds = make_flat_dataset('ppa-gen', rate=20.0)
        assign_tariff(host, ds)  # untagged catch-all → single-rate path
        add_aggregate(gen, period_start=TS, value=5.0)
        run = make_run(tenant, site, period_start=TS, period_end=TS + timedelta(minutes=30))
        engine.run_pipeline(run)

        assert SolarAllocationRecord.objects.filter(billing_run=run).count() == 0
        energy = BillingLineItem.objects.get(billing_run=run, line_kind='energy')
        # Plain single energy line — no leg suffix.
        assert '(solar)' not in energy.period_name and '(grid)' not in energy.period_name
        assert energy.amount_cents == 100  # 5 kWh × 20c

        admin = make_user(tenant)
        resp = auth_client(admin).get(f'/api/v1/billing-runs/{run.id}/allocations/')
        assert resp.status_code == 200
        assert resp.data == []
