"""Celery tasks for the ingestion pipeline.

Sprint 6: Route the topic, look up the device, validate status,
          update topic_format, and discard unknown/unapproved messages.
Sprint 7: Parse the payload and create StreamReadings. Auto-discover
          new stream keys as Stream records.
Sprint 16: Dispatch rule evaluation after each StreamReading batch.

Ref: SPEC.md § Feature: MQTT Ingestion Pipeline
     SPEC.md § Feature: Stream Discovery & Configuration
     SPEC.md § Feature: Rule Evaluation Engine
"""
import logging
from typing import Any

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.devices.health import update_device_health
from apps.devices.models import Device
from apps.readings.models import Stream, StreamReading

from .parsers import parse_json_telemetry, parse_legacy_v1_telemetry
from .router import router

logger = logging.getLogger(__name__)

# Message types that carry stream telemetry and should be stored as StreamReadings.
TELEMETRY_MESSAGE_TYPES = {'telemetry', 'scout_telemetry'}


@shared_task(name='ingestion.process_mqtt_message')
def process_mqtt_message(topic: str, payload: str) -> None:
    """Process a single inbound MQTT message.

    Called by the MQTT subscriber for every message that arrives on a
    subscribed topic. Payload is passed as a UTF-8 string; binary payloads
    are base64-encoded by the subscriber before dispatch.

    Args:
        topic:   The full MQTT topic string, e.g. ``fm/mm/UNIT1/telemetry``.
        payload: The message payload as a UTF-8 string.
    """
    parsed = router.route(topic)

    if parsed is None:
        logger.debug('No pattern matched topic "%s" — discarding', topic)
        return

    logger.debug(
        'Routed topic "%s" → pattern=%s device_serial=%s format=%s',
        topic,
        parsed.pattern_name,
        parsed.device_serial,
        parsed.topic_format,
    )

    # Device lookup
    try:
        device = Device.objects.select_related('tenant', 'device_type').get(
            serial_number=parsed.device_serial,
        )
    except Device.DoesNotExist:
        logger.warning(
            'Inbound message on topic "%s" references unknown serial "%s" — discarding',
            topic,
            parsed.device_serial,
        )
        return

    # Approval gate — only active devices may submit data
    if device.status != Device.Status.ACTIVE:
        logger.warning(
            'Device "%s" (serial=%s, status=%s) is not active — discarding message on topic "%s"',
            device.name,
            device.serial_number,
            device.status,
            topic,
        )
        return

    # Auto-detect and persist topic_format if it has changed
    if device.topic_format != parsed.topic_format:
        Device.objects.filter(pk=device.pk).update(topic_format=parsed.topic_format)
        logger.info(
            'Device "%s" topic_format updated: %s → %s',
            device.serial_number,
            device.topic_format,
            parsed.topic_format,
        )

    # Only telemetry message types produce StreamReadings
    if parsed.message_type not in TELEMETRY_MESSAGE_TYPES:
        logger.debug(
            'Message type "%s" on topic "%s" is not telemetry — no readings stored',
            parsed.message_type,
            topic,
        )
        return

    # Parse payload into stream key → (value, data_type) mapping
    try:
        stream_values = _parse_telemetry(parsed.topic_format, payload)
    except ValueError as exc:
        logger.warning(
            'Failed to parse telemetry payload on topic "%s": %s',
            topic,
            exc,
        )
        return

    ingestion_time = timezone.now()

    if not stream_values:
        logger.warning('Empty telemetry payload on topic "%s" — nothing to store', topic)
        # Still update health — device was heard from even if payload was empty
        update_device_health(device, ingestion_time)
        return

    # Extract reserved health keys before storing streams
    # _battery and _signal are also stored as virtual StreamReadings (per SPEC)
    battery = _extract_health_value(stream_values, '_battery')
    signal = _extract_health_value(stream_values, '_signal')

    # Store all stream readings atomically (including _battery/_signal as virtual streams)
    _store_stream_readings(device, stream_values, ingestion_time)

    # Update device health record on every message
    update_device_health(device, ingestion_time, battery=battery, signal=signal)

    logger.debug(
        'Stored %d reading(s) for device "%s" (tenant=%s)',
        len(stream_values),
        device.serial_number,
        device.tenant.name,
    )


