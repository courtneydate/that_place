"""Tests for ThirdPartyAPIProvider CRUD.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import pytest
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.integrations.models import ThirdPartyAPIProvider

PROVIDERS_URL = '/api/v1/api-providers/'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name='Acme'):
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_fm_admin(email='fm@fieldmouse.io', password='testpass123'):
    return User.objects.create_user(email=email, password=password, is_fieldmouse_admin=True)


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_provider(name='SoilScouts', slug=None):
    return ThirdPartyAPIProvider.objects.create(
        name=name,
        slug=slug or slugify(name),
        base_url='https://api.soilscouts.example.com',
        auth_type='oauth2_password',
        auth_param_schema=[
            {'key': 'username', 'label': 'Username', 'type': 'text', 'required': True},
            {'key': 'password', 'label': 'Password', 'type': 'password', 'required': True},
            {'key': 'token_url', 'label': 'Token URL', 'type': 'text', 'required': True},
        ],
        discovery_endpoint={
            'path': '/api/v2/sites/',
            'method': 'GET',
            'device_id_jsonpath': '$.results[*].id',
            'device_name_jsonpath': '$.results[*].name',
        },
        detail_endpoint={
            'path_template': '/api/v2/devices/{device_id}/latest/',
            'method': 'GET',
        },
        available_streams=[
            {'key': 'soil_moisture', 'label': 'Soil Moisture', 'unit': '%',
             'data_type': 'numeric', 'jsonpath': '$.soil_moisture'},
            {'key': 'soil_temp', 'label': 'Soil Temperature', 'unit': '°C',
             'data_type': 'numeric', 'jsonpath': '$.soil_temperature'},
        ],
        default_poll_interval_seconds=300,
    )


# ---------------------------------------------------------------------------
# FM Admin — full CRUD
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestProviderListFMAdmin:

    def test_fm_admin_sees_all_fields(self):
        fm = make_fm_admin()
        make_provider()
        resp = auth_client(fm).get(PROVIDERS_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        # FM Admin sees internals
        assert 'auth_param_schema' in resp.data[0]
        assert 'discovery_endpoint' in resp.data[0]
        assert 'available_streams' in resp.data[0]
        assert 'jsonpath' in resp.data[0]['available_streams'][0]

    def test_unauthenticated_cannot_list(self):
        resp = APIClient().get(PROVIDERS_URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestProviderListTenantAdmin:

    def test_tenant_admin_sees_limited_fields(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        make_provider()
        resp = auth_client(user).get(PROVIDERS_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        p = resp.data[0]
        # Internals are hidden
        assert 'discovery_endpoint' not in p
        assert 'detail_endpoint' not in p
        assert 'base_url' not in p
        # JSONPath stripped from available_streams
        assert 'jsonpath' not in p['available_streams'][0]
        # But key/label/unit are present
        assert p['available_streams'][0]['key'] == 'soil_moisture'

    def test_tenant_viewer_can_list(self):
        tenant = make_tenant()
        user = make_tenant_user('viewer@acme.com', tenant, role=TenantUser.Role.VIEWER)
        make_provider()
        resp = auth_client(user).get(PROVIDERS_URL)
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestProviderCreate:

    def test_fm_admin_can_create(self):
        fm = make_fm_admin()
        payload = {
            'name': 'TestProvider',
            'slug': 'test-provider',
            'base_url': 'https://api.test.example.com',
            'auth_type': 'api_key_header',
            'auth_param_schema': [{'key': 'X-API-Key', 'label': 'API Key', 'type': 'password', 'required': True}],
            'discovery_endpoint': {'path': '/devices', 'method': 'GET', 'device_id_jsonpath': '$.*.id'},
            'detail_endpoint': {'path_template': '/devices/{device_id}', 'method': 'GET'},
            'available_streams': [],
            'default_poll_interval_seconds': 60,
        }
        resp = auth_client(fm).post(PROVIDERS_URL, payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert ThirdPartyAPIProvider.objects.filter(slug='test-provider').exists()

    def test_tenant_admin_cannot_create(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        payload = {
            'name': 'TestProvider',
            'slug': 'test-provider',
            'base_url': 'https://api.test.example.com',
            'auth_type': 'api_key_header',
        }
        resp = auth_client(user).post(PROVIDERS_URL, payload, format='json')
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_slug_rejected(self):
        fm = make_fm_admin()
        make_provider(slug='duplicate-slug')
        payload = {
            'name': 'Another',
            'slug': 'duplicate-slug',
            'base_url': 'https://other.example.com',
            'auth_type': 'bearer_token',
            'auth_param_schema': [],
            'discovery_endpoint': {},
            'detail_endpoint': {},
            'available_streams': [],
        }
        resp = auth_client(fm).post(PROVIDERS_URL, payload, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestProviderUpdate:

    def test_fm_admin_can_update(self):
        fm = make_fm_admin()
        p = make_provider()
        payload = {
            'name': 'Updated Name',
            'slug': p.slug,
            'base_url': p.base_url,
            'auth_type': p.auth_type,
            'auth_param_schema': p.auth_param_schema,
            'discovery_endpoint': p.discovery_endpoint,
            'detail_endpoint': p.detail_endpoint,
            'available_streams': p.available_streams,
            'default_poll_interval_seconds': 600,
        }
        resp = auth_client(fm).put(f'{PROVIDERS_URL}{p.pk}/', payload, format='json')
        assert resp.status_code == status.HTTP_200_OK
        p.refresh_from_db()
        assert p.name == 'Updated Name'
        assert p.default_poll_interval_seconds == 600

    def test_tenant_admin_cannot_update(self):
        tenant = make_tenant()
        user = make_tenant_user('ta@acme.com', tenant)
        p = make_provider()
        resp = auth_client(user).put(
            f'{PROVIDERS_URL}{p.pk}/',
            {'name': 'Hacked'},
            format='json',
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestProviderDelete:

    def test_fm_admin_can_delete(self):
        fm = make_fm_admin()
        p = make_provider()
        resp = auth_client(fm).delete(f'{PROVIDERS_URL}{p.pk}/')
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not ThirdPartyAPIProvider.objects.filter(pk=p.pk).exists()

    def test_cannot_delete_provider_with_active_datasource(self):
        from apps.integrations.models import DataSource
        fm = make_fm_admin()
        p = make_provider()
        tenant = make_tenant()
        DataSource.objects.create(
            tenant=tenant, provider=p, name='My DS', credentials={},
        )
        resp = auth_client(fm).delete(f'{PROVIDERS_URL}{p.pk}/')
        assert resp.status_code == status.HTTP_409_CONFLICT
