"""Device health computation helpers.

Provides activity level derivation logic used by both the ingestion pipeline
(on every message) and the offline detection Celery beat task (every minute).

Ref: SPEC.md § Feature: Device Health Monitoring
"""
import logging
from datetime import datetime
from typing import Optional

from django.utils import timezone

from .models import DeviceHealth

logger = logging.getLogger(__name__)


def get_offline_threshold(device) -> int:
    """Return the effective offline threshold in minutes for a device.

    Uses the per-device override if set, otherwise falls back to the device
    type default. Returns 10 minutes if neither is configured.
    """
    if device.offline_threshold_override_minutes is not None:
        return device.offline_threshold_override_minutes
    if device.device_type_id and device.device_type.default_offline_threshold_minutes:
        return device.device_type.default_offline_threshold_minutes
    return 10


def compute_activity_level(
    tenant,
    signal: Optional[int],
    battery: Optional[int],
    last_seen_at: Optional[datetime],
    offline_threshold_minutes: int,
    just_came_back: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """Derive the activity level from health metrics and tenant thresholds.

    Args:
        tenant:                    Tenant instance — provides configurable thresholds.
        signal:                    Signal strength in dBm, or None (legacy/unknown).
        battery:                   Battery level as %, or None (legacy/mains/unknown).
        last_seen_at:              Last message timestamp, or None (never heard from).
        offline_threshold_minutes: Effective offline threshold for this device.
        just_came_back:            True if the device was previously offline — forces critical.
        now:                       Current time (injectable for testing). Defaults to utcnow.

    Returns:
        One of ``'normal'``, ``'degraded'``, or ``'critical'``.
    """
    if now is None:
        now = timezone.now()

    # Device just came back online after being offline → critical for this cycle
    if just_came_back:
        return DeviceHealth.ActivityLevel.CRITICAL

    # Signal strength checks
    if signal is not None:
        if signal < tenant.signal_critical_threshold:
            return DeviceHealth.ActivityLevel.CRITICAL
        if signal < tenant.signal_degraded_threshold:
            return DeviceHealth.ActivityLevel.DEGRADED

    # Battery level checks (skip if null — mains-powered or legacy)
    if battery is not None:
        if battery < tenant.battery_critical_threshold:
            return DeviceHealth.ActivityLevel.CRITICAL
        if battery < tenant.battery_degraded_threshold:
            return DeviceHealth.ActivityLevel.DEGRADED

    # Approaching offline threshold check
    if last_seen_at is not None and offline_threshold_minutes:
        elapsed_minutes = (now - last_seen_at).total_seconds() / 60
        approaching_minutes = offline_threshold_minutes * tenant.offline_approaching_percent / 100
        if elapsed_minutes >= approaching_minutes:
            return DeviceHealth.ActivityLevel.DEGRADED

    return DeviceHealth.ActivityLevel.NORMAL


def update_device_health(
    device,
    ingestion_time: datetime,
    battery: Optional[int] = None,
    signal: Optional[int] = None,
) -> DeviceHealth:
    """Create or update the DeviceHealth record for a device on message receipt.

    Called by the ingestion pipeline on every telemetry message. Updates
    last_seen_at unconditionally. Updates battery/signal only when provided
    (v2 devices with _battery/_signal keys in their payload).

    Args:
        device:          Device instance (must have tenant and device_type loaded).
        ingestion_time:  Server-side timestamp of the received message.
        battery:         Extracted _battery value, or None.
        signal:          Extracted _signal value, or None.

    Returns:
        The updated DeviceHealth instance.
    """
    health, created = DeviceHealth.objects.get_or_create(device=device)

    was_offline = not health.is_online and not created

    if health.first_active_at is None:
        health.first_active_at = ingestion_time

    health.last_seen_at = ingestion_time
    health.is_online = True

    if battery is not None:
        health.battery_level = int(battery)
    if signal is not None:
        health.signal_strength = int(signal)

    health.activity_level = compute_activity_level(
        tenant=device.tenant,
        signal=health.signal_strength,
        battery=health.battery_level,
        last_seen_at=ingestion_time,
        offline_threshold_minutes=get_offline_threshold(device),
        just_came_back=was_offline,
        now=ingestion_time,
    )

    health.save()
    return health
