"""Initial migration for the integrations app.

Creates ThirdPartyAPIProvider, DataSource, DataSourceDevice.
"""
import apps.integrations.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Initial integrations schema."""

    initial = True

    dependencies = [
        ('accounts', '0005_tenant_battery_critical_threshold_and_more'),
        ('devices', '0003_devicehealth'),
    ]

    operations = [
        migrations.CreateModel(
            name='ThirdPartyAPIProvider',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(max_length=255, unique=True)),
                ('description', models.TextField(blank=True, default='')),
                ('logo', models.ImageField(
                    blank=True,
                    null=True,
                    upload_to='providers/logos/',
                    help_text='Provider logo — stored in configured object storage (S3/MinIO).',
                )),
                ('base_url', models.URLField(max_length=500)),
                ('auth_type', models.CharField(
                    max_length=40,
                    choices=[
                        ('api_key_header', 'API Key (Header)'),
                        ('api_key_query', 'API Key (Query Parameter)'),
                        ('bearer_token', 'Bearer Token'),
                        ('basic_auth', 'Basic Auth (Username/Password)'),
                        ('oauth2_client_credentials', 'OAuth2 Client Credentials'),
                        ('oauth2_password', 'OAuth2 Password Grant'),
                    ],
                )),
                ('auth_param_schema', models.JSONField(default=list)),
                ('discovery_endpoint', models.JSONField(default=dict)),
                ('detail_endpoint', models.JSONField(default=dict)),
                ('available_streams', models.JSONField(default=list)),
                ('default_poll_interval_seconds', models.PositiveIntegerField(default=300)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='DataSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('credentials', apps.integrations.fields.EncryptedJSONField(default=dict)),
                ('auth_token_cache', apps.integrations.fields.EncryptedJSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='data_sources',
                    to='accounts.tenant',
                )),
                ('provider', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='data_sources',
                    to='integrations.thirdpartyapiprovider',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='DataSourceDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_device_id', models.CharField(max_length=500)),
                ('external_device_name', models.CharField(blank=True, max_length=255, null=True)),
                ('active_stream_keys', models.JSONField(default=list)),
                ('last_polled_at', models.DateTimeField(blank=True, null=True)),
                ('last_poll_status', models.CharField(
                    blank=True,
                    max_length=20,
                    null=True,
                    choices=[('ok', 'OK'), ('error', 'Error'), ('auth_failure', 'Auth Failure')],
                )),
                ('last_poll_error', models.TextField(blank=True, null=True)),
                ('consecutive_poll_failures', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('datasource', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='devices',
                    to='integrations.datasource',
                )),
                ('virtual_device', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='datasource_device',
                    to='devices.device',
                )),
            ],
            options={
                'ordering': ['-datasource__created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='datasourcedevice',
            constraint=models.UniqueConstraint(
                fields=['datasource', 'external_device_id'],
                name='unique_device_per_datasource',
            ),
        ),
    ]
