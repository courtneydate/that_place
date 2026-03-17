"""Django management command: send_test_telemetry.

End-to-end smoke test for the ingestion pipeline. Creates test devices
(if they don't already exist), publishes MQTT telemetry messages for both
a legacy v1 Scout and a Fieldmouse v2 Scout, waits for Celery to process
them, then reports whether StreamReadings landed in the database.

Usage::

    docker-compose exec backend python manage.py send_test_telemetry

Options::

    --legacy-serial   Serial number for the legacy v1 test device (default: TEST-LEGACY-001)
    --v2-serial       Serial number for the v2 test device (default: TEST-V2-001)
    --wait            Seconds to wait for Celery processing (default: 5)
    --broker-host     MQTT broker hostname (default: from MQTT_BROKER_HOST env var or 'mosquitto')
    --broker-port     MQTT broker port (default: 1883)
    --cleanup         Delete test devices and all their readings after the test

WARNING: This command writes to the database. Do not run against production.
"""
import logging
import time

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from paho.mqtt.client import CallbackAPIVersion

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import Stream, StreamReading

logger = logging.getLogger(__name__)

TEST_TENANT_NAME = 'Fieldmouse Test Tenant'
TEST_SITE_NAME = 'Test Site'
TEST_DEVICE_TYPE_NAME = 'Test Scout'

LEGACY_PAYLOAD = '1,0,1,0,3.20,0.00,1.50,9.90,1,0,1,0'
V2_PAYLOAD = '{"Relay_1": true, "Analog_1": 3.20, "Digital_1": true, "temperature": 22.5}'


