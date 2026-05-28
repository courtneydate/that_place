"""AppConfig for the readings app."""
from django.apps import AppConfig


class ReadingsConfig(AppConfig):
    """Configuration for the readings application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.readings'
    label = 'readings'

    def ready(self) -> None:
        """Register derived-stream signal handlers (Sprint 27)."""
        from . import derived_dispatch  # noqa: F401
