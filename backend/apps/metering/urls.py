"""URL patterns for the metering app — Sprint 29.

Routes:
    GET    /api/v1/devices/{device_pk}/meter-profile/
    PUT    /api/v1/devices/{device_pk}/meter-profile/
    PATCH  /api/v1/devices/{device_pk}/meter-profile/
    DELETE /api/v1/devices/{device_pk}/meter-profile/
    POST   /api/v1/meter-profiles/bulk/

Ref: SPEC.md § Feature: Metering Model — Meter Profiles
"""
from django.urls import path

from .views import MeterProfileBulkImportView, MeterProfileDetailView

app_name = 'metering'

urlpatterns = [
    path(
        'devices/<int:device_pk>/meter-profile/',
        MeterProfileDetailView.as_view(),
        name='meter-profile-detail',
    ),
    path(
        'meter-profiles/bulk/',
        MeterProfileBulkImportView.as_view(),
        name='meter-profile-bulk-import',
    ),
]
