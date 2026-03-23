"""Sprint 14 tests — Rule data model & API.

Covers:
  - Happy-path CRUD via POST/GET/PUT/DELETE
  - RuleStreamIndex accuracy after create, update, and delete
  - RuleAuditLog created on every save with before/after snapshot
  - RuleAuditLog immutability (no PUT/DELETE allowed)
  - Tenant B cannot read or modify Tenant A's rules (cross-tenant isolation)
  - Only Tenant Admins can create/edit/delete rules (operators/viewers get 403)
  - Partial update (PATCH) toggles is_active without replacing nested objects

Ref: SPEC.md § Feature: Rules Engine
"""
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Tenant, TenantUser
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import RuleStreamIndex, Stream
from apps.rules.models import Rule, RuleAuditLog

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email: str, tenant: Tenant, role: str = TenantUser.Role.ADMIN) -> User:
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def auth(client, user) -> None:
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


def make_stream(tenant: Tenant, key: str = 'temperature',
                data_type: str = Stream.DataType.NUMERIC) -> Stream:
    """Create a minimal Stream hierarchy for testing."""
    dt, _ = DeviceType.objects.get_or_create(
        slug='test-type',
        defaults={'name': 'Test Type', 'connection_type': 'mqtt'},
    )
    site, _ = Site.objects.get_or_create(
        tenant=tenant,
        name='Test Site',
    )
    device, _ = Device.objects.get_or_create(
        serial_number=f'DEV-{tenant.id}-{key}',
        defaults={
            'tenant': tenant,
            'site': site,
            'device_type': dt,
            'name': 'Test Device',
            'status': Device.Status.ACTIVE,
        },
    )
    stream, _ = Stream.objects.get_or_create(
        device=device,
        key=key,
        defaults={'data_type': data_type},
    )
    return stream


