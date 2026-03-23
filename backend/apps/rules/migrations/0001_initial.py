"""Initial migration for the rules app.

Creates: Rule, RuleConditionGroup, RuleCondition, RuleAction, RuleAuditLog.

RuleStreamIndex is NOT created here — it already exists in readings/0001
as a placeholder (with rule_id as a plain int). It is converted to a proper
FK in readings/0002_rulestreamindex_rule_fk.py which depends on this migration.

Ref: SPEC.md § Data Model — Rules Engine
"""
import django.contrib.postgres.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('devices', '0004_devicetype_status_indicator_mappings'),
        ('readings', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Rule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('cooldown_minutes', models.PositiveIntegerField(
                    blank=True,
                    null=True,
                    help_text='Minimum minutes between firings. Null = no cooldown.',
                )),
                ('active_days', django.contrib.postgres.fields.ArrayField(
                    base_field=models.IntegerField(),
                    blank=True,
                    null=True,
                    size=None,
                    help_text='Days of week the rule may fire: 0=Mon ... 6=Sun. Null = all days.',
                )),
                ('active_from', models.TimeField(
                    blank=True,
                    null=True,
                    help_text='Wall-clock start of the daily active window (tenant timezone).',
                )),
                ('active_to', models.TimeField(
                    blank=True,
                    null=True,
                    help_text='Wall-clock end of the daily active window (tenant timezone).',
                )),
                ('condition_group_operator', models.CharField(
                    choices=[('AND', 'AND — all groups must be true'), ('OR', 'OR — any group being true triggers the rule')],
                    default='AND',
                    max_length=3,
                )),
                ('current_state', models.BooleanField(
                    default=False,
                    help_text='True if the rule is currently in a triggered state.',
                )),
                ('last_fired_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rules',
                    to='accounts.tenant',
                )),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_rules',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='RuleConditionGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('logical_operator', models.CharField(
                    choices=[('AND', 'AND — all conditions must be true'), ('OR', 'OR — any condition being true satisfies the group')],
                    default='AND',
                    max_length=3,
                )),
                ('order', models.PositiveIntegerField(default=0)),
                ('rule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='condition_groups',
                    to='rules.rule',
                )),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='RuleCondition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('condition_type', models.CharField(
                    choices=[('stream', 'Stream value comparison'), ('staleness', 'Stream staleness')],
                    max_length=20,
                )),
                ('operator', models.CharField(blank=True, max_length=10)),
                ('threshold_value', models.TextField(blank=True, null=True)),
                ('staleness_minutes', models.PositiveIntegerField(blank=True, null=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('group', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='conditions',
                    to='rules.ruleconditiongroup',
                )),
                ('stream', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rule_conditions',
                    to='readings.stream',
                )),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='RuleAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(
                    choices=[('notify', 'Send notification'), ('command', 'Send device command')],
                    max_length=10,
                )),
                ('notification_channels', django.contrib.postgres.fields.ArrayField(
                    base_field=models.CharField(max_length=20),
                    blank=True,
                    default=list,
                    size=None,
                )),
                ('group_ids', django.contrib.postgres.fields.ArrayField(
                    base_field=models.IntegerField(),
                    blank=True,
                    default=list,
                    size=None,
                )),
                ('user_ids', django.contrib.postgres.fields.ArrayField(
                    base_field=models.IntegerField(),
                    blank=True,
                    default=list,
                    size=None,
                )),
                ('message_template', models.TextField(blank=True)),
                ('command', models.JSONField(blank=True, null=True)),
                ('rule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='actions',
                    to='rules.rule',
                )),
                ('target_device', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='rule_actions',
                    to='devices.device',
                )),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='RuleAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('changed_at', models.DateTimeField(auto_now_add=True)),
                ('changed_fields', models.JSONField()),
                ('rule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='audit_logs',
                    to='rules.rule',
                )),
                ('changed_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='rule_audit_logs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-changed_at'],
            },
        ),
    ]
