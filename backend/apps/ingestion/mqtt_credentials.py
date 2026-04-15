"""MQTT credential lifecycle management via the Mosquitto Dynamic Security plugin.

Supports two authentication modes for Scout devices:

  password    — username/password over port 1883 (plaintext).
                Used for legacy v1 Scouts that do not support TLS.

  certificate — mutual TLS over port 8883. The Scout presents a client
                certificate signed by the That Place CA. Mosquitto extracts
                the cert CN as the MQTT username via `use_subject_as_username`.
                Authentication is handled by TLS; Dynamic Security only
                enforces ACLs.

Both modes create the same dynamic security role and client entry, restricting
the Scout to its own serial-number topic namespace:
  Publish / Subscribe: that-place/scout/{serial}/#
  Publish / Subscribe: fm/mm/{serial}/#  (legacy namespace, no-op after migration)

Ref: SPEC.md § Feature: Device Registration & Provisioning
     security_risks.md § SR-01
"""
import json
import logging
import secrets
import time

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)

_DYNSEC_CONTROL = '$CONTROL/dynamic-security/v1'
_DYNSEC_RESPONSE = '$CONTROL/dynamic-security/v1/response'
_RESPONSE_TIMEOUT = 5  # seconds


def _scout_username(serial_number: str) -> str:
    """Return the MQTT client username for a Scout device.

    For password mode this is the literal username.
    For certificate mode this must match the certificate CN exactly, since
    Mosquitto's `use_subject_as_username true` uses the CN for ACL lookups.
    """
    return f'scout-{serial_number}'


def _scout_rolename(serial_number: str) -> str:
    """Return the dynamic-security role name for a Scout device."""
    return f'scout-{serial_number}'


def _build_scout_acls(serial_number: str) -> list:
    """Build the ACL list restricting a Scout to its own topic namespace.

    Both v1 and legacy-v1 namespaces are granted. The legacy namespace is
    a no-op once firmware is updated; granting it at provisioning time avoids
    re-provisioning during the migration window.
    """
    return [
        {'acltype': 'publishClientSend',
         'topic': f'that-place/scout/{serial_number}/#',
         'priority': 0, 'allow': True},
        {'acltype': 'subscribePattern',
         'topic': f'that-place/scout/{serial_number}/#',
         'priority': 0, 'allow': True},
        {'acltype': 'publishClientSend',
         'topic': f'fm/mm/{serial_number}/#',
         'priority': 0, 'allow': True},
        {'acltype': 'subscribePattern',
         'topic': f'fm/mm/{serial_number}/#',
         'priority': 0, 'allow': True},
    ]


