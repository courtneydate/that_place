"""AppConfig for the dashboards app."""
from django.apps import AppConfig


class DashboardsConfig(AppConfig):
    """Configuration for the dashboards application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.dashboards'
    label = 'dashboards'
