"""Seed data for the NotificationEventType registry.

The registry is populated by a ``post_migrate`` signal handler (see apps.py)
rather than a data migration, so the v1 event types are present in every
environment — including the test database, which is built with
``--no-migrations`` and therefore never runs data migrations.

Seeding is idempotent: existing rows are left untouched, so an admin's edits
via the CRUD API are never overwritten.

Ref: ROADMAP Sprint 23; SPEC.md §9 (resolved)
"""
import logging

logger = logging.getLogger(__name__)

EVENT_TYPE_SEEDS = [
    # --- Tenant-audience system events (retrofitted from Sprint 19) ---
    {
        'key': 'device_approved',
        'label': 'Device approved',
        'description': 'A pending device was approved and is now active.',
        'severity': 'info',
        'audience': 'tenant',
        'default_channels': ['in_app'],
        'metadata_schema': ['device_name', 'serial_number'],
        'message_template': 'Device {device_name} ({serial_number}) was approved.',
    },
    {
        'key': 'device_offline',
        'label': 'Device offline',
        'description': 'A device has not reported within its offline threshold.',
        'severity': 'warning',
        'audience': 'tenant',
        'default_channels': ['in_app'],
        'metadata_schema': ['device_name', 'serial_number'],
        'message_template': 'Device {device_name} ({serial_number}) has gone offline.',
    },
    {
        'key': 'device_deleted',
        'label': 'Device deleted',
        'description': 'A device was deleted from the tenant.',
        'severity': 'info',
        'audience': 'tenant',
        'default_channels': ['in_app'],
        'metadata_schema': ['device_name', 'serial_number'],
        'message_template': 'Device {device_name} ({serial_number}) was deleted.',
    },
    {
        'key': 'datasource_poll_failure',
        'label': 'Data source poll failure',
        'description': 'A 3rd-party data source device has failed repeated polls.',
        'severity': 'warning',
        'audience': 'tenant',
        'default_channels': ['in_app'],
        'metadata_schema': ['device_name', 'serial_number', 'consecutive_failures'],
        'message_template': (
            'Data source device {device_name} has failed '
            '{consecutive_failures} consecutive polls.'
        ),
    },
    # --- Platform-admin events (Sprint 23 deep dive) ---
    {
        'key': 'device_pending_approval',
        'label': 'Device pending approval',
        'description': 'A device was registered and is awaiting That Place Admin approval.',
        'severity': 'info',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['device_name', 'serial_number', 'tenant_name'],
        'message_template': (
            'Device {device_name} ({serial_number}) is pending approval '
            'for tenant {tenant_name}.'
        ),
    },
    {
        'key': 'mqtt_broker_connectivity_failure',
        'label': 'MQTT broker connectivity failure',
        'description': 'The backend lost its connection to the MQTT broker.',
        'severity': 'critical',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['detail'],
        'message_template': 'MQTT broker connectivity lost: {detail}',
    },
    {
        'key': 'third_party_api_provider_failure',
        'label': '3rd-party API provider failure',
        'description': 'A 3rd-party API provider is failing across multiple tenants.',
        'severity': 'critical',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['provider_name', 'tenant_count'],
        'message_template': (
            '3rd-party API provider {provider_name} is failing across '
            '{tenant_count} tenants.'
        ),
    },
    {
        'key': 'feed_provider_poll_failure',
        'label': 'Feed provider poll failure',
        'description': 'A system feed provider failed every endpoint on a poll cycle.',
        'severity': 'warning',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['provider_name', 'provider_id'],
        'message_template': (
            'Feed provider {provider_name} failed all endpoints on its '
            'last poll cycle.'
        ),
    },
    {
        'key': 'tenant_created',
        'label': 'Tenant created',
        'description': 'A new tenant was created on the platform.',
        'severity': 'info',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['tenant_name', 'tenant_slug'],
        'message_template': 'New tenant created: {tenant_name}.',
    },
    {
        'key': 'tenant_deactivated',
        'label': 'Tenant deactivated',
        'description': 'A tenant was deactivated.',
        'severity': 'warning',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['tenant_name', 'tenant_slug'],
        'message_template': 'Tenant deactivated: {tenant_name}.',
    },
    {
        'key': 'certificate_expiry_warning',
        'label': 'Certificate / credential expiry',
        'description': 'A certificate or credential is approaching expiry.',
        'severity': 'warning',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['cert_name', 'days_remaining'],
        'message_template': 'Certificate {cert_name} expires in {days_remaining} days.',
    },
    {
        'key': 'backend_pipeline_failure',
        'label': 'Backend pipeline failure',
        'description': 'A backend Celery worker or ingestion pipeline failure occurred.',
        'severity': 'critical',
        'audience': 'platform_admin',
        'default_channels': ['in_app', 'email'],
        'metadata_schema': ['detail'],
        'message_template': 'Backend pipeline failure: {detail}',
    },
]


def seed_event_types():
    """Create any missing NotificationEventType rows (idempotent).

    Existing rows are left untouched so admin edits via the CRUD API survive
    re-seeding. Returns the number of rows created.
    """
    from .models import NotificationEventType

    created = 0
    for spec in EVENT_TYPE_SEEDS:
        _, was_created = NotificationEventType.objects.get_or_create(
            key=spec['key'],
            defaults={k: v for k, v in spec.items() if k != 'key'},
        )
        created += int(was_created)
    if created:
        logger.info(
            'seed_event_types: created %d NotificationEventType row(s)', created,
        )
    return created
