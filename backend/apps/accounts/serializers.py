"""Serializers for the accounts app.

Covers User (read-only me endpoint), Tenant CRUD, and TenantUser.
"""
import logging

from django.utils.text import slugify
from rest_framework import serializers

from .models import Tenant, TenantUser, User

logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    """Read-only serializer for the current authenticated user."""

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'is_fieldmouse_admin')
        read_only_fields = fields


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
    """Serializer for the invite endpoint payload."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=TenantUser.Role.choices, default=TenantUser.Role.ADMIN)
