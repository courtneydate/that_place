"""AppConfig for the devices app."""
from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _seed_site_composite_device_type(sender, **kwargs):
    """post_migrate receiver — ensure the reserved Site Composite DeviceType exists.

    Hosts the per-site virtual Device that owns cross-device derived streams.
    Idempotent. Runs in every environment including the ``--no-migrations``
    test database.

    Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
    """
    from .models import DeviceType
    DeviceType.objects.update_or_create(
        slug='site-composite',
        defaults={
            'name': 'Site Composite',
            'description': (
                'Reserved device type hosting per-site virtual Devices that own '
                'cross-device derived streams. Auto-created on the first '
                'cross-device derived stream on a site.'
            ),
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': False,
            'is_active': True,
            'stream_type_definitions': [],
            'commands': [],
        },
    )


class DevicesConfig(AppConfig):
    """Configuration for the devices application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.devices'
    label = 'devices'

    def ready(self) -> None:
        """Register signal handlers."""
        import apps.devices.signals  # noqa: F401
        post_migrate.connect(_seed_site_composite_device_type, sender=self)
