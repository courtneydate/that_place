"""Tests for Sprint 11: Dashboard and DashboardWidget CRUD, tenant isolation,
and stream readings endpoint.

Ref: SPEC.md § Feature: Dashboards & Visualisation
"""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.dashboards.models import Dashboard, DashboardWidget
from apps.devices.models import Device, DeviceType, Site
from apps.readings.models import Stream, StreamReading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def make_dashboard(tenant, name='Main', columns=2, user=None):
    return Dashboard.objects.create(tenant=tenant, name=name, columns=columns, created_by=user)


def make_device_and_stream(tenant):
    """Create minimal device + stream for use in widget tests."""
    site = Site.objects.create(tenant=tenant, name='Site')
    dt = DeviceType.objects.create(name='Sensor', slug=f'sensor-{tenant.pk}')
    device = Device.objects.create(
        tenant=tenant, site=site, device_type=dt,
        name='Dev', serial_number=f'SN-{tenant.pk}', status='active',
    )
    stream = Stream.objects.create(device=device, key='temp', data_type='numeric')
    return stream


DASH_URL = '/api/v1/dashboards/'


def widget_url(dashboard_pk):
    return f'/api/v1/dashboards/{dashboard_pk}/widgets/'


def widget_detail_url(dashboard_pk, widget_pk):
    return f'/api/v1/dashboards/{dashboard_pk}/widgets/{widget_pk}/'