def minimal_rule_payload(stream_id: int) -> dict:
    """Build the minimal valid POST payload for a rule with one condition + one action."""
    return {
        'name': 'High Temp Alert',
        'description': 'Fires when temperature exceeds 80.',
        'is_active': True,
        'condition_group_operator': 'AND',
        'condition_groups': [
            {
                'logical_operator': 'AND',
                'order': 0,
                'conditions': [
                    {
                        'condition_type': 'stream',
                        'stream': stream_id,
                        'operator': '>',
                        'threshold_value': '80',
                        'order': 0,
                    }
                ],
            }
        ],
        'actions': [
            {
                'action_type': 'notify',
                'notification_channels': ['in_app', 'email'],
                'group_ids': [],
                'user_ids': [],
                'message_template': '{{device_name}} temperature is {{value}}{{unit}}.',
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test: Happy-path CRUD
# ---------------------------------------------------------------------------

class TestRuleCRUD(APITestCase):
    """Happy-path rule creation, retrieval, update, and deletion."""

    def setUp(self):
        self.tenant = make_tenant('CRUD Tenant')
        self.admin = make_user('admin@crud.com', self.tenant)
        self.stream = make_stream(self.tenant)
        auth(self.client, self.admin)

    def test_create_rule_returns_201(self):
        payload = minimal_rule_payload(self.stream.id)
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'High Temp Alert')

    def test_create_rule_nested_objects_present(self):
        payload = minimal_rule_payload(self.stream.id)
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(len(resp.data['condition_groups']), 1)
        self.assertEqual(len(resp.data['condition_groups'][0]['conditions']), 1)
        self.assertEqual(len(resp.data['actions']), 1)

    def test_list_rules(self):
        self.client.post('/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json')
        resp = self.client.get('/api/v1/rules/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_retrieve_rule(self):
        create_resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = create_resp.data['id']
        resp = self.client.get(f'/api/v1/rules/{rule_id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['id'], rule_id)

    def test_update_rule(self):
        create_resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = create_resp.data['id']
        updated = minimal_rule_payload(self.stream.id)
        updated['name'] = 'Updated Name'
        resp = self.client.put(f'/api/v1/rules/{rule_id}/', updated, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Updated Name')

    def test_patch_is_active(self):
        create_resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = create_resp.data['id']
        resp = self.client.patch(
            f'/api/v1/rules/{rule_id}/', {'is_active': False}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['is_active'])

    def test_delete_rule_returns_204(self):
        create_resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = create_resp.data['id']
        resp = self.client.delete(f'/api/v1/rules/{rule_id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Rule.objects.filter(pk=rule_id).exists())

    def test_created_by_set_to_requesting_user(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        self.assertEqual(resp.data['created_by'], self.admin.id)


# ---------------------------------------------------------------------------
# Test: RuleStreamIndex accuracy
# ---------------------------------------------------------------------------

class TestRuleStreamIndex(APITestCase):
    """RuleStreamIndex is rebuilt correctly on create, update, and delete."""

    def setUp(self):
        self.tenant = make_tenant('Index Tenant')
        self.admin = make_user('admin@index.com', self.tenant)
        self.stream_a = make_stream(self.tenant, key='temperature')
        self.stream_b = make_stream(self.tenant, key='humidity')
        auth(self.client, self.admin)

    def test_index_entries_created_on_rule_create(self):
        payload = minimal_rule_payload(self.stream_a.id)
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        rule_id = resp.data['id']
        self.assertTrue(
            RuleStreamIndex.objects.filter(rule_id=rule_id, stream=self.stream_a).exists()
        )

    def test_index_updated_when_conditions_change(self):
        """After updating a rule to reference stream_b instead of stream_a, index reflects new streams."""
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream_a.id), format='json'
        )
        rule_id = resp.data['id']

        updated = minimal_rule_payload(self.stream_b.id)
        updated['name'] = 'Updated'
        self.client.put(f'/api/v1/rules/{rule_id}/', updated, format='json')

        self.assertFalse(
            RuleStreamIndex.objects.filter(rule_id=rule_id, stream=self.stream_a).exists()
        )
        self.assertTrue(
            RuleStreamIndex.objects.filter(rule_id=rule_id, stream=self.stream_b).exists()
        )

    def test_index_entries_removed_on_rule_delete(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream_a.id), format='json'
        )
        rule_id = resp.data['id']
        self.client.delete(f'/api/v1/rules/{rule_id}/')
        self.assertFalse(RuleStreamIndex.objects.filter(rule_id=rule_id).exists())

    def test_multiple_streams_indexed(self):
        """A rule with two conditions referencing different streams creates two index entries."""
        payload = {
            'name': 'Multi-stream rule',
            'condition_group_operator': 'AND',
            'condition_groups': [
                {
                    'logical_operator': 'AND',
                    'order': 0,
                    'conditions': [
                        {
                            'condition_type': 'stream',
                            'stream': self.stream_a.id,
                            'operator': '>',
                            'threshold_value': '30',
                            'order': 0,
                        },
                        {
                            'condition_type': 'stream',
                            'stream': self.stream_b.id,
                            'operator': '<',
                            'threshold_value': '90',
                            'order': 1,
                        },
                    ],
                }
            ],
            'actions': [
                {
                    'action_type': 'notify',
                    'notification_channels': ['in_app'],
                    'group_ids': [],
                    'user_ids': [],
                    'message_template': 'Alert!',
                }
            ],
        }
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        rule_id = resp.data['id']
        self.assertEqual(RuleStreamIndex.objects.filter(rule_id=rule_id).count(), 2)


# ---------------------------------------------------------------------------
# Test: RuleAuditLog
# ---------------------------------------------------------------------------

class TestRuleAuditLog(APITestCase):
    """Audit log entries created on create/update; immutable (no delete/update)."""

    def setUp(self):
        self.tenant = make_tenant('Audit Tenant')
        self.admin = make_user('admin@audit.com', self.tenant)
        self.stream = make_stream(self.tenant)
        auth(self.client, self.admin)

    def test_audit_log_created_on_rule_create(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        self.assertEqual(RuleAuditLog.objects.filter(rule_id=rule_id).count(), 1)

    def test_audit_log_on_create_has_null_before(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        log = RuleAuditLog.objects.get(rule_id=rule_id)
        self.assertIsNone(log.changed_fields['name']['before'])
        self.assertEqual(log.changed_fields['name']['after'], 'High Temp Alert')

    def test_audit_log_created_on_rule_update(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        updated = minimal_rule_payload(self.stream.id)
        updated['name'] = 'Updated Name'
        self.client.put(f'/api/v1/rules/{rule_id}/', updated, format='json')
        self.assertEqual(RuleAuditLog.objects.filter(rule_id=rule_id).count(), 2)

    def test_audit_log_update_records_before_after(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        updated = minimal_rule_payload(self.stream.id)
        updated['name'] = 'New Name'
        self.client.put(f'/api/v1/rules/{rule_id}/', updated, format='json')
        latest_log = RuleAuditLog.objects.filter(rule_id=rule_id).order_by('-changed_at').first()
        self.assertEqual(latest_log.changed_fields['name']['before'], 'High Temp Alert')
        self.assertEqual(latest_log.changed_fields['name']['after'], 'New Name')

    def test_audit_log_changed_by_is_requesting_user(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        log = RuleAuditLog.objects.get(rule_id=rule_id)
        self.assertEqual(log.changed_by, self.admin)

    def test_audit_log_returned_via_endpoint(self):
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        audit_resp = self.client.get(f'/api/v1/rules/{rule_id}/audit-logs/')
        self.assertEqual(audit_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(audit_resp.data), 1)

    def test_audit_log_immutable_no_delete_endpoint(self):
        """There is no DELETE endpoint for audit logs — 405 or 404."""
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        log = RuleAuditLog.objects.get(rule_id=rule_id)
        # No audit-log detail URL exists — returns 404
        delete_resp = self.client.delete(f'/api/v1/rules/{rule_id}/audit-logs/{log.id}/')
        self.assertIn(delete_resp.status_code, [404, 405])

    def test_audit_log_not_deleted_when_rule_is_updated(self):
        """Updating a rule appends a new log entry — it does not replace the previous one."""
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        rule_id = resp.data['id']
        for i in range(3):
            updated = minimal_rule_payload(self.stream.id)
            updated['name'] = f'Update {i}'
            self.client.put(f'/api/v1/rules/{rule_id}/', updated, format='json')
        # 1 create + 3 updates = 4 log entries
        self.assertEqual(RuleAuditLog.objects.filter(rule_id=rule_id).count(), 4)


# ---------------------------------------------------------------------------
# Test: Tenant isolation
# ---------------------------------------------------------------------------

class TestRuleTenantIsolation(APITestCase):
    """Tenant B cannot read or modify Tenant A's rules."""

    def setUp(self):
        self.tenant_a = make_tenant('Tenant A')
        self.tenant_b = make_tenant('Tenant B')
        self.admin_a = make_user('a@a.com', self.tenant_a)
        self.admin_b = make_user('b@b.com', self.tenant_b)
        self.stream_a = make_stream(self.tenant_a)
        auth(self.client, self.admin_a)
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream_a.id), format='json'
        )
        self.rule_a_id = resp.data['id']

    def test_tenant_b_cannot_list_tenant_a_rules(self):
        auth(self.client, self.admin_b)
        resp = self.client.get('/api/v1/rules/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

    def test_tenant_b_gets_404_on_tenant_a_rule(self):
        auth(self.client, self.admin_b)
        resp = self.client.get(f'/api/v1/rules/{self.rule_a_id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_b_cannot_update_tenant_a_rule(self):
        auth(self.client, self.admin_b)
        stream_b = make_stream(self.tenant_b)
        payload = minimal_rule_payload(stream_b.id)
        resp = self.client.put(
            f'/api/v1/rules/{self.rule_a_id}/', payload, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_b_cannot_delete_tenant_a_rule(self):
        auth(self.client, self.admin_b)
        resp = self.client.delete(f'/api/v1/rules/{self.rule_a_id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Rule.objects.filter(pk=self.rule_a_id).exists())

    def test_cross_tenant_stream_rejected(self):
        """Creating a rule that references Tenant B's stream from Tenant A returns 400."""
        stream_b = make_stream(self.tenant_b, key='temp_b')
        auth(self.client, self.admin_a)
        payload = minimal_rule_payload(stream_b.id)
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Test: Permission enforcement
# ---------------------------------------------------------------------------

class TestRulePermissions(APITestCase):
    """Operators and view-only users cannot create/edit/delete rules."""

    def setUp(self):
        self.tenant = make_tenant('Perm Tenant')
        self.admin = make_user('admin@perm.com', self.tenant)
        self.operator = make_user('op@perm.com', self.tenant, role=TenantUser.Role.OPERATOR)
        self.viewer = make_user('view@perm.com', self.tenant, role=TenantUser.Role.VIEWER)
        self.stream = make_stream(self.tenant)
        # Create a rule as admin for update/delete tests
        auth(self.client, self.admin)
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        self.rule_id = resp.data['id']

    def test_unauthenticated_gets_401(self):
        self.client.credentials()
        resp = self.client.get('/api/v1/rules/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_operator_cannot_create_rule(self):
        auth(self.client, self.operator)
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_cannot_delete_rule(self):
        auth(self.client, self.operator)
        resp = self.client.delete(f'/api/v1/rules/{self.rule_id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_rule(self):
        auth(self.client, self.viewer)
        resp = self.client.post(
            '/api/v1/rules/', minimal_rule_payload(self.stream.id), format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_list_rules(self):
        auth(self.client, self.viewer)
        resp = self.client.get('/api/v1/rules/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Test: Validation
# ---------------------------------------------------------------------------

class TestRuleValidation(APITestCase):
    """Input validation for conditions and actions."""

    def setUp(self):
        self.tenant = make_tenant('Validation Tenant')
        self.admin = make_user('admin@val.com', self.tenant)
        self.stream = make_stream(self.tenant, data_type=Stream.DataType.NUMERIC)
        self.bool_stream = make_stream(self.tenant, key='door_open', data_type=Stream.DataType.BOOLEAN)
        auth(self.client, self.admin)

    def test_invalid_operator_for_numeric_stream_rejected(self):
        payload = minimal_rule_payload(self.stream.id)
        payload['condition_groups'][0]['conditions'][0]['operator'] = 'LIKE'
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_operator_for_boolean_stream_rejected(self):
        payload = minimal_rule_payload(self.bool_stream.id)
        payload['condition_groups'][0]['conditions'][0]['operator'] = '>'
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_notification_channel_rejected(self):
        payload = minimal_rule_payload(self.stream.id)
        payload['actions'][0]['notification_channels'] = ['telegram']
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staleness_condition_requires_staleness_minutes(self):
        payload = minimal_rule_payload(self.stream.id)
        payload['condition_groups'][0]['conditions'][0]['condition_type'] = 'staleness'
        payload['condition_groups'][0]['conditions'][0].pop('operator', None)
        payload['condition_groups'][0]['conditions'][0].pop('threshold_value', None)
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_command_action_requires_target_device(self):
        payload = minimal_rule_payload(self.stream.id)
        payload['actions'] = [
            {
                'action_type': 'command',
                'notification_channels': [],
                'group_ids': [],
                'user_ids': [],
                'message_template': '',
                'command': {'name': 'reboot', 'params': {}},
            }
        ]
        resp = self.client.post('/api/v1/rules/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
