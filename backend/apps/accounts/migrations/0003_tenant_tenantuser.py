"""Migration to add Tenant and TenantUser models.

Sprint 2: Tenant management — creates the Tenant and TenantUser tables.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create Tenant and TenantUser tables."""

    dependencies = [
        ('accounts', '0002_alter_user_managers'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tenant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(max_length=255, unique=True)),
                ('timezone', models.CharField(
                    default='Australia/Sydney',
                    help_text='IANA timezone string, e.g. "Australia/Brisbane".',
                    max_length=100,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='TenantUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[('admin', 'Admin'), ('operator', 'Operator'), ('viewer', 'View-Only')],
                    default='admin',
                    max_length=20,
                )),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tenant_users',
                    to='accounts.tenant',
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tenantuser',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['joined_at'],
            },
        ),
    ]
