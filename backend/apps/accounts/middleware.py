"""Tenant context middleware.

Attaches `request.tenant` (the Tenant instance for the authenticated user)
to every request. That Place Admins and unauthenticated requests get
`request.tenant = None`.
"""
from django.utils.functional import SimpleLazyObject


def _resolve_tenant(request):
    """Return the Tenant for the authenticated user, or None."""
    tu = getattr(request.user, 'tenantuser', None)
    return tu.tenant if tu is not None else None


class TenantContextMiddleware:
    """Resolves the current tenant from the authenticated user.

    Must be placed after AuthenticationMiddleware in MIDDLEWARE so that
    request.user is already populated when this middleware runs.
    """

    def __init__(self, get_response):
        """Store the next middleware/view callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Attach request.tenant lazily — resolved on first access."""
        request.tenant = SimpleLazyObject(lambda: _resolve_tenant(request))
        return self.get_response(request)
