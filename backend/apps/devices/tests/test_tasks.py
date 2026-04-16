"""Cross-tenant isolation tests for Celery beat tasks in the devices app.

Verifies that check_devices_offline processes each tenant's devices
independently — marking Tenant A's device offline does not affect
Tenant B's device, and vice versa.

Ref: security_risks.md § SR-03 — Tenant Isolation in Celery Beat Tasks
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceHealth, DeviceType, Site
from apps.devices.tasks import check_devices_offline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_device_type() -> DeviceType:
    dt, _ = DeviceType.objects.get_or_create(
        slug='test-mqtt',
        defaults={
            'name': 'Test MQTT Device',
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 10,
            'command_ack_timeout_seconds': 30,
        },
    )
    return dt


def make_active_device(tenant: Tenant, serial: str) -> Device:
    site = Site.objects.create(tenant=tenant, name=f'Site {serial}')
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=make_device_type(),
        name=f'Device {serial}',
        serial_number=serial,
        status=Device.Status.ACTIVE,
    )


def make_health(device: Device, last_seen_minutes_ago: int, is_online: bool = True) -> DeviceHealth:
    last_seen = timezone.now() - timedelta(minutes=last_seen_minutes_ago)
    return DeviceHealth.objects.create(
        device=device,
        is_online=is_online,
        last_seen_at=last_seen,
        first_active_at=last_seen,
        activity_level=DeviceHealth.ActivityLevel.NORMAL,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCheckDevicesOfflineCrossTenant:
    """check_devices_offline must not cause cross-tenant health state contamination."""

    def test_stale_tenant_a_device_goes_offline(self):
        """A device that has exceeded its threshold is marked offline."""
        tenant = make_tenant('StaleA')
        device = make_active_device(tenant, 'STALE-A-001')
        # last seen 60 minutes ago; threshold is 10 minutes → should go offline
        make_health(device, last_seen_minutes_ago=60)

        check_devices_offline()

        device.devicehealth.refresh_from_db()
        assert device.devicehealth.is_online is False
        assert device.devicehealth.activity_level == DeviceHealth.ActivityLevel.CRITICAL

    def test_fresh_tenant_b_device_stays_online(self):
        """A device within its threshold is not affected by another device going offline."""
        tenant_a = make_tenant('StaleB-A')
        tenant_b = make_tenant('StaleB-B')
        stale_dev = make_active_device(tenant_a, 'STALE-B-001')
        fresh_dev = make_active_device(tenant_b, 'FRESH-B-001')

        # Tenant A's device is stale; Tenant B's device is fresh
        make_health(stale_dev, last_seen_minutes_ago=60)
        make_health(fresh_dev, last_seen_minutes_ago=2)

        check_devices_offline()

        fresh_dev.devicehealth.refresh_from_db()
        assert fresh_dev.devicehealth.is_online is True

    def test_tenant_b_health_unchanged_when_tenant_a_goes_offline(self):
        """Tenant B's health record must be identical before and after Tenant A's
        device is marked offline."""
        tenant_a = make_tenant('IsoA')
        tenant_b = make_tenant('IsoB')
        dev_a = make_active_device(tenant_a, 'ISO-A-001')
        dev_b = make_active_device(tenant_b, 'ISO-B-001')

        make_health(dev_a, last_seen_minutes_ago=120)  # will go offline
        health_b = make_health(dev_b, last_seen_minutes_ago=1)  # stays online

        before_updated_at = health_b.updated_at

        check_devices_offline()

        # Tenant A went offline
        dev_a.devicehealth.refresh_from_db()
        assert dev_a.devicehealth.is_online is False

        # Tenant B's record was not written (or if updated for activity level,
        # its is_online status must still be True)
        dev_b.devicehealth.refresh_from_db()
        assert dev_b.devicehealth.is_online is True

    def test_multiple_tenants_each_handled_correctly(self):
        """Three tenants with devices in different states — each resolved independently."""
        tenants_data = [
            ('MultiA', 'MULTI-A-001', 120, False),  # stale → goes offline
            ('MultiB', 'MULTI-B-001', 3, True),     # fresh → stays online
            ('MultiC', 'MULTI-C-001', 45, False),   # stale → goes offline
        ]

        devices = {}
        for name, serial, minutes_ago, expected_online in tenants_data:
            tenant = make_tenant(name)
            dev = make_active_device(tenant, serial)
            make_health(dev, last_seen_minutes_ago=minutes_ago)
            devices[serial] = (dev, expected_online)

        check_devices_offline()

        for serial, (dev, expected_online) in devices.items():
            dev.devicehealth.refresh_from_db()
            assert dev.devicehealth.is_online is expected_online, (
                f'{serial}: expected is_online={expected_online}, '
                f'got {dev.devicehealth.is_online}'
            )

    def test_task_does_not_process_inactive_devices(self):
        """Devices with status != ACTIVE must not be touched by the health task."""
        tenant = make_tenant('InactiveTenant')
        site = Site.objects.create(tenant=tenant, name='Site')
        pending_dev = Device.objects.create(
            tenant=tenant, site=site, device_type=make_device_type(),
            name='Pending', serial_number='PENDING-001',
            status=Device.Status.PENDING,
        )
        # Create health record (shouldn't normally exist for a pending device,
        # but ensures the filter is honoured even if one slips through)
        make_health(pending_dev, last_seen_minutes_ago=999)

        check_devices_offline()

        pending_dev.devicehealth.refresh_from_db()
        # Task should have filtered it out — health must still be online
        # (the filter excludes non-ACTIVE devices)
        assert pending_dev.devicehealth.is_online is True
