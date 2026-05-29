"""App config for the billing app.

Sprint 30 introduces the customer-facing billing model: BillingAccount and
its meter / tariff assignments, plus the immutable audit log every billing
account write produces. Sprint 31 will add BillingRun + line items here.
The metering app (Sprint 29) owns the meter metadata; billing owns who is
billed for what.

Ref: SPEC.md § Feature: Billing Accounts & Tariffs
     ROADMAP.md § Sprint 30 — Billing Accounts, Tariffs & Bulk Import
"""
from django.apps import AppConfig


class BillingConfig(AppConfig):
    """Configuration for the billing app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.billing'
    verbose_name = 'Billing'

    def ready(self):
        """Wire signal receivers for the audit log auto-write."""
        from . import signals  # noqa: F401
