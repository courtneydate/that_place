"""Tests for Sprint 21: Device Commands.

Covers:
  - Command send endpoint — happy path, invalid command, missing param,
    unsupported topic format, View-Only blocked, cross-tenant blocked
  - Command history endpoint — happy path, View-Only blocked
  - Ack handling — valid ack updates CommandLog, missing command field discarded,
    unknown command discarded
  - Timeout beat task — marks timed-out commands, respects ack timeout

Ref: SPEC.md § Feature: Device Control
"""
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import CommandLog, Device, DeviceType, Site
from apps.devices.tasks import check_command_timeouts
from apps.ingestion.tasks import _handle_command_ack

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_fm_admin(email='fm@that-place.io', password='testpass123'):
    return User.objects.create_user(
        email=email, password=password, is_that_place_admin=True,
    )


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_device_type(name='Relay Controller', commands=None):
    if commands is None:
        commands = [
            {
                'name': 'set_relay',
                'label': 'Set Relay',
                'params': [
                    {'key': 'relay', 'label': 'Relay', 'type': 'int'},
                    {'key': 'state', 'label': 'State', 'type': 'bool', 'default': False},
                ],
            }
        ]
    return DeviceType.objects.create(
        name=name,
        slug=slugify(name),
        connection_type='mqtt',
        is_push=True,
        default_offline_threshold_minutes=10,
        command_ack_timeout_seconds=30,
        commands=commands,
    )


def make_device(tenant, site, device_type, serial='SCOUT001', topic_format=Device.TopicFormat.THAT_PLACE_V1):
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=device_type,
        name='Test Device',
        serial_number=serial,
        status=Device.Status.ACTIVE,
        topic_format=topic_format,
    )


def make_site(tenant, name='Main Site'):
    return Site.objects.create(tenant=tenant, name=name)


# ---------------------------------------------------------------------------
# Command send endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_command_happy_path():
    """Admin can send a valid command — CommandLog created with status 'sent'."""
    tenant = make_tenant()
    admin = make_tenant_user('admin@acme.com', tenant)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)
    client = auth_client(admin)

    with patch('apps.ingestion.mqtt_client.publish_mqtt_message') as mock_pub:
        resp = client.post(
            f'/api/v1/devices/{device.pk}/command/',
            {'command_name': 'set_relay', 'params': {'relay': 1, 'state': True}},
            format='json',
        )

    assert resp.status_code == status.HTTP_201_CREATED, resp.data
    assert resp.data['command_name'] == 'set_relay'
    assert resp.data['status'] == 'sent'
    assert resp.data['sent_by_email'] == admin.email
    mock_pub.assert_called_once()
    topic = mock_pub.call_args[0][0]
    assert topic == f'that-place/scout/{device.serial_number}/cmd/set_relay'


@pytest.mark.django_db
def test_send_command_bridged_device():
    """Command to a bridged device uses the gateway Scout's serial in the topic."""
    tenant = make_tenant()
    admin = make_tenant_user('admin@acme.com', tenant)
    site = make_site(tenant)
    dt = make_device_type()
    scout = make_device(tenant, site, dt, serial='SCOUT001')
    bridged = Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Bridged', serial_number='SENSOR001',
        status=Device.Status.ACTIVE,
        topic_format=Device.TopicFormat.THAT_PLACE_V1,
        gateway_device=scout,
    )
    client = auth_client(admin)

    with patch('apps.ingestion.mqtt_client.publish_mqtt_message') as mock_pub:
        resp = client.post(
            f'/api/v1/devices/{bridged.pk}/command/',
            {'command_name': 'set_relay', 'params': {'relay': 1}},
            format='json',
        )

    assert resp.status_code == status.HTTP_201_CREATED
    topic = mock_pub.call_args[0][0]
    assert topic == 'that-place/scout/SCOUT001/SENSOR001/cmd/set_relay'


