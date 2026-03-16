"""AppConfig for the rules app."""
from django.apps import AppConfig


class RulesConfig(AppConfig):
    """Configuration for the rules application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.rules'
    label = 'rules'
