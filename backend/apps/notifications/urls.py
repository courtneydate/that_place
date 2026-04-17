"""Notifications URL patterns.

Ref: SPEC.md § Feature: Notifications
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import NotificationViewSet

app_name = 'notifications'

router = DefaultRouter()
router.register('notifications', NotificationViewSet, basename='notification')

# The DRF router handles all actions except the DELETE snooze which requires
# a rule_id path parameter on a non-detail action — registered manually.
urlpatterns = router.urls + [
    path(
        'notifications/snooze/<int:rule_id>/',
        NotificationViewSet.as_view({'delete': 'snooze_delete'}),
        name='notification-snooze-delete',
    ),
]
