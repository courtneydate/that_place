"""Views for the notifications app.

NotificationViewSet provides:
  list          — GET /api/v1/notifications/          list the user's notifications
  unread_count  — GET /api/v1/notifications/unread-count/
  mark_read     — POST /api/v1/notifications/:id/read/
  mark_all_read — POST /api/v1/notifications/mark-all-read/

All endpoints are scoped to the requesting user — users only see their own
notifications. No cross-user or cross-tenant access is possible.

Ref: SPEC.md § Feature: Notifications
"""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer

logger = logging.getLogger(__name__)


class NotificationViewSet(viewsets.GenericViewSet):
    """In-app notification endpoints for the requesting user.

    All operations are automatically scoped to request.user. There is no way
    to read or modify another user's notifications through these endpoints.

    Ref: SPEC.md § Feature: Notifications
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return Notifications for the requesting user, newest first."""
        return (
            Notification.objects
            .filter(user=self.request.user, channel=Notification.Channel.IN_APP)
            .select_related('alert__rule')
            .order_by('-sent_at')
        )

    def list(self, request):
        """GET /api/v1/notifications/ — list the user's in-app notifications.

        Optional query parameter:
          unread_only=true  — return only unread notifications
        """
        qs = self.get_queryset()
        if request.query_params.get('unread_only', '').lower() == 'true':
            qs = qs.filter(read_at__isnull=True)
        serializer = NotificationSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """GET /api/v1/notifications/unread-count/ — count of unread notifications.

        Returns {"count": N}. Used by the nav bell badge.
        """
        count = self.get_queryset().filter(read_at__isnull=True).count()
        return Response({'count': count})

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        """POST /api/v1/notifications/:id/read/ — mark a single notification as read.

        Idempotent — calling on an already-read notification is a no-op.
        """
        notification = get_object_or_404(self.get_queryset(), pk=pk)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=['read_at'])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        """POST /api/v1/notifications/mark-all-read/ — mark all unread as read.

        Bulk-updates all unread in_app notifications for this user.
        Returns {"marked": N} indicating how many were updated.

        Ref: SPEC.md § Feature: Notifications — Mark all as read
        """
        now = timezone.now()
        marked = (
            self.get_queryset()
            .filter(read_at__isnull=True)
            .update(read_at=now)
        )
        logger.debug(
            'mark_all_read: user %d — marked %d notifications as read', request.user.pk, marked
        )
        return Response({'marked': marked})
