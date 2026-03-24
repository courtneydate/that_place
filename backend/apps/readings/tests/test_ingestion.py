"""Tests for Sprint 7: Stream ingestion, auto-discovery, and payload parsing.

All ingestion tests call the Celery task function directly (synchronously).
No MQTT broker or real Celery workers required.

Ref: SPEC.md § Feature: MQTT Ingestion Pipeline
     SPEC.md § Feature: Stream Discovery & Configuration
"""
import json

import pytest
from django.utils.text import slugify

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceType, Site
from apps.ingestion.parsers import parse_json_telemetry, parse_legacy_v1_telemetry
from apps.ingestion.tasks import process_mqtt_message
from apps.readings.models import Stream, StreamReading

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_device_type(name='Scout', stream_defs=None):
    return DeviceType.objects.create(
        name=name,
        slug=slugify(name),
        connection_type='mqtt',
        is_push=True,
        stream_type_definitions=stream_defs or [],
        commands=[],
    )


def make_device(tenant, serial, status=Device.Status.ACTIVE, device_type=None,
                topic_format='that_place_v1'):
    site = Site.objects.create(tenant=tenant, name='Test Site')
    dt = device_type or make_device_type()
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=dt,
        name='Test Device',
        serial_number=serial,
        status=status,
        topic_format=topic_format,
    )


# ---------------------------------------------------------------------------
# Parser unit tests — legacy v1 CSV
# ---------------------------------------------------------------------------


class TestParseLegacyV1Telemetry:

    def test_parses_twelve_fields(self):
        result = parse_legacy_v1_telemetry('0,0,1,0,3.2,0.0,1.5,0.8,1,0,0,1')
        assert len(result) == 12

    def test_relay_fields_are_boolean(self):
        result = parse_legacy_v1_telemetry('1,0,1,0,0,0,0,0,0,0,0,0')
        assert result['Relay_1'] == (True, 'boolean')
        assert result['Relay_2'] == (False, 'boolean')
        assert result['Relay_3'] == (True, 'boolean')
        assert result['Relay_4'] == (False, 'boolean')

    def test_analog_fields_are_numeric(self):
        result = parse_legacy_v1_telemetry('0,0,0,0,3.2,1.5,0.0,9.9,0,0,0,0')
        assert result['Analog_1'] == (3.2, 'numeric')
        assert result['Analog_2'] == (1.5, 'numeric')

    def test_digital_fields_are_boolean(self):
        result = parse_legacy_v1_telemetry('0,0,0,0,0,0,0,0,1,0,1,0')
        assert result['Digital_1'] == (True, 'boolean')
        assert result['Digital_2'] == (False, 'boolean')
        assert result['Digital_3'] == (True, 'boolean')
        assert result['Digital_4'] == (False, 'boolean')

    def test_all_zeros(self):
        result = parse_legacy_v1_telemetry('0,0,0,0,0,0,0,0,0,0,0,0')
        assert all(v == 0 or v is False for v, _ in result.values())

    def test_wrong_field_count_raises(self):
        with pytest.raises(ValueError, match='12'):
            parse_legacy_v1_telemetry('0,0,0')

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            parse_legacy_v1_telemetry('X,0,0,0,0,0,0,0,0,0,0,0')


# ---------------------------------------------------------------------------
# Parser unit tests — v2 JSON
# ---------------------------------------------------------------------------


class TestParseJsonTelemetry:

    def test_parses_key_value_pairs(self):
        result = parse_json_telemetry('{"temperature": 23.4, "humidity": 60}')
        assert result == {'temperature': 23.4, 'humidity': 60}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match='Invalid JSON'):
            parse_json_telemetry('not json')

    def test_non_object_raises(self):
        with pytest.raises(ValueError, match='object'):
            parse_json_telemetry('[1, 2, 3]')

    def test_empty_object_returns_empty_dict(self):
        assert parse_json_telemetry('{}') == {}

    def test_nested_values_preserved(self):
        result = parse_json_telemetry('{"Relay_1": 1, "Analog_1": 3.14, "label": "on"}')
        assert result['Relay_1'] == 1
        assert result['Analog_1'] == 3.14
        assert result['label'] == 'on'


