"""Tests for Sprint 4: Notification groups and system group auto-maintenance."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import (
    SYSTEM_GROUP_ALL_ADMINS,
    SYSTEM_GROUP_ALL_OPERATORS,
    SYSTEM_GROUP_ALL_USERS,
    NotificationGroup,
    NotificationGroupMember,
    Tenant,
    TenantUser,
    User,
)


def make_tenant(name='Acme'):
    from django.utils.text import slugify
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_tenant_user(email, tenant, role=TenantUser.Role.ADMIN, password='testpass123'):
    user = User.objects.create_user(email=email, password=password)
    tu = TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user, tu


def auth_client(user, password='testpass123'):
    client = APIClient()
    resp = client.post('/api/v1/auth/login/', {'email': user.email, 'password': password})
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
    return client


# ---------------------------------------------------------------------------
# TestSystemGroupCreation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSystemGroupCreation:

    def test_system_groups_created_with_tenant(self):
        tenant = make_tenant()
        names = list(NotificationGroup.objects.filter(tenant=tenant, is_system=True).values_list('name', flat=True))
        assert SYSTEM_GROUP_ALL_USERS in names
        assert SYSTEM_GROUP_ALL_ADMINS in names
        assert SYSTEM_GROUP_ALL_OPERATORS in names

    def test_new_admin_added_to_all_users_and_all_admins(self):
        tenant = make_tenant()
        _, tu = make_tenant_user('admin@t.com', tenant, TenantUser.Role.ADMIN)
        assert NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_USERS, tenant_user=tu
        ).exists()
        assert NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_ADMINS, tenant_user=tu
        ).exists()
        assert not NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_OPERATORS, tenant_user=tu
        ).exists()

    def test_new_operator_added_to_all_users_and_all_operators(self):
        tenant = make_tenant()
        _, tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        assert NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_USERS, tenant_user=tu
        ).exists()
        assert NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_OPERATORS, tenant_user=tu
        ).exists()
        assert not NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_ADMINS, tenant_user=tu
        ).exists()

    def test_new_viewer_added_to_all_users_only(self):
        tenant = make_tenant()
        _, tu = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        assert NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_USERS, tenant_user=tu
        ).exists()
        assert not NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_ADMINS, tenant_user=tu
        ).exists()
        assert not NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_OPERATORS, tenant_user=tu
        ).exists()

    def test_role_change_updates_system_groups(self):
        tenant = make_tenant()
        _, tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        # Promote to admin
        tu.role = TenantUser.Role.ADMIN
        tu.save()
        assert NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_ADMINS, tenant_user=tu
        ).exists()
        assert not NotificationGroupMember.objects.filter(
            group__name=SYSTEM_GROUP_ALL_OPERATORS, tenant_user=tu
        ).exists()

    def test_deleted_tenant_user_removed_from_groups(self):
        tenant = make_tenant()
        _, tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        tu_id = tu.id
        tu.delete()
        assert not NotificationGroupMember.objects.filter(tenant_user_id=tu_id).exists()

    def test_system_groups_isolated_between_tenants(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        assert NotificationGroup.objects.filter(tenant=tenant_a).count() == 3
        assert NotificationGroup.objects.filter(tenant=tenant_b).count() == 3


# ---------------------------------------------------------------------------
# TestGroupList
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupList:
    URL = '/api/v1/groups/'

    def test_tenant_user_can_list_groups(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 3  # three system groups

    def test_unauthenticated_cannot_list(self):
        resp = APIClient().get(self.URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_groups_not_visible(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a, _ = make_tenant_user('admin@a.com', tenant_a)
        NotificationGroup.objects.create(tenant=tenant_b, name='B Team')
        resp = auth_client(admin_a).get(self.URL)
        names = [g['name'] for g in resp.data]
        assert 'B Team' not in names


# ---------------------------------------------------------------------------
# TestGroupCreate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupCreate:
    URL = '/api/v1/groups/'

    def test_admin_can_create_group(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(self.URL, {'name': 'On-Call Team'})
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['name'] == 'On-Call Team'
        assert resp.data['is_system'] is False

    def test_operator_cannot_create_group(self):
        tenant = make_tenant()
        op, _ = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).post(self.URL, {'name': 'Team'})
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# TestGroupUpdate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupUpdate:

    def test_admin_can_rename_custom_group(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        group = NotificationGroup.objects.create(tenant=tenant, name='Old Name')
        resp = auth_client(admin).put(f'/api/v1/groups/{group.pk}/', {'name': 'New Name'})
        assert resp.status_code == status.HTTP_200_OK
        group.refresh_from_db()
        assert group.name == 'New Name'

    def test_system_group_cannot_be_renamed(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        system_group = NotificationGroup.objects.get(tenant=tenant, name=SYSTEM_GROUP_ALL_USERS)
        resp = auth_client(admin).put(f'/api/v1/groups/{system_group.pk}/', {'name': 'Renamed'})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# TestGroupDelete
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupDelete:

    def test_admin_can_delete_custom_group(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        group = NotificationGroup.objects.create(tenant=tenant, name='Temp')
        resp = auth_client(admin).delete(f'/api/v1/groups/{group.pk}/')
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not NotificationGroup.objects.filter(pk=group.pk).exists()

    def test_system_group_cannot_be_deleted(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        system_group = NotificationGroup.objects.get(tenant=tenant, name=SYSTEM_GROUP_ALL_USERS)
        resp = auth_client(admin).delete(f'/api/v1/groups/{system_group.pk}/')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# TestGroupMembers
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupMembers:

    def test_admin_can_add_member_to_custom_group(self):
        tenant = make_tenant()
        admin, admin_tu = make_tenant_user('admin@t.com', tenant)
        _, op_tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        group = NotificationGroup.objects.create(tenant=tenant, name='Team')
        resp = auth_client(admin).post(
            f'/api/v1/groups/{group.pk}/members/', {'tenant_user_id': op_tu.pk}
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert NotificationGroupMember.objects.filter(group=group, tenant_user=op_tu).exists()

    def test_cannot_add_member_twice(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        _, op_tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        group = NotificationGroup.objects.create(tenant=tenant, name='Team')
        NotificationGroupMember.objects.create(group=group, tenant_user=op_tu)
        resp = auth_client(admin).post(
            f'/api/v1/groups/{group.pk}/members/', {'tenant_user_id': op_tu.pk}
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_manually_add_to_system_group(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        _, op_tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        system_group = NotificationGroup.objects.get(tenant=tenant, name=SYSTEM_GROUP_ALL_USERS)
        resp = auth_client(admin).post(
            f'/api/v1/groups/{system_group.pk}/members/', {'tenant_user_id': op_tu.pk}
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_admin_can_remove_member_from_custom_group(self):
        tenant = make_tenant()
        admin, _ = make_tenant_user('admin@t.com', tenant)
        _, op_tu = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        group = NotificationGroup.objects.create(tenant=tenant, name='Team')
        NotificationGroupMember.objects.create(group=group, tenant_user=op_tu)
        resp = auth_client(admin).delete(f'/api/v1/groups/{group.pk}/members/{op_tu.pk}/')
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not NotificationGroupMember.objects.filter(group=group, tenant_user=op_tu).exists()

    def test_cannot_manually_remove_from_system_group(self):
        tenant = make_tenant()
        admin, admin_tu = make_tenant_user('admin@t.com', tenant)
        system_group = NotificationGroup.objects.get(tenant=tenant, name=SYSTEM_GROUP_ALL_USERS)
        resp = auth_client(admin).delete(
            f'/api/v1/groups/{system_group.pk}/members/{admin_tu.pk}/'
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cross_tenant_member_cannot_be_added(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a, _ = make_tenant_user('admin@a.com', tenant_a)
        _, tu_b = make_tenant_user('user@b.com', tenant_b)
        group = NotificationGroup.objects.create(tenant=tenant_a, name='Team A')
        resp = auth_client(admin_a).post(
            f'/api/v1/groups/{group.pk}/members/', {'tenant_user_id': tu_b.pk}
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
