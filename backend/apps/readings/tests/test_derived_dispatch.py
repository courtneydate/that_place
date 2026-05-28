"""Sprint 27 integration tests — derived-stream dispatch, CRUD, and backfill.

Pure-function evaluators are covered by ``test_derived_evaluators.py``. This
file covers the ORM glue, signal-driven index maintenance, idempotency under
the upsert path, and the HTTP API.

Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
"""
from datetime import datetime, timedelta, timezone

import pytest
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.readings.derived_dispatch import (
    dispatch_stream_derived_evaluation,
    evaluate_derived_stream,
    get_or_create_site_composite_device,
)
from apps.readings.models import (
    DerivedStream,
    DerivedStreamSourceIndex,
    Stream,
    StreamReading,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_tenant(name='S27 tenant'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email, tenant, role='admin'):
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_site(tenant, name='Default site'):
    return Site.objects.create(tenant=tenant, name=name)


def make_device(tenant, site, serial, name=None):
    dt, _ = DeviceType.objects.get_or_create(
        slug='s27-mqtt',
        defaults={
            'name': 'Sprint 27 device',
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 60,
            'command_ack_timeout_seconds': 30,
        },
    )
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name=name or f'Device {serial}',
        serial_number=serial,
        status=Device.Status.ACTIVE,
    )


def make_stream(device, key='counter'):
    return Stream.objects.create(
        device=device, key=key, label=key,
        data_type=Stream.DataType.NUMERIC,
    )


def _ts(minute, second=0):
    return datetime(2026, 5, 28, 10, minute, second, tzinfo=UTC)


def auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# ---------------------------------------------------------------------------
# Index maintenance via m2m_changed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_source_index_is_built_on_m2m_set():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-IDX')
    source = make_stream(device, 'cumulative')
    output = Stream.objects.create(
        device=device, key='interval', label='Interval',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])

    assert DerivedStreamSourceIndex.objects.filter(
        derived_stream=derived, source_stream=source,
    ).exists()


@pytest.mark.django_db
def test_source_index_drops_old_entries_on_set():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-IDX2')
    source_a = make_stream(device, 'a')
    source_b = make_stream(device, 'b')
    output = Stream.objects.create(
        device=device, key='out',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='scale', params={'factor': 2.0})
    derived.source_streams.set([source_a])
    derived.source_streams.set([source_b])

    assert not DerivedStreamSourceIndex.objects.filter(source_stream=source_a).exists()
    assert DerivedStreamSourceIndex.objects.filter(source_stream=source_b).exists()


@pytest.mark.django_db
def test_source_index_dropped_on_derived_stream_delete():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-IDX3')
    source = make_stream(device, 'cum')
    output = Stream.objects.create(
        device=device, key='out',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])
    derived_pk = derived.pk

    derived.delete()

    assert not DerivedStreamSourceIndex.objects.filter(derived_stream_id=derived_pk).exists()


# ---------------------------------------------------------------------------
# Dispatch path: source reading → derived StreamReading
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delta_dispatch_writes_interval_reading():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-D1')
    source = make_stream(device, 'cumulative_kwh')
    output = Stream.objects.create(
        device=device, key='interval_kwh',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])

    StreamReading.objects.create(stream=source, value=100.0, timestamp=_ts(0))
    StreamReading.objects.create(stream=source, value=150.0, timestamp=_ts(5))

    # Trigger evaluation as the latest-source dispatch would.
    evaluate_derived_stream(derived.pk, source.pk)

    derived_readings = list(StreamReading.objects.filter(stream=output).order_by('timestamp'))
    assert len(derived_readings) == 1
    assert float(derived_readings[0].value) == 50.0
    assert derived_readings[0].timestamp == _ts(5)


@pytest.mark.django_db
def test_delta_dispatch_is_idempotent_on_rerun():
    """Same inputs evaluated twice produce the same single output reading."""
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-D2')
    source = make_stream(device, 'cum')
    output = Stream.objects.create(
        device=device, key='int',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])

    StreamReading.objects.create(stream=source, value=10.0, timestamp=_ts(0))
    StreamReading.objects.create(stream=source, value=15.0, timestamp=_ts(5))

    evaluate_derived_stream(derived.pk, source.pk)
    evaluate_derived_stream(derived.pk, source.pk)
    evaluate_derived_stream(derived.pk, source.pk)

    assert StreamReading.objects.filter(stream=output).count() == 1


