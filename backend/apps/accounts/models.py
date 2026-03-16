"""Account models: User, Tenant, TenantUser.

Tenant and TenantUser are implemented in Sprint 2.
"""
import logging

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

logger = logging.getLogger(__name__)


class UserManager(BaseUserManager):
    """Custom manager for email-based authentication."""

    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user with the given email and password."""
        if not email:
            raise ValueError('Email address is required.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_fieldmouse_admin', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model for Fieldmouse.

    Uses email as the primary identifier instead of username.
    `is_fieldmouse_admin` marks platform-level admins (Fieldmouse staff)
    who can access all tenants. Regular users belong to a single tenant
    via TenantUser (Sprint 2).
    """

    username = None  # Removed — email is the identifier
    email = models.EmailField(unique=True, verbose_name='email address')
    is_fieldmouse_admin = models.BooleanField(
        default=False,
        help_text='Designates whether this user is a Fieldmouse platform admin with access to all tenants.',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def __str__(self):
        return self.email


class Tenant(models.Model):
    """An organisation (customer) on the Fieldmouse platform.

    Each tenant is a completely isolated data silo. All tenant data
    (devices, streams, rules, alerts) is filtered by tenant_id.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    timezone = models.CharField(
        max_length=100,
        default='Australia/Sydney',
        help_text='IANA timezone string, e.g. "Australia/Brisbane".',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TenantUser(models.Model):
    """Links a User to a Tenant with a role.

    A User belongs to at most one Tenant (Fieldmouse Admins belong to none).
    """

    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        OPERATOR = 'operator', 'Operator'
        VIEWER = 'viewer', 'View-Only'

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='tenantuser',
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='tenant_users',
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADMIN)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['joined_at']

    def __str__(self):
        return f'{self.user.email} @ {self.tenant.name} ({self.role})'
