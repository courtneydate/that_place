"""Telemetry payload parsers for the MQTT ingestion pipeline.

Two formats are supported:

- Legacy v1: 12-value CSV string — fixed field order
  (4 relays, 4 analog inputs, 4 digital inputs)
- That Place v2: JSON object — arbitrary key-value pairs

Ref: SPEC.md § MQTT Topic Structure — Telemetry payloads
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fixed field mapping for legacy v1 CSV telemetry.
# Each entry is (stream_key, data_type).
# Ref: SPEC.md § Legacy v1 telemetry CSV field mapping
LEGACY_V1_TELEMETRY_FIELDS: list[tuple[str, str]] = [
    ('Relay_1', 'boolean'),
    ('Relay_2', 'boolean'),
    ('Relay_3', 'boolean'),
    ('Relay_4', 'boolean'),
    ('Analog_1', 'numeric'),
    ('Analog_2', 'numeric'),
    ('Analog_3', 'numeric'),
    ('Analog_4', 'numeric'),
    ('Digital_1', 'boolean'),
    ('Digital_2', 'boolean'),
    ('Digital_3', 'boolean'),
    ('Digital_4', 'boolean'),
]


def parse_legacy_v1_telemetry(payload: str) -> dict[str, tuple[Any, str]]:
    """Parse a legacy v1 CSV telemetry payload.

    Args:
        payload: 12-value comma-separated string, e.g. ``"0,0,1,0,3.2,0.0,1.5,0.8,1,0,0,1"``.

    Returns:
        Dict mapping stream key → ``(value, data_type)``.
        Boolean fields are returned as Python bools; numeric as floats.

    Raises:
        ValueError: If the payload does not contain exactly 12 comma-separated values.
    """
    parts = [p.strip() for p in payload.strip().split(',')]
    if len(parts) != 12:
        raise ValueError(f'Legacy v1 telemetry expects 12 CSV fields, got {len(parts)}')

    result: dict[str, tuple[Any, str]] = {}
    for i, (key, data_type) in enumerate(LEGACY_V1_TELEMETRY_FIELDS):
        raw = parts[i]
        try:
            if data_type == 'boolean':
                value: Any = bool(int(float(raw)))
            else:
                value = float(raw)
        except ValueError:
            raise ValueError(f'Cannot parse field {i} ("{key}"): invalid value "{raw}"')
        result[key] = (value, data_type)

    return result


def parse_json_telemetry(payload: str) -> dict[str, Any]:
    """Parse a That Place v2 JSON key-value telemetry payload.

    Args:
        payload: JSON object string, e.g. ``'{"temperature": 23.4, "humidity": 60}'``.

    Returns:
        Dict mapping stream key → raw value (type depends on the JSON value).

    Raises:
        ValueError: If the payload is not valid JSON or not a JSON object.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f'Invalid JSON payload: {e}') from e

    if not isinstance(data, dict):
        raise ValueError(f'JSON telemetry payload must be an object, got {type(data).__name__}')

    return data
