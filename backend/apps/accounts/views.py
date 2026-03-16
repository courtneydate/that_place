"""Authentication views for Fieldmouse.

Provides JWT login, token refresh, and logout endpoints.
All endpoints follow the URL pattern /api/v1/auth/*.
"""
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView

# Re-export SimpleJWT views under Fieldmouse names for clarity.
# These are wired up in urls.py.
LoginView = TokenObtainPairView
RefreshView = TokenRefreshView
LogoutView = TokenBlacklistView
