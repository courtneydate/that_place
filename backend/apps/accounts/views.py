"""Views for the accounts app.

Auth endpoints (login, refresh, logout, me, accept-invite) and management
endpoints for That Place Admin (tenants) and Tenant Admin (users).
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from .models import NotificationGroup, NotificationGroupMember, Tenant, TenantInvite, TenantUser
from .permissions import IsTenantAdmin, IsThatPlaceAdmin, IsViewOnly
from .serializers import (
    AcceptInviteSerializer,
    AddMemberSerializer,
    InviteSerializer,
    NotificationGroupMemberSerializer,
    NotificationGroupSerializer,
    TenantSerializer,
    TenantSettingsSerializer,
    TenantUserSerializer,
    UserRoleUpdateSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

class ThatPlaceTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Extends the default serializer to block login for deactivated tenant users."""

    def validate(self, attrs):
        """Validate credentials and check tenant active status."""
        data = super().validate(attrs)
        user = self.user
        tenant_user = getattr(user, 'tenantuser', None)
        if tenant_user is not None and not tenant_user.tenant.is_active:
            raise AuthenticationFailed(
                'Your organisation account has been deactivated. Contact That Place support.'
            )
        return data


class LoginView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — obtain JWT token pair."""

    serializer_class = ThatPlaceTokenObtainPairSerializer


RefreshView = TokenRefreshView
LogoutView = TokenBlacklistView


class MeView(APIView):
    """GET /api/v1/auth/me/ — return the current authenticated user's profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the authenticated user's profile data."""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class AcceptInviteView(APIView):
    """POST /api/v1/auth/accept-invite/ — accept an invite and create account.

    Public endpoint. Validates the signed token, creates the User and
    TenantUser, and returns a JWT token pair so the user is logged in
    immediately after accepting.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Accept invite: create user, return tokens."""
        serializer = AcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        logger.info('Invite accepted: new user %s created', user.email)
        return Response(
            {'access': str(refresh.access_token), 'refresh': str(refresh)},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Tenant management (That Place Admin only)
# ---------------------------------------------------------------------------

class TenantCursorPagination(CursorPagination):
    """Cursor pagination for Tenant list, ordered by creation time."""

    ordering = 'created_at'


class TenantViewSet(viewsets.ModelViewSet):
    """CRUD for Tenant records.

    All actions restricted to That Place Admin users.
    Supports: list, create, retrieve, partial_update, and a custom invite action.
    Destroy is intentionally disabled — tenants are deactivated, not deleted.
    """

    queryset = Tenant.objects.all().order_by('created_at')
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, IsThatPlaceAdmin]
    pagination_class = TenantCursorPagination
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    @action(detail=True, methods=['post'], url_path='invite')
    def invite(self, request, pk=None):
        """POST /api/v1/tenants/{id}/invite/ — send an invite email to a new Tenant Admin.

        Generates a cryptographically random invite token (256-bit entropy), stores only
        its SHA-256 hash in the DB, and emails the raw token to the invitee. Tokens expire
        after 72 hours and are single-use.
        """
        tenant = self.get_object()
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        role = serializer.validated_data['role']

        _, raw_token = TenantInvite.generate(
            tenant=tenant, email=email, role=role, created_by=request.user
        )

        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        invite_url = f'{frontend_url}/accept-invite/{raw_token}/'

        send_mail(
            subject=f'You have been invited to {tenant.name} on That Place',
            message=(
                f'Hello,\n\n'
                f'You have been invited to join {tenant.name} on That Place as {role}.\n\n'
                f'Click the link below to set your password and activate your account:\n'
                f'{invite_url}\n\n'
                f'This invite link expires in 72 hours.\n\n'
                f'— The That Place Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

        logger.info('Invite sent to %s for tenant %s (role: %s)', email, tenant.name, role)
        return Response({'detail': f'Invite sent to {email}.'}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# User management (Tenant Admin / tenant-scoped)
# ---------------------------------------------------------------------------

class UserViewSet(viewsets.GenericViewSet):
    """Tenant-scoped user management.

    All queries are filtered to the requesting user's tenant.
    List is available to all tenant users; invite/update/remove require Tenant Admin.
    """

    serializer_class = TenantUserSerializer

    def get_permissions(self):
        """Restrict write actions to Tenant Admins."""
        if self.action in ('update', 'destroy', 'invite'):
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated(), IsViewOnly()]

    def get_queryset(self):
        """Return TenantUsers scoped to the requesting user's tenant."""
        return (
            TenantUser.objects.filter(tenant=self.request.user.tenantuser.tenant)
            .select_related('user')
            .order_by('joined_at')
        )

    def list(self, request):
        """GET /api/v1/users/ — list all users in the current tenant."""
        serializer = TenantUserSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def update(self, request, pk=None):
        """PUT /api/v1/users/:id/ — update a user's role. Tenant Admin only.

        Cannot change own role. Cannot demote the last admin.
        """
        tenant_user = get_object_or_404(self.get_queryset(), pk=pk)
        my_tenant_user = request.user.tenantuser

        if tenant_user == my_tenant_user:
            return Response(
                {'error': {'code': 'self_update', 'message': 'You cannot change your own role.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UserRoleUpdateSerializer(tenant_user, data=request.data)
        serializer.is_valid(raise_exception=True)

        new_role = serializer.validated_data.get('role')
        if tenant_user.role == TenantUser.Role.ADMIN and new_role != TenantUser.Role.ADMIN:
            admin_count = TenantUser.objects.filter(
                tenant=my_tenant_user.tenant,
                role=TenantUser.Role.ADMIN,
            ).count()
            if admin_count <= 1:
                return Response(
                    {'error': {'code': 'last_admin', 'message': 'Cannot demote the last admin.'}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer.save()
        return Response(TenantUserSerializer(tenant_user).data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/users/:id/ — remove a user from the tenant. Tenant Admin only.

        Deletes the TenantUser record and deactivates the User account so
        existing JWT tokens are immediately rejected by the auth backend.
        """
        tenant_user = get_object_or_404(self.get_queryset(), pk=pk)

        if tenant_user == request.user.tenantuser:
            return Response(
                {'error': {'code': 'self_remove', 'message': 'You cannot remove yourself.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = tenant_user.user
        tenant_user.delete()
        user.is_active = False
        user.save(update_fields=['is_active'])
        logger.info('User %s removed from tenant by %s', user.email, request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'], url_path='invite')
    def invite(self, request):
        """POST /api/v1/users/invite/ — send invite email. Tenant Admin only.

        Generates a cryptographically random invite token (256-bit entropy), stores only
        its SHA-256 hash in the DB, and emails the raw token to the invitee. Tokens expire
        after 72 hours and are single-use.
        """
        tenant = request.user.tenantuser.tenant
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        role = serializer.validated_data['role']

        _, raw_token = TenantInvite.generate(
            tenant=tenant, email=email, role=role, created_by=request.user
        )

        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        invite_url = f'{frontend_url}/accept-invite/{raw_token}/'

        send_mail(
            subject=f'You have been invited to {tenant.name} on That Place',
            message=(
                f'Hello,\n\n'
                f'You have been invited to join {tenant.name} on That Place as {role}.\n\n'
                f'Click the link below to set your password and activate your account:\n'
                f'{invite_url}\n\n'
                f'This invite link expires in 72 hours.\n\n'
                f'— The That Place Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

        logger.info('Tenant invite sent to %s for %s (role: %s)', email, tenant.name, role)
        return Response({'detail': f'Invite sent to {email}.'}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Tenant settings (Tenant Admin / tenant-scoped)
# ---------------------------------------------------------------------------

class TenantSettingsView(APIView):
    """GET/PATCH /api/v1/settings/ — view and update the current tenant's settings.

    GET is available to all tenant users; PATCH requires Tenant Admin.
    """

    permission_classes = [IsAuthenticated, IsViewOnly]

    def get(self, request):
        """Return the current tenant's settings."""
        serializer = TenantSettingsSerializer(request.user.tenantuser.tenant)
        return Response(serializer.data)

    def patch(self, request):
        """Update the current tenant's settings. Tenant Admin only."""
        if not IsTenantAdmin().has_permission(request, self):
            return Response(
                {'error': {'code': 'permission_denied', 'message': 'Tenant Admin access required.'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        tenant = request.user.tenantuser.tenant
        serializer = TenantSettingsSerializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Notification Groups (Tenant Admin / tenant-scoped)
# ---------------------------------------------------------------------------

class NotificationGroupViewSet(viewsets.GenericViewSet):
    """Tenant-scoped notification group management.

    System groups (All Users, All Admins, All Operators) are read-only — they
    cannot be renamed, deleted, or have members manually managed.
    """

    serializer_class = NotificationGroupSerializer

    def get_permissions(self):
        """Read actions available to all tenant users; writes require Tenant Admin."""
        if self.action in ('create', 'update', 'destroy', 'add_member', 'remove_member'):
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated(), IsViewOnly()]

    def get_queryset(self):
        """Return NotificationGroups scoped to the requesting user's tenant."""
        return NotificationGroup.objects.filter(
            tenant=self.request.user.tenantuser.tenant
        ).prefetch_related('members')

    def list(self, request):
        """GET /api/v1/groups/ — list all notification groups in the current tenant."""
        serializer = NotificationGroupSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/v1/groups/:id/ — retrieve a group with its members."""
        group = get_object_or_404(self.get_queryset(), pk=pk)
        data = NotificationGroupSerializer(group).data
        data['members'] = NotificationGroupMemberSerializer(
            group.members.select_related('tenant_user__user'), many=True
        ).data
        return Response(data)

    def create(self, request):
        """POST /api/v1/groups/ — create a custom notification group. Tenant Admin only."""
        serializer = NotificationGroupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant=request.user.tenantuser.tenant, is_system=False)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        """PUT /api/v1/groups/:id/ — rename a group. Tenant Admin only. System groups immutable."""
        group = get_object_or_404(self.get_queryset(), pk=pk)
        if group.is_system:
            return Response(
                {'error': {'code': 'system_group', 'message': 'System groups cannot be modified.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = NotificationGroupSerializer(group, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """DELETE /api/v1/groups/:id/ — delete a group. Tenant Admin only. System groups immutable."""
        group = get_object_or_404(self.get_queryset(), pk=pk)
        if group.is_system:
            return Response(
                {'error': {'code': 'system_group', 'message': 'System groups cannot be deleted.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='members')
    def add_member(self, request, pk=None):
        """POST /api/v1/groups/:id/members/ — add a member. Tenant Admin only. System groups immutable."""
        group = get_object_or_404(self.get_queryset(), pk=pk)
        if group.is_system:
            return Response(
                {'error': {'code': 'system_group', 'message': 'System group membership is managed automatically.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = request.user.tenantuser.tenant
        tenant_user = get_object_or_404(
            TenantUser, pk=serializer.validated_data['tenant_user_id'], tenant=tenant
        )
        _, created = NotificationGroupMember.objects.get_or_create(
            group=group, tenant_user=tenant_user
        )
        if not created:
            return Response(
                {'error': {'code': 'already_member', 'message': 'User is already a member of this group.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'detail': 'Member added.'}, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=['delete'],
        url_path=r'members/(?P<tenant_user_id>[^/.]+)',
        url_name='remove-member',
    )
    def remove_member(self, request, pk=None, tenant_user_id=None):
        """DELETE /api/v1/groups/:id/members/:tenant_user_id/ — remove a member. System groups immutable."""
        group = get_object_or_404(self.get_queryset(), pk=pk)
        if group.is_system:
            return Response(
                {'error': {'code': 'system_group', 'message': 'System group membership is managed automatically.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership = get_object_or_404(
            NotificationGroupMember, group=group, tenant_user_id=tenant_user_id
        )
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
