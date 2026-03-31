"""Views for the integrations app.

ThirdPartyAPIProviderViewSet:  FM Admin CRUD; all authenticated users can list/retrieve.
DataSourceViewSet:             Tenant Admin CRUD + discover + connect/disconnect devices.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import logging

import requests as http_requests
from django.db import transaction
from django.shortcuts import get_object_or_404
from jsonpath_ng.ext import parse as jp_parse
from rest_framework import parsers, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsTenantAdmin, IsThatPlaceAdmin, IsViewOnly
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import Stream

from .auth_handlers import AuthError, get_auth_session
from .models import DataSource, DataSourceDevice, ThirdPartyAPIProvider
from .serializers import (
    ConnectDeviceSerializer,
    DataSourceDeviceSerializer,
    DataSourceSerializer,
    ThirdPartyAPIProviderAdminSerializer,
    ThirdPartyAPIProviderTenantSerializer,
)

logger = logging.getLogger(__name__)

# HTTP timeout for provider API calls during discovery (seconds)
DISCOVERY_TIMEOUT = 15

# Sentinel DeviceType slug used for all virtual API devices
API_DEVICE_TYPE_SLUG = 'third-party-api'


def _get_or_create_api_device_type() -> DeviceType:
    """Return (creating if absent) the platform DeviceType for virtual API devices."""
    dt, _ = DeviceType.objects.get_or_create(
        slug=API_DEVICE_TYPE_SLUG,
        defaults={
            'name': '3rd Party API Device',
            'description': 'Virtual device created from a 3rd party API integration.',
            'connection_type': DeviceType.ConnectionType.API,
            'is_push': False,
            'default_offline_threshold_minutes': 30,
            'command_ack_timeout_seconds': 30,
        },
    )
    return dt


class ThirdPartyAPIProviderViewSet(viewsets.GenericViewSet):
    """3rd party API provider library.

    That Place Admin can create, update, and delete providers.
    All authenticated users can list and retrieve providers — but the serializer
    returned differs by role (full detail for That Place Admin; limited for tenants).

    Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
    """

    parser_classes = (parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser)

    def get_permissions(self):
        """FM Admin only for writes; any authenticated user for reads."""
        if self.action in ('create', 'update', 'destroy'):
            return [IsAuthenticated(), IsThatPlaceAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Return active providers (all authenticated users)."""
        return ThirdPartyAPIProvider.objects.all()

    def get_serializer_class(self):
        """Return full serializer for FM Admins; limited serializer for tenants."""
        if self.request.user.is_that_place_admin:
            return ThirdPartyAPIProviderAdminSerializer
        return ThirdPartyAPIProviderTenantSerializer

    def list(self, request):
        """GET /api/v1/api-providers/ — list all providers."""
        qs = self.get_queryset().filter(is_active=True)
        serializer = self.get_serializer_class()(qs, many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/api-providers/:id/ — retrieve a provider."""
        provider = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = self.get_serializer_class()(provider, context={'request': request})
        return Response(serializer.data)

    def create(self, request):
        """POST /api/v1/api-providers/ — create a provider. FM Admin only."""
        serializer = ThirdPartyAPIProviderAdminSerializer(
            data=request.data, context={'request': request},
        )
        if not serializer.is_valid():
            logger.warning(
                'Provider create validation errors (user=%s): %s',
                request.user.email, serializer.errors,
            )
            raise serializers.ValidationError(serializer.errors)
        provider = serializer.save()
        logger.info('Provider "%s" created by %s', provider.name, request.user.email)
        return Response(
            ThirdPartyAPIProviderAdminSerializer(provider, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, pk=None):
        """PUT /api/v1/api-providers/:id/ — update a provider. FM Admin only."""
        provider = get_object_or_404(ThirdPartyAPIProvider, pk=pk)
        serializer = ThirdPartyAPIProviderAdminSerializer(
            provider, data=request.data, context={'request': request},
        )
        if not serializer.is_valid():
            logger.warning(
                'Provider update validation errors (user=%s, provider=%s): %s',
                request.user.email, pk, serializer.errors,
            )
            raise serializers.ValidationError(serializer.errors)
        serializer.save()
        logger.info('Provider "%s" updated by %s', provider.name, request.user.email)
        return Response(
            ThirdPartyAPIProviderAdminSerializer(provider, context={'request': request}).data,
        )

    def destroy(self, request, pk=None):
        """DELETE /api/v1/api-providers/:id/ — delete a provider. FM Admin only."""
        provider = get_object_or_404(ThirdPartyAPIProvider, pk=pk)
        if provider.data_sources.filter(is_active=True).exists():
            return Response(
                {
                    'error': {
                        'code': 'provider_in_use',
                        'message': 'Cannot delete a provider with active data sources.',
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        provider.delete()
        logger.info('Provider "%s" deleted by %s', provider.name, request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DataSourceViewSet(viewsets.GenericViewSet):
    """Tenant-scoped DataSource CRUD with device discovery and connection.

    All actions require Tenant Admin except list/retrieve which require
    any authenticated tenant user.

    Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
    """

    serializer_class = DataSourceSerializer

    def get_permissions(self):
        """Write actions require Tenant Admin; reads require any tenant user (not FM Admin)."""
        if self.action in ('list', 'retrieve', 'devices', 'device_detail'):
            return [IsAuthenticated(), IsViewOnly()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def _tenant(self):
        """Return the requesting user's Tenant."""
        return self.request.user.tenantuser.tenant

    def get_queryset(self):
        """Return DataSources scoped to the requesting user's tenant."""
        return (
            DataSource.objects
            .filter(tenant=self._tenant())
            .select_related('provider')
            .prefetch_related('devices')
        )

    def list(self, request):
        """GET /api/v1/data-sources/ — list data sources for the tenant."""
        serializer = DataSourceSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/data-sources/:id/ — retrieve a data source."""
        ds = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(DataSourceSerializer(ds).data)

    def create(self, request):
        """POST /api/v1/data-sources/ — create a data source. Tenant Admin only.

        Saves encrypted credentials. Does not yet run discovery or create devices.
        """
        tenant = self._tenant()
        serializer = DataSourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ds = serializer.save(tenant=tenant)
        logger.info(
            'DataSource "%s" created by %s for tenant %s',
            ds.name, request.user.email, tenant.name,
        )
        return Response(DataSourceSerializer(ds).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/data-sources/:id/ — update a data source. Tenant Admin only."""
        ds = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DataSourceSerializer(ds, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(DataSourceSerializer(ds).data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/data-sources/:id/ — delete a data source. Tenant Admin only."""
        ds = get_object_or_404(self.get_queryset(), pk=pk)
        ds.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='discover')
    def discover(self, request, pk=None):
        """POST /api/v1/data-sources/:id/discover/ — call the provider discovery endpoint.

        Uses the saved DataSource credentials to call the provider's discovery
        endpoint and return the list of devices found on the account.

        Returns a list of {external_device_id, external_device_name} dicts.
        Devices already connected via this DataSource are flagged.
        """
        ds = get_object_or_404(self.get_queryset(), pk=pk)
        provider = ds.provider

        # Build auth
        try:
            headers, params, updated_cache = get_auth_session(
                provider, ds.credentials or {}, ds.auth_token_cache or {},
            )
        except AuthError as exc:
            return Response(
                {'error': {'code': 'auth_failure', 'message': str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Persist refreshed token if needed
        if updated_cache is not None:
            ds.auth_token_cache = updated_cache
            ds.save(update_fields=['auth_token_cache'])

        # Build URL
        discovery_cfg = provider.discovery_endpoint
        path = discovery_cfg.get('path', '')
        method = discovery_cfg.get('method', 'GET').upper()
        url = provider.base_url.rstrip('/') + '/' + path.lstrip('/')

        # Call provider
        try:
            resp = http_requests.request(
                method, url, headers=headers, params=params, timeout=DISCOVERY_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except http_requests.RequestException as exc:
            return Response(
                {'error': {'code': 'discovery_failed', 'message': str(exc)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Extract device list via JSONPath
        id_path = discovery_cfg.get('device_id_jsonpath', '$.*.id')
        name_path = discovery_cfg.get('device_name_jsonpath')

        try:
            id_matches = jp_parse(id_path).find(data)
        except Exception as exc:
            logger.error('JSONPath error during discovery for ds=%d: %s', ds.pk, exc)
            return Response(
                {'error': {'code': 'jsonpath_error', 'message': 'Failed to parse discovery response.'}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        name_matches = []
        if name_path:
            try:
                name_matches = jp_parse(name_path).find(data)
            except Exception:
                pass

        # Flag already-connected devices
        connected_ids = set(
            ds.devices.filter(is_active=True).values_list('external_device_id', flat=True)
        )

        devices = []
        for i, match in enumerate(id_matches):
            ext_id = str(match.value)
            ext_name = str(name_matches[i].value) if i < len(name_matches) else None
            devices.append({
                'external_device_id': ext_id,
                'external_device_name': ext_name,
                'already_connected': ext_id in connected_ids,
            })

        return Response({'devices': devices})

    @action(detail=True, methods=['get', 'post'], url_path='devices')
    def devices(self, request, pk=None):
        """GET /api/v1/data-sources/:id/devices/ — list connected devices.
        POST /api/v1/data-sources/:id/devices/ — connect one or more discovered devices.
        """
        ds = get_object_or_404(self.get_queryset(), pk=pk)
        if request.method == 'GET':
            return self._list_devices(ds)
        return self._connect_devices(request, ds)

    def _list_devices(self, ds: DataSource) -> Response:
        """Return all DataSourceDevices for this DataSource."""
        qs = (
            ds.devices
            .select_related('virtual_device__site', 'virtual_device__device_type', 'virtual_device__devicehealth')
            .order_by('external_device_name', 'external_device_id')
        )
        return Response(DataSourceDeviceSerializer(qs, many=True).data)

    def _connect_devices(self, request, ds: DataSource) -> Response:
        """Connect one or more discovered devices to this DataSource.

        Accepts a list of device connection objects. For each device:
          - Creates a virtual Device (status=active, no approval needed)
          - Creates a DataSourceDevice record
          - Creates Stream records for each activated stream key

        Virtual device serial_number: api-{provider_slug}-{tenant_id}-{external_device_id}
        """
        items = request.data if isinstance(request.data, list) else [request.data]

        # Validate all items up front
        validated = []
        for item in items:
            s = ConnectDeviceSerializer(data=item)
            if not s.is_valid():
                return Response(
                    {'error': {'code': 'invalid_input', 'message': s.errors}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            validated.append(s.validated_data)

        provider = ds.provider
        tenant = ds.tenant
        device_type = _get_or_create_api_device_type()

        # Validate all sites belong to this tenant before creating anything
        site_ids = {v['site_id'] for v in validated}
        valid_sites = {
            s.pk: s
            for s in Site.objects.filter(pk__in=site_ids, tenant=tenant)
        }
        missing = site_ids - set(valid_sites.keys())
        if missing:
            return Response(
                {'error': {'code': 'invalid_site', 'message': f'Sites not found: {missing}'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for already-connected devices
        requested_ids = {v['external_device_id'] for v in validated}
        existing_ids = set(
            ds.devices.filter(
                external_device_id__in=requested_ids, is_active=True,
            ).values_list('external_device_id', flat=True)
        )
        if existing_ids:
            return Response(
                {
                    'error': {
                        'code': 'already_connected',
                        'message': f'Devices already connected: {existing_ids}',
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Build available_streams lookup for Stream creation
        streams_by_key = {s['key']: s for s in (provider.available_streams or [])}

        created = []
        with transaction.atomic():
            for v in validated:
                ext_id = v['external_device_id']
                ext_name = v.get('external_device_name') or ''
                site = valid_sites[v['site_id']]
                device_name = v.get('name') or f'{provider.name} — {ext_name or ext_id}'
                serial = f'api-{provider.slug}-{tenant.pk}-{ext_id}'[:255]
                overrides = v.get('stream_overrides', {})

                # Reactivate existing virtual Device if previously disconnected,
                # otherwise create fresh.
                try:
                    virtual_device = Device.objects.get(serial_number=serial, tenant=tenant)
                    virtual_device.site = site
                    virtual_device.name = device_name
                    virtual_device.status = Device.Status.ACTIVE
                    virtual_device.save(update_fields=['site', 'name', 'status'])
                except Device.DoesNotExist:
                    virtual_device = Device.objects.create(
                        tenant=tenant,
                        site=site,
                        device_type=device_type,
                        name=device_name,
                        serial_number=serial,
                        status=Device.Status.ACTIVE,
                    )

                # Reactivate existing DataSourceDevice if previously disconnected,
                # otherwise create fresh.
                dsd, _ = DataSourceDevice.objects.update_or_create(
                    datasource=ds,
                    external_device_id=ext_id,
                    defaults={
                        'external_device_name': ext_name or None,
                        'virtual_device': virtual_device,
                        'active_stream_keys': v['active_stream_keys'],
                        'is_active': True,
                        'consecutive_poll_failures': 0,
                        'last_poll_status': None,
                        'last_poll_error': None,
                    },
                )

                # Ensure Stream records exist for all activated stream keys.
                # Uses get_or_create so re-connection doesn't duplicate streams.
                for stream_key in v['active_stream_keys']:
                    stream_def = streams_by_key.get(stream_key, {})
                    override = overrides.get(stream_key, {})
                    Stream.objects.get_or_create(
                        device=virtual_device,
                        key=stream_key,
                        defaults={
                            'label': override.get('label') or stream_def.get('label', stream_key),
                            'unit': override.get('unit') or stream_def.get('unit', ''),
                            'data_type': stream_def.get('data_type', 'numeric'),
                            'display_enabled': True,
                        },
                    )

                created.append(dsd)
                logger.info(
                    'Connected device "%s" (ext_id=%s) to DataSource %d for tenant %s',
                    device_name, ext_id, ds.pk, tenant.name,
                )

        # Dispatch background metadata fetch if the provider has a device detail endpoint.
        # Runs after the transaction so IDs are guaranteed to exist in the DB.
        if provider.device_detail_endpoint and created:
            from .tasks import fetch_device_metadata
            fetch_device_metadata.delay([dsd.pk for dsd in created])

        return Response(
            DataSourceDeviceSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['patch', 'delete'], url_path=r'devices/(?P<did>\d+)')
    def device_detail(self, request, pk=None, did=None):
        """PATCH /api/v1/data-sources/:id/devices/:did/ — update active_stream_keys.
        DELETE /api/v1/data-sources/:id/devices/:did/ — deactivate a device.
        """
        ds = get_object_or_404(self.get_queryset(), pk=pk)
        dsd = get_object_or_404(DataSourceDevice, pk=did, datasource=ds)

        if request.method == 'PATCH':
            return self._update_device(request, dsd)
        return self._deactivate_device(request, dsd)

    def _update_device(self, request, dsd: DataSourceDevice) -> Response:
        """Update active_stream_keys for a connected device."""
        new_keys = request.data.get('active_stream_keys')
        if not isinstance(new_keys, list) or not new_keys:
            return Response(
                {'error': {'code': 'invalid_input', 'message': 'active_stream_keys must be a non-empty list.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dsd.active_stream_keys = new_keys
        dsd.save(update_fields=['active_stream_keys'])
        return Response(DataSourceDeviceSerializer(dsd).data)

    def _deactivate_device(self, request, dsd: DataSourceDevice) -> Response:
        """Deactivate a device (stop polling; keep virtual Device and history)."""
        dsd.is_active = False
        dsd.save(update_fields=['is_active'])
        logger.info(
            'DataSourceDevice %d deactivated by %s (ext_id=%s)',
            dsd.pk, request.user.email, dsd.external_device_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
