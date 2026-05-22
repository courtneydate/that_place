"""Sprint 23b tests — That Place Admin hardening (accounts).

Covers:
  - GET /api/v1/tenants/:id/users/ — That Place Admin sees a tenant's members
    and pending invites; tenant users and anonymous requests are rejected
  - Duplicate-email invite guard — both invite endpoints reject an email that
    already belongs to (or is invited to) another tenant, or is already a
    member of the same tenant
  - Accept-invite guard — acceptance is blocked when the email already
    belongs to a tenant

Ref: SPEC.md §9; ROADMAP Sprint 23b
"""
import pytest
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantInvite, TenantUser, User


def make_tenant(name):
    """Create a tenant with a slugified name."""
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email, tenant, role='admin'):
    """Create a User with a TenantUser membership in the given tenant."""
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_platform_admin(email='pa@example.com'):
    """Create a That Place platform admin (no tenant)."""
    return User.objects.create_user(
        email=email, password='testpass123', is_that_place_admin=True,
    )


def auth(user):
    """Return an APIClient authenticated as the given user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Per-tenant users endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTenantUsersEndpoint:
    """GET /api/v1/tenants/:id/users/ is a read-only That Place Admin view."""

    def test_platform_admin_sees_members_and_pending_invites(self):
        """The endpoint returns the tenant's members and outstanding invites."""
        tenant = make_tenant('UsersViewT')
        make_user('m1@example.com', tenant, role='admin')
        make_user('m2@example.com', tenant, role='operator')
        TenantInvite.generate(tenant, 'invitee@example.com', 'viewer', None)

        resp = auth(make_platform_admin()).get(f'/api/v1/tenants/{tenant.pk}/users/')

        assert resp.status_code == 200
        assert len(resp.data['members']) == 2
        assert len(resp.data['pending_invites']) == 1
        assert resp.data['pending_invites'][0]['email'] == 'invitee@example.com'

    def test_tenant_admin_is_forbidden(self):
        """A tenant admin cannot access the platform-level tenant-users view."""
        tenant = make_tenant('UsersViewForbidT')
        admin = make_user('ta@example.com', tenant, role='admin')
        resp = auth(admin).get(f'/api/v1/tenants/{tenant.pk}/users/')
        assert resp.status_code == 403

    def test_unauthenticated_is_rejected(self):
        """An unauthenticated request is rejected."""
        tenant = make_tenant('UsersViewAnonT')
        resp = APIClient().get(f'/api/v1/tenants/{tenant.pk}/users/')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Duplicate-email invite guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDuplicateEmailInviteGuard:
    """Invite endpoints reject an email already tied to a tenant."""

    def test_tenant_admin_cannot_invite_email_from_another_tenant(self):
        """A Tenant Admin cannot invite an email that belongs to another tenant."""
        tenant_a = make_tenant('DupInviteAT')
        tenant_b = make_tenant('DupInviteBT')
        make_user('shared@example.com', tenant_b, role='operator')
        admin_a = make_user('admin-a@example.com', tenant_a, role='admin')

        resp = auth(admin_a).post('/api/v1/users/invite/', {
            'email': 'shared@example.com', 'role': 'viewer',
        })
        assert resp.status_code == 400

    def test_platform_admin_cannot_invite_email_from_another_tenant(self):
        """The tenant-invite endpoint also rejects a cross-tenant duplicate."""
        tenant_a = make_tenant('DupTenantInviteAT')
        tenant_b = make_tenant('DupTenantInviteBT')
        make_user('member@example.com', tenant_a, role='admin')

        resp = auth(make_platform_admin()).post(
            f'/api/v1/tenants/{tenant_b.pk}/invite/',
            {'email': 'member@example.com', 'role': 'admin'},
        )
        assert resp.status_code == 400

    def test_cannot_invite_existing_member_of_same_tenant(self):
        """Inviting an email that is already a member of the tenant is rejected."""
        tenant = make_tenant('DupSameTenantT')
        admin = make_user('admin@example.com', tenant, role='admin')
        make_user('existing@example.com', tenant, role='operator')

        resp = auth(admin).post('/api/v1/users/invite/', {
            'email': 'existing@example.com', 'role': 'viewer',
        })
        assert resp.status_code == 400

    def test_cannot_invite_email_with_pending_invite_elsewhere(self):
        """An email holding an unexpired invite to another tenant is rejected."""
        tenant_a = make_tenant('PendingInviteAT')
        tenant_b = make_tenant('PendingInviteBT')
        TenantInvite.generate(tenant_a, 'pending@example.com', 'viewer', None)
        admin_b = make_user('admin-b@example.com', tenant_b, role='admin')

        resp = auth(admin_b).post('/api/v1/users/invite/', {
            'email': 'pending@example.com', 'role': 'viewer',
        })
        assert resp.status_code == 400

    def test_fresh_email_invite_succeeds(self):
        """A brand-new email can still be invited."""
        tenant = make_tenant('FreshInviteT')
        admin = make_user('admin@example.com', tenant, role='admin')
        resp = auth(admin).post('/api/v1/users/invite/', {
            'email': 'brand-new@example.com', 'role': 'viewer',
        })
        assert resp.status_code == 200
        assert TenantInvite.objects.filter(email='brand-new@example.com').exists()


# ---------------------------------------------------------------------------
# Accept-invite guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAcceptInviteGuard:
    """Acceptance is blocked when the email already belongs to a tenant."""

    def test_acceptance_blocked_when_email_belongs_to_a_tenant(self):
        """An invite cannot be accepted by an email already tied to a tenant."""
        tenant_a = make_tenant('AcceptGuardAT')
        tenant_b = make_tenant('AcceptGuardBT')
        make_user('taken@example.com', tenant_a, role='operator')
        _, raw_token = TenantInvite.generate(
            tenant_b, 'taken@example.com', 'viewer', None,
        )

        resp = APIClient().post('/api/v1/auth/accept-invite/', {
            'token': raw_token,
            'first_name': 'Taken',
            'last_name': 'User',
            'password': 'newpass12345',
        })
        assert resp.status_code == 400

    def test_fresh_acceptance_succeeds(self):
        """A fresh email can still accept an invite."""
        tenant = make_tenant('AcceptFreshT')
        _, raw_token = TenantInvite.generate(
            tenant, 'fresh-accept@example.com', 'admin', None,
        )

        resp = APIClient().post('/api/v1/auth/accept-invite/', {
            'token': raw_token,
            'first_name': 'Fresh',
            'last_name': 'User',
            'password': 'newpass12345',
        })
        assert resp.status_code in (200, 201)
        assert TenantUser.objects.filter(
            user__email='fresh-accept@example.com',
        ).exists()
