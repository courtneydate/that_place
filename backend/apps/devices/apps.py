"""AppConfig for the devices app."""
from django.apps import AppConfig


class DevicesConfig(AppConfig):
    """Configuration for the devices application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.devices'
    label = 'devices'

    def ready(self) -> None:
        """Register signal handlers."""
        import apps.devices.signals  # noqa: F401
