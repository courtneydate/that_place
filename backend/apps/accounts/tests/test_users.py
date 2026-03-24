"""Tests for Sprint 3: invite accept flow, user management, role permissions.

Covers:
- AcceptInviteView: valid token creates user, expired/bad/used tokens rejected
- UserViewSet.list: all tenant users can list, cross-tenant blocked
- UserViewSet.invite: tenant admin can invite, operator/viewer cannot
- UserViewSet.update: role change rules enforced
- UserViewSet.destroy: removal rules enforced, removed user loses access
"""
from unittest.mock import patch

import pytest
from django.core import mail, signing
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tenant(name='Acme Corp'):
    """Create and return a Tenant."""
    from django.utils.text import slugify
    slug = slugify(name)
    return Tenant.objects.create(name=name, slug=slug)


def make_user(email, password='testpass123', **kwargs):
    """Create and return a User."""
    return User.objects.create_user(email=email, password=password, **kwargs)


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    """Create a User + TenantUser and return both."""
    user = make_user(email, password)
    tu = TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user, tu


def auth_client(user, password='testpass123'):
    """Return an authenticated APIClient for the given user."""
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


def make_invite_token(email, tenant_id, role='admin'):
    """Generate a valid signed invite token."""
    return signing.dumps(
        {'email': email, 'tenant_id': tenant_id, 'role': role},
        salt='that-place-invite',
    )


