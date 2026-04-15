"""Tests for MQTT credential lifecycle management (SR-01).

Unit tests — no live broker or CA required. The paho client and PKI module
are mocked so tests run without Docker.

Ref: security_risks.md § SR-01
"""
from unittest.mock import MagicMock, patch

import pytest

from apps.ingestion.mqtt_credentials import (
    MQTTCredentialService,
    _build_scout_acls,
    _scout_rolename,
    _scout_username,
)


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

class TestNamingHelpers:

    def test_scout_username_prefixes_serial(self):
        assert _scout_username('SCOUT-001') == 'scout-SCOUT-001'

    def test_scout_rolename_prefixes_serial(self):
        assert _scout_rolename('SCOUT-001') == 'scout-SCOUT-001'

    def test_username_and_rolename_match(self):
        """Username must equal the cert CN for mTLS ACL lookups to work."""
        serial = 'FM-UNIT-42'
        assert _scout_username(serial) == _scout_rolename(serial)


# ---------------------------------------------------------------------------
# ACL construction
# ---------------------------------------------------------------------------

class TestBuildScoutAcls:

    def test_grants_v1_publish(self):
        topics = [a['topic'] for a in _build_scout_acls('S1') if a['acltype'] == 'publishClientSend']
        assert 'that-place/scout/S1/#' in topics

    def test_grants_legacy_publish(self):
        topics = [a['topic'] for a in _build_scout_acls('S1') if a['acltype'] == 'publishClientSend']
        assert 'fm/mm/S1/#' in topics

    def test_grants_v1_subscribe(self):
        topics = [a['topic'] for a in _build_scout_acls('S1') if a['acltype'] == 'subscribePattern']
        assert 'that-place/scout/S1/#' in topics

    def test_grants_legacy_subscribe(self):
        topics = [a['topic'] for a in _build_scout_acls('S1') if a['acltype'] == 'subscribePattern']
        assert 'fm/mm/S1/#' in topics

    def test_does_not_reference_other_serials(self):
        for entry in _build_scout_acls('SCOUT-001'):
            assert 'SCOUT-002' not in entry['topic']

    def test_all_entries_are_allow(self):
        assert all(a['allow'] is True for a in _build_scout_acls('SCOUT-999'))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_device_password():
    device = MagicMock()
    device.serial_number = 'SCOUT-PW-01'
    device.mqtt_auth_mode = 'password'
    return device


@pytest.fixture()
def mock_device_cert():
    device = MagicMock()
    device.serial_number = 'SCOUT-CERT-01'
    device.mqtt_auth_mode = 'certificate'
    return device


@pytest.fixture()
def broker_settings(settings):
    settings.MQTT_ADMIN_USERNAME = 'admin'
    settings.MQTT_ADMIN_PASSWORD = 'adminpass'
    settings.MQTT_BROKER_HOST = 'localhost'
    settings.MQTT_BROKER_PORT = 1883
    return settings


# ---------------------------------------------------------------------------
# Password mode — provision_device
# ---------------------------------------------------------------------------

