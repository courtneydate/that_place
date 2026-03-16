"""Test settings for Fieldmouse.

Used by pytest-django via pytest.ini DJANGO_SETTINGS_MODULE.
Optimised for speed: faster password hashing, eager Celery tasks, in-memory email.
"""
from .base import *  # noqa: F401, F403
from .base import env  # noqa: F811

DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'fieldmouse_test',
        'USER': 'fieldmouse',
        'PASSWORD': 'fieldmouse',
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