# ---------------------------------------------------------------------------
# TestAcceptInvite
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAcceptInvite:
    URL = '/api/v1/auth/accept-invite/'

    def test_valid_token_creates_user_and_returns_tokens(self):
        tenant = make_tenant()
        token = make_invite_token('new@example.com', tenant.id, 'admin')
        client = APIClient()
        resp = client.post(self.URL, {
            'token': token,
            'first_name': 'Alice',
            'last_name': 'Smith',
            'password': 'securepass1',
        })
        assert resp.status_code == status.HTTP_201_CREATED
        assert 'access' in resp.data
        assert 'refresh' in resp.data
        user = User.objects.get(email='new@example.com')
        assert user.first_name == 'Alice'
        assert TenantUser.objects.filter(user=user, tenant=tenant, role='admin').exists()

    def test_expired_token_rejected(self):
        tenant = make_tenant()
        # Sign with a timestamp in the past beyond max_age
        with patch('django.core.signing.time') as mock_time:
            mock_time.return_value = 0
            token = signing.dumps(
                {'email': 'old@example.com', 'tenant_id': tenant.id, 'role': 'admin'},
                salt='that-place-invite',
            )
        client = APIClient()
        resp = client.post(self.URL, {
            'token': token,
            'first_name': 'Bob',
            'last_name': 'Jones',
            'password': 'securepass1',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_bad_signature_rejected(self):
        client = APIClient()
        resp = client.post(self.URL, {
            'token': 'not.a.valid.token',
            'first_name': 'Eve',
            'last_name': 'Hacker',
            'password': 'securepass1',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_already_used_token_rejected(self):
        tenant = make_tenant()
        make_user('taken@example.com')
        token = make_invite_token('taken@example.com', tenant.id, 'admin')
        client = APIClient()
        resp = client.post(self.URL, {
            'token': token,
            'first_name': 'Re',
            'last_name': 'Use',
            'password': 'securepass1',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_deactivated_tenant_token_rejected(self):
        tenant = make_tenant()
        tenant.is_active = False
        tenant.save()
        token = make_invite_token('new@example.com', tenant.id, 'admin')
        client = APIClient()
        resp = client.post(self.URL, {
            'token': token,
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'securepass1',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_reinvite_deactivated_user_succeeds(self):
        """A previously removed (is_active=False) user can accept a new invite."""
        tenant = make_tenant(name='Reactivate Corp')
        # Simulate a user who was previously removed from the tenant
        existing = make_user('returnee@example.com', is_active=False)
        token = make_invite_token('returnee@example.com', tenant.id, 'operator')
        client = APIClient()
        resp = client.post(self.URL, {
            'token': token,
            'first_name': 'Re',
            'last_name': 'Turned',
            'password': 'newpassword99',
        })
        assert resp.status_code == status.HTTP_201_CREATED
        existing.refresh_from_db()
        assert existing.is_active is True
        assert TenantUser.objects.filter(user=existing, tenant=tenant, role='operator').exists()

    def test_short_password_rejected(self):
        tenant = make_tenant()
        token = make_invite_token('pw@example.com', tenant.id, 'admin')
        client = APIClient()
        resp = client.post(self.URL, {
            'token': token,
            'first_name': 'Weak',
            'last_name': 'Pass',
            'password': 'short',
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# TestUserList
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserList:
    URL = '/api/v1/users/'

    def test_tenant_admin_can_list_users(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant, TenantUser.Role.ADMIN)
        make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(admin).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_operator_can_list_users(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant, TenantUser.Role.ADMIN)
        op, _ = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_viewer_can_list_users(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant, TenantUser.Role.ADMIN)
        viewer, _ = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(viewer).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_unauthenticated_cannot_list(self):
        resp = APIClient().get(self.URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_that_place_admin_cannot_list(self):
        fm_admin = make_user('fm@that-place.io', is_that_place_admin=True)
        resp = auth_client(fm_admin).get(self.URL)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_users_not_visible(self):
        tenant_a = make_tenant('Tenant A')
        tenant_b = make_tenant('Tenant B')
        admin_a, _ = make_tenant_user('admin@a.com', tenant_a)
        make_tenant_user('user@b.com', tenant_b)
        resp = auth_client(admin_a).get(self.URL)
        emails = [u['email'] for u in resp.data]
        assert 'user@b.com' not in emails
        assert 'admin@a.com' in emails


# ---------------------------------------------------------------------------
# TestUserInvite
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserInvite:
    URL = '/api/v1/users/invite/'

    def test_tenant_admin_can_invite(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(self.URL, {'email': 'new@t.com', 'role': 'operator'})
        assert resp.status_code == status.HTTP_200_OK
        assert len(mail.outbox) == 1
        assert 'new@t.com' in mail.outbox[0].to

    def test_operator_cannot_invite(self):
        tenant = make_tenant()
        op, _ = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).post(self.URL, {'email': 'new@t.com', 'role': 'viewer'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_cannot_invite(self):
        tenant = make_tenant()
        viewer, _ = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(viewer).post(self.URL, {'email': 'new@t.com', 'role': 'viewer'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_email_rejected(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(self.URL, {'email': 'not-an-email', 'role': 'admin'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# TestUserRoleUpdate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserRoleUpdate:

    def url(self, tenant_user_id):
        return f'/api/v1/users/{tenant_user_id}/'

    def test_admin_can_change_role(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        target, target_tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(admin).put(self.url(target_tu.pk), {'role': 'viewer'})
        assert resp.status_code == status.HTTP_200_OK
        target_tu.refresh_from_db()
        assert target_tu.role == TenantUser.Role.VIEWER

    def test_operator_cannot_change_role(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op, op_tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        target, target_tu = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(op).put(self.url(target_tu.pk), {'role': 'operator'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_change_own_role(self):
        tenant = make_tenant()
        admin, admin_tu = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).put(self.url(admin_tu.pk), {'role': 'operator'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_demote_last_admin(self):
        tenant = make_tenant()
        admin, admin_tu = make_tenant_user('admin@t.com', tenant)
        target, target_tu = make_tenant_user('admin2@t.com', tenant, TenantUser.Role.ADMIN)
        # Demote target_tu — allowed since admin is still admin
        resp = auth_client(admin).put(self.url(target_tu.pk), {'role': 'operator'})
        assert resp.status_code == status.HTTP_200_OK
        # Now try to demote the last admin (admin_tu) via target (now operator) — 403 first
        # Re-promote target to admin, then demote admin_tu
        target_tu.role = TenantUser.Role.ADMIN
        target_tu.save()
        # Try to demote admin_tu — only 1 admin left now (admin)
        # Make admin_tu the last admin by demoting target first
        target_tu.role = TenantUser.Role.OPERATOR
        target_tu.save()
        resp2 = auth_client(admin).put(self.url(admin_tu.pk), {'role': 'operator'})
        assert resp2.status_code == status.HTTP_400_BAD_REQUEST

    def test_cross_tenant_update_not_allowed(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a, _ = make_tenant_user('admin@a.com', tenant_a)
        _, tu_b = make_tenant_user('user@b.com', tenant_b, TenantUser.Role.OPERATOR)
        resp = auth_client(admin_a).put(self.url(tu_b.pk), {'role': 'viewer'})
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# TestUserRemove
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserRemove:

    def url(self, tenant_user_id):
        return f'/api/v1/users/{tenant_user_id}/'

    def test_admin_can_remove_user(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        target, target_tu = make_tenant_user('target@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(admin).delete(self.url(target_tu.pk))
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        target.refresh_from_db()
        assert not target.is_active
        assert not TenantUser.objects.filter(pk=target_tu.pk).exists()

    def test_operator_cannot_remove_user(self):
        tenant = make_tenant()
        make_tenant_user('admin@t.com', tenant)
        op, _ = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        target, target_tu = make_tenant_user('target@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(op).delete(self.url(target_tu.pk))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_remove_self(self):
        tenant = make_tenant()
        admin, admin_tu = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).delete(self.url(admin_tu.pk))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_removed_user_cannot_login(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        target, target_tu = make_tenant_user('target@t.com', tenant, TenantUser.Role.OPERATOR)
        auth_client(admin).delete(self.url(target_tu.pk))
        login_resp = APIClient().post('/api/v1/auth/login/', {
            'email': 'target@t.com',
            'password': 'testpass123',
        })
        assert login_resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_remove_not_allowed(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a, _ = make_tenant_user('admin@a.com', tenant_a)
        _, tu_b = make_tenant_user('user@b.com', tenant_b)
        resp = auth_client(admin_a).delete(self.url(tu_b.pk))
        assert resp.status_code == status.HTTP_404_NOT_FOUND
