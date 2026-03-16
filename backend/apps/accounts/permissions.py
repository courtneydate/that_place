"""Custom DRF permission classes for Fieldmouse.

IsFieldmouseAdmin: grants access only to platform-level admin accounts.
Additional permission classes (IsTenantAdmin, IsOperator, IsViewOnly)
are added in Sprint 3.
"""
import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)


class IsFieldmouseAdmin(BasePermission):
    """Allows access only to users with is_fieldmouse_admin=True.

    Used on all Fieldmouse platform management endpoints (tenant management,
    device type library, provider library).
    """

    message = 'Access restricted to Fieldmouse platform administrators.'

    def has_permission(self, request, view):
        """Return True only if the user is authenticated and is a Fieldmouse Admin."""
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_fieldmouse_admin
        )
