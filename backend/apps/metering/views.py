"""Views for the metering app — Sprint 29.

MeterProfile lives at the device-nested URL because there is at most one
profile per device — exposing it as `/api/v1/devices/:id/meter-profile/`
keeps the access path consistent with the device detail page.

Bulk import is exposed on a top-level URL so the Tenant Admin can upload
the entire site's meter inventory in one go.

Ref: SPEC.md § Feature: Metering Model — Meter Profiles
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import parsers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTenantAdmin, IsViewOnly
from apps.devices.models import Device

from .models import MeterProfile
from .serializers import BulkMeterProfileImportSerializer, MeterProfileSerializer

logger = logging.getLogger(__name__)


def _tenant_scoped_device(request, device_pk):
    """Resolve a Device by PK in the requesting user's tenant or raise 404."""
    if request.user.is_that_place_admin:
        return get_object_or_404(
            Device.objects.select_related('site', 'tenant'),
            pk=device_pk,
        )
    tenant = request.user.tenantuser.tenant
    return get_object_or_404(
        Device.objects.select_related('site', 'tenant').filter(tenant=tenant),
        pk=device_pk,
    )


class MeterProfileDetailView(APIView):
    """GET/PUT/PATCH/DELETE /api/v1/devices/:device_pk/meter-profile/.

    Reads available to any authenticated tenant user; writes require Tenant
    Admin. GET returns 404 when the device has no profile (a UI can use this
    to show the "Mark as meter" button vs. the panel).
    """

    def get_permissions(self):
        """Read open to tenant users; write restricted to Tenant Admin."""
        if self.request.method in ('GET', 'HEAD'):
            return [IsAuthenticated(), IsViewOnly()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def get(self, request, device_pk):
        """Return the device's MeterProfile, or 404 if not yet created."""
        device = _tenant_scoped_device(request, device_pk)
        profile = getattr(device, 'meter_profile', None)
        if profile is None:
            return Response(
                {'error': {'code': 'no_meter_profile',
                           'message': 'This device has no MeterProfile.'}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(MeterProfileSerializer(profile).data)

    def put(self, request, device_pk):
        """Create or replace the MeterProfile for this device. Tenant Admin only."""
        return self._upsert(request, device_pk, partial=False)

    def patch(self, request, device_pk):
        """Patch the MeterProfile (or create from a partial payload)."""
        return self._upsert(request, device_pk, partial=True)

    def _upsert(self, request, device_pk, *, partial: bool):
        device = _tenant_scoped_device(request, device_pk)
        profile = getattr(device, 'meter_profile', None)
        serializer = MeterProfileSerializer(
            instance=profile,
            data=request.data,
            partial=partial,
            context={'device': device, 'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(device=device, tenant=device.tenant)
        created = profile is None
        logger.info(
            'MeterProfile %s for device %s (role=%s) by %s',
            'created' if created else 'updated',
            device.serial_number,
            serializer.validated_data.get('meter_role') or serializer.data.get('meter_role'),
            request.user.email,
        )
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, device_pk):
        """Delete the MeterProfile.

        Blocks deletion of a `gate` MeterProfile while any child meter still
        points to it — this is the "deactivating an active gate while children
        are active is blocked" invariant from SPEC §3.
        """
        device = _tenant_scoped_device(request, device_pk)
        profile = getattr(device, 'meter_profile', None)
        if profile is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        if profile.meter_role == MeterProfile.MeterRole.GATE:
            child_count = MeterProfile.objects.filter(parent_meter_id=device.id).count()
            if child_count:
                return Response(
                    {'error': {
                        'code': 'gate_has_children',
                        'message': (
                            f'Cannot remove gate meter: {child_count} child meter(s) '
                            'still depend on it. Reassign or remove the children first.'
                        ),
                    }},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        profile.delete()
        logger.info('MeterProfile removed from device %s by %s',
                    device.serial_number, request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeterProfileBulkImportView(APIView):
    """POST /api/v1/meter-profiles/bulk/ — CSV upsert of MeterProfiles.

    Tenant Admin only. Match key = `device_serial`.

    Returns: {imported: N, errors: [{row: N, error: "..."}]}.
    Mirrors the reference-dataset bulk import pattern (Sprint 15a).
    """

    permission_classes = [IsAuthenticated, IsTenantAdmin]
    parser_classes = [parsers.MultiPartParser]

    def post(self, request):
        serializer = BulkMeterProfileImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = request.user.tenantuser.tenant
        result = serializer.import_rows(tenant)
        http_status = (
            status.HTTP_200_OK if result['imported'] > 0 else status.HTTP_400_BAD_REQUEST
        )
        logger.info(
            'MeterProfile bulk import by %s: imported=%s errors=%s',
            request.user.email, result['imported'], len(result['errors']),
        )
        return Response(result, status=http_status)
