"""Tests for Sprint 8: Device health monitoring.

Covers:
- Activity level derivation (normal / degraded / critical)
- Offline detection Celery task
- Per-device threshold override respected
- Health record created/updated on message receipt
- Health API endpoint

Ref: SPEC.md § Feature: Device Health Monitoring
"""
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.health import compute_activity_level, update_device_health
from apps.devices.models import Device, DeviceHealth, DeviceType, Site
from apps.devices.tasks import check_devices_offline
from apps.ingestion.tasks import process_mqtt_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tenant(**kwargs):
    name = kwargs.pop('name', 'Acme')
    return Tenant.objects.create(name=name, slug=slugify(name), **kwargs)


def make_device_type(name='Scout'):
    return DeviceType.objects.create(
        name=name, slug=slugify(name),
        connection_type='mqtt', is_push=True,
        default_offline_threshold_minutes=10,
        stream_type_definitions=[], commands=[],
    )


def make_device(tenant, serial, status=Device.Status.ACTIVE,
                threshold_override=None, device_type=None):
    site = Site.objects.create(tenant=tenant, name='Site')
    dt = device_type or make_device_type()
    return Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Test Device', serial_number=serial,
        status=status, topic_format='fieldmouse_v2',
        offline_threshold_override_minutes=threshold_override,
    )


def make_health(device, is_online=True, last_seen_at=None,
                signal=None, battery=None,
                activity_level=DeviceHealth.ActivityLevel.NORMAL):
    return DeviceHealth.objects.create(
        device=device,
        is_online=is_online,
        last_seen_at=last_seen_at or timezone.now(),
        first_active_at=timezone.now(),
        signal_strength=signal,
        battery_level=battery,
        activity_level=activity_level,
    )


