"""Serializers for the accounts app.

Covers User (read-only me endpoint), Tenant CRUD, TenantUser management,
and the invite accept flow.
"""
import hashlib
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from .models import NotificationGroup, NotificationGroupMember, Tenant, TenantInvite, TenantUser, User

logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    """Read-only serializer for the current authenticated user.

    Includes tenant_role so the frontend knows what the user can do
    without a separate API call.
    """

    tenant_role = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'is_that_place_admin', 'tenant_role', 'tenant_name')
        read_only_fields = fields

    def get_tenant_role(self, obj):
        """Return the user's role in their tenant, or None for That Place Admins."""
        tu = getattr(obj, 'tenantuser', None)
        return tu.role if tu is not None else None

    def get_tenant_name(self, obj):
        """Return the name of the user's tenant, or None for That Place Admins."""
        tu = getattr(obj, 'tenantuser', None)
        return tu.tenant.name if tu is not None else None


class TenantSerializer(serializers.ModelSerializer):
    """Serializer for Tenant CRUD."""

    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ('id', 'name', 'slug', 'timezone', 'is_active', 'created_at', 'user_count')
        read_only_fields = ('id', 'slug', 'created_at', 'user_count')

    def get_user_count(self, obj):
        """Return number of active users in this tenant."""
        return obj.tenant_users.filter(user__is_active=True).count()

    def create(self, validated_data):
        """Auto-generate a unique slug from the tenant name on creation."""
        name = validated_data['name']
        base_slug = slugify(name)
        slug = base_slug
        counter = 1
        while Tenant.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
        validated_data['slug'] = slug
        return super().create(validated_data)


class InviteSerializer(serializers.Serializer):
    """Serializer for invite endpoint payloads (That Place Admin and Tenant Admin)."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=TenantUser.Role.choices, default=TenantUser.Role.ADMIN)


class AcceptInviteSerializer(serializers.Serializer):
    """Serializer for the accept-invite endpoint.

    Validates the stored invite record (looked up by SHA-256 hash of the raw token),
    enforces TTL and single-use, then creates the User and TenantUser records atomically.

    The raw token is never stored — only its SHA-256 hash — so a DB breach cannot be
    used to accept outstanding invites.
    """

    token = serializers.CharField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_token(self, value: str) -> str:
        """Look up the invite by token hash and enforce TTL and single-use."""
        token_hash = hashlib.sha256(value.encode()).hexdigest()
        try:
            invite = TenantInvite.objects.select_related('tenant').get(token_hash=token_hash)
        except TenantInvite.DoesNotExist:
            raise serializers.ValidationError('Invalid invite link.')

        if invite.is_used:
            raise serializers.ValidationError('This invite link has already been used.')
        if invite.is_expired:
            raise serializers.ValidationError('Invite link has expired.')
        if not invite.tenant.is_active:
            raise serializers.ValidationError('The organisation account has been deactivated.')

        self._invite = invite
        return value

    def validate(self, attrs):
        """Ensure the invite email has not already been registered as an active account."""
        invite = getattr(self, '_invite', None)
        if invite and User.objects.filter(email=invite.email, is_active=True).exists():
            raise serializers.ValidationError(
                {'token': 'This invite has already been accepted.'}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        """Create (or reactivate) the User and TenantUser from the validated invite.

        If a previously deactivated user exists with the invite email, reactivate
        them and update their details rather than creating a duplicate record.
        Marks the invite as used so it cannot be replayed.
        """
        invite = self._invite
        existing = User.objects.filter(email=invite.email).first()
        if existing is not None:
            # Reactivate a previously removed user
            existing.set_password(validated_data['password'])
            existing.first_name = validated_data['first_name']
            existing.last_name = validated_data['last_name']
            existing.is_active = True
            existing.save(update_fields=['password', 'first_name', 'last_name', 'is_active'])
            user = existing
        else:
            user = User.objects.create_user(
                email=invite.email,
                password=validated_data['password'],
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
            )
        TenantUser.objects.create(user=user, tenant=invite.tenant, role=invite.role)
        # Mark invite as used — single-use enforcement
        invite.used_at = timezone.now()
        invite.save(update_fields=['used_at'])
        return user


class TenantUserSerializer(serializers.ModelSerializer):
    """Serializer for listing and updating tenant users."""

    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)

    class Meta:
        model = TenantUser
        fields = ('id', 'email', 'first_name', 'last_name', 'role', 'joined_at')
        read_only_fields = ('id', 'email', 'first_name', 'last_name', 'joined_at')


class UserRoleUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a TenantUser's role."""

    class Meta:
        model = TenantUser
        fields = ('role',)


class TenantSettingsSerializer(serializers.ModelSerializer):
    """Serializer for the tenant settings endpoint.

    Exposes tenant metadata as read-only and allows Tenant Admin to update timezone.
    """

    class Meta:
        model = Tenant
        fields = ('id', 'name', 'slug', 'timezone', 'is_active', 'created_at')
        read_only_fields = ('id', 'name', 'slug', 'is_active', 'created_at')


class NotificationGroupMemberSerializer(serializers.ModelSerializer):
    """Serializer for a group member — embeds basic user info."""

    email = serializers.EmailField(source='tenant_user.user.email', read_only=True)
    first_name = serializers.CharField(source='tenant_user.user.first_name', read_only=True)
    last_name = serializers.CharField(source='tenant_user.user.last_name', read_only=True)
    role = serializers.CharField(source='tenant_user.role', read_only=True)

    class Meta:
        model = NotificationGroupMember
        fields = ('tenant_user_id', 'email', 'first_name', 'last_name', 'role', 'added_at')
        read_only_fields = fields


class NotificationGroupSerializer(serializers.ModelSerializer):
    """Serializer for NotificationGroup list/detail."""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = NotificationGroup
        fields = ('id', 'name', 'is_system', 'member_count', 'created_at')
        read_only_fields = ('id', 'is_system', 'created_at')

    def get_member_count(self, obj):
        """Return number of members in this group."""
        return obj.members.count()


class AddMemberSerializer(serializers.Serializer):
    """Serializer for adding a member to a notification group."""

    tenant_user_id = serializers.IntegerField()
