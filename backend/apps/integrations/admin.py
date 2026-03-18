"""Django admin registration for the integrations app."""
from django.contrib import admin

from .models import DataSource, DataSourceDevice, ThirdPartyAPIProvider


@admin.register(ThirdPartyAPIProvider)
class ThirdPartyAPIProviderAdmin(admin.ModelAdmin):
    """Admin for ThirdPartyAPIProvider."""

    list_display = ('name', 'slug', 'auth_type', 'default_poll_interval_seconds', 'is_active')
    list_filter = ('auth_type', 'is_active')
    search_fields = ('name', 'slug')


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    """Admin for DataSource."""

    list_display = ('name', 'tenant', 'provider', 'is_active', 'created_at')
    list_filter = ('is_active', 'provider')
    search_fields = ('name', 'tenant__name')


@admin.register(DataSourceDevice)
class DataSourceDeviceAdmin(admin.ModelAdmin):
    """Admin for DataSourceDevice."""

    list_display = (
        'external_device_name', 'external_device_id', 'datasource',
        'last_poll_status', 'consecutive_poll_failures', 'is_active',
    )
    list_filter = ('last_poll_status', 'is_active')
    search_fields = ('external_device_id', 'external_device_name')
