import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_tenant_battery_critical_threshold_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantInvite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('role', models.CharField(
                    choices=[('admin', 'Admin'), ('operator', 'Operator'), ('viewer', 'View-Only')],
                    max_length=20,
                )),
                ('token_hash', models.CharField(
                    help_text='SHA-256 hex digest of the raw invite token. Never store the raw token.',
                    max_length=64,
                    unique=True,
                )),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sent_invites',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invites',
                    to='accounts.tenant',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
