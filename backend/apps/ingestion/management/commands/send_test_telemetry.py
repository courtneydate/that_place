"""Django management command: send_test_telemetry.

End-to-end smoke test for the ingestion pipeline. Creates test devices
(if they don't already exist), then continuously publishes MQTT telemetry
for both a legacy v1 Scout and a That Place v1 Scout (with battery/signal)
so the health monitoring pipeline can be observed in real time.

Usage::

    docker-compose exec backend python manage.py send_test_telemetry

Options::

    --legacy-serial   Serial number for the legacy v1 test device (default: TEST-LEGACY-001)
    --v2-serial       Serial number for the v2 test device (default: TEST-V2-001)
    --duration        Total seconds to run (default: 120)
    --interval        Seconds between each publish round (default: 5)
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
from apps.devices.models import Device, DeviceHealth, DeviceType, Site
from apps.readings.models import Stream, StreamReading

logger = logging.getLogger(__name__)

TEST_TENANT_NAME = 'That Place Test Tenant'
TEST_SITE_NAME = 'Test Site'
TEST_DEVICE_TYPE_NAME = 'Test Scout'

LEGACY_PAYLOAD = '1,0,1,0,3.20,0.00,1.50,9.90,1,0,1,0'


def _v2_payload(round_num: int) -> str:
    """Return a v2 JSON payload with slowly varying battery and signal."""
    # Battery drifts from 90 down toward 70 over the run; signal varies ±5 dBm
    battery = max(70, 90 - round_num)
    signal = -60 - (round_num % 5)
    return (
        f'{{"Relay_1": true, "Analog_1": 3.20, "Digital_1": true, '
        f'"temperature": 22.5, "_battery": {battery}, "_signal": {signal}}}'
    )


class Command(BaseCommand):
    """Publish test MQTT telemetry continuously and verify health records update."""

    help = 'Smoke test the ingestion pipeline and health monitoring end-to-end.'

    def add_arguments(self, parser):
        """Register command-line arguments."""
        parser.add_argument('--legacy-serial', default='TEST-LEGACY-001')
        parser.add_argument('--v2-serial', default='TEST-V2-001')
        parser.add_argument('--duration', type=int, default=120,
                            help='Total seconds to run (default: 120).')
        parser.add_argument('--interval', type=int, default=5,
                            help='Seconds between each publish round (default: 5).')
        parser.add_argument('--broker-host',
                            default=getattr(settings, 'MQTT_BROKER_HOST', 'mosquitto'))
        parser.add_argument('--broker-port', type=int, default=1883)
        parser.add_argument('--cleanup', action='store_true',
                            help='Delete test data after the run.')

    def handle(self, *args, **options):
        """Run the continuous ingestion / health smoke test."""
        legacy_serial = options['legacy_serial']
        v2_serial = options['v2_serial']
        duration = options['duration']
        interval = options['interval']
        broker_host = options['broker_host']
        broker_port = options['broker_port']
        cleanup = options['cleanup']

        total_rounds = duration // interval

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== That Place Ingestion + Health Smoke Test ===\n'
        ))
        self.stdout.write(
            f'   Duration : {duration}s   Interval : {interval}s   '
            f'Rounds : {total_rounds}\n'
        )

        # ------------------------------------------------------------------
        # Step 1: Ensure test devices exist and are active
        # ------------------------------------------------------------------
        self.stdout.write('1. Setting up test devices…')
        legacy_device, v2_device = self._setup_devices(legacy_serial, v2_serial)
        self.stdout.write(self.style.SUCCESS(
            f'   Legacy device : {legacy_device.serial_number} (status={legacy_device.status})'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'   v2 device     : {v2_device.serial_number} (status={v2_device.status})\n'
        ))

        # ------------------------------------------------------------------
        # Step 2: Record baselines
        # ------------------------------------------------------------------
        legacy_before = StreamReading.objects.filter(stream__device=legacy_device).count()
        v2_before = StreamReading.objects.filter(stream__device=v2_device).count()

        legacy_topic = f'fm/mm/{legacy_serial}/telemetry'
        v2_topic = f'that-place/scout/{v2_serial}/telemetry'

        # ------------------------------------------------------------------
        # Step 3: Publish loop
        # ------------------------------------------------------------------
        self.stdout.write(f'2. Publishing every {interval}s for {duration}s '
                          f'(Ctrl-C to stop early)…\n')
        self.stdout.write(
            f'   {"Round":<6} {"Elapsed":>8}   '
            f'{"v2 activity":<12} {"online":<8} {"battery":>8} {"signal":>8}'
        )
        self.stdout.write('   ' + '-' * 58)

        start = time.time()
        round_num = 0

        try:
            while round_num < total_rounds:
                v2_payload = _v2_payload(round_num)

                self._publish(broker_host, broker_port, [
                    (legacy_topic, LEGACY_PAYLOAD),
                    (v2_topic, v2_payload),
                ])

                # Wait a beat for Celery, then print health snapshot
                time.sleep(min(2, interval))
                elapsed = time.time() - start

                v2_device.refresh_from_db()
                try:
                    health = v2_device.devicehealth
                    activity = health.activity_level
                    online = 'yes' if health.is_online else 'NO'
                    battery = f'{health.battery_level}%' if health.battery_level is not None else '—'
                    signal = f'{health.signal_strength} dBm' if health.signal_strength is not None else '—'
                except DeviceHealth.DoesNotExist:
                    activity, online, battery, signal = 'no data', '—', '—', '—'

                self.stdout.write(
                    f'   {round_num + 1:<6} {elapsed:>7.1f}s   '
                    f'{activity:<12} {online:<8} {battery:>8} {signal:>8}'
                )
                self.stdout.flush()

                round_num += 1
                remaining = interval - 2
                if remaining > 0 and round_num < total_rounds:
                    time.sleep(remaining)

        except KeyboardInterrupt:
            self.stdout.write('\n\n   Stopped early.\n')

        # ------------------------------------------------------------------
        # Step 4: Final verification
        # ------------------------------------------------------------------
        self.stdout.write('\n3. Final checks…\n')
        all_passed = True
        all_passed &= self._check_device(legacy_device, legacy_before, round_num * 12)
        all_passed &= self._check_device(v2_device, v2_before, round_num * 4)
        all_passed &= self._check_health(v2_device)

        # ------------------------------------------------------------------
        # Step 5: Optional cleanup
        # ------------------------------------------------------------------
        if cleanup:
            self.stdout.write('\n4. Cleaning up test data…')
            self._cleanup(legacy_device, v2_device)
            self.stdout.write(self.style.SUCCESS('   Test devices and readings removed.'))

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
                'topic_format': 'that_place_v1',
            },
        )
        if v2_device.status != Device.Status.ACTIVE:
            v2_device.status = Device.Status.ACTIVE
            v2_device.save(update_fields=['status'])

        return legacy_device, v2_device

    def _publish(self, host: str, port: int, messages: list[tuple[str, str]]) -> None:
        """Connect to the MQTT broker and publish a list of (topic, payload) pairs."""
        client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id='that-place-test-publisher')
        client.connect(host, port, keepalive=10)
        client.loop_start()
        for topic, payload in messages:
            client.publish(topic, payload, qos=1)
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()

    def _check_device(self, device: Device, readings_before: int, expected_new_readings: int) -> bool:
        """Report on StreamReadings created for a device. Returns True if check passed."""
        readings_after = StreamReading.objects.filter(stream__device=device).count()
        new_readings = readings_after - readings_before
        streams = Stream.objects.filter(device=device)

        passed = new_readings >= expected_new_readings
        status_icon = self.style.SUCCESS('✓') if passed else self.style.ERROR('✗')
        self.stdout.write(
            f'   {status_icon}  {device.serial_number} ({device.topic_format})'
        )
        self.stdout.write(
            f'      Streams  : {streams.count()} — '
            + ', '.join(f'{s.key} ({s.data_type})' for s in streams[:6])
            + (' …' if streams.count() > 6 else '')
        )
        self.stdout.write(
            f'      Readings : {new_readings} new (expected ≥ {expected_new_readings})'
        )
        return passed

    def _check_health(self, device: Device) -> bool:
        """Verify a DeviceHealth record exists and is populated. Returns True if passed."""
        try:
            health = device.devicehealth
        except DeviceHealth.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                f'   ✗  {device.serial_number} — no DeviceHealth record found'
            ))
            return False

        passed = (
            health.last_seen_at is not None
            and health.battery_level is not None
            and health.signal_strength is not None
        )
        status_icon = self.style.SUCCESS('✓') if passed else self.style.ERROR('✗')
        self.stdout.write(
            f'   {status_icon}  {device.serial_number} health record'
        )
        self.stdout.write(
            f'      Activity : {health.activity_level}   Online : {health.is_online}'
        )
        self.stdout.write(
            f'      Battery  : {health.battery_level}%   '
            f'Signal : {health.signal_strength} dBm'
        )
        self.stdout.write(
            f'      Last seen: {health.last_seen_at}'
        )
        return passed

    def _cleanup(self, *devices: Device) -> None:
        """Delete StreamReadings, Streams, and the test devices themselves."""
        for device in devices:
            StreamReading.objects.filter(stream__device=device).delete()
            Stream.objects.filter(device=device).delete()
            device.delete()
