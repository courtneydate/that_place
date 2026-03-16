"""URL patterns for the accounts app.

Auth endpoints:
    POST /api/v1/auth/login/     — obtain JWT token pair
    POST /api/v1/auth/refresh/   — refresh access token
    POST /api/v1/auth/logout/    — blacklist refresh token (logout)
"""
from django.urls import path

from .views import LoginView, LogoutView, RefreshView

app_name = 'accounts'

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/refresh/', RefreshView.as_view(), name='refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
]
