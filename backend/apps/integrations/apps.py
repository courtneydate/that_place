"""AppConfig for the integrations app."""
from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Configuration for the integrations application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.integrations'
    label = 'integrations'
