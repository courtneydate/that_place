"""Production settings for That Place.

Security hardening is applied here. All secrets must be supplied via
environment variables — never hardcoded.
"""
import environ

from .base import *  # noqa: F401, F403

env = environ.Env()

DEBUG = False
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