# ---------------------------------------------------------------------------
# Ingestion task — happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngestionHappyPath:

    def test_v2_json_creates_stream_readings(self):
        tenant = make_tenant()
        device = make_device(tenant, 'SCOUT-001', topic_format='that_place_v1')
        payload = json.dumps({'temperature': 23.4, 'humidity': 60.0})

        process_mqtt_message('that-place/scout/SCOUT-001/telemetry', payload)

        assert StreamReading.objects.filter(stream__device=device).count() == 2

    def test_v2_json_correct_values_stored(self):
        tenant = make_tenant(name='Beta')
        device = make_device(tenant, 'SCOUT-002', topic_format='that_place_v1')
        payload = json.dumps({'temperature': 23.4})

        process_mqtt_message('that-place/scout/SCOUT-002/telemetry', payload)

        reading = StreamReading.objects.get(stream__device=device, stream__key='temperature')
        assert reading.value == 23.4

    def test_legacy_v1_creates_twelve_readings(self):
        tenant = make_tenant(name='Legacy Co')
        device = make_device(tenant, 'UNIT-001', topic_format='legacy_v1')

        process_mqtt_message('fm/mm/UNIT-001/telemetry', '0,1,0,0,3.2,0.0,1.5,0.8,1,0,0,1')

        assert StreamReading.objects.filter(stream__device=device).count() == 12

    def test_legacy_v1_relay_stored_as_boolean_value(self):
        tenant = make_tenant(name='Legacy Co 2')
        device = make_device(tenant, 'UNIT-002', topic_format='legacy_v1')

        process_mqtt_message('fm/mm/UNIT-002/telemetry', '1,0,0,0,0,0,0,0,0,0,0,0')

        reading = StreamReading.objects.get(stream__device=device, stream__key='Relay_1')
        assert reading.value is True

    def test_bridged_device_v2_creates_readings(self):
        tenant = make_tenant(name='Bridge Co')
        device = make_device(tenant, 'SENSOR-007', topic_format='that_place_v1')
        payload = json.dumps({'pressure': 1013.2, 'flow': 4.5})

        process_mqtt_message('that-place/scout/SCOUT-001/SENSOR-007/telemetry', payload)

        assert StreamReading.objects.filter(stream__device=device).count() == 2


