"""AppConfig for the notifications app."""
import logging

from celery.signals import task_failure
from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


def _seed_event_registry(sender, **kwargs):
    """post_migrate receiver — populate the NotificationEventType registry.

    Runs after the notifications app's tables are created/migrated, in every
    environment including the ``--no-migrations`` test database. Idempotent.
    """
    from .event_seeds import seed_event_types
    seed_event_types()


def _on_task_failure(sender=None, exception=None, **kwargs):
    """Celery task_failure receiver — emit the backend_pipeline_failure event.

    Fires for any failed Celery task. Deduplicated per (task name, hour) so a
    recurring failure does not flood That Place Admins. The notifications
    tasks are skipped to avoid a failure -> emit -> failure loop.

    Ref: ROADMAP Sprint 23
    """
    task_name = getattr(sender, 'name', '') or 'unknown'
    if task_name.startswith('notifications.'):
        return
    try:
        from django.core.cache import cache
        if not cache.add(f'pipeline_failure_notified_{task_name}', True, timeout=3600):
            return
        from .tasks import emit_event
        emit_event.delay(
            'backend_pipeline_failure',
            {'detail': f'{task_name} failed: {exception}'},
        )
    except Exception:
        logger.exception('backend_pipeline_failure emitter failed')


class NotificationsConfig(AppConfig):
    """Configuration for the notifications application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notifications'
    label = 'notifications'

    def ready(self):
        """Connect signal handlers for the notifications app."""
        post_migrate.connect(_seed_event_registry, sender=self)
        task_failure.connect(_on_task_failure)
