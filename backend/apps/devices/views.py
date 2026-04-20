"""Views for the devices app."""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsOperator, IsTenantAdmin, IsThatPlaceAdmin, IsViewOnly

from .models import CommandLog, Device, DeviceHealth, DeviceType, Site
from .serializers import (
    CommandLogSerializer,
    DeviceHealthSerializer,
    DeviceSerializer,
    DeviceTypeSerializer,
    SendCommandSerializer,
    SiteSerializer,
)

logger = logging.getLogger(__name__)


class SiteViewSet(viewsets.GenericViewSet):
    """Tenant-scoped Site CRUD.

    All queries are filtered to the requesting user's tenant.
    List/retrieve available to all tenant users; create/update/delete require Tenant Admin.
    Ref: SPEC.md § Feature: Site Management
    """

    serializer_class = SiteSerializer

    def get_permissions(self):
        """Restrict write actions to Tenant Admins."""
        if self.action in ('create', 'update', 'destroy'):
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated(), IsViewOnly()]

    def get_queryset(self):
        """Return Sites scoped to the requesting user's tenant."""
        return Site.objects.filter(tenant=self.request.user.tenantuser.tenant)

    def list(self, request):
        """GET /api/v1/sites/ — list all sites in the current tenant."""
        serializer = SiteSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/sites/:id/ — retrieve a site."""
        site = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(SiteSerializer(site).data)

    def create(self, request):
        """POST /api/v1/sites/ — create a site. Tenant Admin only."""
        serializer = SiteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant=request.user.tenantuser.tenant)
        logger.info('Site "%s" created by %s', serializer.instance.name, request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/sites/:id/ — update a site. Tenant Admin only."""
        site = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = SiteSerializer(site, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/sites/:id/ — delete a site. Tenant Admin only."""
        site = get_object_or_404(self.get_queryset(), pk=pk)
        site.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceTypeViewSet(viewsets.GenericViewSet):
    """Device type library.

    Reads are open to all authenticated users (tenant users and FM Admins).
    Writes (create/update) are restricted to That Place Admins.
    Ref: SPEC.md § Feature: Device Type Library
    """

    serializer_class = DeviceTypeSerializer

    def get_permissions(self):
        """Restrict write actions to That Place Admins."""
        if self.action in ('create', 'update'):
            return [IsAuthenticated(), IsThatPlaceAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Return all device types (platform-wide, not tenant-scoped)."""
        return DeviceType.objects.all()

    def list(self, request):
        """GET /api/v1/device-types/ — list all device types."""
        serializer = DeviceTypeSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/device-types/:id/ — retrieve a device type."""
        device_type = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(DeviceTypeSerializer(device_type).data)

    def create(self, request):
        """POST /api/v1/device-types/ — create a device type. That Place Admin only."""
        serializer = DeviceTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('DeviceType "%s" created by %s', serializer.instance.name, request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/device-types/:id/ — update a device type. That Place Admin only."""
        device_type = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DeviceTypeSerializer(device_type, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DeviceViewSet(viewsets.GenericViewSet):
    """Tenant-scoped Device CRUD with registration and approval flow.

    Tenant users see only their own tenant's devices.
    That Place Admins see all devices (needed for the approval queue).
    Registration creates a device with status=pending; approval is FM Admin only.
    Ref: SPEC.md § Feature: Device Registration & Approval
    """

    serializer_class = DeviceSerializer

    def get_permissions(self):
        """Permission matrix per action."""
        if self.action in ('approve', 'reject'):
            return [IsAuthenticated(), IsThatPlaceAdmin()]
        if self.action in ('create', 'update', 'destroy'):
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Return devices scoped to the requesting user's tenant.

        That Place Admins bypass tenant scoping so they can access any device
        for the approval queue and cross-tenant operations.
        """
        if self.request.user.is_that_place_admin:
            qs = Device.objects.select_related('tenant', 'site', 'device_type', 'devicehealth').all()
        else:
            tenant = self.request.user.tenantuser.tenant
            qs = Device.objects.select_related('site', 'device_type', 'devicehealth').filter(tenant=tenant)

        # Optional query param filters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        site_filter = self.request.query_params.get('site')
        if site_filter:
            qs = qs.filter(site_id=site_filter)

        device_type_filter = self.request.query_params.get('device_type')
        if device_type_filter:
            qs = qs.filter(device_type_id=device_type_filter)

        return qs

    def list(self, request):
        """GET /api/v1/devices/ — list devices. Tenant-scoped."""
        serializer = DeviceSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/devices/:id/ — retrieve a device."""
        device = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(DeviceSerializer(device).data)

    def create(self, request):
        """POST /api/v1/devices/ — register a new device. Tenant Admin only.

        Device is created with status=pending and must be approved by a
        That Place Admin before it can submit data.
        """
        tenant = request.user.tenantuser.tenant
        serializer = DeviceSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save(tenant=tenant, status=Device.Status.PENDING)
        logger.info(
            'Device "%s" (serial=%s) registered by %s for tenant %s',
            device.name,
            device.serial_number,
            request.user.email,
            tenant.name,
        )
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/devices/:id/ — update a device. Tenant Admin only."""
        device = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DeviceSerializer(device, data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(DeviceSerializer(device).data)

    def partial_update(self, request, pk=None):
        """PATCH /api/v1/devices/:id/ — partially update a device. Tenant Admin only.

        Accepts any subset of writable fields (e.g. just name).
        """
        device = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DeviceSerializer(
            device, data=request.data, partial=True, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(
            'Device "%s" (id=%s) partially updated by %s: %s',
            device.name, device.pk, request.user.email, list(request.data.keys()),
        )
        return Response(DeviceSerializer(device).data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/devices/:id/ — delete a device. Tenant Admin only."""
        device = get_object_or_404(self.get_queryset(), pk=pk)
        tenant_id = device.tenant_id
        event_data = {'device_name': device.name, 'serial_number': device.serial_number}
        device.delete()
        from apps.notifications.tasks import create_system_notification
        create_system_notification.delay('device_deleted', tenant_id, event_data)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """POST /api/v1/devices/:id/approve/ — approve a pending device.

        Sets status to active. That Place Admin only.
        """
        device = get_object_or_404(Device, pk=pk)
        if device.status != Device.Status.PENDING:
            return Response(
                {'error': {'code': 'not_pending', 'message': 'Device is not in pending status.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        device.status = Device.Status.ACTIVE
        device.save(update_fields=['status'])
        logger.info('Device "%s" (id=%s) approved by %s', device.name, device.pk, request.user.email)
        from apps.notifications.tasks import create_system_notification
        create_system_notification.delay(
            'device_approved',
            device.tenant_id,
            {'device_name': device.name, 'serial_number': device.serial_number},
        )
        return Response(DeviceSerializer(device).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """POST /api/v1/devices/:id/reject/ — reject a pending device.

        Sets status to rejected. That Place Admin only.
        """
        device = get_object_or_404(Device, pk=pk)
        if device.status != Device.Status.PENDING:
            return Response(
                {'error': {'code': 'not_pending', 'message': 'Device is not in pending status.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        device.status = Device.Status.REJECTED
        device.save(update_fields=['status'])
        logger.info('Device "%s" (id=%s) rejected by %s', device.name, device.pk, request.user.email)
        return Response(DeviceSerializer(device).data)

    @action(detail=True, methods=['get'], url_path='streams')
    def streams(self, request, pk=None):
        """GET /api/v1/devices/:id/streams/ — list all streams for a device.

        Accessible to all authenticated users (View-Only and above).
        Each stream includes its latest reading value and timestamp.
        """
        from apps.readings.serializers import StreamSerializer
        from apps.readings.views import _annotate_latest

        device = get_object_or_404(self.get_queryset(), pk=pk)
        qs = _annotate_latest(device.streams.all())
        return Response(StreamSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'], url_path='health-history')
    def health_history(self, request, pk=None):
        """GET /api/v1/devices/:id/health-history/ — synthetic online/offline timeline.

        Derives presence from StreamReading timestamps: for each time bucket, if any
        reading was received the device is considered online; otherwise offline.

        Query params:
            time_range  '1h' | '24h' | '7d' | '30d' (default: '24h')
            from        ISO 8601 datetime override for range start
            to          ISO 8601 datetime override for range end

        Returns:
            { timeline: [{timestamp, is_online}], bucket_minutes: int }

        Ref: SPEC.md § Feature: Dashboards & Visualisation — Health/Uptime Chart widget
        """
        from datetime import timedelta

        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        from apps.readings.models import StreamReading

        device = get_object_or_404(self.get_queryset(), pk=pk)

        range_map = {
            '1h': timedelta(hours=1),
            '24h': timedelta(hours=24),
            '7d': timedelta(days=7),
            '30d': timedelta(days=30),
        }
        time_range = request.query_params.get('time_range', '24h')
        now = timezone.now()
        start = now - range_map.get(time_range, timedelta(hours=24))

        from_param = request.query_params.get('from')
        to_param = request.query_params.get('to')
        if from_param:
            parsed = parse_datetime(from_param)
            if parsed:
                start = parsed
        if to_param:
            parsed = parse_datetime(to_param)
            if parsed:
                now = parsed

        total_seconds = (now - start).total_seconds()
        if total_seconds <= 3600:
            bucket_minutes = 5
        elif total_seconds <= 86400:
            bucket_minutes = 30
        elif total_seconds <= 7 * 86400:
            bucket_minutes = 120
        else:
            bucket_minutes = 360

        reading_times = StreamReading.objects.filter(
            stream__device=device,
            timestamp__gte=start,
            timestamp__lte=now,
        ).values_list('timestamp', flat=True)

        active_buckets: set = set()
        for ts in reading_times:
            epoch_minutes = int(ts.timestamp() / 60)
            bucket_key = (epoch_minutes // bucket_minutes) * bucket_minutes
            active_buckets.add(bucket_key)

        timeline = []
        current = start
        bucket_delta = timedelta(minutes=bucket_minutes)
        while current <= now:
            epoch_minutes = int(current.timestamp() / 60)
            bucket_key = (epoch_minutes // bucket_minutes) * bucket_minutes
            timeline.append({
                'timestamp': current.isoformat(),
                'is_online': bucket_key in active_buckets,
            })
            current += bucket_delta

        return Response({'timeline': timeline, 'bucket_minutes': bucket_minutes})

    @action(detail=True, methods=['post'], url_path='command')
    def command(self, request, pk=None):
        """POST /api/v1/devices/:id/command/ — send a command to a device.

        Validates command name and params against the device type definition,
        then dispatches the send_device_command Celery task.
        Admin and Operator only.

        Ref: SPEC.md § Feature: Device Control — Sending commands
        """
        if not (IsOperator().has_permission(request, self)):
            return Response(
                {'error': {'code': 'permission_denied', 'message': 'Admin or Operator role required.'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        device = get_object_or_404(self.get_queryset(), pk=pk)

        if device.topic_format != Device.TopicFormat.THAT_PLACE_V1:
            return Response(
                {'error': {
                    'code': 'unsupported_format',
                    'message': 'Commands are only supported for That Place v1 devices.',
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SendCommandSerializer(
            data=request.data,
            context={'device': device},
        )
        serializer.is_valid(raise_exception=True)

        # Call synchronously — command sends are low-frequency UI actions so
        # blocking briefly is acceptable and avoids Celery result-backend issues.
        from .tasks import send_device_command
        log_id = send_device_command(
            device_id=device.pk,
            command_name=serializer.validated_data['command_name'],
            params=serializer.validated_data.get('params', {}),
            sent_by_id=request.user.pk,
        )

        if log_id is None:
            return Response(
                {'error': {'code': 'command_failed', 'message': 'Failed to dispatch command.'}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        log = CommandLog.objects.get(pk=log_id)
        logger.info(
            'Command "%s" dispatched to device "%s" by %s',
            serializer.validated_data['command_name'], device.serial_number, request.user.email,
        )
        return Response(CommandLogSerializer(log).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='commands')
    def commands(self, request, pk=None):
        """GET /api/v1/devices/:id/commands/ — command history for a device.

        Admin and Operator only.
        Ref: SPEC.md § Feature: Device Control — Command history
        """
        if not (IsOperator().has_permission(request, self)):
            return Response(
                {'error': {'code': 'permission_denied', 'message': 'Admin or Operator role required.'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        device = get_object_or_404(self.get_queryset(), pk=pk)
        logs = device.command_logs.select_related('sent_by', 'triggered_by_rule').all()
        return Response(CommandLogSerializer(logs, many=True).data)

    @action(detail=True, methods=['get'], url_path='health')
    def health(self, request, pk=None):
        """GET /api/v1/devices/:id/health/ — return the health record for a device.

        Accessible to all authenticated users (View-Only and above).
        Returns 404 if the device has never been heard from.
        """
        device = self.get_object()
        try:
            health = device.devicehealth
        except DeviceHealth.DoesNotExist:
            return Response(
                {'error': {'code': 'no_health_data', 'message': 'No health data received yet.'}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(DeviceHealthSerializer(health).data)