@pytest.mark.django_db
def test_send_command_operator_allowed():
    """Operators can send commands."""
    tenant = make_tenant()
    operator = make_tenant_user('op@acme.com', tenant, role=TenantUser.Role.OPERATOR)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)
    client = auth_client(operator)

    with patch('apps.ingestion.mqtt_client.publish_mqtt_message'):
        resp = client.post(
            f'/api/v1/devices/{device.pk}/command/',
            {'command_name': 'set_relay', 'params': {'relay': 1}},
            format='json',
        )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_send_command_view_only_blocked():
    """View-Only users cannot send commands."""
    tenant = make_tenant()
    viewer = make_tenant_user('view@acme.com', tenant, role=TenantUser.Role.VIEWER)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)
    client = auth_client(viewer)

    resp = client.post(
        f'/api/v1/devices/{device.pk}/command/',
        {'command_name': 'set_relay', 'params': {'relay': 1}},
        format='json',
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_send_command_invalid_command_name():
    """Unknown command name returns 400."""
    tenant = make_tenant()
    admin = make_tenant_user('admin@acme.com', tenant)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)
    client = auth_client(admin)

    resp = client.post(
        f'/api/v1/devices/{device.pk}/command/',
        {'command_name': 'nonexistent_cmd', 'params': {}},
        format='json',
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_send_command_missing_required_param():
    """Missing required param (no default) returns 400."""
    tenant = make_tenant()
    admin = make_tenant_user('admin@acme.com', tenant)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)
    client = auth_client(admin)

    # 'relay' param has no default — required
    resp = client.post(
        f'/api/v1/devices/{device.pk}/command/',
        {'command_name': 'set_relay', 'params': {}},
        format='json',
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_send_command_legacy_format_blocked():
    """Commands to legacy_v1 format devices return 400."""
    tenant = make_tenant()
    admin = make_tenant_user('admin@acme.com', tenant)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt, topic_format=Device.TopicFormat.LEGACY_V1)
    client = auth_client(admin)

    resp = client.post(
        f'/api/v1/devices/{device.pk}/command/',
        {'command_name': 'set_relay', 'params': {'relay': 1}},
        format='json',
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.data['error']['code'] == 'unsupported_format'


@pytest.mark.django_db
def test_send_command_cross_tenant_blocked():
    """Tenant B admin cannot send commands to Tenant A's device."""
    tenant_a = make_tenant('TenantA')
    tenant_b = make_tenant('TenantB')
    admin_b = make_tenant_user('admin@b.com', tenant_b)
    site_a = make_site(tenant_a)
    dt = make_device_type()
    device_a = make_device(tenant_a, site_a, dt, serial='SCOUT_A')
    client = auth_client(admin_b)

    resp = client.post(
        f'/api/v1/devices/{device_a.pk}/command/',
        {'command_name': 'set_relay', 'params': {'relay': 1}},
        format='json',
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Command history tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_command_history_happy_path():
    """Admin can retrieve command history for their device."""
    tenant = make_tenant()
    admin = make_tenant_user('admin@acme.com', tenant)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    CommandLog.objects.create(
        device=device, command_name='set_relay', params_sent={'relay': 1},
        status=CommandLog.Status.ACKNOWLEDGED, sent_by=admin,
    )

    client = auth_client(admin)
    resp = client.get(f'/api/v1/devices/{device.pk}/commands/')
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.data) == 1
    assert resp.data[0]['command_name'] == 'set_relay'
    assert resp.data[0]['status'] == 'acknowledged'


@pytest.mark.django_db
def test_command_history_view_only_blocked():
    """View-Only users cannot access command history."""
    tenant = make_tenant()
    viewer = make_tenant_user('view@acme.com', tenant, role=TenantUser.Role.VIEWER)
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)
    client = auth_client(viewer)

    resp = client.get(f'/api/v1/devices/{device.pk}/commands/')
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Ack handling tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ack_updates_command_log():
    """Valid ack payload marks the matching CommandLog as acknowledged."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    log = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={'relay': 1}, status=CommandLog.Status.SENT,
    )

    _handle_command_ack(device, json.dumps({'command': 'set_relay'}))

    log.refresh_from_db()
    assert log.status == CommandLog.Status.ACKNOWLEDGED
    assert log.ack_received_at is not None


@pytest.mark.django_db
def test_ack_missing_command_field_discarded():
    """Ack without 'command' field is discarded; CommandLog unchanged."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    log = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={}, status=CommandLog.Status.SENT,
    )

    _handle_command_ack(device, json.dumps({'other': 'data'}))

    log.refresh_from_db()
    assert log.status == CommandLog.Status.SENT


@pytest.mark.django_db
def test_ack_unknown_command_discarded():
    """Ack with command name that matches no sent log is silently discarded."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    log = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={}, status=CommandLog.Status.SENT,
    )

    _handle_command_ack(device, json.dumps({'command': 'nonexistent_cmd'}))

    log.refresh_from_db()
    assert log.status == CommandLog.Status.SENT


@pytest.mark.django_db
def test_ack_invalid_json_discarded():
    """Non-JSON ack payload is discarded without error."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    # Should not raise
    _handle_command_ack(device, 'not-json')