def auth_client(user, password='pass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


# ---------------------------------------------------------------------------
# Activity level derivation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeActivityLevel:

    def setup_method(self):
        self.tenant = make_tenant(name='Threshold Co')
        self.now = timezone.now()

    def test_normal_when_all_ok(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-60, battery=80,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.NORMAL

    def test_degraded_on_weak_signal(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-75, battery=80,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.DEGRADED

    def test_critical_on_very_weak_signal(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-90, battery=80,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.CRITICAL

    def test_degraded_on_low_battery(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-60, battery=30,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.DEGRADED

    def test_critical_on_very_low_battery(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-60, battery=10,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.CRITICAL

    def test_degraded_approaching_offline_threshold(self):
        """75% of a 10-minute threshold = 7.5 minutes elapsed → degraded."""
        level = compute_activity_level(
            tenant=self.tenant, signal=None, battery=None,
            last_seen_at=self.now - timedelta(minutes=8),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.DEGRADED

    def test_normal_below_approaching_threshold(self):
        """Less than 75% elapsed → normal."""
        level = compute_activity_level(
            tenant=self.tenant, signal=None, battery=None,
            last_seen_at=self.now - timedelta(minutes=5),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.NORMAL

    def test_critical_when_just_came_back(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-60, battery=80,
            last_seen_at=self.now,
            offline_threshold_minutes=10,
            just_came_back=True, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.CRITICAL

    def test_null_signal_and_battery_treated_as_normal(self):
        """Legacy v1 devices — no signal/battery. Should not trigger degraded/critical."""
        level = compute_activity_level(
            tenant=self.tenant, signal=None, battery=None,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.NORMAL

    def test_mains_powered_battery_100_is_normal(self):
        level = compute_activity_level(
            tenant=self.tenant, signal=-60, battery=100,
            last_seen_at=self.now - timedelta(minutes=1),
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.NORMAL

    def test_custom_tenant_thresholds_respected(self):
        tenant = make_tenant(
            name='Custom Thresholds',
            signal_degraded_threshold=-50,
            signal_critical_threshold=-60,
        )
        # Signal of -55 is below custom degraded (-50) but above default (-70)
        level = compute_activity_level(
            tenant=tenant, signal=-55, battery=None,
            last_seen_at=self.now,
            offline_threshold_minutes=10, now=self.now,
        )
        assert level == DeviceHealth.ActivityLevel.DEGRADED


# ---------------------------------------------------------------------------
# update_device_health
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpdateDeviceHealth:

    def test_creates_health_record_on_first_message(self):
        tenant = make_tenant(name='First Msg')
        device = make_device(tenant, 'FIRST-001')
        now = timezone.now()

        update_device_health(device, now)

        assert DeviceHealth.objects.filter(device=device).exists()

    def test_sets_first_active_at_on_creation(self):
        tenant = make_tenant(name='First Active')
        device = make_device(tenant, 'FA-001')
        now = timezone.now()

        health = update_device_health(device, now)

        assert health.first_active_at == now

    def test_does_not_overwrite_first_active_at(self):
        tenant = make_tenant(name='No Overwrite')
        device = make_device(tenant, 'NO-001')
        first = timezone.now()
        update_device_health(device, first)

        later = first + timedelta(minutes=5)
        health = update_device_health(device, later)

        assert health.first_active_at == first

    def test_updates_last_seen_at(self):
        tenant = make_tenant(name='Last Seen')
        device = make_device(tenant, 'LS-001')
        t1 = timezone.now()
        t2 = t1 + timedelta(minutes=2)

        update_device_health(device, t1)
        health = update_device_health(device, t2)

        assert health.last_seen_at == t2

    def test_updates_battery_and_signal(self):
        tenant = make_tenant(name='Bat Sig')
        device = make_device(tenant, 'BS-001')

        health = update_device_health(device, timezone.now(), battery=75, signal=-65)

        assert health.battery_level == 75
        assert health.signal_strength == -65

    def test_marks_online_true(self):
        tenant = make_tenant(name='Online Co')
        device = make_device(tenant, 'ON-001')
        make_health(device, is_online=False)

        health = update_device_health(device, timezone.now())

        assert health.is_online is True

    def test_critical_when_device_was_offline(self):
        tenant = make_tenant(name='Comeback Co')
        device = make_device(tenant, 'CB-001')
        make_health(device, is_online=False, last_seen_at=timezone.now() - timedelta(hours=1))

        health = update_device_health(device, timezone.now())

        assert health.activity_level == DeviceHealth.ActivityLevel.CRITICAL


# ---------------------------------------------------------------------------
# Offline detection Celery task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckDevicesOffline:

    def test_marks_device_offline_when_threshold_exceeded(self):
        tenant = make_tenant(name='Offline Co')
        device = make_device(tenant, 'OFF-001')
        # Last seen 20 minutes ago, threshold is 10 minutes
        make_health(device, last_seen_at=timezone.now() - timedelta(minutes=20))

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.is_online is False

    def test_does_not_mark_offline_within_threshold(self):
        tenant = make_tenant(name='Online Co')
        device = make_device(tenant, 'ON-002')
        make_health(device, last_seen_at=timezone.now() - timedelta(minutes=5))

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.is_online is True

    def test_per_device_threshold_override_respected(self):
        tenant = make_tenant(name='Override Co')
        # Override is 30 minutes; default is 10 minutes
        device = make_device(tenant, 'OVR-001', threshold_override=30)
        # Last seen 15 minutes ago — should still be online with override
        make_health(device, last_seen_at=timezone.now() - timedelta(minutes=15))

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.is_online is True

    def test_device_type_default_threshold_used_when_no_override(self):
        tenant = make_tenant(name='DT Threshold')
        dt = make_device_type(name='SlowDevice')
        dt.default_offline_threshold_minutes = 30
        dt.save()
        device = make_device(tenant, 'DT-001', device_type=dt)
        # Last seen 15 minutes ago — still within 30-min type default
        make_health(device, last_seen_at=timezone.now() - timedelta(minutes=15))

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.is_online is True

    def test_offline_device_gets_critical_activity_level(self):
        tenant = make_tenant(name='Critical Co')
        device = make_device(tenant, 'CRIT-001')
        make_health(device, last_seen_at=timezone.now() - timedelta(minutes=20))

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.activity_level == DeviceHealth.ActivityLevel.CRITICAL

    def test_pending_device_not_checked(self):
        tenant = make_tenant(name='Pending Co')
        device = make_device(tenant, 'PEND-002', status=Device.Status.PENDING)
        make_health(device, last_seen_at=timezone.now() - timedelta(hours=1))

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.is_online is True


# ---------------------------------------------------------------------------
# Ingestion pipeline — health updates via MQTT
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngestionHealthUpdates:

    def test_v2_telemetry_creates_health_record(self):
        tenant = make_tenant(name='Health Ingest')
        device = make_device(tenant, 'HI-001')

        process_mqtt_message(
            'fieldmouse/scout/HI-001/telemetry',
            json.dumps({'Relay_1': 1}),
        )

        assert DeviceHealth.objects.filter(device=device).exists()

    def test_battery_and_signal_update_health(self):
        tenant = make_tenant(name='Bat Sig Ingest')
        device = make_device(tenant, 'BSI-001')

        process_mqtt_message(
            'fieldmouse/scout/BSI-001/telemetry',
            json.dumps({'Relay_1': 0, '_battery': 75, '_signal': -65}),
        )

        health = device.devicehealth
        assert health.battery_level == 75
        assert health.signal_strength == -65

    def test_legacy_v1_telemetry_updates_last_seen(self):
        tenant = make_tenant(name='Legacy Health')
        device = make_device(tenant, 'LH-001', status=Device.Status.ACTIVE)
        device.topic_format = Device.TopicFormat.LEGACY_V1
        device.save()

        process_mqtt_message(
            'fm/mm/LH-001/telemetry',
            '0,0,0,0,0,0,0,0,0,0,0,0',
        )

        health = device.devicehealth
        assert health.last_seen_at is not None
        assert health.battery_level is None
        assert health.signal_strength is None


# ---------------------------------------------------------------------------
# Health API endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealthEndpoint:

    def _make_user(self, tenant, role=TenantUser.Role.ADMIN):
        user = User.objects.create_user(email=f'{role}@test.com', password='pass123')
        TenantUser.objects.create(user=user, tenant=tenant, role=role)
        return user

    def test_returns_health_data(self):
        tenant = make_tenant(name='API Health')
        device = make_device(tenant, 'AH-001')
        make_health(device, signal=-65, battery=80)
        user = self._make_user(tenant)

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/health/')

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['signal_strength'] == -65
        assert resp.data['battery_level'] == 80
        assert 'activity_level' in resp.data
        assert 'last_seen_at' in resp.data

    def test_returns_404_when_no_health_data(self):
        tenant = make_tenant(name='No Health')
        device = make_device(tenant, 'NH-001')
        user = self._make_user(tenant)

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/health/')

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_view_only_can_access(self):
        tenant = make_tenant(name='View Only Health')
        device = make_device(tenant, 'VOH-001')
        make_health(device)
        user = self._make_user(tenant, role=TenantUser.Role.VIEWER)

        resp = auth_client(user).get(f'/api/v1/devices/{device.pk}/health/')

        assert resp.status_code == status.HTTP_200_OK

    def test_cross_tenant_blocked(self):
        tenant_a = make_tenant(name='Tenant A Health')
        tenant_b = make_tenant(name='Tenant B Health')
        device_a = make_device(tenant_a, 'TA-001')
        make_health(device_a)
        user_b = self._make_user(tenant_b)

        resp = auth_client(user_b).get(f'/api/v1/devices/{device_a.pk}/health/')

        assert resp.status_code == status.HTTP_404_NOT_FOUND
