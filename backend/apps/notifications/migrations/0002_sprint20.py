"""Sprint 20 migration — adds UserNotificationPreference and NotificationSnooze.

Ref: SPEC.md § Data Model — UserNotificationPreference, NotificationSnooze
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
        ('rules', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserNotificationPreference',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID',
                )),
                ('in_app_enabled', models.BooleanField(
                    default=True,
                    help_text='Show notifications in the in-app bell/dropdown.',
                )),
                ('email_enabled', models.BooleanField(
                    default=True,
                    help_text='Send email notifications. On by default — user must opt out.',
                )),
                ('sms_enabled', models.BooleanField(
                    default=False,
                    help_text='Send SMS notifications. Off by default — user must opt in.',
                )),
                ('phone_number', models.CharField(
                    blank=True,
                    max_length=20,
                    help_text='E.164 format preferred (e.g. +61412345678). Required for SMS.',
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notification_preference',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='NotificationSnooze',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID',
                )),
                ('snoozed_until', models.DateTimeField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notification_snoozes',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('rule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notification_snoozes',
                    to='rules.rule',
                )),
            ],
            options={
                'unique_together': {('user', 'rule')},
            },
        ),
    ]
