"""Sprint 28 — Interval Aggregation Engine + Data Quality Flags tests.

Covers:
  - Period alignment (clock_align, period_end, previous_period_start) for every
    period including month boundaries
  - Per-kind aggregation correctness: sum / mean / min / max / last
  - Quality propagation: worst-input rule, mixed-quality breakdown, gap on
    zero-reading periods
  - Idempotency: rerun produces the same row (no duplicates)
  - Backfill: walks every bucket between aligned endpoints, multi-kind in one pass
  - Beat task: maintains the previous bucket for active streams
  - HTTP: aggregate read endpoint with pagination, cross-tenant 404, period
    validation; backfill endpoint requires Tenant Admin
  - Derived streams inherit worst-input quality through the upsert path

Ref: SPEC.md § Feature: Interval Aggregation Engine; § Feature: Data Quality
Flags; ROADMAP Sprint 28
"""
from datetime import datetime, timedelta, timezone

import pytest
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.readings.aggregates import (
    clock_align,
    compute_aggregate,
    period_end,
    previous_period_start,
)
from apps.readings.aggregate_tasks import backfill_aggregates, maintain_interval_aggregates
from apps.readings.models import (
    DerivedStream,
    IntervalAggregate,
    Stream,
    StreamReading,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tenant(name='S28 tenant'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email, tenant, role='admin'):
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_site(tenant):
    return Site.objects.create(tenant=tenant, name='Site')


def make_device(tenant, site, serial='S28-001'):
    dt, _ = DeviceType.objects.get_or_create(
        slug='s28-dt',
        defaults={'name': 'S28 device', 'connection_type': 'mqtt', 'is_push': True},
    )
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Device', serial_number=serial, status=Device.Status.ACTIVE,
    )


def make_stream(device, key='kw', kind='mean'):
    return Stream.objects.create(
        device=device, key=key, data_type=Stream.DataType.NUMERIC,
        aggregation_kind_default=kind,
    )


def _ts(hour=10, minute=0, second=0):
    return datetime(2026, 5, 28, hour, minute, second, tzinfo=UTC)


def auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# ---------------------------------------------------------------------------
# Period alignment
# ---------------------------------------------------------------------------


def test_clock_align_5min_floors_to_5min_boundary():
    assert clock_align(_ts(10, 12, 34), '5min') == _ts(10, 10, 0)
    assert clock_align(_ts(10, 5, 0), '5min') == _ts(10, 5, 0)
    assert clock_align(_ts(10, 4, 59), '5min') == _ts(10, 0, 0)


def test_clock_align_30min_and_hour():
    assert clock_align(_ts(10, 45, 0), '30min') == _ts(10, 30, 0)
    assert clock_align(_ts(10, 12, 0), '30min') == _ts(10, 0, 0)
    assert clock_align(_ts(10, 59, 59), '1h') == _ts(10, 0, 0)


def test_clock_align_day_and_month():
    assert clock_align(_ts(13, 22, 11), '1d') == _ts(0, 0, 0)
    aligned = clock_align(datetime(2026, 5, 28, 13, 0, tzinfo=UTC), '1mo')
    assert aligned == datetime(2026, 5, 1, 0, 0, tzinfo=UTC)


def test_period_end_5min():
    assert period_end(_ts(10, 5), '5min') == _ts(10, 10)


def test_period_end_month_wraps_year():
    end_dec = period_end(datetime(2026, 12, 1, tzinfo=UTC), '1mo')
    assert end_dec == datetime(2027, 1, 1, tzinfo=UTC)


def test_previous_period_start_is_completed_bucket():
    # At 10:12 the in-progress 5-min bucket starts at 10:10; the previous
    # (completed) bucket starts at 10:05.
    assert previous_period_start(_ts(10, 12), '5min') == _ts(10, 5)


# ---------------------------------------------------------------------------
# Aggregation correctness — per kind
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sum_aggregates_values_in_bucket():
    tenant = make_tenant()
    device = make_device(tenant, make_site(tenant))
    stream = make_stream(device, kind='sum')

    bucket = _ts(10, 5)
    for v, sec in [(2.0, 0), (3.0, 60), (5.0, 240)]:
        StreamReading.objects.create(stream=stream, value=v, timestamp=bucket + timedelta(seconds=sec))

    agg = compute_aggregate(stream, '5min', bucket, 'sum')
    assert float(agg.value) == 10.0
    assert agg.count == 3
    assert agg.quality == 'measured'


@pytest.mark.django_db
def test_mean_aggregates_values_in_bucket():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)), kind='mean')
    bucket = _ts(10, 5)
    for v, sec in [(10.0, 0), (20.0, 60), (30.0, 120)]:
        StreamReading.objects.create(stream=stream, value=v, timestamp=bucket + timedelta(seconds=sec))

    agg = compute_aggregate(stream, '5min', bucket, 'mean')
    assert float(agg.value) == 20.0


