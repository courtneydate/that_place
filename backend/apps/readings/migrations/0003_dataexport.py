"""Add DataExport model for CSV export audit logging.

Ref: SPEC.md § Feature: Data Export (CSV) — Export history
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('readings', '0002_rulestreamindex_rule_fk'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DataExport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stream_ids', models.JSONField(help_text='List of Stream PKs included in this export.')),
                ('date_from', models.DateTimeField()),
                ('date_to', models.DateTimeField()),
                ('exported_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='exports',
                    to='accounts.tenant',
                )),
                ('exported_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='exports',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-exported_at'],
            },
        ),
    ]
