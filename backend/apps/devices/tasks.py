"""Celery tasks for device health monitoring.

Sprint 8: Offline detection — runs every minute, checks all active devices
          against their offline threshold, marks offline when exceeded.

Ref: SPEC.md § Feature: Device Health Monitoring
"""
import logging

from celery import shared_task
from django.utils import timezone

from .health import compute_activity_level, get_offline_threshold
from .models import Device, DeviceHealth

logger = logging.getLogger(__name__)


@shared_task(name='devices.check_devices_offline')
def check_devices_offline() -> None:
    """Check all active devices and mark offline those that have exceeded their threshold.

    Runs every minute via Celery beat. For each active device with a health
    record, compares time since last message against the effective offline
    threshold. Marks is_online=False and activity_level=critical when exceeded.

    Also re-derives activity_level for online devices to catch the
    approaching-offline-threshold degraded state.
    """
    now = timezone.now()
    marked_offline = 0
    updated = 0

    healths = (
        DeviceHealth.objects
        .filter(device__status=Device.Status.ACTIVE)
        .select_related('device__device_type', 'device__tenant')
        .exclude(last_seen_at=None)
    )

    for health in healths:
        device = health.device
        threshold = get_offline_threshold(device)
        elapsed_minutes = (now - health.last_seen_at).total_seconds() / 60

        if elapsed_minutes > threshold:
            if health.is_online:
                health.is_online = False
                health.activity_level = DeviceHealth.ActivityLevel.CRITICAL
                health.save(update_fields=['is_online', 'activity_level', 'updated_at'])
                marked_offline += 1
                logger.info(
                    'Device "%s" marked offline (elapsed=%.1f min, threshold=%d min)',
                    device.serial_number,
                    elapsed_minutes,
                    threshold,
                )
        else:
            new_level = compute_activity_level(
                tenant=device.tenant,
                signal=health.signal_strength,
                battery=health.battery_level,
                last_seen_at=health.last_seen_at,
                offline_threshold_minutes=threshold,
                now=now,
            )
            if new_level != health.activity_level or not health.is_online:
                health.is_online = True
                health.activity_level = new_level
                health.save(update_fields=['is_online', 'activity_level', 'updated_at'])
                updated += 1

    if marked_offline or updated:
        logger.info(
            'Health check complete: %d marked offline, %d activity levels updated',
            marked_offline,
            updated,
        )
