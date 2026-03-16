"""AppConfig for the notifications app."""
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Configuration for the notifications application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notifications'
    label = 'notifications'
