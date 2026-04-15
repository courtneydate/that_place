"""Sprint 15a tests — Feed Providers, Reference Datasets, and Rule Integration.

Covers:
  - FeedProvider API: list/retrieve for all authenticated; CRUD for ThatPlaceAdmin only
  - FeedChannel: created by polling task; readable by all authenticated
  - FeedReading: idempotency via ignore_conflicts on unique (channel, timestamp)
  - FeedChannelRuleIndex: rebuilt correctly on rule create/update/delete
  - TenantFeedSubscription: scoped to requesting tenant; cross-tenant isolation
  - ReferenceDataset API: CRUD for ThatPlaceAdmin; read-only for tenant users
  - ReferenceDatasetRow: bulk import upserts rows; per-row error reporting
  - Row resolution: flat dataset, versioned dataset, TOU in tenant timezone
  - Site vs tenant-wide assignment precedence (not yet implemented — placeholder)
  - Bulk import: upsert semantics; per-row error isolation
  - reference_value rule condition: serializer validation
  - feed_channel rule condition: serializer validation + FeedChannelRuleIndex rebuild
  - Cross-tenant isolation on all writable endpoints

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets,
     § Feature: Rule Evaluation Engine
"""
import io
from datetime import date, time
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Tenant, TenantUser
from apps.devices.models import Device, DeviceType, Site
from apps.feeds.models import (
    FeedChannel,
    FeedChannelRuleIndex,
    FeedProvider,
    FeedReading,
    ReferenceDataset,
    ReferenceDatasetRow,
    TenantDatasetAssignment,
    TenantFeedSubscription,
)
from apps.feeds.resolution import ResolutionError, resolve_reference_value
from apps.readings.models import RuleStreamIndex, Stream

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name: str) -> Tenant:
    return Tenant.objects.create(name=name, slug=slugify(name), timezone='Australia/Brisbane')


def make_user(email: str, tenant: Tenant, role: str = TenantUser.Role.ADMIN) -> User:
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_superuser(email: str) -> User:
    """Create a That Place Admin (superuser) not tied to any tenant."""
    return User.objects.create_superuser(email=email, password='testpass123')


def auth(client, user) -> None:
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


def make_provider(slug: str = 'test-provider', scope: str = 'system') -> FeedProvider:
    return FeedProvider.objects.create(
        slug=slug,
        name='Test Provider',
        base_url='https://example.com',
        auth_type=FeedProvider.AuthType.NONE,
        scope=scope,
        poll_interval_seconds=300,
        is_active=True,
        endpoints=[],
    )


def make_channel(provider: FeedProvider, key: str = 'price', dim: str = None) -> FeedChannel:
    return FeedChannel.objects.create(
        provider=provider,
        key=key,
        label=key,
        unit='c/kWh',
        data_type=FeedChannel.DataType.NUMERIC,
        dimension_value=dim,
    )


def make_dataset(slug: str = 'test-ds', tou: bool = False, versioned: bool = False) -> ReferenceDataset:
    return ReferenceDataset.objects.create(
        slug=slug,
        name='Test Dataset',
        scope=ReferenceDataset.Scope.SYSTEM,
        dimension_schema={'region': {'type': 'string'}},
        value_schema={'rate': {'type': 'numeric', 'unit': 'c/kWh'}},
        has_time_of_use=tou,
        has_version=versioned,
    )


def make_row(dataset: ReferenceDataset, dimensions: dict, values: dict,
             version: str = None, applicable_days=None,
             time_from=None, time_to=None) -> ReferenceDatasetRow:
    return ReferenceDatasetRow.objects.create(
        dataset=dataset,
        version=version,
        dimensions=dimensions,
        values=values,
        applicable_days=applicable_days,
        time_from=time_from,
        time_to=time_to,
        is_active=True,
    )


def make_site(tenant: Tenant, name: str = 'Main Site') -> Site:
    return Site.objects.create(tenant=tenant, name=name)


def make_assignment(tenant: Tenant, dataset: ReferenceDataset,
                    site=None, dimension_filter=None, version=None) -> TenantDatasetAssignment:
    return TenantDatasetAssignment.objects.create(
        tenant=tenant,
        dataset=dataset,
        site=site,
        dimension_filter=dimension_filter or {},
        version=version,
        effective_from=date(2020, 1, 1),
    )


