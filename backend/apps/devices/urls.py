"""URL patterns for the devices app.

Sites (tenant-scoped):
    GET    /api/v1/sites/         — list sites
    POST   /api/v1/sites/         — create site
    GET    /api/v1/sites/{id}/    — retrieve site
    PUT    /api/v1/sites/{id}/    — update site
    DELETE /api/v1/sites/{id}/    — delete site

Device Types (platform library — FM Admin write, all read):
    GET    /api/v1/device-types/         — list device types
    POST   /api/v1/device-types/         — create device type
    GET    /api/v1/device-types/{id}/    — retrieve device type
    PUT    /api/v1/device-types/{id}/    — update device type

Devices (tenant-scoped):
    GET    /api/v1/devices/              — list devices (?status=, ?site=, ?device_type=)
    POST   /api/v1/devices/              — register device (creates as pending)
    GET    /api/v1/devices/{id}/         — retrieve device
    PUT    /api/v1/devices/{id}/         — update device
    DELETE /api/v1/devices/{id}/         — delete device
    POST   /api/v1/devices/{id}/approve/ — approve device (FM Admin only)
    POST   /api/v1/devices/{id}/reject/  — reject device (FM Admin only)
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DeviceTypeViewSet, DeviceViewSet, SiteViewSet

router = DefaultRouter()
router.register('sites', SiteViewSet, basename='site')
router.register('device-types', DeviceTypeViewSet, basename='device-type')
router.register('devices', DeviceViewSet, basename='device')

app_name = 'devices'

urlpatterns = [
    path('', include(router.urls)),
]
