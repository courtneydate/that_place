"""Views for the readings app.

Ref: SPEC.md § Feature: Stream Discovery & Configuration
"""
import logging

from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsTenantAdmin

from .models import Stream, StreamReading
from .serializers import StreamReadingSerializer, StreamSerializer

logger = logging.getLogger(__name__)


def _annotate_latest(qs):
    """Annotate a Stream queryset with the latest reading value and timestamp.

    Uses subqueries so the entire list is fetched in a fixed number of DB queries
    rather than one per stream (N+1).
    """
    latest_value = Subquery(
        StreamReading.objects.filter(
            stream=OuterRef('pk'),
        ).order_by('-timestamp').values('value')[:1]
    )
    latest_ts = Subquery(
        StreamReading.objects.filter(
            stream=OuterRef('pk'),
        ).order_by('-timestamp').values('timestamp')[:1]
    )
    return qs.annotate(
        annotated_latest_value=latest_value,
        annotated_latest_ts=latest_ts,
    )


class StreamViewSet(viewsets.GenericViewSet):
    """Retrieve and update individual Stream records.

    Streams are scoped to the requesting user's tenant (via device).
    Reads are open to all authenticated tenant users.
    Updates (label, unit, display_enabled) require Tenant Admin.

    Ref: SPEC.md § Feature: Stream Discovery & Configuration
    """

    serializer_class = StreamSerializer

    def get_permissions(self):
        """Writes require Tenant Admin; reads are open to all tenant roles."""
        if self.action == 'update':
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Return streams scoped to the requesting user's tenant."""
        if self.request.user.is_that_place_admin:
            return _annotate_latest(Stream.objects.select_related('device'))
        tenant = self.request.user.tenantuser.tenant
        return _annotate_latest(
            Stream.objects.select_related('device').filter(device__tenant=tenant)
        )

    def retrieve(self, request, pk=None):
        """GET /api/v1/streams/:id/ — retrieve a single stream."""
        stream = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(StreamSerializer(stream).data)

    def update(self, request, pk=None):
        """PUT /api/v1/streams/:id/ — update label, unit, display_enabled. Tenant Admin only."""
        stream = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = StreamSerializer(stream, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            'Stream "%s" on device "%s" updated by %s',
            stream.key,
            stream.device.serial_number,
            request.user.email,
        )
        return Response(serializer.data)

    def readings(self, request, pk=None):
        """GET /api/v1/streams/:id/readings/ — list readings with optional time/limit filtering.

        Query params:
            from  — ISO 8601 datetime; only readings at or after this time
            to    — ISO 8601 datetime; only readings at or before this time
            limit — max number of results (default 100, max 1000); newest first
        """
        stream = get_object_or_404(self.get_queryset(), pk=pk)
        qs = StreamReading.objects.filter(stream=stream).order_by('-timestamp')

        from_param = request.query_params.get('from')
        to_param = request.query_params.get('to')
        limit_param = request.query_params.get('limit', '100')

        if from_param:
            from_dt = parse_datetime(from_param)
            if from_dt:
                qs = qs.filter(timestamp__gte=from_dt)

        if to_param:
            to_dt = parse_datetime(to_param)
            if to_dt:
                qs = qs.filter(timestamp__lte=to_dt)

        try:
            limit = min(int(limit_param), 1000)
        except (ValueError, TypeError):
            limit = 100

        qs = qs[:limit]
        return Response(StreamReadingSerializer(qs, many=True).data)
