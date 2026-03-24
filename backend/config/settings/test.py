"""Test settings for That Place.

Used by pytest-django via pytest.ini DJANGO_SETTINGS_MODULE.
Optimised for speed: faster password hashing, eager Celery tasks, in-memory email.
"""
import os

# Must be set before base.py is imported so env('FIELD_ENCRYPTION_KEY') resolves.
os.environ.setdefault('FIELD_ENCRYPTION_KEY', 'pUGVWTlYu9EqyIaT7EjM4zUdA38mdLNPlpbu60uNKZU=')

from .base import *  # noqa: E402, F401, F403
from .base import env  # noqa: E402, F811

DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'that_place_test',
        'USER': 'that_place',
        'PASSWORD': 'that_place',
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': '5432',
    }
}

# Faster password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Use in-memory email backend in tests
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
