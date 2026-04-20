"""Add CommandLog model for device command history and ack tracking.

Sprint 21: Device Commands
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0007_device_mqtt_auth_fields'),
        ('rules', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CommandLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('command_name', models.CharField(max_length=255)),
                ('params_sent', models.JSONField(default=dict)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('ack_received_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[('sent', 'Sent'), ('acknowledged', 'Acknowledged'), ('timed_out', 'Timed Out')],
                    default='sent',
                    max_length=20,
                )),
                ('device', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='command_logs',
                    to='devices.device',
                )),
                ('sent_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sent_commands',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('triggered_by_rule', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='triggered_commands',
                    to='rules.rule',
                )),
            ],
            options={
                'ordering': ['-sent_at'],
            },
        ),
    ]
