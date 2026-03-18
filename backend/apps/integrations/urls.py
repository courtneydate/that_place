"""URL patterns for the integrations app.

3rd Party API Provider Library (FM Admin write, all authenticated read):
    GET    /api/v1/api-providers/         — list providers
    POST   /api/v1/api-providers/         — create provider (FM Admin)
    GET    /api/v1/api-providers/{id}/    — retrieve provider
    PUT    /api/v1/api-providers/{id}/    — update provider (FM Admin)
    DELETE /api/v1/api-providers/{id}/    — delete provider (FM Admin)

Data Sources (Tenant Admin):
    GET    /api/v1/data-sources/                        — list data sources
    POST   /api/v1/data-sources/                        — create data source
    GET    /api/v1/data-sources/{id}/                   — retrieve
    PUT    /api/v1/data-sources/{id}/                   — update
    DELETE /api/v1/data-sources/{id}/                   — delete
    POST   /api/v1/data-sources/{id}/discover/          — run device discovery
    GET    /api/v1/data-sources/{id}/devices/           — list connected devices
    POST   /api/v1/data-sources/{id}/devices/           — connect devices (wizard)
    PATCH  /api/v1/data-sources/{id}/devices/{did}/     — update stream keys
    DELETE /api/v1/data-sources/{id}/devices/{did}/     — deactivate device
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DataSourceViewSet, ThirdPartyAPIProviderViewSet

router = DefaultRouter()
router.register('api-providers', ThirdPartyAPIProviderViewSet, basename='api-provider')
router.register('data-sources', DataSourceViewSet, basename='data-source')

app_name = 'integrations'

urlpatterns = [
    path('', include(router.urls)),
]
