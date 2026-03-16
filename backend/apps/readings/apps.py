"""AppConfig for the readings app."""
from django.apps import AppConfig


class ReadingsConfig(AppConfig):
    """Configuration for the readings application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.readings'
    label = 'readings'
