"""URL patterns for the accounts app.

Auth:
    POST   /api/v1/auth/login/            — obtain JWT token pair
    POST   /api/v1/auth/refresh/          — refresh access token
    POST   /api/v1/auth/logout/           — blacklist refresh token
    GET    /api/v1/auth/me/               — current user profile
    POST   /api/v1/auth/accept-invite/    — accept invite & create account

Tenant management (That Place Admin only):
    GET    /api/v1/tenants/              — list tenants
    POST   /api/v1/tenants/              — create tenant
    GET    /api/v1/tenants/{id}/         — tenant detail
    PATCH  /api/v1/tenants/{id}/         — update tenant (incl. deactivate)
    POST   /api/v1/tenants/{id}/invite/  — send invite email

User management (Tenant Admin / tenant-scoped):
    GET    /api/v1/users/                — list users in tenant
    POST   /api/v1/users/invite/         — send invite email
    PUT    /api/v1/users/{id}/           — update user role
    DELETE /api/v1/users/{id}/           — remove user from tenant

Tenant settings (tenant-scoped):
    GET    /api/v1/settings/             — view tenant settings
    PATCH  /api/v1/settings/             — update timezone (Tenant Admin only)

Notification Groups (tenant-scoped):
    GET    /api/v1/groups/               — list groups
    POST   /api/v1/groups/               — create custom group
    GET    /api/v1/groups/{id}/          — retrieve group with members
    PUT    /api/v1/groups/{id}/          — rename group
    DELETE /api/v1/groups/{id}/          — delete group
    POST   /api/v1/groups/{id}/members/  — add member
    DELETE /api/v1/groups/{id}/members/{tenant_user_id}/ — remove member
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AcceptInviteView,
    LoginView,
    LogoutView,
    MeView,
    NotificationGroupViewSet,
    RefreshView,
    TenantSettingsView,
    TenantViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register('tenants', TenantViewSet, basename='tenant')
router.register('users', UserViewSet, basename='user')
router.register('groups', NotificationGroupViewSet, basename='group')

app_name = 'accounts'

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/refresh/', RefreshView.as_view(), name='refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', MeView.as_view(), name='me'),
    path('auth/accept-invite/', AcceptInviteView.as_view(), name='accept-invite'),
    path('settings/', TenantSettingsView.as_view(), name='settings'),
    path('', include(router.urls)),
]
