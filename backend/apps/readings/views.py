"""Views for the readings app.

Ref: SPEC.md § Feature: Stream Discovery & Configuration, § Feature: Data Export (CSV)
"""
import csv
import io
import logging

from django.db.models import OuterRef, Subquery
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTenantAdmin

from .models import DataExport, DerivedStream, IntervalAggregate, Stream, StreamReading
from .serializers import (
    DataExportSerializer,
    DerivedStreamBackfillSerializer,
    DerivedStreamSerializer,
    ExportRequestSerializer,
    IntervalAggregateBackfillSerializer,
    IntervalAggregateSerializer,
    StreamReadingSerializer,
    StreamSerializer,
)

logger = logging.getLogger(__name__)


def _annotate_latest(qs):
    """Annotate a Stream queryset with the latest reading value, timestamp, and quality.

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
    latest_quality = Subquery(
        StreamReading.objects.filter(
            stream=OuterRef('pk'),
        ).order_by('-timestamp').values('quality')[:1]
    )
    return qs.annotate(
        annotated_latest_value=latest_value,
        annotated_latest_ts=latest_ts,
        annotated_latest_quality=latest_quality,
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

    def aggregates(self, request, pk=None):
        """GET /api/v1/streams/:id/aggregates/ — paginated rolled-up aggregates.

        Query params:
            period — '5min' / '30min' / '1h' / '1d' / '1mo' (required)
            kind   — sum / mean / min / max / last (default: stream default)
            from   — ISO 8601 datetime, inclusive
            to     — ISO 8601 datetime, exclusive
            cursor — opaque base64 timestamp cursor (newest first; pass the
                     next_cursor from a prior response to page back further)
            limit  — page size (default 100, max 1000)
        """
        import base64
        import binascii
        from .models import IntervalAggregate

        stream = get_object_or_404(self.get_queryset(), pk=pk)
        period = request.query_params.get('period')
        if period not in dict(IntervalAggregate.Period.choices):
            return Response(
                {'error': {'code': 'period_required',
                           'message': "period must be one of '5min', '30min', '1h', '1d', '1mo'."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kind = request.query_params.get('kind', stream.aggregation_kind_default)

        qs = IntervalAggregate.objects.filter(
            stream=stream, period=period, aggregation_kind=kind,
        ).order_by('-period_start')

        from_param = request.query_params.get('from')
        to_param = request.query_params.get('to')
        if from_param:
            dt = parse_datetime(from_param)
            if dt:
                qs = qs.filter(period_start__gte=dt)
        if to_param:
            dt = parse_datetime(to_param)
            if dt:
                qs = qs.filter(period_start__lt=dt)

        cursor = request.query_params.get('cursor')
        if cursor:
            try:
                cursor_ts = parse_datetime(base64.urlsafe_b64decode(cursor).decode())
                if cursor_ts is not None:
                    qs = qs.filter(period_start__lt=cursor_ts)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return Response(
                    {'error': {'code': 'invalid_cursor', 'message': 'Cursor is malformed.'}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            limit = min(int(request.query_params.get('limit', '100')), 1000)
        except (ValueError, TypeError):
            limit = 100

        rows = list(qs[:limit + 1])
        next_cursor = None
        if len(rows) > limit:
            last_in_page = rows[limit - 1]
            next_cursor = base64.urlsafe_b64encode(
                last_in_page.period_start.isoformat().encode(),
            ).decode()
            rows = rows[:limit]

        return Response({
            'results': IntervalAggregateSerializer(rows, many=True).data,
            'next_cursor': next_cursor,
        })

    def aggregates_backfill(self, request, pk=None):
        """POST /api/v1/streams/:id/aggregates/backfill/ — recompute a date range."""
        stream = get_object_or_404(self.get_queryset(), pk=pk)
        # Tenant Admin only.
        tenant_user = getattr(request.user, 'tenantuser', None)
        if tenant_user is None or tenant_user.role != 'admin':
            return Response(
                {'error': {'code': 'forbidden', 'message': 'Tenant Admin only.'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = IntervalAggregateBackfillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from .aggregate_tasks import backfill_aggregates
        kinds = serializer.validated_data.get('kinds') or None
        backfill_aggregates.delay(
            stream.pk,
            serializer.validated_data['period'],
            serializer.validated_data['date_from'].isoformat(),
            serializer.validated_data['date_to'].isoformat(),
            kinds,
        )
        return Response({'detail': 'Backfill dispatched.'}, status=status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

_CSV_HEADERS = ['timestamp', 'site_name', 'device_name', 'device_id', 'device_serial', 'stream_label', 'value', 'unit']
_EXPORT_BATCH = 500


def _csv_row_generator(readings_qs):
    """Yield CSV rows one at a time from a StreamReading queryset.

    Uses a StringIO buffer + csv.writer so values are properly quoted, then
    yields the raw string so Django can flush it to the client immediately.
    Each row is yielded individually to keep memory usage flat on large exports.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    writer.writerow(_CSV_HEADERS)
    yield buf.getvalue()

    for reading in readings_qs.iterator(chunk_size=_EXPORT_BATCH):
        buf.seek(0)
        buf.truncate()
        stream = reading.stream
        device = stream.device
        site = device.site
        writer.writerow([
            reading.timestamp.isoformat(),
            site.name if site else '',
            device.name,
            device.pk,
            device.serial_number,
            stream.label or stream.key,
            reading.value,
            stream.unit,
        ])
        yield buf.getvalue()