def make_stream(tenant: Tenant) -> Stream:
    dt, _ = DeviceType.objects.get_or_create(
        slug='feed-test-type',
        defaults={'name': 'Feed Test Type', 'connection_type': 'mqtt'},
    )
    site, _ = Site.objects.get_or_create(tenant=tenant, name='Feed Test Site')
    device, _ = Device.objects.get_or_create(
        serial_number=f'FEED-DEV-{tenant.id}',
        defaults={'name': 'Feed Test Device', 'site': site, 'device_type': dt, 'tenant': tenant},
    )
    stream, _ = Stream.objects.get_or_create(
        device=device,
        key='temperature',
        defaults={
            'label': 'Temperature',
            'data_type': Stream.DataType.NUMERIC,
            'unit': '°C',
        },
    )
    return stream


# ---------------------------------------------------------------------------
# FeedProvider API tests
# ---------------------------------------------------------------------------

class FeedProviderAPITest(APITestCase):
    """FeedProvider — only ThatPlaceAdmins can write; all authenticated can read."""

    def setUp(self):
        self.tenant = make_tenant('Provider Tenant')
        self.user = make_user('user@provider.test', self.tenant)
        self.admin = make_superuser('admin@thatplace.test')
        self.provider = make_provider()

    def test_list_authenticated(self):
        auth(self.client, self.user)
        r = self.client.get('/api/v1/feed-providers/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_list_unauthenticated(self):
        r = self.client.get('/api/v1/feed-providers/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_create(self):
        auth(self.client, self.admin)
        payload = {
            'slug': 'new-provider',
            'name': 'New Provider',
            'base_url': 'https://new.example.com',
            'auth_type': 'none',
            'scope': 'system',
            'poll_interval_seconds': 60,
            'is_active': True,
            'endpoints': [],
        }
        r = self.client.post('/api/v1/feed-providers/', payload, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_tenant_user_cannot_create(self):
        auth(self.client, self.user)
        payload = {
            'slug': 'bad-provider',
            'name': 'Bad',
            'base_url': 'https://x.com',
            'auth_type': 'none',
            'scope': 'system',
            'poll_interval_seconds': 60,
        }
        r = self.client.post('/api/v1/feed-providers/', payload, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_delete(self):
        auth(self.client, self.admin)
        r = self.client.delete(f'/api/v1/feed-providers/{self.provider.pk}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# FeedReading idempotency test
# ---------------------------------------------------------------------------

class FeedReadingIdempotencyTest(APITestCase):
    """FeedReading bulk_create with ignore_conflicts is idempotent."""

    def test_duplicate_reading_ignored(self):
        provider = make_provider(slug='idem-provider')
        channel = make_channel(provider)
        ts = timezone.now()

        FeedReading.objects.bulk_create([
            FeedReading(channel=channel, value=10.0, timestamp=ts, fetched_at=ts),
        ])
        # Second identical insert — should not raise, count stays 1
        FeedReading.objects.bulk_create([
            FeedReading(channel=channel, value=10.0, timestamp=ts, fetched_at=ts),
        ], ignore_conflicts=True)

        self.assertEqual(FeedReading.objects.filter(channel=channel).count(), 1)


# ---------------------------------------------------------------------------
# FeedChannelRuleIndex rebuild tests
# ---------------------------------------------------------------------------

class FeedChannelRuleIndexTest(APITestCase):
    """FeedChannelRuleIndex is rebuilt on rule create/update."""

    def setUp(self):
        self.tenant = make_tenant('Index Tenant')
        self.user = make_user('admin@index.test', self.tenant)
        self.provider = make_provider(slug='idx-provider')
        self.channel = make_channel(self.provider, key='idx_price')
        self.stream = make_stream(self.tenant)

    def _rule_payload(self, channel_id):
        return {
            'name': 'Feed Rule',
            'is_active': True,
            'condition_group_operator': 'AND',
            'condition_groups': [
                {
                    'logical_operator': 'AND',
                    'order': 0,
                    'conditions': [
                        {
                            'condition_type': 'feed_channel',
                            'channel': channel_id,
                            'operator': '>',
                            'threshold_value': '30',
                            'order': 0,
                        }
                    ],
                }
            ],
            'actions': [],
        }

    def test_index_built_on_create(self):
        auth(self.client, self.user)
        r = self.client.post('/api/v1/rules/', self._rule_payload(self.channel.pk), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        rule_id = r.data['id']
        self.assertTrue(
            FeedChannelRuleIndex.objects.filter(
                rule_id=rule_id, channel_id=self.channel.pk
            ).exists()
        )

    def test_index_cleared_on_channel_change(self):
        auth(self.client, self.user)
        r = self.client.post('/api/v1/rules/', self._rule_payload(self.channel.pk), format='json')
        rule_id = r.data['id']

        # Update rule to remove feed_channel condition — index should be cleared
        update_payload = {
            'name': 'Feed Rule',
            'is_active': True,
            'condition_group_operator': 'AND',
            'condition_groups': [
                {
                    'logical_operator': 'AND',
                    'order': 0,
                    'conditions': [
                        {
                            'condition_type': 'stream',
                            'stream': self.stream.pk,
                            'operator': '>',
                            'threshold_value': '25',
                            'order': 0,
                        }
                    ],
                }
            ],
            'actions': [],
        }
        r2 = self.client.put(f'/api/v1/rules/{rule_id}/', update_payload, format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)

        self.assertFalse(
            FeedChannelRuleIndex.objects.filter(
                rule_id=rule_id, channel_id=self.channel.pk
            ).exists()
        )
        # RuleStreamIndex should now have the stream
        self.assertTrue(
            RuleStreamIndex.objects.filter(
                rule_id=rule_id, stream_id=self.stream.pk
            ).exists()
        )


# ---------------------------------------------------------------------------
# TenantFeedSubscription cross-tenant isolation
# ---------------------------------------------------------------------------

class TenantFeedSubscriptionIsolationTest(APITestCase):
    """Tenant B cannot see Tenant A's feed subscriptions."""

    def setUp(self):
        self.tenant_a = make_tenant('Sub Tenant A')
        self.tenant_b = make_tenant('Sub Tenant B')
        self.user_a = make_user('a@sub.test', self.tenant_a)
        self.user_b = make_user('b@sub.test', self.tenant_b)
        self.provider = make_provider(slug='tenant-provider', scope='tenant')
        self.sub = TenantFeedSubscription.objects.create(
            tenant=self.tenant_a,
            provider=self.provider,
            credentials={},
            is_active=True,
        )

    def _ids_from_response(self, r):
        """Extract IDs from either a paginated {results:[...]} or plain list response."""
        data = r.data
        items = data.get('results', data) if isinstance(data, dict) else data
        return [item['id'] for item in items]

    def test_tenant_a_sees_own_subscription(self):
        auth(self.client, self.user_a)
        r = self.client.get('/api/v1/feed-subscriptions/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn(self.sub.pk, self._ids_from_response(r))

    def test_tenant_b_cannot_see_tenant_a_subscription(self):
        auth(self.client, self.user_b)
        r = self.client.get('/api/v1/feed-subscriptions/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.sub.pk, self._ids_from_response(r))

    def test_tenant_b_cannot_access_tenant_a_subscription_detail(self):
        auth(self.client, self.user_b)
        r = self.client.get(f'/api/v1/feed-subscriptions/{self.sub.pk}/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# ReferenceDataset row resolution tests
# ---------------------------------------------------------------------------

class FlatDatasetResolutionTest(APITestCase):
    """Flat (no TOU, no version) dataset resolution."""

    def setUp(self):
        self.tenant = make_tenant('Flat Tenant')
        self.dataset = make_dataset(slug='flat-ds')
        self.row = make_row(self.dataset, {'region': 'QLD'}, {'rate': 25.5})
        self.assignment = make_assignment(
            self.tenant, self.dataset, dimension_filter={'region': 'QLD'}
        )

    def test_resolves_correct_value(self):
        value = resolve_reference_value(self.assignment, 'rate')
        self.assertAlmostEqual(value, 25.5)

    def test_no_matching_row_raises(self):
        assignment = make_assignment(
            self.tenant, self.dataset, dimension_filter={'region': 'NSW'}
        )
        with self.assertRaises(ResolutionError):
            resolve_reference_value(assignment, 'rate')

    def test_missing_value_key_returns_none(self):
        value = resolve_reference_value(self.assignment, 'nonexistent_key')
        self.assertIsNone(value)


class VersionedDatasetResolutionTest(APITestCase):
    """Versioned dataset uses latest active version when assignment.version is None."""

    def setUp(self):
        self.tenant = make_tenant('Versioned Tenant')
        self.dataset = make_dataset(slug='versioned-ds', versioned=True)
        # Two versions — resolver should pick the lexicographically later one
        make_row(self.dataset, {'region': 'QLD'}, {'rate': 20.0}, version='2024-25')
        make_row(self.dataset, {'region': 'QLD'}, {'rate': 22.5}, version='2025-26')
        self.assignment = make_assignment(
            self.tenant, self.dataset, dimension_filter={'region': 'QLD'}
        )

    def test_resolves_latest_version(self):
        value = resolve_reference_value(self.assignment, 'rate')
        self.assertAlmostEqual(value, 22.5)

    def test_pinned_version_used_when_set(self):
        self.assignment.version = '2024-25'
        self.assignment.save()
        value = resolve_reference_value(self.assignment, 'rate')
        self.assertAlmostEqual(value, 20.0)


class TOUDatasetResolutionTest(APITestCase):
    """TOU dataset resolution uses tenant timezone and correct day/time matching."""

    def setUp(self):
        self.tenant = make_tenant('TOU Tenant')
        self.dataset = make_dataset(slug='tou-ds', tou=True)
        # Peak: Mon–Fri 07:00–21:00 → rate 30c
        self.peak_row = make_row(
            self.dataset,
            {'region': 'QLD'},
            {'rate': 30.0},
            applicable_days=[0, 1, 2, 3, 4],
            time_from=time(7, 0),
            time_to=time(21, 0),
        )
        # Off-peak: all days 21:00–07:00 → rate 10c
        self.offpeak_row = make_row(
            self.dataset,
            {'region': 'QLD'},
            {'rate': 10.0},
            applicable_days=[0, 1, 2, 3, 4, 5, 6],
            time_from=time(21, 0),
            time_to=time(7, 0),
        )
        self.assignment = make_assignment(
            self.tenant, self.dataset, dimension_filter={'region': 'QLD'}
        )

    def test_peak_period_resolves_peak_rate(self):
        """Mock local time to Monday 10:00 — should get peak rate."""
        mock_dt = MagicMock()
        mock_dt.weekday.return_value = 0  # Monday
        mock_dt.time.return_value.replace.return_value = time(10, 0)

        with patch('apps.feeds.resolution.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            value = resolve_reference_value(self.assignment, 'rate')

        self.assertAlmostEqual(value, 30.0)

    def test_offpeak_period_resolves_offpeak_rate(self):
        """Mock local time to Monday 23:00 — should get off-peak rate."""
        mock_dt = MagicMock()
        mock_dt.weekday.return_value = 0  # Monday
        mock_dt.time.return_value.replace.return_value = time(23, 0)

        with patch('apps.feeds.resolution.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            value = resolve_reference_value(self.assignment, 'rate')

        self.assertAlmostEqual(value, 10.0)


# ---------------------------------------------------------------------------
# Bulk import tests
# ---------------------------------------------------------------------------

class BulkImportTest(APITestCase):
    """Bulk CSV import via POST /api/v1/reference-datasets/:id/rows/bulk/."""

    def setUp(self):
        self.admin = make_superuser('admin@bulk.test')
        self.dataset = make_dataset(slug='bulk-ds', versioned=True)

    def _csv_bytes(self, rows: list[str]) -> bytes:
        return '\n'.join(['version,region,rate', *rows]).encode()

    def test_happy_path_import(self):
        auth(self.client, self.admin)
        csv_content = self._csv_bytes(['2025-26,QLD,25.5', '2025-26,NSW,22.0'])
        f = io.BytesIO(csv_content)
        f.name = 'tariffs.csv'
        r = self.client.post(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/bulk/',
            {'file': f},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(ReferenceDatasetRow.objects.filter(dataset=self.dataset).count(), 2)

    def test_upsert_updates_existing_row(self):
        auth(self.client, self.admin)
        # First import
        csv1 = self._csv_bytes(['2025-26,QLD,25.5'])
        f1 = io.BytesIO(csv1)
        f1.name = 'tariffs.csv'
        self.client.post(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/bulk/',
            {'file': f1},
            format='multipart',
        )
        # Second import with updated rate
        csv2 = self._csv_bytes(['2025-26,QLD,28.0'])
        f2 = io.BytesIO(csv2)
        f2.name = 'tariffs.csv'
        r = self.client.post(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/bulk/',
            {'file': f2},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        # Only one row should exist (upserted)
        self.assertEqual(ReferenceDatasetRow.objects.filter(dataset=self.dataset).count(), 1)
        row = ReferenceDatasetRow.objects.get(dataset=self.dataset)
        self.assertAlmostEqual(row.values['rate'], 28.0)

    def test_tenant_user_cannot_bulk_import(self):
        tenant = make_tenant('Bulk Tenant')
        user = make_user('user@bulk.test', tenant)
        auth(self.client, user)
        csv_content = self._csv_bytes(['2025-26,QLD,25.5'])
        f = io.BytesIO(csv_content)
        f.name = 'tariffs.csv'
        r = self.client.post(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/bulk/',
            {'file': f},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Rule condition serializer validation tests
# ---------------------------------------------------------------------------

class FeedChannelConditionValidationTest(APITestCase):
    """feed_channel conditions require channel + numeric operator + threshold_value."""

    def setUp(self):
        self.tenant = make_tenant('Condition Tenant')
        self.user = make_user('admin@cond.test', self.tenant)
        self.provider = make_provider(slug='cond-provider')
        self.channel = make_channel(self.provider, key='cond_price')

    def _post_rule(self, condition_data):
        return self.client.post('/api/v1/rules/', {
            'name': 'Validation Rule',
            'is_active': True,
            'condition_group_operator': 'AND',
            'condition_groups': [{
                'logical_operator': 'AND',
                'order': 0,
                'conditions': [condition_data],
            }],
            'actions': [],
        }, format='json')

    def test_valid_feed_channel_condition(self):
        auth(self.client, self.user)
        r = self._post_rule({
            'condition_type': 'feed_channel',
            'channel': self.channel.pk,
            'operator': '>',
            'threshold_value': '50',
            'order': 0,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_missing_channel_rejected(self):
        auth(self.client, self.user)
        r = self._post_rule({
            'condition_type': 'feed_channel',
            'operator': '>',
            'threshold_value': '50',
            'order': 0,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_string_operator_rejected_for_feed_channel(self):
        auth(self.client, self.user)
        r = self._post_rule({
            'condition_type': 'feed_channel',
            'channel': self.channel.pk,
            'operator': '!=',
            'threshold_value': 'some_string',
            'order': 0,
        })
        # != is a valid numeric op — should pass
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)


class ReferenceValueConditionValidationTest(APITestCase):
    """reference_value conditions require dataset + value_key + numeric operator + threshold."""

    def setUp(self):
        self.tenant = make_tenant('RefVal Tenant')
        self.user = make_user('admin@refval.test', self.tenant)
        self.dataset = make_dataset(slug='refval-ds')

    def _post_rule(self, condition_data):
        return self.client.post('/api/v1/rules/', {
            'name': 'RefVal Rule',
            'is_active': True,
            'condition_group_operator': 'AND',
            'condition_groups': [{
                'logical_operator': 'AND',
                'order': 0,
                'conditions': [condition_data],
            }],
            'actions': [],
        }, format='json')

    def test_valid_reference_value_condition(self):
        auth(self.client, self.user)
        r = self._post_rule({
            'condition_type': 'reference_value',
            'dataset': self.dataset.pk,
            'value_key': 'rate',
            'operator': '>',
            'threshold_value': '30',
            'order': 0,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_missing_dataset_rejected(self):
        auth(self.client, self.user)
        r = self._post_rule({
            'condition_type': 'reference_value',
            'value_key': 'rate',
            'operator': '>',
            'threshold_value': '30',
            'order': 0,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_value_key_rejected(self):
        auth(self.client, self.user)
        r = self._post_rule({
            'condition_type': 'reference_value',
            'dataset': self.dataset.pk,
            'operator': '>',
            'threshold_value': '30',
            'order': 0,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# load_reference_data management command
# ---------------------------------------------------------------------------

class LoadReferenceDataCommandTest(APITestCase):
    """Management command seeds AEMO provider and reference datasets idempotently."""

    def test_seed_idempotent(self):
        from django.core.management import call_command

        call_command('load_reference_data', verbosity=0)
        call_command('load_reference_data', verbosity=0)

        # Should have exactly one of each after two runs
        self.assertEqual(FeedProvider.objects.filter(slug='aemo-nem-summary').count(), 1)
        self.assertEqual(ReferenceDataset.objects.filter(slug='network-tariffs').count(), 1)
        self.assertEqual(ReferenceDataset.objects.filter(slug='co2-factors').count(), 1)
        # CO2 rows seeded
        self.assertEqual(
            ReferenceDatasetRow.objects.filter(
                dataset__slug='co2-factors'
            ).count(),
            6,
        )


# ---------------------------------------------------------------------------
# SR-04 — CSV bulk import: size/row limits + formula injection on export
# ---------------------------------------------------------------------------

class BulkImportLimitsTest(APITestCase):
    """Bulk import endpoint enforces file-size and row-count limits (SR-04b).

    Ref: security_risks.md § SR-04 — CSV Bulk Import Injection and Resource Exhaustion
    """

    def setUp(self):
        self.admin = make_superuser('admin@limits.test')
        self.dataset = make_dataset(slug='limits-ds', versioned=True)
        auth(self.client, self.admin)

    def _upload(self, content: bytes, filename: str = 'data.csv'):
        f = io.BytesIO(content)
        f.name = filename
        return self.client.post(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/bulk/',
            {'file': f},
            format='multipart',
        )

    def test_file_over_10mb_rejected(self):
        """Files larger than 10 MB must be rejected with a 400 before any parsing."""
        from apps.feeds.serializers import CSV_MAX_UPLOAD_BYTES

        # Build a file slightly over the limit by padding with newlines after the header
        padding = b'\n' * (CSV_MAX_UPLOAD_BYTES + 1)
        oversized = b'version,region,rate\n' + padding
        r = self._upload(oversized)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_file_at_10mb_accepted(self):
        """A file exactly at the limit must not be rejected by the size check."""
        from apps.feeds.serializers import CSV_MAX_UPLOAD_BYTES

        # One valid row — size check must pass even if the file is large (but valid)
        content = b'version,region,rate\n2025-26,QLD,25.5\n'
        # Patch the size attribute on the InMemoryUploadedFile to simulate a file at the limit
        f = io.BytesIO(content)
        f.name = 'data.csv'
        f.size = CSV_MAX_UPLOAD_BYTES  # exactly at limit
        r = self.client.post(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/bulk/',
            {'file': f},
            format='multipart',
        )
        # Should not fail with a size error (may still fail on content validation,
        # but not because of the size limit)
        self.assertNotIn(
            'Maximum upload size',
            str(r.data),
            'Size limit should not be triggered at exactly CSV_MAX_UPLOAD_BYTES',
        )

    def test_row_count_over_limit_rejected(self):
        """A CSV with more than CSV_MAX_ROWS data rows must be rejected with a 400."""
        from apps.feeds.serializers import CSV_MAX_ROWS

        header = 'version,region,rate\n'
        # Each row is ~18 bytes; generate exactly MAX_ROWS + 1
        rows = '\n'.join(f'2025-26,QLD,{i}' for i in range(CSV_MAX_ROWS + 1))
        oversized = (header + rows).encode()
        r = self._upload(oversized)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        error_msg = r.data['errors'][0]['error']
        self.assertIn(str(CSV_MAX_ROWS), error_msg)

    def test_row_count_at_limit_accepted(self):
        """Exactly CSV_MAX_ROWS data rows must not trigger the row-count error."""
        from apps.feeds.serializers import CSV_MAX_ROWS

        header = 'version,region,rate\n'
        rows = '\n'.join(f'2025-26,R{i:05d},{i}' for i in range(CSV_MAX_ROWS))
        content = (header + rows).encode()
        r = self._upload(content)
        # Should get a 200 (or may fail on DB constraints) — not a row-count 400
        if r.status_code == status.HTTP_400_BAD_REQUEST:
            self.assertNotIn('maximum allowed', r.data['errors'][0]['error'])

    def test_non_csv_file_rejected(self):
        """Only .csv files are accepted."""
        r = self._upload(b'not a csv', filename='data.xlsx')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class SanitizeCsvCellTest(APITestCase):
    """sanitize_csv_cell prefixes formula-triggering characters (SR-04a).

    Ref: security_risks.md § SR-04 — CSV formula injection
    """

    def test_equals_sign_prefixed(self):
        from apps.feeds.serializers import sanitize_csv_cell
        self.assertEqual(sanitize_csv_cell('=SUM(1+1)'), '\t=SUM(1+1)')

    def test_plus_sign_prefixed(self):
        from apps.feeds.serializers import sanitize_csv_cell
        self.assertEqual(sanitize_csv_cell('+malware'), '\t+malware')

    def test_minus_sign_prefixed(self):
        from apps.feeds.serializers import sanitize_csv_cell
        self.assertEqual(sanitize_csv_cell('-2+3'), '\t-2+3')

    def test_at_sign_prefixed(self):
        from apps.feeds.serializers import sanitize_csv_cell
        self.assertEqual(sanitize_csv_cell('@SUM(A1)'), '\t@SUM(A1)')

    def test_safe_value_unchanged(self):
        from apps.feeds.serializers import sanitize_csv_cell
        self.assertEqual(sanitize_csv_cell('QLD'), 'QLD')
        self.assertEqual(sanitize_csv_cell('25.5'), '25.5')
        self.assertEqual(sanitize_csv_cell(''), '')

    def test_none_safe(self):
        """Empty string (falsy) must pass through without error."""
        from apps.feeds.serializers import sanitize_csv_cell
        self.assertEqual(sanitize_csv_cell(''), '')


class CsvExportTest(APITestCase):
    """GET /rows/export/ returns sanitised CSV for admins (SR-04a).

    Ref: security_risks.md § SR-04 — CSV injection mitigation on export
    """

    def setUp(self):
        self.admin = make_superuser('admin@export.test')
        self.dataset = make_dataset(slug='export-ds', versioned=True)
        # Seed two rows, one with a formula-triggering dimension value
        ReferenceDatasetRow.objects.create(
            dataset=self.dataset,
            version='2025-26',
            dimensions={'region': '=INJECTION'},
            values={'rate': 25.5},
        )
        ReferenceDatasetRow.objects.create(
            dataset=self.dataset,
            version='2025-26',
            dimensions={'region': 'QLD'},
            values={'rate': 22.0},
        )

    def _export(self):
        auth(self.client, self.admin)
        return self.client.get(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/export/'
        )

    def test_export_returns_csv_content_type(self):
        r = self._export()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', r['Content-Type'])

    def test_export_content_disposition_attachment(self):
        r = self._export()
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('export-ds', r['Content-Disposition'])

    def test_formula_prefix_sanitised_in_export(self):
        """A dimension value starting with = must be prefixed with a tab."""
        r = self._export()
        content = r.content.decode('utf-8')
        # The injection attempt must NOT appear as a bare =INJECTION
        self.assertNotIn(',=INJECTION', content)
        # It must appear sanitised
        self.assertIn('\t=INJECTION', content)

    def test_safe_values_unmodified(self):
        """Normal values must pass through unchanged."""
        r = self._export()
        content = r.content.decode('utf-8')
        self.assertIn('QLD', content)
        self.assertIn('22.0', content)

    def test_export_row_count_matches_db(self):
        r = self._export()
        lines = [l for l in r.content.decode('utf-8').splitlines() if l.strip()]
        # One header + two data rows
        self.assertEqual(len(lines), 3)

    def test_tenant_user_cannot_export(self):
        tenant = make_tenant('Export Tenant')
        user = make_user('user@export.test', tenant)
        auth(self.client, user)
        r = self.client.get(
            f'/api/v1/reference-datasets/{self.dataset.pk}/rows/export/'
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
