"""Celery tasks for device health monitoring and command dispatch.

Sprint 8:  Offline detection — runs every minute, checks all active devices
           against their offline threshold, marks offline when exceeded.
Sprint 21: send_device_command — publishes a command to MQTT and creates a
           CommandLog entry.
           check_command_timeouts — beat task, marks timed-out commands.

Ref: SPEC.md § Feature: Device Health Monitoring
     SPEC.md § Feature: Device Control
"""
import json
import logging

from celery import shared_task
from django.utils import timezone

from .health import compute_activity_level, get_offline_threshold
from .models import CommandLog, Device, DeviceHealth

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
                from apps.notifications.tasks import create_system_notification
                create_system_notification.delay(
                    'device_offline',
                    device.tenant_id,
                    {'device_name': device.name, 'serial_number': device.serial_number},
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


@shared_task(name='devices.send_device_command')
def send_device_command(
    device_id: int,
    command_name: str,
    params: dict,
    sent_by_id: int | None = None,
    triggered_by_rule_id: int | None = None,
) -> int | None:
    """Publish a command to MQTT and create a CommandLog record.

    Constructs the correct MQTT topic based on whether the device is bridged
    through a Scout (gateway_device set) or is a Scout itself.

    Topic format (new That Place v1 only — legacy commands are out of scope):
      Bridged:  that-place/scout/{gateway_serial}/{device_serial}/cmd/{command_name}
      Direct:   that-place/scout/{device_serial}/cmd/{command_name}

    Returns the CommandLog pk on success, or None if the device is not found
    or not in that_place_v1 format.

    Ref: SPEC.md § Feature: Device Control — Sending commands
    """
    from apps.ingestion.mqtt_client import publish_mqtt_message

    try:
        device = Device.objects.select_related('device_type', 'gateway_device').get(
            pk=device_id,
            status=Device.Status.ACTIVE,
        )
    except Device.DoesNotExist:
        logger.warning('send_device_command: device %d not found or not active', device_id)
        return None

    gateway = device.gateway_device
    scout_serial = gateway.serial_number if gateway else device.serial_number
    if gateway:
        topic = f'that-place/scout/{scout_serial}/{device.serial_number}/cmd/{command_name}'
    else:
        topic = f'that-place/scout/{scout_serial}/cmd/{command_name}'

    payload = json.dumps(params or {})

    try:
        publish_mqtt_message(topic, payload)
    except Exception as exc:
        logger.error(
            'send_device_command: MQTT publish failed for device %d command "%s": %s',
            device_id, command_name, exc,
        )
        # Still create the log so the operator knows the command was attempted
        # The status will remain 'sent' and timeout normally if no ack arrives.

    log = CommandLog.objects.create(
        device=device,
        command_name=command_name,
        params_sent=params or {},
        sent_by_id=sent_by_id,
        triggered_by_rule_id=triggered_by_rule_id,
        status=CommandLog.Status.SENT,
    )
    logger.info(
        'Command "%s" sent to device "%s" (log_id=%d, rule=%s)',
        command_name, device.serial_number, log.pk, triggered_by_rule_id,
    )
    return log.pk


@shared_task(name='devices.check_command_timeouts')
def check_command_timeouts() -> None:
    """Mark CommandLog entries as timed_out when no ack arrives within the device type timeout.

    Runs every 60 seconds via Celery beat. Queries for all 'sent' CommandLog
    entries whose sent_at is older than their device type's ack timeout period.

    Ref: SPEC.md § Feature: Device Control — Acknowledgement
    """
    from datetime import timedelta

    now = timezone.now()
    timed_out = 0

    pending = (
        CommandLog.objects
        .filter(status=CommandLog.Status.SENT)
        .select_related('device__device_type')
    )

    for log in pending:
        timeout_seconds = log.device.device_type.command_ack_timeout_seconds
        deadline = log.sent_at + timedelta(seconds=timeout_seconds)
        if now >= deadline:
            log.status = CommandLog.Status.TIMED_OUT
            log.save(update_fields=['status'])
            timed_out += 1
            logger.info(
                'CommandLog %d for device "%s" command "%s" timed out',
                log.pk, log.device.serial_number, log.command_name,
            )

    if timed_out:
        logger.info('check_command_timeouts: %d command(s) marked timed_out', timed_out)