class ExportStreamView(APIView):
    """POST /api/v1/exports/stream/ — stream a CSV export to the client.

    Writes the DataExport audit log before streaming begins so the record is
    always present even if the client disconnects mid-download.

    Admin and Operator only. View-Only users receive 403.

    Ref: SPEC.md § Feature: Data Export (CSV)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Validate request, log export, and return a streaming CSV response."""
        if request.user.is_that_place_admin:
            return Response(
                {'error': {'code': 'forbidden', 'message': 'Use tenant account to export data.'}},
                status=403,
            )

        tenant_user = getattr(request.user, 'tenantuser', None)
        if tenant_user is None:
            return Response(
                {'error': {'code': 'forbidden', 'message': 'No tenant association.'}},
                status=403,
            )

        from apps.accounts.models import TenantUser
        if tenant_user.role == TenantUser.Role.VIEWER:
            return Response(
                {'error': {'code': 'forbidden', 'message': 'View-Only users cannot export data.'}},
                status=403,
            )

        tenant = tenant_user.tenant

        serializer = ExportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'error': {'code': 'invalid', 'message': serializer.errors}}, status=400)

        stream_ids = serializer.validated_data['stream_ids']
        date_from = serializer.validated_data['date_from']
        date_to = serializer.validated_data['date_to']

        # Verify all requested streams belong to this tenant
        valid_streams = Stream.objects.filter(
            pk__in=stream_ids,
            device__tenant=tenant,
        ).values_list('pk', flat=True)
        valid_stream_ids = set(valid_streams)
        if len(valid_stream_ids) != len(set(stream_ids)):
            return Response(
                {'error': {'code': 'invalid', 'message': 'One or more stream IDs are invalid or not accessible.'}},
                status=400,
            )

        # Write audit log before streaming (Option A — record intent regardless of client behaviour)
        DataExport.objects.create(
            tenant=tenant,
            exported_by=request.user,
            stream_ids=stream_ids,
            date_from=date_from,
            date_to=date_to,
        )
        logger.info(
            'CSV export started: user=%s tenant=%s streams=%s from=%s to=%s',
            request.user.email, tenant.slug, stream_ids, date_from, date_to,
        )

        readings_qs = (
            StreamReading.objects
            .filter(
                stream_id__in=stream_ids,
                timestamp__gt=date_from,
                timestamp__lte=date_to,
            )
            .select_related('stream__device__site')
            .order_by('timestamp')
        )

        response = StreamingHttpResponse(
            _csv_row_generator(readings_qs),
            content_type='text/csv',
        )
        response['Content-Disposition'] = 'attachment; filename="that-place-export.csv"'
        return response


class ExportHistoryView(APIView):
    """GET /api/v1/exports/ — list export history for the tenant. Admin only.

    Ref: SPEC.md § Feature: Data Export (CSV) — Export history
    """

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        """Return all DataExport records for the requesting tenant."""
        tenant_user = getattr(request.user, 'tenantuser', None)
        if tenant_user is None:
            return Response({'error': {'code': 'forbidden', 'message': 'No tenant association.'}}, status=403)

        exports = DataExport.objects.filter(
            tenant=tenant_user.tenant,
        ).select_related('exported_by')
        return Response(DataExportSerializer(exports, many=True).data)


# ---------------------------------------------------------------------------
# Derived streams (Sprint 27)
# ---------------------------------------------------------------------------


class DerivedStreamViewSet(viewsets.GenericViewSet):
    """CRUD + backfill for tenant-scoped derived streams.

    Reads are open to all authenticated tenant users; writes (create / update /
    delete / backfill) require Tenant Admin.

    Ref: SPEC.md § Feature: Derived / Computed Streams; ROADMAP Sprint 27
    """

    serializer_class = DerivedStreamSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def get_queryset(self):
        tenant_user = getattr(self.request.user, 'tenantuser', None)
        if tenant_user is None:
            return DerivedStream.objects.none()
        return (
            DerivedStream.objects
            .filter(stream__device__tenant=tenant_user.tenant)
            .select_related('stream', 'stream__device')
            .prefetch_related('source_streams')
        )

    def list(self, request):
        return Response(DerivedStreamSerializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, pk=None):
        derived = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(DerivedStreamSerializer(derived).data)

    def create(self, request):
        serializer = DerivedStreamSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            'Derived stream created by %s: formula=%s key=%s',
            request.user.email, serializer.data['formula'], serializer.data['stream_key'],
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        derived = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DerivedStreamSerializer(
            derived, data=request.data, partial=False, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        derived = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DerivedStreamSerializer(
            derived, data=request.data, partial=True, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        derived = get_object_or_404(self.get_queryset(), pk=pk)
        # Deleting the output Stream cascades to the DerivedStream (one-to-one).
        derived.stream.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def backfill(self, request, pk=None):
        """POST /api/v1/derived-streams/:id/backfill/ — recompute a date range."""
        derived = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DerivedStreamBackfillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from .derived_dispatch import backfill_derived_stream
        backfill_derived_stream.delay(
            derived.pk,
            serializer.validated_data['date_from'].isoformat(),
            serializer.validated_data['date_to'].isoformat(),
        )
        return Response(
            {'detail': 'Backfill dispatched.'},
            status=status.HTTP_202_ACCEPTED,
        )