@pytest.mark.django_db
def test_min_max_aggregates():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)))
    bucket = _ts(10, 5)
    for v, sec in [(5.0, 0), (50.0, 30), (25.0, 60)]:
        StreamReading.objects.create(stream=stream, value=v, timestamp=bucket + timedelta(seconds=sec))

    assert float(compute_aggregate(stream, '5min', bucket, 'min').value) == 5.0
    assert float(compute_aggregate(stream, '5min', bucket, 'max').value) == 50.0


@pytest.mark.django_db
def test_last_aggregates_to_most_recent_in_bucket():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)), kind='last')
    bucket = _ts(10, 5)
    StreamReading.objects.create(stream=stream, value=1.0, timestamp=bucket + timedelta(seconds=0))
    StreamReading.objects.create(stream=stream, value=99.0, timestamp=bucket + timedelta(seconds=240))
    StreamReading.objects.create(stream=stream, value=5.0, timestamp=bucket + timedelta(seconds=120))

    agg = compute_aggregate(stream, '5min', bucket, 'last')
    assert float(agg.value) == 99.0


# ---------------------------------------------------------------------------
# Quality propagation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_zero_reading_period_produces_gap_aggregate():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)))
    bucket = _ts(10, 5)

    agg = compute_aggregate(stream, '5min', bucket, 'mean')
    assert agg.count == 0
    assert agg.value is None
    assert agg.quality == 'gap'
    assert agg.quality_breakdown == {}


@pytest.mark.django_db
def test_worst_input_quality_rolls_up_to_aggregate():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)))
    bucket = _ts(10, 5)
    StreamReading.objects.create(stream=stream, value=1.0, timestamp=bucket, quality='measured')
    StreamReading.objects.create(stream=stream, value=2.0, timestamp=bucket + timedelta(seconds=60), quality='estimated')
    StreamReading.objects.create(stream=stream, value=3.0, timestamp=bucket + timedelta(seconds=120), quality='substituted')

    agg = compute_aggregate(stream, '5min', bucket, 'mean')
    assert agg.quality == 'substituted'
    assert agg.quality_breakdown == {'measured': 1, 'estimated': 1, 'substituted': 1}


@pytest.mark.django_db
def test_lgc_filter_by_measured_only():
    """An LGC-claim filter: quality == 'measured' must reject any aggregate
    that mixed in non-measured input."""
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)), kind='sum')
    bucket = _ts(10, 5)
    StreamReading.objects.create(stream=stream, value=1.0, timestamp=bucket, quality='measured')
    StreamReading.objects.create(stream=stream, value=2.0, timestamp=bucket + timedelta(seconds=60), quality='estimated')
    compute_aggregate(stream, '5min', bucket, 'sum')

    measured_only = IntervalAggregate.objects.filter(
        stream=stream, period='5min', quality='measured',
    )
    assert not measured_only.exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compute_aggregate_is_idempotent_on_rerun():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)), kind='sum')
    bucket = _ts(10, 5)
    StreamReading.objects.create(stream=stream, value=4.0, timestamp=bucket)

    compute_aggregate(stream, '5min', bucket, 'sum')
    compute_aggregate(stream, '5min', bucket, 'sum')
    compute_aggregate(stream, '5min', bucket, 'sum')

    assert IntervalAggregate.objects.filter(stream=stream, period='5min').count() == 1


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_walks_all_buckets_in_range():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)), kind='sum')

    # Three readings across three 5-min buckets.
    for offset in (0, 5, 10):
        StreamReading.objects.create(
            stream=stream, value=float(offset),
            timestamp=_ts(10, offset),
        )

    written = backfill_aggregates(
        stream.pk, '5min',
        _ts(10, 0).isoformat(),
        _ts(10, 15).isoformat(),
    )

    # Three buckets (10:00, 10:05, 10:10) × 1 kind = 3 writes.
    assert written == 3
    aggs = list(IntervalAggregate.objects.filter(stream=stream, period='5min').order_by('period_start'))
    assert [float(a.value) for a in aggs] == [0.0, 5.0, 10.0]


@pytest.mark.django_db
def test_backfill_multi_kind_in_one_pass():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)), kind='mean')
    bucket = _ts(10, 5)
    for v, sec in [(2.0, 0), (4.0, 60), (6.0, 120)]:
        StreamReading.objects.create(stream=stream, value=v, timestamp=bucket + timedelta(seconds=sec))

    backfill_aggregates(
        stream.pk, '5min',
        bucket.isoformat(),
        period_end(bucket, '5min').isoformat(),
        ['sum', 'mean', 'max'],
    )

    aggs = {
        a.aggregation_kind: float(a.value)
        for a in IntervalAggregate.objects.filter(stream=stream, period='5min')
    }
    assert aggs == {'sum': 12.0, 'mean': 4.0, 'max': 6.0}


