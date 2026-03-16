"""Views for the devices app."""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsFieldmouseAdmin, IsTenantAdmin, IsViewOnly

from .models import Device, DeviceType, Site
from .serializers import DeviceSerializer, DeviceTypeSerializer, SiteSerializer

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
    Writes (create/update) are restricted to Fieldmouse Admins.
    Ref: SPEC.md § Feature: Device Type Library
    """

    serializer_class = DeviceTypeSerializer

    def get_permissions(self):
        """Restrict write actions to Fieldmouse Admins."""
        if self.action in ('create', 'update'):
            return [IsAuthenticated(), IsFieldmouseAdmin()]
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
        """POST /api/v1/device-types/ — create a device type. Fieldmouse Admin only."""
        serializer = DeviceTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('DeviceType "%s" created by %s', serializer.instance.name, request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/device-types/:id/ — update a device type. Fieldmouse Admin only."""
        device_type = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DeviceTypeSerializer(device_type, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DeviceViewSet(viewsets.GenericViewSet):
    """Tenant-scoped Device CRUD with registration and approval flow.

    Tenant users see only their own tenant's devices.
    Fieldmouse Admins see all devices (needed for the approval queue).
    Registration creates a device with status=pending; approval is FM Admin only.
    Ref: SPEC.md § Feature: Device Registration & Approval
    """

    serializer_class = DeviceSerializer

    def get_permissions(self):
        """Permission matrix per action."""
        if self.action in ('approve', 'reject'):
            return [IsAuthenticated(), IsFieldmouseAdmin()]
        if self.action in ('create', 'update', 'destroy'):
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Return devices scoped to the requesting user's tenant.

        Fieldmouse Admins bypass tenant scoping so they can access any device
        for the approval queue and cross-tenant operations.
        """
        if self.request.user.is_fieldmouse_admin:
            qs = Device.objects.select_related('tenant', 'site', 'device_type').all()
        else:
            tenant = self.request.user.tenantuser.tenant
            qs = Device.objects.select_related('site', 'device_type').filter(tenant=tenant)

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
        Fieldmouse Admin before it can submit data.
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

    def destroy(self, request, pk=None):
        """DELETE /api/v1/devices/:id/ — delete a device. Tenant Admin only."""
        device = get_object_or_404(self.get_queryset(), pk=pk)
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """POST /api/v1/devices/:id/approve/ — approve a pending device.

        Sets status to active. Fieldmouse Admin only.
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
        return Response(DeviceSerializer(device).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """POST /api/v1/devices/:id/reject/ — reject a pending device.

        Sets status to rejected. Fieldmouse Admin only.
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
