"""MQTT client for the That Place ingestion pipeline.

Connects to the configured broker using mTLS (port 8883) when backend
certificate env vars are present, falling back to username/password for
local development without TLS.

Wildcard subscriptions
----------------------
``fm/mm/+/#``           — all legacy v1 inbound topics
``that-place/scout/+/#`` — all That Place v2 topics (Scout + device, + acks)

The router inside the Celery task handles filtering of outbound/unknown topics
(e.g. fm/mm/{serial}/relays) so we subscribe broadly and let the pattern
registry decide what to process.

``publish_mqtt_message(topic, payload)`` — short-lived publish function used by
Celery worker tasks (send_device_command) to publish to command topics without
sharing the long-lived subscriber connection across processes.

Ref: SPEC.md § Feature: MQTT Infrastructure
     SPEC.md § Backend MQTT Service Identity
"""
import base64
import logging
import os
import ssl
import tempfile

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)

# Topics the subscriber listens on (QoS 1 — at least once delivery)
SUBSCRIPTIONS = [
    ('fm/mm/+/#', 1),
    ('that-place/scout/+/#', 1),
]


def _build_tls_context() -> ssl.SSLContext | None:
    """Build an SSLContext for mTLS if backend cert env vars are set.

    Returns None if MQTT_BACKEND_CERT_B64 is not configured (local dev
    without TLS falls back to username/password on port 1883).
    """
    cert_b64 = getattr(settings, 'MQTT_BACKEND_CERT_B64', '')
    key_b64 = getattr(settings, 'MQTT_BACKEND_KEY_B64', '')
    ca_b64 = getattr(settings, 'MQTT_CA_CERT_B64', '')

    if not cert_b64:
        return None

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False  # Mosquitto uses IP or 'mosquitto' hostname in dev

    if ca_b64:
        ca_pem = base64.b64decode(ca_b64)
        # SSLContext.load_verify_locations requires a file path or bytes (Python 3.13+)
        # Use a temp file for compatibility with Python 3.11/3.12.
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pem') as f:
            f.write(ca_pem)
            ca_path = f.name
        try:
            ctx.load_verify_locations(cafile=ca_path)
        finally:
            os.unlink(ca_path)

    if cert_b64 and key_b64:
        cert_pem = base64.b64decode(cert_b64)
        key_pem = base64.b64decode(key_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pem') as cf:
            cf.write(cert_pem)
            cert_path = cf.name
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pem') as kf:
            kf.write(key_pem)
            key_path = kf.name
        try:
            ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    return ctx


def _configure_client(client: mqtt.Client) -> None:
    """Apply mTLS or username/password auth to a paho client instance."""
    tls_ctx = _build_tls_context()
    if tls_ctx:
        client.tls_set_context(tls_ctx)
        logger.debug('MQTT client configured with mTLS (port 8883)')
    else:
        username = getattr(settings, 'MQTT_USERNAME', '')
        password = getattr(settings, 'MQTT_PASSWORD', '')
        if username:
            client.username_pw_set(username, password or None)
            logger.debug('MQTT client configured with username/password (local dev)')


def publish_mqtt_message(topic: str, payload: str, qos: int = 1) -> None:
    """Publish a single message to the broker using a short-lived connection.

    Used by Celery worker tasks (send_device_command) which run in a separate
    process from the long-lived ThatPlaceMQTTClient subscriber. Creates a
    fresh paho client, connects, publishes, and disconnects immediately.

    Raises an exception if the publish fails so the caller can log / retry.

    Ref: SPEC.md § Backend MQTT Service Identity — Publish approach
    """
    host = settings.MQTT_BROKER_HOST
    port = settings.MQTT_BROKER_PORT

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id='that-place-backend-pub',
    )
    _configure_client(client)

    client.connect(host, port, keepalive=10)
    result = client.publish(topic, payload, qos=qos)
    result.wait_for_publish(timeout=5)
    client.disconnect()

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f'MQTT publish failed with rc={result.rc} on topic "{topic}"')

    logger.debug('Published to MQTT topic "%s"', topic)


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

        _configure_client(self._client)

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