# ---------------------------------------------------------------------------
# Ingestion task — stream auto-discovery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStreamAutoDiscovery:

    def test_new_key_creates_stream_record(self):
        tenant = make_tenant(name='Discovery Co')
        device = make_device(tenant, 'DISC-001')
        payload = json.dumps({'new_sensor': 42.0})

        process_mqtt_message('that-place/scout/DISC-001/telemetry', payload)

        assert Stream.objects.filter(device=device, key='new_sensor').exists()

    def test_auto_created_stream_defaults_to_numeric(self):
        tenant = make_tenant(name='Discovery Co 2')
        device = make_device(tenant, 'DISC-002')
        payload = json.dumps({'unknown_key': 99.9})

        process_mqtt_message('that-place/scout/DISC-002/telemetry', payload)

        stream = Stream.objects.get(device=device, key='unknown_key')
        assert stream.data_type == Stream.DataType.NUMERIC

    def test_second_message_reuses_existing_stream(self):
        tenant = make_tenant(name='Discovery Co 3')
        device = make_device(tenant, 'DISC-003')
        payload = json.dumps({'temp': 20.0})

        process_mqtt_message('that-place/scout/DISC-003/telemetry', payload)
        process_mqtt_message('that-place/scout/DISC-003/telemetry', payload)

        assert Stream.objects.filter(device=device, key='temp').count() == 1
        assert StreamReading.objects.filter(stream__device=device).count() == 2

    def test_device_type_definition_sets_data_type(self):
        tenant = make_tenant(name='Typed Co')
        stream_defs = [
            {'key': 'Relay_1', 'label': 'Relay 1', 'data_type': 'boolean', 'unit': ''},
        ]
        dt = make_device_type(name='Typed Scout', stream_defs=stream_defs)
        device = make_device(tenant, 'TYPED-001', device_type=dt)
        payload = json.dumps({'Relay_1': 1})

        process_mqtt_message('that-place/scout/TYPED-001/telemetry', payload)

        stream = Stream.objects.get(device=device, key='Relay_1')
        assert stream.data_type == Stream.DataType.BOOLEAN

    def test_device_type_definition_sets_label_and_unit(self):
        tenant = make_tenant(name='Label Co')
        stream_defs = [
            {'key': 'temperature', 'label': 'Air Temperature', 'data_type': 'numeric', 'unit': '°C'},
        ]
        dt = make_device_type(name='Label Scout', stream_defs=stream_defs)
        device = make_device(tenant, 'LABEL-001', device_type=dt)
        payload = json.dumps({'temperature': 22.5})

        process_mqtt_message('that-place/scout/LABEL-001/telemetry', payload)

        stream = Stream.objects.get(device=device, key='temperature')
        assert stream.label == 'Air Temperature'
        assert stream.unit == '°C'

    def test_legacy_v1_streams_have_correct_data_types(self):
        tenant = make_tenant(name='Legacy Types')
        device = make_device(tenant, 'LT-001', topic_format='legacy_v1')

        process_mqtt_message('fm/mm/LT-001/telemetry', '1,0,0,0,3.2,0.0,0.0,0.0,1,0,0,0')

        relay = Stream.objects.get(device=device, key='Relay_1')
        analog = Stream.objects.get(device=device, key='Analog_1')
        digital = Stream.objects.get(device=device, key='Digital_1')
        assert relay.data_type == Stream.DataType.BOOLEAN
        assert analog.data_type == Stream.DataType.NUMERIC
        assert digital.data_type == Stream.DataType.BOOLEAN


# ---------------------------------------------------------------------------
# Ingestion task — unapproved / unknown devices rejected
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngestionRejection:

    def test_unknown_device_creates_no_readings(self):
        process_mqtt_message('that-place/scout/UNKNOWN-999/telemetry', '{"temp": 1}')
        assert StreamReading.objects.count() == 0

    def test_pending_device_creates_no_readings(self):
        tenant = make_tenant(name='Pending Co')
        device = make_device(tenant, 'PEND-001', status=Device.Status.PENDING)

        process_mqtt_message('that-place/scout/PEND-001/telemetry', '{"temp": 1}')

        assert StreamReading.objects.filter(stream__device=device).count() == 0

    def test_deactivated_device_creates_no_readings(self):
        tenant = make_tenant(name='Deactivated Co')
        device = make_device(tenant, 'DEACT-001', status=Device.Status.DEACTIVATED)

        process_mqtt_message('that-place/scout/DEACT-001/telemetry', '{"temp": 1}')

        assert StreamReading.objects.filter(stream__device=device).count() == 0

    def test_invalid_payload_creates_no_readings(self):
        tenant = make_tenant(name='Bad Payload Co')
        device = make_device(tenant, 'BAD-001')

        process_mqtt_message('that-place/scout/BAD-001/telemetry', 'not valid json')

        assert StreamReading.objects.filter(stream__device=device).count() == 0

    def test_unmatched_topic_creates_no_readings(self):
        process_mqtt_message('some/unknown/topic', '{"temp": 1}')
        assert StreamReading.objects.count() == 0

    def test_non_telemetry_message_type_creates_no_readings(self):
        """Relay and admin topics must not create StreamReadings."""
        tenant = make_tenant(name='Non-Telem Co')
        device = make_device(tenant, 'NT-001', topic_format='legacy_v1')

        process_mqtt_message('fm/mm/NT-001/relays', '1,0,0,0')

        assert StreamReading.objects.filter(stream__device=device).count() == 0
