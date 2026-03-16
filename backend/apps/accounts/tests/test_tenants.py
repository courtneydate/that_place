"""Tests for Tenant management endpoints.

Covers Sprint 2 acceptance criteria:
- Fieldmouse Admin can create, list, retrieve, and update (deactivate) tenants
- Duplicate slug is handled (auto-incremented)
- Non-admin users cannot access tenant endpoints (403)
- Invite sends email (mocked)
- Deactivated tenant users cannot log in
"""
import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def fm_admin(db):
    return User.objects.create_user(
        email='admin@fieldmouse.io',
        password='AdminPass123!',
        is_fieldmouse_admin=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(email='user@tenant.com', password='UserPass123!')


@pytest.fixture
def fm_admin_client(client, fm_admin):
    client.force_authenticate(user=fm_admin)
    return client


@pytest.fixture
def regular_client(client, regular_user):
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Council', slug='acme-council', timezone='Australia/Sydney')


class TestTenantList:
    def test_fm_admin_can_list_tenants(self, fm_admin_client, tenant):
        response = fm_admin_client.get(reverse('accounts:tenant-list'))
        assert response.status_code == status.HTTP_200_OK

    def test_regular_user_cannot_list_tenants(self, regular_client):
        response = regular_client.get(reverse('accounts:tenant-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_cannot_list_tenants(self, client):
        response = client.get(reverse('accounts:tenant-list'))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestTenantCreate:
    def test_fm_admin_can_create_tenant(self, fm_admin_client):
        response = fm_admin_client.post(
            reverse('accounts:tenant-list'),
            {'name': 'Green City Council', 'timezone': 'Australia/Brisbane'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['slug'] == 'green-city-council'
        assert Tenant.objects.filter(slug='green-city-council').exists()

    def test_slug_auto_incremented_on_duplicate(self, fm_admin_client, tenant):
        # 'acme-council' already exists
        response = fm_admin_client.post(
            reverse('accounts:tenant-list'),
            {'name': 'Acme Council', 'timezone': 'Australia/Sydney'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['slug'] == 'acme-council-1'

    def test_regular_user_cannot_create_tenant(self, regular_client):
        response = regular_client.post(
            reverse('accounts:tenant-list'),
            {'name': 'Rogue Tenant', 'timezone': 'UTC'},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestTenantDetail:
    def test_fm_admin_can_retrieve_tenant(self, fm_admin_client, tenant):
        response = fm_admin_client.get(reverse('accounts:tenant-detail', args=[tenant.id]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == 'Acme Council'

    def test_fm_admin_can_deactivate_tenant(self, fm_admin_client, tenant):
        response = fm_admin_client.patch(
            reverse('accounts:tenant-detail', args=[tenant.id]),
            {'is_active': False},
        )
        assert response.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.is_active is False

    def test_delete_not_allowed(self, fm_admin_client, tenant):
        response = fm_admin_client.delete(reverse('accounts:tenant-detail', args=[tenant.id]))
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


class TestTenantInvite:
    def test_invite_sends_email(self, fm_admin_client, tenant):
        response = fm_admin_client.post(
            reverse('accounts:tenant-invite', args=[tenant.id]),
            {'email': 'newadmin@acme.com', 'role': 'admin'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['newadmin@acme.com']
        assert 'accept-invite' in mail.outbox[0].body

    def test_invite_invalid_email(self, fm_admin_client, tenant):
        response = fm_admin_client.post(
            reverse('accounts:tenant-invite', args=[tenant.id]),
            {'email': 'not-an-email', 'role': 'admin'},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data

    def test_non_admin_cannot_invite(self, regular_client, tenant):
        response = regular_client.post(
            reverse('accounts:tenant-invite', args=[tenant.id]),
            {'email': 'someone@example.com', 'role': 'admin'},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestDeactivatedTenantLogin:
    def test_deactivated_tenant_user_cannot_login(self, client, db):
        """A user whose tenant is deactivated cannot obtain tokens."""
        tenant = Tenant.objects.create(name='Dead Corp', slug='dead-corp', is_active=False)
        user = User.objects.create_user(email='blocked@dead.com', password='Pass123!')
        TenantUser.objects.create(user=user, tenant=tenant, role='admin')

        response = client.post(
            reverse('accounts:login'),
            {'email': 'blocked@dead.com', 'password': 'Pass123!'},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'error' in response.data

    def test_active_tenant_user_can_login(self, client, db):
        """A user whose tenant is active can log in normally."""
        tenant = Tenant.objects.create(name='Live Corp', slug='live-corp', is_active=True)
        user = User.objects.create_user(email='active@live.com', password='Pass123!')
        TenantUser.objects.create(user=user, tenant=tenant, role='admin')

        response = client.post(
            reverse('accounts:login'),
            {'email': 'active@live.com', 'password': 'Pass123!'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
