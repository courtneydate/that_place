"""Tests for Sprint 4: Tenant settings endpoint."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User


def make_tenant(name='Acme'):
    from django.utils.text import slugify
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


URL = '/api/v1/settings/'


@pytest.mark.django_db
class TestTenantSettings:

    def test_tenant_user_can_get_settings(self):
        tenant = make_tenant()
        user = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(user).get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['timezone'] == 'Australia/Sydney'
        assert resp.data['name'] == 'Acme'

    def test_tenant_admin_can_update_timezone(self):
        tenant = make_tenant()
        user = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(user).patch(URL, {'timezone': 'Australia/Brisbane'})
        assert resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.timezone == 'Australia/Brisbane'

    def test_operator_cannot_update_timezone(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).patch(URL, {'timezone': 'UTC'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_cannot_update_timezone(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        viewer = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(viewer).patch(URL, {'timezone': 'UTC'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_cannot_access_settings(self):
        resp = APIClient().get(URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_fieldmouse_admin_cannot_access_settings(self):
        fm = User.objects.create_user(email='fm@fieldmouse.io', password='pass', is_fieldmouse_admin=True)
        resp = auth_client(fm, 'pass').get(URL)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_name_and_slug_are_read_only(self):
        tenant = make_tenant()
        user = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(user).patch(URL, {'name': 'New Name', 'slug': 'new-slug'})
        assert resp.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.name == 'Acme'
        assert tenant.slug == 'acme'