class TestProvisionPassword:

    def test_returns_dict_with_mode_password(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        with patch.object(service, '_send_commands', return_value=True):
            result = service.provision_device(mock_device_password)
        assert result['mode'] == 'password'

    def test_returns_port_1883(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        with patch.object(service, '_send_commands', return_value=True):
            result = service.provision_device(mock_device_password)
        assert result['port'] == 1883

    def test_returns_password_string(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        with patch.object(service, '_send_commands', return_value=True):
            result = service.provision_device(mock_device_password)
        assert isinstance(result['password'], str)
        assert len(result['password']) > 20

    def test_returns_none_on_failure(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        with patch.object(service, '_send_commands', return_value=False):
            result = service.provision_device(mock_device_password)
        assert result is None

    def test_unique_password_each_call(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        passwords = set()
        with patch.object(service, '_send_commands', return_value=True):
            for _ in range(10):
                r = service.provision_device(mock_device_password)
                passwords.add(r['password'])
        assert len(passwords) == 10

    def test_commands_include_createRole_and_createClient(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        captured = {}
        with patch.object(service, '_send_commands', side_effect=lambda c: captured.update({'c': c}) or True):
            service.provision_device(mock_device_password)
        names = [cmd['command'] for cmd in captured['c']]
        assert 'createRole' in names
        assert 'createClient' in names

    def test_createClient_includes_password(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        captured = {}
        with patch.object(service, '_send_commands', side_effect=lambda c: captured.update({'c': c}) or True):
            service.provision_device(mock_device_password)
        create_client = next(c for c in captured['c'] if c['command'] == 'createClient')
        assert 'password' in create_client


# ---------------------------------------------------------------------------
# Certificate mode — provision_device
# ---------------------------------------------------------------------------

_FAKE_CERT_DATA = {
    'cn': 'scout-SCOUT-CERT-01',
    'certificate_pem': '-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n',
    'private_key_pem': '-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----\n',
    'ca_cert_pem': '-----BEGIN CERTIFICATE-----\nFAKECA\n-----END CERTIFICATE-----\n',
}


class TestProvisionCertificate:

    def test_returns_dict_with_mode_certificate(self, mock_device_cert, broker_settings):
        service = MQTTCredentialService()
        with patch.object(service, '_send_commands', return_value=True), \
             patch('apps.ingestion.mqtt_credentials.MQTTCredentialService._provision_certificate',
                   return_value={**_FAKE_CERT_DATA, 'mode': 'certificate', 'port': 8883, 'username': 'scout-SCOUT-CERT-01'}):
            result = service.provision_device(mock_device_cert)
        assert result['mode'] == 'certificate'

    def test_returns_port_8883(self, mock_device_cert, broker_settings):
        service = MQTTCredentialService()
        with patch('apps.ingestion.pki.issue_device_certificate', return_value=_FAKE_CERT_DATA), \
             patch.object(service, '_send_commands', return_value=True):
            result = service.provision_device(mock_device_cert)
        assert result['port'] == 8883

    def test_returns_certificate_pem(self, mock_device_cert, broker_settings):
        service = MQTTCredentialService()
        with patch('apps.ingestion.pki.issue_device_certificate', return_value=_FAKE_CERT_DATA), \
             patch.object(service, '_send_commands', return_value=True):
            result = service.provision_device(mock_device_cert)
        assert 'certificate_pem' in result
        assert 'private_key_pem' in result
        assert 'ca_cert_pem' in result

    def test_returns_none_when_pki_raises(self, mock_device_cert, broker_settings):
        service = MQTTCredentialService()
        with patch('apps.ingestion.pki.issue_device_certificate',
                   side_effect=ValueError('CA not configured')):
            result = service.provision_device(mock_device_cert)
        assert result is None

    def test_returns_none_when_dynsec_fails(self, mock_device_cert, broker_settings):
        service = MQTTCredentialService()
        with patch('apps.ingestion.pki.issue_device_certificate', return_value=_FAKE_CERT_DATA), \
             patch.object(service, '_send_commands', return_value=False):
            result = service.provision_device(mock_device_cert)
        assert result is None

    def test_createClient_has_no_password_for_cert_mode(self, mock_device_cert, broker_settings):
        """Cert-based clients authenticate via TLS — no password in dynsec."""
        service = MQTTCredentialService()
        captured = {}
        with patch('apps.ingestion.pki.issue_device_certificate', return_value=_FAKE_CERT_DATA), \
             patch.object(service, '_send_commands',
                          side_effect=lambda c: captured.update({'c': c}) or True):
            service.provision_device(mock_device_cert)
        create_client = next(c for c in captured['c'] if c['command'] == 'createClient')
        assert 'password' not in create_client


# ---------------------------------------------------------------------------
# revoke_device
# ---------------------------------------------------------------------------

class TestRevokeDevice:

    def test_sends_disable_client_command(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        captured = {}
        with patch.object(service, '_send_commands',
                          side_effect=lambda c: captured.update({'c': c}) or True):
            service.revoke_device(mock_device_password)
        assert captured['c'][0]['command'] == 'disableClient'
        assert captured['c'][0]['username'] == _scout_username('SCOUT-PW-01')

    def test_works_for_cert_mode_device(self, mock_device_cert, broker_settings):
        """revoke_device is auth-mode agnostic — disables by username."""
        service = MQTTCredentialService()
        captured = {}
        with patch.object(service, '_send_commands',
                          side_effect=lambda c: captured.update({'c': c}) or True):
            service.revoke_device(mock_device_cert)
        assert captured['c'][0]['username'] == _scout_username('SCOUT-CERT-01')

    def test_does_not_raise_on_failure(self, mock_device_password, broker_settings):
        service = MQTTCredentialService()
        with patch.object(service, '_send_commands', return_value=False):
            service.revoke_device(mock_device_password)  # must not raise


# ---------------------------------------------------------------------------
# Missing config guard
# ---------------------------------------------------------------------------

class TestMissingConfig:

    def test_send_commands_returns_false_without_credentials(self, settings):
        settings.MQTT_ADMIN_USERNAME = ''
        settings.MQTT_ADMIN_PASSWORD = ''
        service = MQTTCredentialService()
        assert service._send_commands([{'command': 'test'}]) is False

    def test_provision_returns_none_without_admin_credentials(
        self, mock_device_password, settings
    ):
        settings.MQTT_ADMIN_USERNAME = ''
        settings.MQTT_ADMIN_PASSWORD = ''
        service = MQTTCredentialService()
        assert service.provision_device(mock_device_password) is None
