"""MQTT client for the That Place ingestion pipeline.

Connects to the configured broker, subscribes to the two wildcard topics that
cover both legacy v1 and That Place v2 traffic, and dispatches a Celery task
for every inbound message.

Wildcard subscriptions
----------------------
``fm/mm/+/#``           — all legacy v1 inbound topics
``that-place/scout/+/#`` — all That Place v2 topics (Scout + device)

The router inside the Celery task handles filtering of outbound/unknown topics
(e.g. fm/mm/{serial}/relays) so we subscribe broadly and let the pattern
registry decide what to process.

Ref: SPEC.md § Feature: MQTT Infrastructure
"""
import logging

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)

# Topics the subscriber listens on (QoS 1 — at least once delivery)
SUBSCRIPTIONS = [
    ('fm/mm/+/#', 1),
    ('that-place/scout/+/#', 1),
]


class ThatPlaceMQTTClient:
    """Wrapper around the paho-mqtt client for the That Place subscriber.

    Connects to the broker using settings from ``django.conf.settings``,
    subscribes to the wildcard topics, and dispatches
    :func:`~apps.ingestion.tasks.process_mqtt_message` for each message.
    """

    def __init__(self) -> None:
        """Initialise the paho client and bind callbacks."""
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=getattr(settings, 'MQTT_CLIENT_ID', 'that-place-backend'),
        )

        username = getattr(settings, 'MQTT_USERNAME', '')
        password = getattr(settings, 'MQTT_PASSWORD', '')
        if username:
            self._client.username_pw_set(username, password or None)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        """Called when the broker connection is established."""
        if reason_code.is_failure:
            logger.error('MQTT connection failed: %s', reason_code)
            return

        logger.info(
            'MQTT connected to %s:%s',
            settings.MQTT_BROKER_HOST,
            settings.MQTT_BROKER_PORT,
        )
        for topic, qos in SUBSCRIPTIONS:
            client.subscribe(topic, qos)
            logger.info('MQTT subscribed to %s (QoS %d)', topic, qos)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Called on disconnect — paho will auto-reconnect if loop_forever is running."""
        if reason_code.value != 0:
            logger.warning('MQTT unexpectedly disconnected (reason=%s) — will reconnect', reason_code)
        else:
            logger.info('MQTT disconnected cleanly')

    def _on_message(self, client, userdata, message):
        """Called for every inbound message — dispatches a Celery task."""
        topic = message.topic
        try:
            payload = message.payload.decode('utf-8', errors='replace')
        except Exception:
            payload = repr(message.payload)

        logger.debug('MQTT message received on topic "%s"', topic)

        # Import here to avoid circular imports at module load time
        from .tasks import process_mqtt_message  # noqa: PLC0415
        process_mqtt_message.delay(topic, payload)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to the broker and start the blocking event loop.

        This method blocks indefinitely — run it in a dedicated process
        (see the ``start_mqtt`` management command).
        """
        host = settings.MQTT_BROKER_HOST
        port = settings.MQTT_BROKER_PORT

        logger.info('MQTT client connecting to %s:%s …', host, port)
        self._client.connect(host, port, keepalive=60)
        self._client.loop_forever(retry_first_connection=True)