def _extract_health_value(
    stream_values: dict[str, tuple[Any, str | None]],
    key: str,
) -> Any | None:
    """Extract a numeric health value from stream_values by key, or return None.

    Used to pull ``_battery`` and ``_signal`` out of v2 telemetry payloads.
    The keys remain in stream_values so they are also stored as StreamReadings.
    """
    entry = stream_values.get(key)
    if entry is None:
        return None
    value, _ = entry
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_telemetry(topic_format: str, payload: str) -> dict[str, tuple[Any, str | None]]:
    """Parse a raw telemetry payload into a stream key → (value, data_type) mapping.

    Args:
        topic_format: ``'legacy_v1'`` or ``'that_place_v1'``.
        payload:      Raw payload string from the MQTT message.

    Returns:
        Dict of ``{stream_key: (value, data_type)}``.
        data_type is ``None`` for v2 JSON payloads (inferred from DeviceType or defaults to numeric).
    """
    if topic_format == 'legacy_v1':
        return parse_legacy_v1_telemetry(payload)

    # That Place v1 — JSON key-value; data_type inferred downstream
    raw_json = parse_json_telemetry(payload)
    return {key: (value, None) for key, value in raw_json.items()}


@transaction.atomic
def _store_stream_readings(
    device: Device,
    stream_values: dict[str, tuple[Any, str | None]],
    ingestion_time: Any,
) -> None:
    """Create StreamReading records for each stream key in the payload.

    Auto-creates Stream records for any key not yet seen on this device.
    DeviceType stream_type_definitions are used to populate label, unit,
    and data_type on newly created streams where available.

    Args:
        device:         The Device instance the readings belong to.
        stream_values:  Mapping of ``stream_key → (value, data_type | None)``.
        ingestion_time: Server-side timestamp applied to all readings in this batch.
    """
    # Build a lookup of stream definitions from the DeviceType for enriching auto-created streams
    stream_defs: dict[str, dict] = {}
    if device.device_type_id and device.device_type.stream_type_definitions:
        for sd in device.device_type.stream_type_definitions:
            if isinstance(sd, dict) and 'key' in sd:
                stream_defs[sd['key']] = sd

    readings_to_create = []

    for key, (value, data_type) in stream_values.items():
        # Resolve data_type: explicit (legacy CSV) > DeviceType definition > default numeric
        if data_type is None:
            data_type = stream_defs.get(key, {}).get('data_type', Stream.DataType.NUMERIC)

        stream, created = Stream.objects.get_or_create(
            device=device,
            key=key,
            defaults={
                'label': stream_defs.get(key, {}).get('label', key),
                'unit': stream_defs.get(key, {}).get('unit', ''),
                'data_type': data_type,
            },
        )

        if created:
            logger.info(
                'Auto-discovered new stream "%s" (data_type=%s) on device "%s" (tenant=%s)',
                key,
                data_type,
                device.serial_number,
                device.tenant.name,
            )

        readings_to_create.append(StreamReading(
            stream=stream,
            value=value,
            timestamp=ingestion_time,
        ))

    StreamReading.objects.bulk_create(readings_to_create)

    # Dispatch rule evaluation after the transaction commits so workers see the
    # new readings immediately. on_commit is a no-op if no transaction is active
    # (CELERY_TASK_ALWAYS_EAGER in tests handles this transparently).
    stream_ids = frozenset(r.stream_id for r in readings_to_create)

    def _dispatch():
        for stream_id in stream_ids:
            _dispatch_stream_rule_evaluation.delay(stream_id)

    transaction.on_commit(_dispatch)


@shared_task(name='ingestion.dispatch_stream_rule_evaluation')
def _dispatch_stream_rule_evaluation(stream_id: int) -> None:
    """Look up rules referencing this stream and dispatch one evaluate_rule task each.

    Uses RuleStreamIndex for an O(matching rules) lookup rather than scanning
    all tenant rules on every reading.

    Ref: SPEC.md § Feature: Rule Evaluation Engine — RuleStreamIndex
    """
    from apps.readings.models import RuleStreamIndex
    from apps.rules.tasks import evaluate_rule

    rule_ids = list(
        RuleStreamIndex.objects
        .filter(stream_id=stream_id, rule__is_active=True)
        .values_list('rule_id', flat=True)
    )

    for rule_id in rule_ids:
        evaluate_rule.delay(rule_id)
