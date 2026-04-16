"""Tests for MQTT PKI certificate issuance (SR-01).

Uses a test CA generated at module load time — no broker, no external
services required.

Ref: security_risks.md § SR-01
"""
import base64
import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from apps.ingestion.pki import _CERT_VALID_DAYS, issue_device_certificate

# ---------------------------------------------------------------------------
# Test CA fixture — generated once per session
# ---------------------------------------------------------------------------


def _make_test_ca() -> tuple[str, str]:
    """Generate a minimal self-signed CA for testing. Returns (key_b64, cert_b64)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Test CA')]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Test CA')]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_b64 = base64.b64encode(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    ).decode()
    cert_b64 = base64.b64encode(
        cert.public_bytes(serialization.Encoding.PEM)
    ).decode()
    return key_b64, cert_b64


_TEST_CA_KEY_B64, _TEST_CA_CERT_B64 = _make_test_ca()


@pytest.fixture(autouse=True)
def ca_settings(settings):
    """Inject test CA into Django settings for all tests in this module."""
    settings.MQTT_CA_KEY_B64 = _TEST_CA_KEY_B64
    settings.MQTT_CA_CERT_B64 = _TEST_CA_CERT_B64


# ---------------------------------------------------------------------------
# Return value structure
# ---------------------------------------------------------------------------

class TestIssueCertificateReturnValue:

    def test_returns_dict_with_required_keys(self):
        result = issue_device_certificate('SCOUT-001')
        assert set(result.keys()) == {'cn', 'certificate_pem', 'private_key_pem', 'ca_cert_pem'}

    def test_cn_matches_expected_format(self):
        result = issue_device_certificate('SCOUT-001')
        assert result['cn'] == 'scout-SCOUT-001'

    def test_certificate_pem_is_valid_pem(self):
        result = issue_device_certificate('SCOUT-001')
        assert result['certificate_pem'].startswith('-----BEGIN CERTIFICATE-----')

    def test_private_key_pem_is_valid_pem(self):
        result = issue_device_certificate('SCOUT-001')
        assert result['private_key_pem'].startswith('-----BEGIN RSA PRIVATE KEY-----')

    def test_ca_cert_pem_matches_configured_ca(self):
        result = issue_device_certificate('SCOUT-001')
        ca_cert = x509.load_pem_x509_certificate(result['ca_cert_pem'].encode())
        assert ca_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == 'Test CA'


# ---------------------------------------------------------------------------
# Certificate properties
# ---------------------------------------------------------------------------

class TestCertificateProperties:

    @pytest.fixture(autouse=True)
    def _parse(self):
        result = issue_device_certificate('SCOUT-XYZ')
        self.cert = x509.load_pem_x509_certificate(result['certificate_pem'].encode())

    def test_cn_is_scout_prefixed_serial(self):
        cn = self.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == 'scout-SCOUT-XYZ'

    def test_is_not_a_ca(self):
        bc = self.cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is False

    def test_has_client_auth_extended_key_usage(self):
        eku = self.cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert ExtendedKeyUsageOID.CLIENT_AUTH in eku.value

    def test_key_usage_digital_signature(self):
        ku = self.cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert ku.value.digital_signature is True

    def test_not_valid_before_is_recent(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - self.cert.not_valid_before_utc
        assert delta.total_seconds() < 10

    def test_valid_for_correct_duration(self):
        duration = self.cert.not_valid_after_utc - self.cert.not_valid_before_utc
        assert duration.days == _CERT_VALID_DAYS

    def test_signed_by_test_ca(self):
        ca_cert = x509.load_pem_x509_certificate(
            base64.b64decode(_TEST_CA_CERT_B64)
        )
        assert self.cert.issuer == ca_cert.subject


# ---------------------------------------------------------------------------
# Key pair isolation — each call produces a unique key pair
# ---------------------------------------------------------------------------

class TestKeyPairUniqueness:

    def test_each_device_gets_a_unique_private_key(self):
        keys = {issue_device_certificate(f'SCOUT-{i}')['private_key_pem'] for i in range(5)}
        assert len(keys) == 5

    def test_same_serial_called_twice_produces_different_keys(self):
        r1 = issue_device_certificate('SCOUT-001')
        r2 = issue_device_certificate('SCOUT-001')
        assert r1['private_key_pem'] != r2['private_key_pem']


# ---------------------------------------------------------------------------
# Error handling — missing CA config
# ---------------------------------------------------------------------------

class TestMissingCAConfig:

    def test_raises_value_error_when_ca_key_missing(self, settings):
        settings.MQTT_CA_KEY_B64 = ''
        with pytest.raises(ValueError, match='MQTT_CA_KEY_B64'):
            issue_device_certificate('SCOUT-001')

    def test_raises_value_error_when_ca_cert_missing(self, settings):
        settings.MQTT_CA_CERT_B64 = ''
        with pytest.raises(ValueError, match='MQTT_CA_CERT_B64'):
            issue_device_certificate('SCOUT-001')
