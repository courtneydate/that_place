"""Seed a realistic StreamReadings dataset for the Sprint 25 perf audit.

Generates ``--count`` readings (default 100,000) across a tenant + site +
device + stream tree, distributed over ``--days`` days backwards from now.
The fixture is independent of the Playwright E2E seed — it lives under its
own tenant so perf testing can run against a deterministic, isolated world.

Usage::

    docker-compose exec backend python manage.py seed_perf_data
    docker-compose exec backend python manage.py seed_perf_data --count 250000 --days 60
    docker-compose exec backend python manage.py seed_perf_data --reset

Idempotent: re-running tops the dataset up to ``--count`` total. ``--reset``
deletes the perf tenant's readings + streams before regenerating.
"""
import math
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Tenant
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import Stream, StreamReading

PERF_TENANT_NAME = 'Perf Audit Tenant'
PERF_SITE_NAME = 'Perf Audit Site'
PERF_DEVICE_TYPE = 'Perf Audit Scout'
PERF_DEVICE_SERIAL = 'PERF-DEVICE-001'
PERF_DEVICE_NAME = 'Perf Audit Scout 001'
STREAM_KEYS = [
    ('temperature', 'numeric', '°C'),
    ('humidity', 'numeric', '%'),
    ('pressure', 'numeric', 'kPa'),
    ('battery', 'numeric', '%'),
]
BATCH_SIZE = 5_000


class Command(BaseCommand):
    help = 'Seed a realistic StreamReadings dataset for the Sprint 25 perf audit.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=100_000,
                            help='Total number of StreamReadings to ensure exist (default 100k).')
        parser.add_argument('--days', type=int, default=30,
                            help='Spread readings across this many days back from now (default 30).')
        parser.add_argument('--reset', action='store_true',
                            help='Wipe existing perf data before regenerating.')

    @transaction.atomic
    def handle(self, *args, **options):
        count = options['count']
        days = options['days']
        reset = options['reset']

        tenant, _ = Tenant.objects.get_or_create(
            slug=slugify(PERF_TENANT_NAME),
            defaults={'name': PERF_TENANT_NAME, 'is_active': True},
        )
        site, _ = Site.objects.get_or_create(tenant=tenant, name=PERF_SITE_NAME)
        device_type, _ = DeviceType.objects.update_or_create(
            slug=slugify(PERF_DEVICE_TYPE),
            defaults={
                'name': PERF_DEVICE_TYPE,
                'connection_type': DeviceType.ConnectionType.MQTT,
                'is_push': True,
                'stream_type_definitions': [
                    {'key': k, 'label': k.capitalize(), 'data_type': dt, 'unit': u}
                    for (k, dt, u) in STREAM_KEYS
                ],
            },
        )
        device, _ = Device.objects.get_or_create(
            serial_number=PERF_DEVICE_SERIAL,
            defaults={
                'tenant': tenant,
                'site': site,
                'device_type': device_type,
                'name': PERF_DEVICE_NAME,
                'status': Device.Status.ACTIVE,
                'topic_format': Device.TopicFormat.THAT_PLACE_V1,
            },
        )

        streams = []
        for key, dtype, unit in STREAM_KEYS:
            s, _ = Stream.objects.update_or_create(
                device=device, key=key,
                defaults={'label': key.capitalize(), 'unit': unit, 'data_type': dtype},
            )
            streams.append(s)

        if reset:
            self.stdout.write(self.style.WARNING('Resetting perf readings…'))
            StreamReading.objects.filter(stream__device=device).delete()

        existing = StreamReading.objects.filter(stream__device=device).count()
        target = max(0, count - existing)
        self.stdout.write(
            f'Tenant : {tenant.name}\n'
            f'Device : {device.serial_number}  (id={device.id})\n'
            f'Streams: {[s.key for s in streams]}\n'
            f'Existing readings: {existing}    Need to add: {target}\n'
        )

        if target == 0:
            self.stdout.write(self.style.SUCCESS('Already at target count — nothing to do.'))
            return

        now = timezone.now()
        window = timedelta(days=days)
        rng = random.Random(42)

        readings_per_stream = math.ceil(target / len(streams))
        created = 0

        for stream in streams:
            base = self._base_value(stream.key)
            to_create = []
            for i in range(readings_per_stream):
                if created >= target:
                    break
                # Spread readings evenly across the window with small jitter.
                fraction = i / max(1, readings_per_stream - 1)
                offset = window * fraction
                jitter = timedelta(seconds=rng.uniform(-30, 30))
                ts = now - window + offset + jitter
                value = base + rng.uniform(-2, 2)
                to_create.append(StreamReading(stream=stream, value=value, timestamp=ts))
                created += 1
                if len(to_create) >= BATCH_SIZE:
                    StreamReading.objects.bulk_create(to_create)
                    self.stdout.write(f'  inserted {created:>8,} / {target:,}', ending='\r')
                    self.stdout.flush()
                    to_create = []
            if to_create:
                StreamReading.objects.bulk_create(to_create)
                self.stdout.write(f'  inserted {created:>8,} / {target:,}', ending='\r')
                self.stdout.flush()
            if created >= target:
                break

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Total readings on device {PERF_DEVICE_SERIAL}: '
            f'{StreamReading.objects.filter(stream__device=device).count():,}'
        ))

    @staticmethod
    def _base_value(key: str) -> float:
        """Return a sensible base value per stream key so readings look real."""
        return {
            'temperature': 22.0,
            'humidity': 55.0,
            'pressure': 101.3,
            'battery': 85.0,
        }.get(key, 0.0)
