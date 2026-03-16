"""Account models: User, Tenant, TenantUser.

Fully implemented in Sprint 1. Placeholder custom User model defined here
so AUTH_USER_MODEL is set correctly from the start and avoids migration issues.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model for Fieldmouse.

    Extends AbstractUser. Additional fields (e.g. is_fieldmouse_admin)
    are added in Sprint 1.
    """

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
