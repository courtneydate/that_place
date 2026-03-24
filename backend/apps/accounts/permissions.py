"""Custom DRF permission classes for That Place.

Hierarchy (least → most privileged):
  IsViewOnly   — any authenticated tenant user (viewer, operator, or admin)
  IsOperator   — tenant admin or operator
  IsTenantAdmin — tenant admin only
  IsThatPlaceAdmin — That Place platform admin only
"""
import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)


def _get_tenant_user(request):
    """Return the TenantUser for the request user, or None."""
    return getattr(request.user, 'tenantuser', None)


class IsThatPlaceAdmin(BasePermission):
    """Allows access only to users with is_that_place_admin=True.

    Used on all That Place platform management endpoints (tenant management,
    device type library, provider library).
    """

    message = 'Access restricted to That Place platform administrators.'

    def has_permission(self, request, view):
        """Return True only if the user is authenticated and is a That Place Admin."""
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_that_place_admin
        )


class IsViewOnly(BasePermission):
    """Any authenticated tenant user (viewer, operator, or admin).

    This is the minimum permission required for tenant-scoped read endpoints.
    That Place Admins (who have no TenantUser) are explicitly excluded.
    """

    message = 'Access restricted to tenant users.'

    def has_permission(self, request, view):
        """Return True if the user is authenticated and belongs to a tenant."""
        return bool(
            request.user
            and request.user.is_authenticated
            and _get_tenant_user(request) is not None
        )


class IsOperator(BasePermission):
    """Authenticated tenant user with admin or operator role.

    Used for write endpoints that operators are permitted to use
    (dashboard management, sending commands, acknowledging alerts, CSV export).
    """

    message = 'Access restricted to Tenant Admins and Operators.'

    def has_permission(self, request, view):
        """Return True if the user is a tenant admin or operator."""
        from .models import TenantUser  # local import avoids circular deps
        if not (request.user and request.user.is_authenticated):
            return False
        tu = _get_tenant_user(request)
        return tu is not None and tu.role in (
            TenantUser.Role.ADMIN,
            TenantUser.Role.OPERATOR,
        )


class IsTenantAdmin(BasePermission):
    """Authenticated tenant user with admin role.

    Used for endpoints restricted to Tenant Admins:
    user management, device registration, rule management.
    """

    message = 'Access restricted to Tenant Admins.'

    def has_permission(self, request, view):
        """Return True if the user is a tenant admin."""
        from .models import TenantUser  # local import avoids circular deps
        if not (request.user and request.user.is_authenticated):
            return False
        tu = _get_tenant_user(request)
        return tu is not None and tu.role == TenantUser.Role.ADMIN