@pytest.mark.django_db
def test_ack_matches_oldest_sent_log():
    """When multiple sent logs exist, ack matches the oldest (FIFO)."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    # Create two sent logs — first is the older one
    log1 = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={'relay': 1}, status=CommandLog.Status.SENT,
    )
    log2 = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={'relay': 2}, status=CommandLog.Status.SENT,
    )
    # Force log1 to appear older
    CommandLog.objects.filter(pk=log1.pk).update(
        sent_at=timezone.now() - timedelta(seconds=10)
    )

    _handle_command_ack(device, json.dumps({'command': 'set_relay'}))

    log1.refresh_from_db()
    log2.refresh_from_db()
    assert log1.status == CommandLog.Status.ACKNOWLEDGED
    assert log2.status == CommandLog.Status.SENT


# ---------------------------------------------------------------------------
# Timeout beat task tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_check_command_timeouts_marks_timed_out():
    """Commands older than ack_timeout_seconds are marked timed_out."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()  # command_ack_timeout_seconds = 30
    device = make_device(tenant, site, dt)

    log = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={}, status=CommandLog.Status.SENT,
    )
    # Backdate sent_at beyond the timeout
    CommandLog.objects.filter(pk=log.pk).update(
        sent_at=timezone.now() - timedelta(seconds=60)
    )

    check_command_timeouts()

    log.refresh_from_db()
    assert log.status == CommandLog.Status.TIMED_OUT


@pytest.mark.django_db
def test_check_command_timeouts_respects_ack_timeout():
    """Commands within the timeout window are not marked timed_out."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()  # command_ack_timeout_seconds = 30
    device = make_device(tenant, site, dt)

    log = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={}, status=CommandLog.Status.SENT,
    )
    # sent_at is now — well within 30s timeout

    check_command_timeouts()

    log.refresh_from_db()
    assert log.status == CommandLog.Status.SENT


@pytest.mark.django_db
def test_check_command_timeouts_skips_acknowledged():
    """Already-acknowledged commands are not touched by the timeout task."""
    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    log = CommandLog.objects.create(
        device=device, command_name='set_relay',
        params_sent={}, status=CommandLog.Status.ACKNOWLEDGED,
    )
    CommandLog.objects.filter(pk=log.pk).update(
        sent_at=timezone.now() - timedelta(seconds=60)
    )

    check_command_timeouts()

    log.refresh_from_db()
    assert log.status == CommandLog.Status.ACKNOWLEDGED


# ---------------------------------------------------------------------------
# Rule-triggered command test
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_rule_triggered_command_creates_log():
    """send_device_command with triggered_by_rule creates a CommandLog with correct fields."""
    from apps.devices.tasks import send_device_command
    from apps.rules.models import Rule

    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    rule = Rule.objects.create(
        tenant=tenant,
        name='Fan Speed Rule',
        is_active=True,
    )

    with patch('apps.ingestion.mqtt_client.publish_mqtt_message'):
        log_id = send_device_command(
            device_id=device.pk,
            command_name='set_relay',
            params={'relay': 1, 'state': True},
            triggered_by_rule_id=rule.pk,
        )

    assert log_id is not None
    log = CommandLog.objects.get(pk=log_id)
    assert log.triggered_by_rule_id == rule.pk
    assert log.sent_by_id is None
    assert log.command_name == 'set_relay'


@pytest.mark.django_db
def test_dispatch_command_actions_calls_task():
    """_dispatch_command_actions dispatches send_device_command for each command action."""
    from unittest.mock import patch as mock_patch

    from apps.rules.models import Rule, RuleAction
    from apps.rules.tasks import _dispatch_command_actions

    tenant = make_tenant()
    site = make_site(tenant)
    dt = make_device_type()
    device = make_device(tenant, site, dt)

    rule = Rule.objects.create(tenant=tenant, name='Test Rule', is_active=True)
    RuleAction.objects.create(
        rule=rule,
        action_type=RuleAction.ActionType.COMMAND,
        target_device=device,
        command={'name': 'set_relay', 'params': {'relay': 1}},
    )

    with mock_patch('apps.devices.tasks.send_device_command') as mock_task:
        _dispatch_command_actions(rule)

    mock_task.delay.assert_called_once_with(
        device_id=device.pk,
        command_name='set_relay',
        params={'relay': 1},
        triggered_by_rule_id=rule.pk,
    )
