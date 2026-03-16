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
