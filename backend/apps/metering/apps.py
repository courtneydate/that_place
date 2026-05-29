"""App config for the metering app.

Holds the billing-metadata models (MeterProfile in Sprint 29) that tag
which Devices are billing meters and which Streams carry billable energy.
Sprint 30 onwards adds BillingAccount and the billing engine in a separate
`billing` app.

Ref: SPEC.md § Feature: Metering Model — Meter Profiles
     ROADMAP.md § Sprint 29 — Meter Profiles & Billing Roles
"""
from django.apps import AppConfig


class MeteringConfig(AppConfig):
    """Configuration for the metering app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.metering'
    verbose_name = 'Metering'
