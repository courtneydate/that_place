"""Seed the deterministic fixture used by the Playwright E2E suite.

Idempotent: re-running clears volatile state (StreamReadings, Alerts,
Notifications, CommandLogs) but preserves the Tenant and user accounts so
existing browser storage states stay valid.

Usage::

    docker-compose exec backend python manage.py seed_e2e

Creates:

* That Place Admin user ``e2e_tp_admin@test.thatplace.local``
* Tenant Admin user ``e2e_tenant_admin@test.thatplace.local``
* Tenant ``E2E Tenant`` with site ``Default Site``
* Device type ``E2E Test Scout`` (commands, stream type hints, status mappings)
* One approved device ``E2E-DEVICE-001`` ready to ingest telemetry

Both users share the password ``e2e-password`` unless overridden with
``--password``.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import Tenant, TenantUser, User
from apps.alerts.models import Alert
from apps.devices.models import CommandLog, Device, DeviceHealth, DeviceType, Site
from apps.ingestion.mqtt_credentials import MQTTCredentialService
from apps.notifications.models import Notification
from apps.readings.models import Stream, StreamReading

E2E_PUBLISHER_USERNAME = 'e2e-publisher'
E2E_PUBLISHER_PASSWORD = 'e2e-publisher-password'  # noqa: S105 — fixed dev creds for E2E only
E2E_PUBLISHER_ROLE = 'e2e-publisher'

TP_ADMIN_EMAIL = 'e2e_tp_admin@test.thatplace.local'
TENANT_ADMIN_EMAIL = 'e2e_tenant_admin@test.thatplace.local'
TENANT_NAME = 'E2E Tenant'
SITE_NAME = 'Default Site'
DEVICE_TYPE_NAME = 'E2E Test Scout'
DEVICE_SERIAL = 'E2E-DEVICE-001'


class Command(BaseCommand):
    help = 'Seed the deterministic Playwright E2E fixture (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='e2e-password')

    @transaction.atomic
    def handle(self, *args, **options):
        password = options['password']

        tp_admin, created = User.objects.get_or_create(
            email=TP_ADMIN_EMAIL,
            defaults={'is_that_place_admin': True, 'is_active': True},
        )
        tp_admin.is_that_place_admin = True
        tp_admin.is_active = True
        tp_admin.set_password(password)
        tp_admin.save()
        self._echo('TP Admin', tp_admin.email, created)

        tenant, created = Tenant.objects.get_or_create(
            slug=slugify(TENANT_NAME),
            defaults={'name': TENANT_NAME, 'is_active': True},
        )
        if not tenant.is_active:
            tenant.is_active = True
            tenant.save(update_fields=['is_active'])
        self._echo('Tenant', tenant.name, created)

        tenant_admin, created = User.objects.get_or_create(
            email=TENANT_ADMIN_EMAIL,
            defaults={'is_active': True},
        )
        tenant_admin.is_active = True
        tenant_admin.set_password(password)
        tenant_admin.save()
        TenantUser.objects.update_or_create(
            user=tenant_admin,
            defaults={'tenant': tenant, 'role': TenantUser.Role.ADMIN},
        )
        self._echo('Tenant Admin', tenant_admin.email, created)

        site, created = Site.objects.get_or_create(
            tenant=tenant,
            name=SITE_NAME,
        )
        self._echo('Site', site.name, created)

        dt_defaults = {
            'name': DEVICE_TYPE_NAME,
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 10,
            'command_ack_timeout_seconds': 30,
            'stream_type_definitions': [
                {'key': 'temperature', 'label': 'Temperature', 'data_type': 'numeric', 'unit': '°C'},
                {'key': 'Relay_1', 'label': 'Relay 1', 'data_type': 'boolean', 'unit': ''},
            ],
            'commands': [
                {
                    'name': 'set_relay',
                    'label': 'Set Relay',
                    'description': 'Turn the relay on or off.',
                    'params': [
                        {'key': 'state', 'label': 'State', 'type': 'bool', 'default': True},
                    ],
                }
            ],
        }
        device_type, created = DeviceType.objects.update_or_create(
            slug=slugify(DEVICE_TYPE_NAME),
            defaults=dt_defaults,
        )
        self._echo('Device type', device_type.name, created)

        device, created = Device.objects.get_or_create(
            serial_number=DEVICE_SERIAL,
            defaults={
                'tenant': tenant,
                'site': site,
                'device_type': device_type,
                'name': 'E2E Scout 001',
                'status': Device.Status.ACTIVE,
                'topic_format': Device.TopicFormat.THAT_PLACE_V1,
            },
        )
        if device.status != Device.Status.ACTIVE:
            device.status = Device.Status.ACTIVE
            device.save(update_fields=['status'])
        self._echo('Device', device.serial_number, created)

        # Reset volatile per-run state so reseeding gives a clean slate without
        # invalidating the cached browser storage from global-setup. Also wipe
        # any residual devices/sites/tenants left over from previous spec runs
        # (e.g. the onboarding spec creates throwaway tenants) so each spec
        # starts from a deterministic world.
        deleted_readings = StreamReading.objects.filter(stream__device__tenant=tenant).delete()[0]
        deleted_streams = Stream.objects.filter(device__tenant=tenant).delete()[0]
        deleted_alerts = Alert.objects.filter(tenant=tenant).delete()[0]
        deleted_cmds = CommandLog.objects.filter(device__tenant=tenant).delete()[0]
        deleted_notes = Notification.objects.filter(user__tenantuser__tenant=tenant).delete()[0]
        DeviceHealth.objects.filter(device__tenant=tenant).delete()

        # Strip any leftover devices / sites in this tenant that aren't the
        # seeded canonical pair.
        Device.objects.filter(tenant=tenant).exclude(serial_number=DEVICE_SERIAL).delete()
        Site.objects.filter(tenant=tenant).exclude(name=SITE_NAME).delete()

        # Drop throwaway "E2E Onboard *" tenants created by the onboarding spec.
        Tenant.objects.filter(name__startswith='E2E Onboard').delete()

        self.stdout.write(self.style.SUCCESS(
            f'\nReset volatile state — readings={deleted_readings}, streams={deleted_streams}, '
            f'alerts={deleted_alerts}, commands={deleted_cmds}, notifications={deleted_notes}'
        ))
        # Dynsec client with broad publish access so the E2E spec can publish
        # telemetry payloads on any that-place/scout/+/# topic. Idempotent:
        # createRole / createClient fail silently if they already exist.
        self._ensure_e2e_publisher()

        self.stdout.write(self.style.SUCCESS('\nE2E fixture seeded. Password: ' + password))
        self.stdout.write(self.style.SUCCESS(
            f'MQTT publisher: {E2E_PUBLISHER_USERNAME} / {E2E_PUBLISHER_PASSWORD}'
        ))

    def _ensure_e2e_publisher(self):
        """Create or reset a fixed-credential dynsec client with publish access."""
        svc = MQTTCredentialService()
        # Try to create — if it exists, set the password to the known value.
        created = svc._send_commands([  # noqa: SLF001 — internal API by design
            {
                'command': 'createRole',
                'rolename': E2E_PUBLISHER_ROLE,
                'acls': [
                    {'acltype': 'publishClientSend', 'topic': 'that-place/scout/#',
                     'priority': 0, 'allow': True},
                    {'acltype': 'publishClientSend', 'topic': 'fm/mm/#',
                     'priority': 0, 'allow': True},
                ],
            },
            {
                'command': 'createClient',
                'username': E2E_PUBLISHER_USERNAME,
                'textname': 'Playwright E2E publisher',
                'roles': [{'rolename': E2E_PUBLISHER_ROLE}],
                'password': E2E_PUBLISHER_PASSWORD,
            },
        ])
        if not created:
            # Already exists — make sure the password matches.
            svc._send_commands([  # noqa: SLF001
                {
                    'command': 'setClientPassword',
                    'username': E2E_PUBLISHER_USERNAME,
                    'password': E2E_PUBLISHER_PASSWORD,
                },
            ])

    def _echo(self, label, name, created):
        verb = self.style.SUCCESS('created') if created else self.style.WARNING('exists ')
        self.stdout.write(f'  {verb}  {label:<14} {name}')
