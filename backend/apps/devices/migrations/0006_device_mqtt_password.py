"""Add encrypted mqtt_password field to Device.

The mqtt_password field stores the plaintext MQTT credential (encrypted at
rest via django-encrypted-model-fields) provisioned when a Scout device is
approved. It is null for API-connected and bridged devices.

Related: security_risks.md § SR-01
"""
from django.db import migrations
import encrypted_model_fields.fields


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0005_alter_devicetype_status_indicator_mappings'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='mqtt_password',
            field=encrypted_model_fields.fields.EncryptedTextField(
                blank=True,
                null=True,
                help_text=(
                    'Encrypted plaintext MQTT password provisioned when the device is approved. '
                    'Null for API-connected devices and bridged (non-Scout) devices. '
                    'Provide to the device operator for Scout firmware configuration.'
                ),
            ),
        ),
    ]
