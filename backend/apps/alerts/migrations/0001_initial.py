"""Initial migration for the alerts app.

Creates: Alert

Ref: SPEC.md § Data Model — Alert
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0001_initial'),
        ('rules', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Alert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('triggered_at', models.DateTimeField()),
                ('status', models.CharField(
                    choices=[
                        ('active', 'Active'),
                        ('acknowledged', 'Acknowledged'),
                        ('resolved', 'Resolved'),
                    ],
                    db_index=True,
                    default='active',
                    max_length=20,
                )),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
                ('acknowledged_note', models.TextField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('rule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='alerts',
                    to='rules.rule',
                )),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='alerts',
                    to='accounts.tenant',
                )),
                ('acknowledged_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='acknowledged_alerts',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('resolved_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='resolved_alerts',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-triggered_at'],
            },
        ),
    ]
