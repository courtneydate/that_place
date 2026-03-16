"""AppConfig for the ingestion app."""
from django.apps import AppConfig


class IngestionConfig(AppConfig):
    """Configuration for the ingestion application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ingestion'
    label = 'ingestion'
