"""URL patterns for the accounts app.

Auth:
    POST   /api/v1/auth/login/           — obtain JWT token pair
    POST   /api/v1/auth/refresh/         — refresh access token
    POST   /api/v1/auth/logout/          — blacklist refresh token
    GET    /api/v1/auth/me/              — current user profile

Tenant management (Fieldmouse Admin only):
    GET    /api/v1/tenants/              — list tenants
    POST   /api/v1/tenants/              — create tenant
    GET    /api/v1/tenants/{id}/         — tenant detail
    PATCH  /api/v1/tenants/{id}/         — update tenant (incl. deactivate)
    POST   /api/v1/tenants/{id}/invite/  — send invite email
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import LoginView, LogoutView, MeView, RefreshView, TenantViewSet

router = DefaultRouter()
router.register('tenants', TenantViewSet, basename='tenant')

app_name = 'accounts'

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/refresh/', RefreshView.as_view(), name='refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/me/', MeView.as_view(), name='me'),
    path('', include(router.urls)),
]
