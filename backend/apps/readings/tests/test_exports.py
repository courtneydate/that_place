"""Tests for Sprint 22: CSV Data Export.

Covers:
- POST /api/v1/exports/stream/ — streaming CSV download
- GET  /api/v1/exports/        — export history (Admin only)

Ref: SPEC.md § Feature: Data Export (CSV)
"""
import csv
import io
from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import DataExport, Stream, StreamReading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_device(tenant, serial='DEV-001', site=None):
    dt = DeviceType.objects.get_or_create(
        slug='scout',
        defaults=dict(
            name='Scout', connection_type='mqtt', is_push=True,
            stream_type_definitions=[], commands=[],
        ),
    )[0]
    if site is None:
        site = Site.objects.create(tenant=tenant, name='Main Site')
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Test Device', serial_number=serial,
        status=Device.Status.ACTIVE, topic_format='that_place_v1',
    )


def make_stream(device, key='temp', label='Temperature', unit='°C'):
    return Stream.objects.create(device=device, key=key, label=label, unit=unit)


def make_reading(stream, value=25.0, offset_seconds=0):
    ts = timezone.now() - timedelta(seconds=offset_seconds)
    return StreamReading.objects.create(stream=stream, value=value, timestamp=ts)


def make_user(tenant, role=TenantUser.Role.ADMIN, email=None):
    email = email or f'{role}_{tenant.slug}@test.com'
    user = User.objects.create_user(email=email, password='pass')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def parse_csv(content: bytes) -> list[dict]:
    """Parse raw CSV bytes into a list of row dicts."""
    text = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def export_payload(stream_ids, date_from=None, date_to=None):
    now = timezone.now()
    return {
        'stream_ids': stream_ids,
        'date_from': (date_from or (now - timedelta(hours=1))).isoformat(),
        'date_to': (date_to or now).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/v1/exports/stream/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_csv_format():
    """Exported CSV has correct headers and one row per reading."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    reading = make_reading(stream, value=22.5)
    user = make_user(tenant)

    payload = export_payload(
        [stream.pk],
        date_from=reading.timestamp - timedelta(seconds=1),
        date_to=reading.timestamp + timedelta(seconds=1),
    )
    response = auth_client(user).post('/api/v1/exports/stream/', payload, format='json')

    assert response.status_code == status.HTTP_200_OK
    assert 'text/csv' in response['Content-Type']

    rows = parse_csv(b''.join(response.streaming_content))
    assert len(rows) == 1
    row = rows[0]
    assert row['site_name'] == 'Main Site'
    assert row['device_name'] == device.name
    assert row['device_id'] == str(device.pk)
    assert row['device_serial'] == device.serial_number
    assert row['stream_label'] == stream.label
    assert row['unit'] == stream.unit
    assert float(row['value']) == 22.5


@pytest.mark.django_db
def test_export_multi_stream():
    """Multi-stream export includes readings from all selected streams."""
    tenant = make_tenant()
    device = make_device(tenant)
    s1 = make_stream(device, key='temp', label='Temp')
    s2 = make_stream(device, key='humidity', label='Humidity', unit='%')
    r1 = make_reading(s1, value=20.0)
    r2 = make_reading(s2, value=65.0)

    user = make_user(tenant)
    earliest = min(r1.timestamp, r2.timestamp)
    latest = max(r1.timestamp, r2.timestamp)
    payload = export_payload(
        [s1.pk, s2.pk],
        date_from=earliest - timedelta(seconds=1),
        date_to=latest + timedelta(seconds=1),
    )
    response = auth_client(user).post('/api/v1/exports/stream/', payload, format='json')

    assert response.status_code == status.HTTP_200_OK
    rows = parse_csv(b''.join(response.streaming_content))
    assert len(rows) == 2
    labels = {r['stream_label'] for r in rows}
    assert labels == {'Temp', 'Humidity'}


@pytest.mark.django_db
def test_export_date_to_is_inclusive():
    """Readings at exactly date_to are included; readings before date_from are excluded."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    now = timezone.now()
    inside = StreamReading.objects.create(stream=stream, value=1, timestamp=now)
    before = StreamReading.objects.create(stream=stream, value=2, timestamp=now - timedelta(hours=2))

    user = make_user(tenant)
    payload = export_payload(
        [stream.pk],
        date_from=now - timedelta(hours=1),
        date_to=inside.timestamp,
    )
    response = auth_client(user).post('/api/v1/exports/stream/', payload, format='json')
    rows = parse_csv(b''.join(response.streaming_content))

    timestamps = [r['timestamp'] for r in rows]
    assert inside.timestamp.isoformat() in timestamps
    assert before.timestamp.isoformat() not in timestamps


@pytest.mark.django_db
def test_export_logs_dataexport_record():
    """A DataExport record is written before streaming begins."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    user = make_user(tenant)

    assert DataExport.objects.count() == 0
    payload = export_payload([stream.pk])
    response = auth_client(user).post('/api/v1/exports/stream/', payload, format='json')

    # Consume the stream so the view fully executes
    b''.join(response.streaming_content)

    assert DataExport.objects.count() == 1
    log = DataExport.objects.first()
    assert log.tenant == tenant
    assert log.exported_by == user
    assert stream.pk in log.stream_ids


@pytest.mark.django_db
def test_export_view_only_blocked():
    """View-Only users cannot export data (403)."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    viewer = make_user(tenant, role=TenantUser.Role.VIEWER, email='viewer@test.com')

    payload = export_payload([stream.pk])
    response = auth_client(viewer).post('/api/v1/exports/stream/', payload, format='json')
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_export_cross_tenant_stream_rejected():
    """Streams from another tenant cannot be included in an export."""
    tenant_a = make_tenant('TenantA')
    tenant_b = make_tenant('TenantB')
    device_b = make_device(tenant_b, serial='B-001')
    stream_b = make_stream(device_b)
    user_a = make_user(tenant_a)

    payload = export_payload([stream_b.pk])
    response = auth_client(user_a).post('/api/v1/exports/stream/', payload, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_export_date_from_must_be_before_date_to():
    """date_from >= date_to returns 400."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    user = make_user(tenant)

    now = timezone.now()
    payload = {
        'stream_ids': [stream.pk],
        'date_from': now.isoformat(),
        'date_to': (now - timedelta(hours=1)).isoformat(),
    }
    response = auth_client(user).post('/api/v1/exports/stream/', payload, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_export_operator_can_export():
    """Operators (not just Admins) can export data."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    operator = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@test.com')

    payload = export_payload([stream.pk])
    response = auth_client(operator).post('/api/v1/exports/stream/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_export_empty_result_returns_headers_only():
    """An export with no matching readings returns only the CSV header row."""
    tenant = make_tenant()
    device = make_device(tenant)
    stream = make_stream(device)
    user = make_user(tenant)

    now = timezone.now()
    payload = export_payload(
        [stream.pk],
        date_from=now - timedelta(seconds=10),
        date_to=now,
    )
    response = auth_client(user).post('/api/v1/exports/stream/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    rows = parse_csv(b''.join(response.streaming_content))
    assert len(rows) == 0  # DictReader yields no rows when only header is present


# ---------------------------------------------------------------------------
# GET /api/v1/exports/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_history_admin_only():
    """Only Admins can view export history; Operators receive 403."""
    tenant = make_tenant()
    operator = make_user(tenant, role=TenantUser.Role.OPERATOR, email='op@test.com')

    response = auth_client(operator).get('/api/v1/exports/')
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_export_history_lists_correct_records():
    """Export history returns records for the requesting tenant only."""
    tenant_a = make_tenant('A')
    tenant_b = make_tenant('B')
    user_a = make_user(tenant_a)

    # Create a log entry for tenant A and one for tenant B
    now = timezone.now()
    DataExport.objects.create(
        tenant=tenant_a, exported_by=user_a, stream_ids=[1],
        date_from=now - timedelta(hours=1), date_to=now,
    )
    user_b = make_user(tenant_b, email='b@test.com')
    DataExport.objects.create(
        tenant=tenant_b, exported_by=user_b, stream_ids=[2],
        date_from=now - timedelta(hours=1), date_to=now,
    )

    response = auth_client(user_a).get('/api/v1/exports/')
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]['exported_by_email'] == user_a.email


@pytest.mark.django_db
def test_export_history_includes_email():
    """Export history serializer includes the exporter's email."""
    tenant = make_tenant()
    user = make_user(tenant)
    DataExport.objects.create(
        tenant=tenant, exported_by=user, stream_ids=[1],
        date_from=timezone.now() - timedelta(hours=1), date_to=timezone.now(),
    )

    response = auth_client(user).get('/api/v1/exports/')
    assert response.status_code == status.HTTP_200_OK
    assert response.data[0]['exported_by_email'] == user.email
