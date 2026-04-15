"""Add MQTT auth mode, certificate, and private key fields to Device.

Extends the credential model from password-only (0006) to support both
username/password and mTLS client certificate authentication.

Related: security_risks.md § SR-01
"""
from django.db import migrations, models
import encrypted_model_fields.fields


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0006_device_mqtt_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='mqtt_auth_mode',
            field=models.CharField(
                choices=[
                    ('password', 'Username / Password (port 1883)'),
                    ('certificate', 'Client Certificate / mTLS (port 8883)'),
                ],
                default='password',
                max_length=20,
                help_text=(
                    'Authentication mode used when this Scout connects to the MQTT broker. '
                    'Password: legacy devices or devices without TLS support (port 1883). '
                    'Certificate: new That Place v1 Scouts with mTLS support (port 8883).'
                ),
            ),
        ),
        migrations.AddField(
            model_name='device',
            name='mqtt_certificate',
            field=models.TextField(
                blank=True,
                null=True,
                help_text=(
                    'PEM-encoded client certificate (certificate mode only). '
                    'Public — safe to store unencrypted.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='device',
            name='mqtt_private_key',
            field=encrypted_model_fields.fields.EncryptedTextField(
                blank=True,
                null=True,
                help_text=(
                    'Encrypted PEM-encoded private key (certificate mode only). '
                    'Clear this field once the operator confirms the key has been loaded.'
                ),
            ),
        ),
    ]