class MQTTCredentialService:
    """Create and revoke per-device MQTT credentials.

    Communicates with the Mosquitto Dynamic Security plugin via the
    $CONTROL/dynamic-security/v1 topic using the platform admin account.
    """

    def _send_commands(self, commands: list) -> bool:
        """Publish a batch of dynamic-security commands and wait for a response.

        Opens a short-lived admin connection, publishes the command JSON,
        waits up to _RESPONSE_TIMEOUT seconds for a response, then disconnects.

        Returns True if all commands succeeded, False on any error or timeout.
        """
        username = getattr(settings, 'MQTT_ADMIN_USERNAME', '')
        password = getattr(settings, 'MQTT_ADMIN_PASSWORD', '')

        if not username or not password:
            logger.error(
                'MQTT_ADMIN_USERNAME / MQTT_ADMIN_PASSWORD not configured — '
                'cannot manage device credentials'
            )
            return False

        _result = {'done': False, 'success': False}

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f'tp-dynsec-{secrets.token_hex(4)}',
        )
        client.username_pw_set(username, password)

        def _on_connect(c, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                logger.error('Dynsec admin connect failed: %s', reason_code)
                _result['done'] = True
                return
            c.subscribe(_DYNSEC_RESPONSE, qos=1)
            c.publish(_DYNSEC_CONTROL, json.dumps({'commands': commands}), qos=1)

        def _on_message(c, userdata, message):
            try:
                response = json.loads(message.payload.decode())
                errors = [
                    r['error']
                    for r in response.get('responses', [])
                    if r.get('error')
                ]
                if errors:
                    for err in errors:
                        logger.error('Dynamic security error: %s', err)
                    _result['success'] = False
                else:
                    _result['success'] = True
            except Exception:
                logger.exception('Failed to parse dynamic security response')
            finally:
                _result['done'] = True
                c.disconnect()

        client.on_connect = _on_connect
        client.on_message = _on_message

        host = getattr(settings, 'MQTT_BROKER_HOST', 'localhost')
        port = int(getattr(settings, 'MQTT_BROKER_PORT', 1883))

        try:
            client.connect(host, port, keepalive=10)
            client.loop_start()
            deadline = time.monotonic() + _RESPONSE_TIMEOUT
            while not _result['done'] and time.monotonic() < deadline:
                time.sleep(0.05)
            client.loop_stop()
            if not _result['done']:
                logger.error(
                    'Dynamic security command timed out after %ss', _RESPONSE_TIMEOUT
                )
                return False
        except Exception:
            logger.exception('Error connecting to broker for dynamic security command')
            return False

        return _result['success']

    def _create_dynsec_client(
        self, serial_number: str, password: str | None = None
    ) -> bool:
        """Create a dynamic security role + client entry for a Scout.

        If password is None, no password is set on the client — authentication
        is expected via TLS certificate on the mTLS listener (port 8883).
        """
        commands = [
            {
                'command': 'createRole',
                'rolename': _scout_rolename(serial_number),
                'acls': _build_scout_acls(serial_number),
            },
            {
                'command': 'createClient',
                'username': _scout_username(serial_number),
                'textname': f'Scout {serial_number}',
                'roles': [{'rolename': _scout_rolename(serial_number)}],
                **({'password': password} if password else {}),
            },
        ]
        return self._send_commands(commands)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def provision_device(self, device) -> dict | None:
        """Provision MQTT credentials for a Scout device.

        Behaviour depends on device.mqtt_auth_mode:

          'password'    — generates a random password, creates a dynamic
                          security client entry with that password.
                          Device connects on port 1883.

          'certificate' — issues an X.509 client certificate signed by the
                          That Place CA, creates a dynamic security client
                          entry without a password (TLS cert is the auth).
                          Device connects on port 8883.

        Returns a dict on success:

          Password mode:
            {'mode': 'password', 'port': 1883, 'username': '...', 'password': '...'}

          Certificate mode:
            {'mode': 'certificate', 'port': 8883, 'username': '...',
             'certificate_pem': '...', 'private_key_pem': '...', 'ca_cert_pem': '...'}

        Returns None on failure.
        The caller is responsible for persisting the returned credentials
        (encrypted) on the Device record.
        """
        from apps.devices.models import Device as DeviceModel

        serial = device.serial_number
        mode = getattr(device, 'mqtt_auth_mode', DeviceModel.MQTTAuthMode.PASSWORD)

        if mode == DeviceModel.MQTTAuthMode.CERTIFICATE:
            return self._provision_certificate(serial)
        return self._provision_password(serial)

    def _provision_password(self, serial_number: str) -> dict | None:
        """Issue username/password credentials for a Scout."""
        password = secrets.token_urlsafe(32)
        if self._create_dynsec_client(serial_number, password=password):
            logger.info('Provisioned password credentials for Scout %s', serial_number)
            return {
                'mode': 'password',
                'port': 1883,
                'username': _scout_username(serial_number),
                'password': password,
            }
        logger.error('Failed to provision password credentials for Scout %s', serial_number)
        return None

    def _provision_certificate(self, serial_number: str) -> dict | None:
        """Issue mTLS client certificate credentials for a Scout."""
        from apps.ingestion.pki import issue_device_certificate

        try:
            cert_data = issue_device_certificate(serial_number)
        except ValueError as exc:
            logger.error('Cannot issue certificate for Scout %s: %s', serial_number, exc)
            return None

        # Create dynamic security entry without a password — auth is via cert.
        if self._create_dynsec_client(serial_number, password=None):
            logger.info('Provisioned certificate credentials for Scout %s', serial_number)
            return {
                'mode': 'certificate',
                'port': 8883,
                'username': cert_data['cn'],
                'certificate_pem': cert_data['certificate_pem'],
                'private_key_pem': cert_data['private_key_pem'],
                'ca_cert_pem': cert_data['ca_cert_pem'],
            }
        logger.error('Failed to create dynsec entry for Scout %s', serial_number)
        return None

    def revoke_device(self, device) -> None:
        """Disable the MQTT client for a deactivated or rejected Scout.

        The client is disabled rather than deleted so the record persists
        for audit purposes. Works for both auth modes.
        """
        serial = device.serial_number
        commands = [{'command': 'disableClient', 'username': _scout_username(serial)}]
        if self._send_commands(commands):
            logger.info('Disabled MQTT client for Scout %s', serial)
        else:
            logger.error('Failed to disable MQTT client for Scout %s', serial)
