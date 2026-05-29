"""Django admin for metering models."""
from django.contrib import admin

from .models import MeterProfile


@admin.register(MeterProfile)
class MeterProfileAdmin(admin.ModelAdmin):
    """Admin view for MeterProfile (Sprint 29)."""

    list_display = ('device', 'nmi', 'meter_role', 'phases', 'install_date')
    list_filter = ('meter_role', 'phases')
    search_fields = ('nmi', 'device__name', 'device__serial_number', 'serial_number_secondary')
    raw_id_fields = ('device', 'parent_meter', 'tenant')
