"""Tests for Sprint 4: Site CRUD and tenant isolation."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Site


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


def make_site(tenant, name='Main Site'):
    return Site.objects.create(tenant=tenant, name=name)


URL = '/api/v1/sites/'


@pytest.mark.django_db
class TestSiteList:

    def test_tenant_admin_can_list_sites(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        make_site(tenant, 'Site A')
        make_site(tenant, 'Site B')
        resp = auth_client(admin).get(URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_operator_can_list_sites(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).get(URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_unauthenticated_cannot_list(self):
        resp = APIClient().get(URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_sites_not_visible(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        make_site(tenant_b, 'B Site')
        resp = auth_client(admin_a).get(URL)
        names = [s['name'] for s in resp.data]
        assert 'B Site' not in names


@pytest.mark.django_db
class TestSiteCreate:

    def test_admin_can_create_site(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(URL, {
            'name': 'Pumping Station 1',
            'description': 'Main pump',
            'latitude': '-33.865143',
            'longitude': '151.209900',
        })
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['name'] == 'Pumping Station 1'
        assert Site.objects.filter(tenant=tenant, name='Pumping Station 1').exists()

    def test_operator_cannot_create_site(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).post(URL, {'name': 'Site'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_name_required(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(URL, {'description': 'No name'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestSiteUpdate:

    def test_admin_can_update_site(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        resp = auth_client(admin).put(f'{URL}{site.pk}/', {'name': 'Updated Name'})
        assert resp.status_code == status.HTTP_200_OK
        site.refresh_from_db()
        assert site.name == 'Updated Name'

    def test_operator_cannot_update_site(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        site = make_site(tenant)
        resp = auth_client(op).put(f'{URL}{site.pk}/', {'name': 'Hack'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_update_not_allowed(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        site_b = make_site(tenant_b, 'B Site')
        resp = auth_client(admin_a).put(f'{URL}{site_b.pk}/', {'name': 'Stolen'})
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestSiteDelete:

    def test_admin_can_delete_site(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        site = make_site(tenant)
        resp = auth_client(admin).delete(f'{URL}{site.pk}/')
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Site.objects.filter(pk=site.pk).exists()

    def test_operator_cannot_delete_site(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        site = make_site(tenant)
        resp = auth_client(op).delete(f'{URL}{site.pk}/')
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_delete_not_allowed(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('admin@a.com', tenant_a)
        site_b = make_site(tenant_b)
        resp = auth_client(admin_a).delete(f'{URL}{site_b.pk}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND
