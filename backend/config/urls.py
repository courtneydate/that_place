"""Root URL configuration. All API routes are under /api/v1/."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.accounts.urls')),
    path('api/v1/', include('apps.devices.urls')),
    path('api/v1/', include('apps.readings.urls')),
    path('api/v1/', include('apps.integrations.urls')),
    path('api/v1/', include('apps.dashboards.urls')),
    path('api/v1/', include('apps.rules.urls')),
    path('api/v1/', include('apps.feeds.urls')),
    path('api/v1/', include('apps.alerts.urls')),
    path('api/v1/', include('apps.notifications.urls')),
]