# ---------------------------------------------------------------------------
# Dashboard list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDashboardList:

    def test_admin_can_list(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        make_dashboard(tenant, 'D1')
        make_dashboard(tenant, 'D2')
        resp = auth_client(admin).get(DASH_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_operator_can_list(self):
        tenant = make_tenant()
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).get(DASH_URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_view_only_can_list(self):
        tenant = make_tenant()
        viewer = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(viewer).get(DASH_URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_unauthenticated_cannot_list(self):
        resp = APIClient().get(DASH_URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_dashboards_not_visible(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('a@a.com', tenant_a)
        make_dashboard(tenant_b, 'B Dashboard')
        resp = auth_client(admin_a).get(DASH_URL)
        names = [d['name'] for d in resp.data]
        assert 'B Dashboard' not in names


# ---------------------------------------------------------------------------
# Dashboard create
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDashboardCreate:

    def test_admin_can_create(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(DASH_URL, {'name': 'New Board', 'columns': 3})
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['name'] == 'New Board'
        assert resp.data['columns'] == 3
        assert Dashboard.objects.filter(tenant=tenant, name='New Board').exists()

    def test_operator_can_create(self):
        tenant = make_tenant()
        op = make_tenant_user('op@t.com', tenant, TenantUser.Role.OPERATOR)
        resp = auth_client(op).post(DASH_URL, {'name': 'Op Board', 'columns': 1})
        assert resp.status_code == status.HTTP_201_CREATED

    def test_view_only_cannot_create(self):
        tenant = make_tenant()
        viewer = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        resp = auth_client(viewer).post(DASH_URL, {'name': 'Sneak', 'columns': 1})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_name_required(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(DASH_URL, {'columns': 2})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_columns_rejected(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        resp = auth_client(admin).post(DASH_URL, {'name': 'Bad', 'columns': 5})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_created_by_set_to_requesting_user(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        auth_client(admin).post(DASH_URL, {'name': 'Board', 'columns': 2})
        db = Dashboard.objects.get(tenant=tenant, name='Board')
        assert db.created_by.email == 'admin@t.com'


# ---------------------------------------------------------------------------
# Dashboard retrieve / update / delete
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDashboardDetail:

    def test_retrieve_includes_widgets(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        board = make_dashboard(tenant)
        DashboardWidget.objects.create(
            dashboard=board, widget_type='value_card',
            stream_ids=[], config={}, position={'order': 0},
        )
        resp = auth_client(admin).get(f'{DASH_URL}{board.pk}/')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data['widgets']) == 1

    def test_cross_tenant_retrieve_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('a@a.com', tenant_a)
        board_b = make_dashboard(tenant_b, 'B Board')
        resp = auth_client(admin_a).get(f'{DASH_URL}{board_b.pk}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_admin_can_update(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        board = make_dashboard(tenant)
        resp = auth_client(admin).put(f'{DASH_URL}{board.pk}/', {'name': 'Updated', 'columns': 1})
        assert resp.status_code == status.HTTP_200_OK
        board.refresh_from_db()
        assert board.name == 'Updated'
        assert board.columns == 1

    def test_view_only_cannot_update(self):
        tenant = make_tenant()
        viewer = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        board = make_dashboard(tenant)
        resp = auth_client(viewer).put(f'{DASH_URL}{board.pk}/', {'name': 'X', 'columns': 2})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_delete(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        board = make_dashboard(tenant)
        resp = auth_client(admin).delete(f'{DASH_URL}{board.pk}/')
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Dashboard.objects.filter(pk=board.pk).exists()

    def test_cross_tenant_delete_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('a@a.com', tenant_a)
        board_b = make_dashboard(tenant_b)
        resp = auth_client(admin_a).delete(f'{DASH_URL}{board_b.pk}/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Widget CRUD
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestWidgetCreate:

    def test_admin_can_add_widget(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        stream = make_device_and_stream(tenant)
        board = make_dashboard(tenant)
        payload = {
            'widget_type': 'value_card',
            'stream_ids': [stream.pk],
            'config': {},
            'position': {'order': 0},
        }
        resp = auth_client(admin).post(widget_url(board.pk), payload, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert DashboardWidget.objects.filter(dashboard=board).count() == 1

    def test_cross_tenant_stream_id_rejected(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('a@a.com', tenant_a)
        stream_b = make_device_and_stream(tenant_b)
        board = make_dashboard(tenant_a)
        payload = {
            'widget_type': 'value_card',
            'stream_ids': [stream_b.pk],
            'config': {},
            'position': {'order': 0},
        }
        resp = auth_client(admin_a).post(widget_url(board.pk), payload, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_view_only_cannot_add_widget(self):
        tenant = make_tenant()
        viewer = make_tenant_user('v@t.com', tenant, TenantUser.Role.VIEWER)
        board = make_dashboard(tenant)
        resp = auth_client(viewer).post(widget_url(board.pk), {
            'widget_type': 'value_card', 'stream_ids': [], 'config': {}, 'position': {'order': 0},
        }, format='json')
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_dashboard_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('a@a.com', tenant_a)
        board_b = make_dashboard(tenant_b)
        resp = auth_client(admin_a).post(widget_url(board_b.pk), {
            'widget_type': 'value_card', 'stream_ids': [], 'config': {}, 'position': {'order': 0},
        }, format='json')
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestWidgetUpdateDelete:

    def test_admin_can_update_widget(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        board = make_dashboard(tenant)
        widget = DashboardWidget.objects.create(
            dashboard=board, widget_type='value_card',
            stream_ids=[], config={}, position={'order': 0},
        )
        resp = auth_client(admin).put(
            widget_detail_url(board.pk, widget.pk),
            {'widget_type': 'value_card', 'stream_ids': [], 'config': {'title': 'X'}, 'position': {'order': 1}},
            format='json',
        )
        assert resp.status_code == status.HTTP_200_OK
        widget.refresh_from_db()
        assert widget.config == {'title': 'X'}
        assert widget.position == {'order': 1}

    def test_admin_can_delete_widget(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        board = make_dashboard(tenant)
        widget = DashboardWidget.objects.create(
            dashboard=board, widget_type='value_card',
            stream_ids=[], config={}, position={'order': 0},
        )
        resp = auth_client(admin).delete(widget_detail_url(board.pk, widget.pk))
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not DashboardWidget.objects.filter(pk=widget.pk).exists()

    def test_widget_from_other_dashboard_returns_404(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        board_1 = make_dashboard(tenant, 'Board 1')
        board_2 = make_dashboard(tenant, 'Board 2')
        widget = DashboardWidget.objects.create(
            dashboard=board_2, widget_type='value_card',
            stream_ids=[], config={}, position={'order': 0},
        )
        # Try to delete board_2's widget via board_1's URL
        resp = auth_client(admin).delete(widget_detail_url(board_1.pk, widget.pk))
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Stream readings endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStreamReadings:

    def _make_stream_with_readings(self, tenant):
        from datetime import timedelta

        from django.utils import timezone
        stream = make_device_and_stream(tenant)
        now = timezone.now()
        for i in range(5):
            StreamReading.objects.create(
                stream=stream,
                value=float(i * 10),
                timestamp=now - timedelta(minutes=i),
            )
        return stream, now

    def test_can_list_readings(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        stream, _ = self._make_stream_with_readings(tenant)
        resp = auth_client(admin).get(f'/api/v1/streams/{stream.pk}/readings/')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 5

    def test_limit_respected(self):
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        stream, _ = self._make_stream_with_readings(tenant)
        resp = auth_client(admin).get(f'/api/v1/streams/{stream.pk}/readings/?limit=2')
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 2

    def test_from_filter(self):
        from datetime import timedelta
        tenant = make_tenant()
        admin = make_tenant_user('admin@t.com', tenant)
        stream, now = self._make_stream_with_readings(tenant)
        # Only readings in the last 2.5 minutes — that's 3 readings (0, 1, 2 minutes ago)
        cutoff = (now - timedelta(minutes=2, seconds=30)).isoformat()
        resp = auth_client(admin).get(
            f'/api/v1/streams/{stream.pk}/readings/',
            {'from': cutoff},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 3

    def test_cross_tenant_stream_returns_404(self):
        tenant_a = make_tenant('A')
        tenant_b = make_tenant('B')
        admin_a = make_tenant_user('a@a.com', tenant_a)
        stream_b = make_device_and_stream(tenant_b)
        resp = auth_client(admin_a).get(f'/api/v1/streams/{stream_b.pk}/readings/')
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthenticated_cannot_access(self):
        tenant = make_tenant()
        stream = make_device_and_stream(tenant)
        resp = APIClient().get(f'/api/v1/streams/{stream.pk}/readings/')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