@pytest.mark.django_db
def test_scale_dispatch_writes_scaled_reading():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-SCALE')
    source = make_stream(device, 'raw')
    output = Stream.objects.create(
        device=device, key='scaled',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(
        stream=output, formula='scale', params={'factor': 2.5},
    )
    derived.source_streams.set([source])

    StreamReading.objects.create(stream=source, value=4.0, timestamp=_ts(10))

    evaluate_derived_stream(derived.pk, source.pk)

    out_reading = StreamReading.objects.filter(stream=output).get()
    assert float(out_reading.value) == 10.0


@pytest.mark.django_db
def test_sum_dispatch_pairs_cross_device_in_same_minute():
    tenant = make_tenant()
    site = make_site(tenant)
    device_a = make_device(tenant, site, 'S27-SUM-A')
    device_b = make_device(tenant, site, 'S27-SUM-B')
    source_a = make_stream(device_a, 'grid_import')
    source_b = make_stream(device_b, 'battery_discharge')

    composite = get_or_create_site_composite_device(site)
    output = Stream.objects.create(
        device=composite, key='consumption',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='sum')
    derived.source_streams.set([source_a, source_b])

    # Readings 18 seconds apart — same minute bucket.
    StreamReading.objects.create(stream=source_a, value=100.0, timestamp=_ts(5, 12))
    StreamReading.objects.create(stream=source_b, value=50.0, timestamp=_ts(5, 30))

    evaluate_derived_stream(derived.pk, source_b.pk)

    out_readings = list(StreamReading.objects.filter(stream=output))
    assert len(out_readings) == 1
    assert float(out_readings[0].value) == 150.0
    assert out_readings[0].timestamp == _ts(5)  # bucket boundary


@pytest.mark.django_db
def test_difference_dispatch_a_minus_b():
    tenant = make_tenant()
    site = make_site(tenant)
    device_a = make_device(tenant, site, 'S27-DIFF-A')
    device_b = make_device(tenant, site, 'S27-DIFF-B')
    source_a = make_stream(device_a, 'gen')
    source_b = make_stream(device_b, 'export')

    composite = get_or_create_site_composite_device(site)
    output = Stream.objects.create(
        device=composite, key='consumption_from_solar',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(
        stream=output, formula='difference',
        params={'source_a_id': source_a.pk, 'source_b_id': source_b.pk},
    )
    derived.source_streams.set([source_a, source_b])

    StreamReading.objects.create(stream=source_a, value=200.0, timestamp=_ts(5, 0))
    StreamReading.objects.create(stream=source_b, value=80.0, timestamp=_ts(5, 30))

    evaluate_derived_stream(derived.pk, source_b.pk)

    out_reading = StreamReading.objects.filter(stream=output).get()
    assert float(out_reading.value) == 120.0


@pytest.mark.django_db
def test_window_min_dispatch():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-WMIN')
    source = make_stream(device, 'temp')
    output = Stream.objects.create(
        device=device, key='temp_min_5m',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(
        stream=output, formula='window_min', params={'window_minutes': 5},
    )
    derived.source_streams.set([source])

    StreamReading.objects.create(stream=source, value=30.0, timestamp=_ts(0))
    StreamReading.objects.create(stream=source, value=22.0, timestamp=_ts(2))
    StreamReading.objects.create(stream=source, value=25.0, timestamp=_ts(4))

    evaluate_derived_stream(derived.pk, source.pk)

    out_reading = StreamReading.objects.filter(stream=output).order_by('-timestamp').first()
    assert out_reading is not None
    assert float(out_reading.value) == 22.0


@pytest.mark.django_db
def test_dispatch_stream_skips_inactive_derived():
    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-INACTIVE')
    source = make_stream(device, 'cum')
    output = Stream.objects.create(
        device=device, key='int',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta', is_active=False)
    derived.source_streams.set([source])

    StreamReading.objects.create(stream=source, value=10.0, timestamp=_ts(0))
    StreamReading.objects.create(stream=source, value=15.0, timestamp=_ts(5))

    dispatch_stream_derived_evaluation(source.pk)

    assert StreamReading.objects.filter(stream=output).count() == 0


# ---------------------------------------------------------------------------
# Site composite Device auto-create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_site_composite_device_is_idempotent():
    tenant = make_tenant()
    site = make_site(tenant, 'Composite test site')

    first = get_or_create_site_composite_device(site)
    second = get_or_create_site_composite_device(site)

    assert first.pk == second.pk
    assert first.is_virtual is True
    assert first.device_type.slug == 'site-composite'
    assert first.serial_number == f'SITE-COMPOSITE-{site.pk}'


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_recomputes_derived_history_idempotently():
    from apps.readings.derived_dispatch import backfill_derived_stream

    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-BF')
    source = make_stream(device, 'cum')
    output = Stream.objects.create(
        device=device, key='int',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])

    # Source history — 4 cumulative readings 5 minutes apart.
    for i, value in enumerate([100.0, 110.0, 125.0, 140.0]):
        StreamReading.objects.create(stream=source, value=value, timestamp=_ts(i * 5))

    backfill_derived_stream(derived.pk, _ts(0).isoformat(), _ts(20).isoformat())

    # Three deltas expected: at minutes 5, 10, 15.
    derived_readings = list(StreamReading.objects.filter(stream=output).order_by('timestamp'))
    assert [float(r.value) for r in derived_readings] == [10.0, 15.0, 15.0]

    # Rerun — same end state, no duplicates.
    backfill_derived_stream(derived.pk, _ts(0).isoformat(), _ts(20).isoformat())
    derived_readings = list(StreamReading.objects.filter(stream=output).order_by('timestamp'))
    assert [float(r.value) for r in derived_readings] == [10.0, 15.0, 15.0]


@pytest.mark.django_db
def test_backfill_does_not_touch_readings_outside_range():
    from apps.readings.derived_dispatch import backfill_derived_stream

    tenant = make_tenant()
    site = make_site(tenant)
    device = make_device(tenant, site, 'S27-BF2')
    source = make_stream(device, 'cum')
    output = Stream.objects.create(
        device=device, key='int',
        data_type=Stream.DataType.NUMERIC, stream_type=Stream.StreamType.DERIVED,
    )
    derived = DerivedStream.objects.create(stream=output, formula='delta')
    derived.source_streams.set([source])

    # Pre-existing derived reading outside the window — should survive.
    StreamReading.objects.create(stream=output, value=99.0, timestamp=_ts(30))

    for i, value in enumerate([100.0, 110.0, 120.0]):
        StreamReading.objects.create(stream=source, value=value, timestamp=_ts(i * 5))

    backfill_derived_stream(derived.pk, _ts(0).isoformat(), _ts(10).isoformat())

    survivor = StreamReading.objects.get(stream=output, timestamp=_ts(30))
    assert float(survivor.value) == 99.0


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_derived_stream_via_api_single_source():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('admin@s27.test', tenant)
    device = make_device(tenant, site, 'S27-API1')
    source = make_stream(device, 'cum')

    resp = auth(admin).post('/api/v1/derived-streams/', {
        'key': 'interval_kwh',
        'label': 'Interval kWh',
        'unit': 'kWh',
        'formula': 'delta',
        'source_stream_ids': [source.pk],
    }, format='json')

    assert resp.status_code == 201, resp.content
    data = resp.json()
    assert data['stream_key'] == 'interval_kwh'
    assert data['stream_device_id'] == device.pk  # single-device → hosted on source device


@pytest.mark.django_db
def test_create_derived_stream_cross_device_uses_site_composite():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('cd@s27.test', tenant)
    device_a = make_device(tenant, site, 'S27-CD-A')
    device_b = make_device(tenant, site, 'S27-CD-B')
    source_a = make_stream(device_a, 'gen')
    source_b = make_stream(device_b, 'export')

    resp = auth(admin).post('/api/v1/derived-streams/', {
        'key': 'consumption_from_solar',
        'unit': 'kWh',
        'formula': 'difference',
        'source_stream_ids': [source_a.pk, source_b.pk],
    }, format='json')

    assert resp.status_code == 201, resp.content
    data = resp.json()
    host = Device.objects.get(pk=data['stream_device_id'])
    assert host.is_virtual is True
    assert host.device_type.slug == 'site-composite'
    assert host.site_id == site.pk


@pytest.mark.django_db
def test_create_derived_stream_validates_source_count():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('val@s27.test', tenant)
    device = make_device(tenant, site, 'S27-VAL')
    source = make_stream(device, 's')
    # `delta` requires exactly 1 source — sending 2 should 400.
    other_device = make_device(tenant, site, 'S27-VAL-2')
    source2 = make_stream(other_device, 's2')

    resp = auth(admin).post('/api/v1/derived-streams/', {
        'key': 'd',
        'formula': 'delta',
        'source_stream_ids': [source.pk, source2.pk],
    }, format='json')

    assert resp.status_code == 400


@pytest.mark.django_db
def test_operator_cannot_create_derived_stream():
    tenant = make_tenant()
    site = make_site(tenant)
    operator = make_user('op@s27.test', tenant, role='operator')
    device = make_device(tenant, site, 'S27-OP')
    source = make_stream(device, 'cum')

    resp = auth(operator).post('/api/v1/derived-streams/', {
        'key': 'd', 'formula': 'delta', 'source_stream_ids': [source.pk],
    }, format='json')
    assert resp.status_code == 403


@pytest.mark.django_db
def test_viewer_can_list_derived_streams():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('a@s27-list.test', tenant)
    viewer = make_user('v@s27-list.test', tenant, role='viewer')
    device = make_device(tenant, site, 'S27-LST')
    source = make_stream(device, 's')

    auth(admin).post('/api/v1/derived-streams/', {
        'key': 'd', 'formula': 'delta', 'source_stream_ids': [source.pk],
    }, format='json')

    resp = auth(viewer).get('/api/v1/derived-streams/')
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.django_db
def test_cross_tenant_derived_stream_isolation():
    tenant_a = make_tenant('S27 Tenant A')
    tenant_b = make_tenant('S27 Tenant B')
    site_a = make_site(tenant_a)
    site_b = make_site(tenant_b)
    admin_a = make_user('aa@s27.test', tenant_a)
    admin_b = make_user('bb@s27.test', tenant_b)
    device_a = make_device(tenant_a, site_a, 'S27-CT-A')
    source_a = make_stream(device_a, 's')

    resp = auth(admin_a).post('/api/v1/derived-streams/', {
        'key': 'd', 'formula': 'delta', 'source_stream_ids': [source_a.pk],
    }, format='json')
    assert resp.status_code == 201
    derived_id = resp.json()['id']

    # Tenant B sees nothing on list.
    resp = auth(admin_b).get('/api/v1/derived-streams/')
    assert resp.status_code == 200 and resp.json() == []

    # Tenant B 404s on direct fetch.
    resp = auth(admin_b).get(f'/api/v1/derived-streams/{derived_id}/')
    assert resp.status_code == 404

    # Tenant B cannot reference Tenant A's source stream in their own tenant.
    device_b = make_device(tenant_b, site_b, 'S27-CT-B')
    source_b = make_stream(device_b, 's')
    resp = auth(admin_b).post('/api/v1/derived-streams/', {
        'key': 'd', 'formula': 'sum',
        'source_stream_ids': [source_a.pk, source_b.pk],
    }, format='json')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_backfill_endpoint_dispatches_task():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('bf@s27.test', tenant)
    device = make_device(tenant, site, 'S27-BFEP')
    source = make_stream(device, 'cum')

    create_resp = auth(admin).post('/api/v1/derived-streams/', {
        'key': 'd', 'formula': 'delta', 'source_stream_ids': [source.pk],
    }, format='json')
    derived_id = create_resp.json()['id']

    # Seed source history so the backfill has work to do.
    StreamReading.objects.create(stream=source, value=100.0, timestamp=_ts(0))
    StreamReading.objects.create(stream=source, value=120.0, timestamp=_ts(5))

    resp = auth(admin).post(
        f'/api/v1/derived-streams/{derived_id}/backfill/',
        {'date_from': _ts(0).isoformat(), 'date_to': _ts(10).isoformat()},
        format='json',
    )
    assert resp.status_code == 202

    # Eager mode + on_commit interaction: invoke the underlying task directly
    # to verify behaviour, then assert the side effect.
    from apps.readings.derived_dispatch import backfill_derived_stream
    backfill_derived_stream(derived_id, _ts(0).isoformat(), _ts(10).isoformat())

    output = Stream.objects.get(stream_type=Stream.StreamType.DERIVED, device=device)
    derived_readings = list(StreamReading.objects.filter(stream=output))
    assert len(derived_readings) == 1
    assert float(derived_readings[0].value) == 20.0


@pytest.mark.django_db
def test_destroy_derived_stream_deletes_output_stream():
    tenant = make_tenant()
    site = make_site(tenant)
    admin = make_user('del@s27.test', tenant)
    device = make_device(tenant, site, 'S27-DEL')
    source = make_stream(device, 's')

    create_resp = auth(admin).post('/api/v1/derived-streams/', {
        'key': 'd', 'formula': 'delta', 'source_stream_ids': [source.pk],
    }, format='json')
    derived_id = create_resp.json()['id']
    output_id = create_resp.json()['stream_id']

    resp = auth(admin).delete(f'/api/v1/derived-streams/{derived_id}/')
    assert resp.status_code == 204
    assert not DerivedStream.objects.filter(pk=derived_id).exists()
    assert not Stream.objects.filter(pk=output_id).exists()
