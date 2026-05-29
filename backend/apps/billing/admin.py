"""Django admin for billing models."""
from django.contrib import admin

from .models import (
    BillingAccount,
    BillingAccountAuditLog,
    BillingAccountMeter,
    BillingAccountTariffAssignment,
)


@admin.register(BillingAccount)
class BillingAccountAdmin(admin.ModelAdmin):
    """Admin view for BillingAccount."""

    list_display = ('name', 'tenant', 'account_type', 'customer_reference', 'is_active')
    list_filter = ('tenant', 'account_type', 'is_active')
    search_fields = ('name', 'customer_reference', 'abn')
    raw_id_fields = ('tenant', 'parent_account')


@admin.register(BillingAccountMeter)
class BillingAccountMeterAdmin(admin.ModelAdmin):
    """Admin view for BillingAccountMeter."""

    list_display = ('billing_account', 'stream', 'effective_from', 'effective_to')
    raw_id_fields = ('billing_account', 'stream')


@admin.register(BillingAccountTariffAssignment)
class BillingAccountTariffAssignmentAdmin(admin.ModelAdmin):
    """Admin view for BillingAccountTariffAssignment."""

    list_display = ('billing_account', 'dataset', 'effective_from', 'effective_to')
    raw_id_fields = ('billing_account', 'stream', 'dataset')


@admin.register(BillingAccountAuditLog)
class BillingAccountAuditLogAdmin(admin.ModelAdmin):
    """Read-only admin view for the immutable audit log."""

    list_display = ('billing_account', 'actor_user', 'action', 'occurred_at')
    list_filter = ('action',)
    raw_id_fields = ('billing_account', 'actor_user')
    readonly_fields = (
        'billing_account', 'actor_user', 'action', 'changed_fields', 'occurred_at',
    )

    def has_add_permission(self, request):
        """Audit log is append-only via app code — block manual creation."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Audit log is immutable."""
        return False