@pytest.mark.django_db
def test_backfill_rejects_invalid_range():
    tenant = make_tenant()
    stream = make_stream(make_device(tenant, make_site(tenant)))
    with pytest.raises(ValueError):
        backfill_aggregates(stream.pk, '5min', _ts(10, 10).isoformat(), _ts(10, 0).isoformat())


@pytest.mark.django_db
def test_backfill_no_op_for_missing_stream():
    assert backfill_aggregates(999_999, '5min', _ts(10, 0).isoformat(), _ts(11, 0).isoformat()) == 0


# ---------------------------------------------------------------------------
# Beat task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_maintain_writes_previous_bucket_for_active_streams():
    from django.utils import timezone as dj_tz
    tenant = make_tenant()
    device = make_device(tenant, make_site(tenant))
    stream = make_stream(device, kind='sum')

    # Seed a reading in the previous 5-min bucket so the aggregate has work to do.
    now = dj_tz.now()
    previous_5min = previous_period_start(now, '5min')
    StreamReading.objects.create(stream=stream, value=7.5, timestamp=previous_5min)

    maintain_interval_aggregates()

    agg = IntervalAggregate.objects.filter(
        stream=stream, period='5min', period_start=previous_5min, aggregation_kind='sum',
    ).first()
    assert agg is not None
    assert float(agg.value) == 7.5


# ---------------------------------------------------------------------------
# Derived stream quality inheritance (Sprint 27 + Sprint 28 wiring)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_derived_delta_inherits_gap_quality_from_source():
    """A derived stream whose source has a `gap` input inherits `gap`."""
    from apps.readings.derived_dispatch import evaluate_derived_stream
    tenant = make_tenant()
    device = make_device(tenant, make_site(tenant))
    source = make_stream(device, key='cum')
    output = Stream.objects.create(
        device=device, key='delta',
        data_type=Stream.DataType.NUMERIC,
        stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])

    StreamReading.objects.create(stream=source, value=10.0, timestamp=_ts(10, 0), quality='measured')
    StreamReading.objects.create(stream=source, value=15.0, timestamp=_ts(10, 5), quality='gap')

    evaluate_derived_stream(derived.pk, source.pk)

    out = StreamReading.objects.filter(stream=output).first()
    assert out is not None
    assert out.quality == 'gap'


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_aggregates_endpoint_requires_period():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('a@s28.test', tenant)
    stream = make_stream(make_device(tenant, site))

    resp = auth(admin).get(f'/api/v1/streams/{stream.pk}/aggregates/')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_aggregates_endpoint_returns_paginated_rows():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('p@s28.test', tenant)
    stream = make_stream(make_device(tenant, site), kind='sum')

    # 5 buckets back-to-back with one reading each.
    for i in range(5):
        bucket = _ts(10, 0) + timedelta(minutes=i * 5)
        StreamReading.objects.create(stream=stream, value=float(i), timestamp=bucket)
        compute_aggregate(stream, '5min', bucket, 'sum')

    resp = auth(admin).get(
        f'/api/v1/streams/{stream.pk}/aggregates/',
        {'period': '5min', 'limit': '2'},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body['results']) == 2
    assert body['next_cursor'] is not None


@pytest.mark.django_db
def test_aggregates_endpoint_cross_tenant_returns_404():
    tenant_a = make_tenant('T-A')
    tenant_b = make_tenant('T-B')
    stream_a = make_stream(make_device(tenant_a, make_site(tenant_a)))
    admin_b = make_user('b@s28.test', tenant_b)

    resp = auth(admin_b).get(
        f'/api/v1/streams/{stream_a.pk}/aggregates/',
        {'period': '5min'},
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_aggregates_backfill_requires_tenant_admin():
    tenant = make_tenant()
    site = make_site(tenant)
    operator = make_user('op@s28.test', tenant, role='operator')
    stream = make_stream(make_device(tenant, site))

    resp = auth(operator).post(
        f'/api/v1/streams/{stream.pk}/aggregates/backfill/',
        {'period': '5min', 'date_from': _ts(10, 0).isoformat(), 'date_to': _ts(10, 30).isoformat()},
        format='json',
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_aggregates_backfill_admin_succeeds():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('a@s28-bf.test', tenant)
    stream = make_stream(make_device(tenant, site), kind='sum')
    bucket = _ts(10, 5)
    StreamReading.objects.create(stream=stream, value=3.0, timestamp=bucket)

    resp = auth(admin).post(
        f'/api/v1/streams/{stream.pk}/aggregates/backfill/',
        {'period': '5min', 'date_from': _ts(10, 0).isoformat(), 'date_to': _ts(10, 10).isoformat()},
        format='json',
    )
    assert resp.status_code == 202
