"""Views for the accounts app.

Auth endpoints (login, refresh, logout, me) and Tenant management
endpoints for Fieldmouse Admin.
"""
import logging

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import send_mail
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import AuthenticationFailed, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView

from .models import Tenant, TenantUser
from .permissions import IsFieldmouseAdmin
from .serializers import InviteSerializer, TenantSerializer, UserSerializer

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

class FieldmouseTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Extends the default serializer to block login for deactivated tenant users."""

    def validate(self, attrs):
        """Validate credentials and check tenant active status."""
        data = super().validate(attrs)
        user = self.user
        # Check if the user belongs to a deactivated tenant
        tenant_user = getattr(user, 'tenantuser', None)
        if tenant_user is not None and not tenant_user.tenant.is_active:
            raise AuthenticationFailed(
                'Your organisation account has been deactivated. Contact Fieldmouse support.'
            )
        return data


class LoginView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — obtain JWT token pair."""

    serializer_class = FieldmouseTokenObtainPairSerializer


RefreshView = TokenRefreshView
LogoutView = TokenBlacklistView


class MeView(APIView):
    """GET /api/v1/auth/me/ — return the current authenticated user's profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the authenticated user's profile data."""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Tenant management (Fieldmouse Admin only)
# ---------------------------------------------------------------------------

class TenantCursorPagination(CursorPagination):
    """Cursor pagination for Tenant list, ordered by creation time."""

    ordering = 'created_at'


class TenantViewSet(viewsets.ModelViewSet):
    """CRUD for Tenant records.

    All actions restricted to Fieldmouse Admin users.
    Supports: list, create, retrieve, partial_update, and a custom invite action.
    Destroy is intentionally disabled — tenants are deactivated, not deleted.
    """

    queryset = Tenant.objects.all().order_by('created_at')
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, IsFieldmouseAdmin]
    pagination_class = TenantCursorPagination
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    @action(detail=True, methods=['post'], url_path='invite')
    def invite(self, request, pk=None):
        """POST /api/v1/tenants/{id}/invite/ — send an invite email to a new Tenant Admin.

        Generates a signed invite token containing email, tenant_id, and role.
        The accept flow (Sprint 3) validates the token and creates the User.
        """
        tenant = self.get_object()
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        role = serializer.validated_data['role']

        # Generate a signed invite token (validated on accept in Sprint 3)
        token = signing.dumps(
            {'email': email, 'tenant_id': tenant.id, 'role': role},
            salt='fieldmouse-invite',
        )

        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        invite_url = f'{frontend_url}/accept-invite/{token}/'

        send_mail(
            subject=f'You have been invited to {tenant.name} on Fieldmouse',
            message=(
                f'Hello,\n\n'
                f'You have been invited to join {tenant.name} on Fieldmouse as {role}.\n\n'
                f'Click the link below to set your password and activate your account:\n'
                f'{invite_url}\n\n'
                f'This invite link expires in 7 days.\n\n'
                f'— The Fieldmouse Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

        logger.info('Invite sent to %s for tenant %s (role: %s)', email, tenant.name, role)
        return Response({'detail': f'Invite sent to {email}.'}, status=status.HTTP_200_OK)
