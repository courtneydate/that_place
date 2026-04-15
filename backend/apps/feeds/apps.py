"""App config for the feeds app.

Provides two engines:
  FeedProvider  — API-polled data channels (AEMO, any future live feed)
  ReferenceDataset — admin-managed lookup tables (tariffs, CO2 factors, etc.)

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets
"""
from django.apps import AppConfig


class FeedsConfig(AppConfig):
    """Configuration for the feeds app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.feeds'
    verbose_name = 'Feeds'
