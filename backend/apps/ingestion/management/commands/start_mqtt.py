"""Django management command: start_mqtt.

Starts the long-running MQTT subscriber process. Intended to be run as a
dedicated Docker service (see docker-compose.yml: mqtt_subscriber).

Usage::

    python manage.py start_mqtt

The command blocks until interrupted (SIGTERM / Ctrl-C). paho-mqtt handles
automatic reconnection via loop_forever(retry_first_connection=True).

Ref: SPEC.md § Feature: MQTT Infrastructure
"""
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Start the That Place MQTT subscriber worker."""

    help = 'Start the MQTT subscriber. Blocks until interrupted.'

    def handle(self, *args, **options) -> None:
        """Connect to the MQTT broker and run the event loop."""
        self.stdout.write('Starting That Place MQTT subscriber…')
        logger.info('MQTT subscriber starting')

        # Import here so Django is fully initialised before paho loads
        from apps.ingestion.mqtt_client import ThatPlaceMQTTClient

        client = ThatPlaceMQTTClient()
        try:
            client.start()
        except KeyboardInterrupt:
            self.stdout.write('MQTT subscriber stopped.')
            logger.info('MQTT subscriber stopped by KeyboardInterrupt')
