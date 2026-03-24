"""Development settings for That Place.

Overrides base settings for local development.
All services run via docker-compose.
"""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ['*']
CORS_ALLOW_ALL_ORIGINS = True

INSTALLED_APPS += ['django_extensions']  # noqa: F405
