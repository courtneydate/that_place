"""Initial migration for the notifications app.

Creates: Notification

Ref: SPEC.md § Data Model — Notification
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('alerts', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(
                    choices=[('alert', 'Alert'), ('system_event', 'System event')],
                    max_length=20,
                )),
                ('event_type', models.CharField(blank=True, max_length=50)),
                ('event_data', models.JSONField(blank=True, null=True)),
                ('channel', models.CharField(
                    choices=[('in_app', 'In-app'), ('email', 'Email'), ('sms', 'SMS'), ('push', 'Push')],
                    default='in_app',
                    max_length=10,
                )),
                ('sent_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('delivery_status', models.CharField(
                    choices=[('sent', 'Sent'), ('delivered', 'Delivered'), ('failed', 'Failed')],
                    default='sent',
                    max_length=10,
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('alert', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='notifications',
                    to='alerts.alert',
                )),
            ],
            options={
                'ordering': ['-sent_at'],
            },
        ),
    ]