class Command(BaseCommand):
    """Publish test MQTT telemetry and verify StreamReadings are created."""

    help = 'Smoke test the ingestion pipeline end-to-end.'

    def add_arguments(self, parser):
        """Register command-line arguments."""
        parser.add_argument('--legacy-serial', default='TEST-LEGACY-001')
        parser.add_argument('--v2-serial', default='TEST-V2-001')
        parser.add_argument('--wait', type=int, default=5,
                            help='Seconds to wait for Celery processing.')
        parser.add_argument('--broker-host',
                            default=getattr(settings, 'MQTT_BROKER_HOST', 'mosquitto'))
        parser.add_argument('--broker-port', type=int, default=1883)
        parser.add_argument('--cleanup', action='store_true',
                            help='Delete test data after the run.')

    def handle(self, *args, **options):
        """Run the end-to-end ingestion smoke test."""
        legacy_serial = options['legacy_serial']
        v2_serial = options['v2_serial']
        wait_seconds = options['wait']
        broker_host = options['broker_host']
        broker_port = options['broker_port']
        cleanup = options['cleanup']

        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Fieldmouse Ingestion Smoke Test ===\n'))

        # ------------------------------------------------------------------
        # Step 1: Ensure test devices exist and are active
        # ------------------------------------------------------------------
        self.stdout.write('1. Setting up test devices…')
        legacy_device, v2_device = self._setup_devices(legacy_serial, v2_serial)
        self.stdout.write(self.style.SUCCESS(
            f'   Legacy device : {legacy_device.serial_number} (status={legacy_device.status})'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'   v2 device     : {v2_device.serial_number} (status={v2_device.status})'
        ))

        # ------------------------------------------------------------------
        # Step 2: Record reading counts before publishing
        # ------------------------------------------------------------------
        legacy_before = StreamReading.objects.filter(stream__device=legacy_device).count()
        v2_before = StreamReading.objects.filter(stream__device=v2_device).count()

        # ------------------------------------------------------------------
        # Step 3: Publish MQTT messages
        # ------------------------------------------------------------------
        self.stdout.write(f'\n2. Publishing to broker {broker_host}:{broker_port}…')
        legacy_topic = f'fm/mm/{legacy_serial}/telemetry'
        v2_topic = f'fieldmouse/scout/{v2_serial}/telemetry'

        self._publish(broker_host, broker_port, [
            (legacy_topic, LEGACY_PAYLOAD),
            (v2_topic, V2_PAYLOAD),
        ])

        self.stdout.write(f'   Legacy → {legacy_topic}')
        self.stdout.write(f'            payload: {LEGACY_PAYLOAD}')
        self.stdout.write(f'   v2     → {v2_topic}')
        self.stdout.write(f'            payload: {V2_PAYLOAD}')

        # ------------------------------------------------------------------
        # Step 4: Wait for Celery
        # ------------------------------------------------------------------
        self.stdout.write(f'\n3. Waiting {wait_seconds}s for Celery to process…')
        for i in range(wait_seconds, 0, -1):
            self.stdout.write(f'   {i}…', ending='\r')
            self.stdout.flush()
            time.sleep(1)
        self.stdout.write('')

        # ------------------------------------------------------------------
        # Step 5: Verify results
        # ------------------------------------------------------------------
        self.stdout.write('4. Checking database…\n')
        all_passed = True

        all_passed &= self._check_device(legacy_device, legacy_before, expected_new_readings=12)
        all_passed &= self._check_device(v2_device, v2_before, expected_new_readings=4)

        # ------------------------------------------------------------------
        # Step 6: Optional cleanup
        # ------------------------------------------------------------------
        if cleanup:
            self.stdout.write('\n5. Cleaning up test data…')
            self._cleanup(legacy_device, v2_device)
            self.stdout.write(self.style.SUCCESS('   Test devices and readings removed.'))

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.stdout.write('')
        if all_passed:
            self.stdout.write(self.style.SUCCESS('=== All checks passed ✓ ===\n'))
        else:
            self.stdout.write(self.style.ERROR('=== Some checks FAILED — see above ===\n'))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _setup_devices(self, legacy_serial: str, v2_serial: str):
        """Get or create test tenant, site, device type, and both test devices."""
        tenant, _ = Tenant.objects.get_or_create(
            name=TEST_TENANT_NAME,
            defaults={'slug': slugify(TEST_TENANT_NAME)},
        )
        site, _ = Site.objects.get_or_create(
            tenant=tenant,
            name=TEST_SITE_NAME,
        )
        device_type, _ = DeviceType.objects.get_or_create(
            slug=slugify(TEST_DEVICE_TYPE_NAME),
            defaults={
                'name': TEST_DEVICE_TYPE_NAME,
                'connection_type': 'mqtt',
                'is_push': True,
                'stream_type_definitions': [],
                'commands': [],
            },
        )

        legacy_device, _ = Device.objects.get_or_create(
            serial_number=legacy_serial,
            defaults={
                'tenant': tenant,
                'site': site,
                'device_type': device_type,
                'name': f'Test Legacy Scout ({legacy_serial})',
                'status': Device.Status.ACTIVE,
                'topic_format': 'legacy_v1',
            },
        )
        # Ensure active even if it already existed
        if legacy_device.status != Device.Status.ACTIVE:
            legacy_device.status = Device.Status.ACTIVE
            legacy_device.save(update_fields=['status'])

        v2_device, _ = Device.objects.get_or_create(
            serial_number=v2_serial,
            defaults={
                'tenant': tenant,
                'site': site,
                'device_type': device_type,
                'name': f'Test v2 Scout ({v2_serial})',
                'status': Device.Status.ACTIVE,
                'topic_format': 'fieldmouse_v2',
            },
        )
        if v2_device.status != Device.Status.ACTIVE:
            v2_device.status = Device.Status.ACTIVE
            v2_device.save(update_fields=['status'])

        return legacy_device, v2_device

    def _publish(self, host: str, port: int, messages: list[tuple[str, str]]) -> None:
        """Connect to the MQTT broker and publish a list of (topic, payload) pairs."""
        client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id='fieldmouse-test-publisher')
        client.connect(host, port, keepalive=10)
        client.loop_start()
        for topic, payload in messages:
            client.publish(topic, payload, qos=1)
        # Give paho a moment to send before disconnecting
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()

    def _check_device(self, device: Device, readings_before: int, expected_new_readings: int) -> bool:
        """Report on StreamReadings created for a device. Returns True if check passed."""
        readings_after = StreamReading.objects.filter(stream__device=device).count()
        new_readings = readings_after - readings_before
        streams = Stream.objects.filter(device=device)

        passed = new_readings == expected_new_readings

        status_icon = self.style.SUCCESS('✓') if passed else self.style.ERROR('✗')
        self.stdout.write(
            f'   {status_icon}  {device.serial_number} ({device.topic_format})'
        )
        self.stdout.write(
            f'      Streams    : {streams.count()} record(s) — '
            + ', '.join(f'{s.key} ({s.data_type})' for s in streams[:6])
            + (' …' if streams.count() > 6 else '')
        )
        self.stdout.write(
            f'      Readings   : {new_readings} new (expected {expected_new_readings})'
        )

        if not passed:
            self.stdout.write(self.style.ERROR(
                f'      FAIL: expected {expected_new_readings} new readings, got {new_readings}'
            ))

        return passed

    def _cleanup(self, *devices: Device) -> None:
        """Delete StreamReadings, Streams, and the test devices themselves."""
        for device in devices:
            StreamReading.objects.filter(stream__device=device).delete()
            Stream.objects.filter(device=device).delete()
            device.delete()
