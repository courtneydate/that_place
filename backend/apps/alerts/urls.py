"""Alerts URL patterns.

Ref: SPEC.md § API — Alerts
"""
from rest_framework.routers import DefaultRouter

from .views import AlertViewSet

app_name = 'alerts'

router = DefaultRouter()
router.register('alerts', AlertViewSet, basename='alert')

urlpatterns = router.urls
