"""Views for the notifications app.

NotificationViewSet provides:
  list          — GET  /api/v1/notifications/
  unread_count  — GET  /api/v1/notifications/unread-count/
  mark_read     — POST /api/v1/notifications/:id/read/
  mark_all_read — POST /api/v1/notifications/mark-all-read/
  preferences   — GET/PUT /api/v1/notifications/preferences/
  snooze_list   — GET /api/v1/notifications/snooze/
  snooze_create — POST /api/v1/notifications/snooze/
  snooze_delete — DELETE /api/v1/notifications/snooze/:rule_id/

All endpoints are scoped to the requesting user.

Ref: SPEC.md § Feature: Notifications
"""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification, NotificationSnooze, UserNotificationPreference
from .serializers import (
    NotificationSerializer,
    NotificationSnoozeSerializer,
    SnoozeCreateSerializer,
    UserNotificationPreferenceSerializer,
)

logger = logging.getLogger(__name__)


class NotificationViewSet(viewsets.GenericViewSet):
    """Notification endpoints for the requesting user.

    All operations are automatically scoped to request.user.

    Ref: SPEC.md § Feature: Notifications
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return in_app Notifications for the requesting user, newest first."""
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
        return Response(NotificationSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """GET /api/v1/notifications/unread-count/ — count of unread notifications."""
        count = self.get_queryset().filter(read_at__isnull=True).count()
        return Response({'count': count})

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        """POST /api/v1/notifications/:id/read/ — mark a notification as read.

        Idempotent — no-op if already read.
        """
        notification = get_object_or_404(self.get_queryset(), pk=pk)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=['read_at'])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        """POST /api/v1/notifications/mark-all-read/ — mark all unread as read.

        Returns {"marked": N}.
        """
        now = timezone.now()
        marked = (
            self.get_queryset()
            .filter(read_at__isnull=True)
            .update(read_at=now)
        )
        return Response({'marked': marked})

    # ------------------------------------------------------------------
    # Notification preferences
    # ------------------------------------------------------------------

    @action(detail=False, methods=['get', 'put'], url_path='preferences')
    def preferences(self, request):
        """GET/PUT /api/v1/notifications/preferences/ — user channel prefs.

        GET returns current preferences, creating a default row if none exists.
        PUT updates any combination of fields.

        Ref: SPEC.md § Feature: Notifications — Channels
        """
        pref, _ = UserNotificationPreference.objects.get_or_create(
            user=request.user,
            defaults={
                'in_app_enabled': True,
                'email_enabled': True,
                'sms_enabled': False,
                'phone_number': '',
            },
        )

        if request.method == 'GET':
            return Response(UserNotificationPreferenceSerializer(pref).data)

        # PUT
        serializer = UserNotificationPreferenceSerializer(
            pref, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Snooze
    # ------------------------------------------------------------------

    @action(detail=False, methods=['get', 'post'], url_path='snooze')
    def snooze(self, request):
        """GET/POST /api/v1/notifications/snooze/

        GET  — list active snoozes for the requesting user.
        POST — create or extend a snooze for a rule.
               Body: { "rule_id": N, "duration_minutes": 15|60|240|1440 }

        Ref: SPEC.md § Feature: Notifications — Notification snooze
        """
        if request.method == 'GET':
            snoozes = (
                NotificationSnooze.objects
                .filter(user=request.user, snoozed_until__gt=timezone.now())
                .select_related('rule')
            )
            return Response(NotificationSnoozeSerializer(snoozes, many=True).data)

        # POST — create or update snooze
        serializer = SnoozeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rule_id = serializer.validated_data['rule_id']
        duration_minutes = serializer.validated_data['duration_minutes']

        # Verify the rule belongs to this user's tenant
        from apps.rules.models import Rule
        try:
            tenant_id = request.user.tenantuser.tenant_id
        except Exception:
            return Response(
                {'error': {'code': 'no_tenant', 'message': 'User has no tenant.'}},
                status=400,
            )
        rule = get_object_or_404(Rule, pk=rule_id, tenant_id=tenant_id)

        snoozed_until = timezone.now() + timezone.timedelta(minutes=duration_minutes)
        snooze, created = NotificationSnooze.objects.update_or_create(
            user=request.user,
            rule=rule,
            defaults={'snoozed_until': snoozed_until},
        )
        status_code = 201 if created else 200
        return Response(
            NotificationSnoozeSerializer(snooze).data,
            status=status_code,
        )

    @action(
        detail=False,
        methods=['delete'],
        url_path=r'snooze/(?P<rule_id>[0-9]+)',
    )
    def snooze_delete(self, request, rule_id=None):
        """DELETE /api/v1/notifications/snooze/:rule_id/ — cancel a snooze.

        No-op (204) if no active snooze exists for this rule.

        Ref: SPEC.md § Feature: Notifications — Notification snooze
        """
        NotificationSnooze.objects.filter(
            user=request.user,
            rule_id=rule_id,
        ).delete()
        return Response(status=204)
