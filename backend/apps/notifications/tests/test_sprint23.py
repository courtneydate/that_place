"""Sprint 23 tests — That Place Admin Notifications & the event registry.

Covers:
  - NotificationEventType.render() template rendering (incl. missing keys)
  - emit_event: platform_admin vs tenant audience resolution
  - emit_event: in_app + email channel fan-out
  - emit_event: unknown / inactive event keys are safe no-ops
  - emit_event: tenant audience without tenant_id is a no-op
  - emit_event: platform events never reach tenant users
  - Retrofit: create_system_notification routes through the registry
  - Platform emitters: tenant created / deactivated, device pending approval
  - send_event_email delivers a platform notification email
  - NotificationEventType CRUD — That Place Admin only

Ref: SPEC.md § Data Model — NotificationEventType; ROADMAP Sprint 23
"""
import pytest
from django.utils.text import slugify
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, TenantUser, User
from apps.devices.models import Device, DeviceType, Site
from apps.notifications.models import Notification, NotificationEventType
from apps.notifications.tasks import (
    create_system_notification,
    emit_event,
    send_event_email,
)

EVENT_TYPES_URL = '/api/v1/notification-event-types/'

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _eager(settings):
    """Run Celery tasks inline, clear the cache, and disable the backend cert check.

    Clearing the cache isolates the per-test cooldown / dedup keys used by the
    infrastructure emitters; blanking MQTT_BACKEND_CERT_B64 keeps the
    certificate-expiry task focused on test-created device certs.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    settings.MQTT_BACKEND_CERT_B64 = ''
    from django.core.cache import cache
    cache.clear()


def make_tenant(name: str) -> Tenant:
    """Create a tenant with a slugified name."""
    return Tenant.objects.create(name=name, slug=slugify(name))


def make_user(email: str, tenant: Tenant, role: str = 'admin') -> User:
    """Create a tenant user with the given role."""
    user = User.objects.create_user(email=email, password='testpass123')
    TenantUser.objects.create(user=user, tenant=tenant, role=role)
    return user


def make_platform_admin(email: str) -> User:
    """Create a That Place platform admin (no tenant)."""
    return User.objects.create_user(
        email=email, password='testpass123', is_that_place_admin=True,
    )


# ---------------------------------------------------------------------------
# NotificationEventType.render
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventTypeRender:
    """The message template renders against event metadata."""

    def test_render_fills_placeholders(self):
        """Placeholders are substituted from the metadata dict."""
        event_type = NotificationEventType.objects.get(key='device_offline')
        message = event_type.render({'device_name': 'Pump', 'serial_number': 'P-1'})
        assert message == 'Device Pump (P-1) has gone offline.'

    def test_render_missing_key_is_blank(self):
        """A missing placeholder resolves to an empty string, not an error."""
        event_type = NotificationEventType.objects.get(key='device_offline')
        message = event_type.render({})
        assert message == 'Device  () has gone offline.'


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEmitEvent:
    """emit_event resolves recipients, renders, and fans out across channels."""

    def test_platform_event_notifies_all_platform_admins(self):
        """A platform_admin event reaches every That Place Admin on each channel."""
        admin_a = make_platform_admin('pa-a@example.com')
        admin_b = make_platform_admin('pa-b@example.com')

        emit_event('tenant_created', {'tenant_name': 'Acme', 'tenant_slug': 'acme'})

        for admin in (admin_a, admin_b):
            channels = set(
                Notification.objects
                .filter(user=admin, event_type='tenant_created')
                .values_list('channel', flat=True)
            )
            assert channels == {'in_app', 'email'}

    def test_message_is_rendered_and_stored(self):
        """The rendered template text is stored on Notification.message."""
        admin = make_platform_admin('pa-msg@example.com')
        emit_event('tenant_created', {'tenant_name': 'Acme', 'tenant_slug': 'acme'})
        notif = Notification.objects.filter(user=admin, channel='in_app').first()
        assert notif.message == 'New tenant created: Acme.'
        assert notif.notification_type == Notification.NotificationType.SYSTEM_EVENT

    def test_tenant_event_notifies_tenant_admins_only(self):
        """A tenant-audience event reaches that tenant's admins, not operators."""
        tenant = make_tenant('EmitTenantT')
        admin = make_user('et-admin@example.com', tenant, role='admin')
        operator = make_user('et-op@example.com', tenant, role='operator')

        emit_event(
            'device_offline',
            {'device_name': 'D', 'serial_number': 'S'},
            tenant_id=tenant.pk,
        )

        assert Notification.objects.filter(user=admin).count() == 1
        assert Notification.objects.filter(user=operator).count() == 0

    def test_tenant_event_without_tenant_id_is_noop(self):
        """A tenant-audience event with no tenant_id creates nothing."""
        tenant = make_tenant('NoTenantIdT')
        make_user('nti-admin@example.com', tenant, role='admin')

        emit_event('device_offline', {'device_name': 'D', 'serial_number': 'S'})

        assert Notification.objects.count() == 0

    def test_unknown_event_key_is_noop(self):
        """An unregistered event key is logged and skipped — no exception."""
        make_platform_admin('pa-unknown@example.com')
        emit_event('this_event_does_not_exist', {})
        assert Notification.objects.count() == 0

    def test_inactive_event_type_is_noop(self):
        """An inactive event type produces no notifications."""
        make_platform_admin('pa-inactive@example.com')
        NotificationEventType.objects.filter(key='tenant_created').update(
            is_active=False,
        )
        emit_event('tenant_created', {'tenant_name': 'Acme', 'tenant_slug': 'acme'})
        assert Notification.objects.count() == 0

    def test_platform_event_does_not_reach_tenant_users(self):
        """Tenant users never receive a platform_admin-audience event."""
        platform_admin = make_platform_admin('pa-scope@example.com')
        tenant = make_tenant('ScopeTenantT')
        tenant_admin = make_user('st-admin@example.com', tenant, role='admin')

        emit_event('tenant_created', {'tenant_name': 'Acme', 'tenant_slug': 'acme'})

        assert Notification.objects.filter(user=platform_admin).exists()
        assert not Notification.objects.filter(user=tenant_admin).exists()


# ---------------------------------------------------------------------------
# Retrofit — create_system_notification routes through the registry
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRetrofit:
    """The Sprint 19 create_system_notification shim uses the registry."""

    def test_create_system_notification_renders_message(self):
        """The shim now stores a registry-rendered message on the notification."""
        tenant = make_tenant('RetrofitT')
        admin = make_user('rf-admin@example.com', tenant, role='admin')

        create_system_notification(
            'device_approved',
            tenant.pk,
            {'device_name': 'Gateway', 'serial_number': 'GW-9'},
        )

        notif = Notification.objects.get(user=admin, event_type='device_approved')
        assert notif.message == 'Device Gateway (GW-9) was approved.'
        assert notif.channel == 'in_app'


# ---------------------------------------------------------------------------
# Platform emitters wired into views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlatformEmitters:
    """Platform events fire from the views that detect the condition."""

    def test_tenant_creation_emits_event(self):
        """Creating a tenant notifies That Place Admins."""
        platform_admin = make_platform_admin('pe-create@example.com')
        client = APIClient()
        client.force_authenticate(user=platform_admin)

        resp = client.post(
            '/api/v1/tenants/', {'name': 'Newco', 'slug': 'newco'},
        )
        assert resp.status_code == 201
        assert Notification.objects.filter(
            user=platform_admin, event_type='tenant_created',
        ).exists()

    def test_tenant_deactivation_emits_event(self):
        """Deactivating a tenant notifies That Place Admins."""
        platform_admin = make_platform_admin('pe-deact@example.com')
        tenant = make_tenant('ToDeactivateT')
        client = APIClient()
        client.force_authenticate(user=platform_admin)

        resp = client.patch(
            f'/api/v1/tenants/{tenant.pk}/', {'is_active': False},
        )
        assert resp.status_code == 200
        assert Notification.objects.filter(
            user=platform_admin, event_type='tenant_deactivated',
        ).exists()

    def test_tenant_update_without_deactivation_emits_nothing(self):
        """A non-deactivating tenant update does not emit tenant_deactivated."""
        platform_admin = make_platform_admin('pe-noop@example.com')
        tenant = make_tenant('RenameT')
        client = APIClient()
        client.force_authenticate(user=platform_admin)

        resp = client.patch(
            f'/api/v1/tenants/{tenant.pk}/', {'name': 'Renamed'},
        )
        assert resp.status_code == 200
        assert not Notification.objects.filter(
            event_type='tenant_deactivated',
        ).exists()

    def test_device_registration_emits_pending_event(self):
        """Registering a device notifies That Place Admins it awaits approval."""
        platform_admin = make_platform_admin('pe-device@example.com')
        tenant = make_tenant('DeviceRegT')
        tenant_admin = make_user('dr-admin@example.com', tenant, role='admin')
        device_type = DeviceType.objects.create(
            name='S23 Device Type',
            slug='s23-device-type',
            connection_type=DeviceType.ConnectionType.MQTT,
            is_push=True,
            default_offline_threshold_minutes=60,
            command_ack_timeout_seconds=30,
        )
        site = Site.objects.create(tenant=tenant, name='S23 Site')

        client = APIClient()
        client.force_authenticate(user=tenant_admin)
        resp = client.post('/api/v1/devices/', {
            'name': 'Pending Scout',
            'serial_number': 'S23-PEND-1',
            'site': site.pk,
            'device_type': device_type.pk,
        })
        assert resp.status_code == 201

        notif = Notification.objects.filter(
            user=platform_admin, event_type='device_pending_approval',
        ).first()
        assert notif is not None
        assert 'Pending Scout' in notif.message


# ---------------------------------------------------------------------------
# send_event_email
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendEventEmail:
    """Platform notification emails are delivered."""

    def test_send_event_email_delivers(self, mailoutbox):
        """send_event_email sends the rendered message and marks it delivered."""
        admin = make_platform_admin('see@example.com')
        notif = Notification.objects.create(
            user=admin,
            notification_type=Notification.NotificationType.SYSTEM_EVENT,
            event_type='tenant_created',
            message='New tenant created: Acme.',
            channel=Notification.Channel.EMAIL,
            delivery_status=Notification.DeliveryStatus.SENT,
        )

        send_event_email(notif.pk)

        assert len(mailoutbox) == 1
        assert 'New tenant created: Acme.' in mailoutbox[0].body
        notif.refresh_from_db()
        assert notif.delivery_status == Notification.DeliveryStatus.DELIVERED


# ---------------------------------------------------------------------------
# NotificationEventType CRUD API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventTypeCRUD:
    """The event registry CRUD endpoint is restricted to That Place Admins."""

    def test_platform_admin_can_list(self):
        """A That Place Admin sees the seeded event types."""
        client = APIClient()
        client.force_authenticate(user=make_platform_admin('crud-list@example.com'))
        resp = client.get(EVENT_TYPES_URL)
        assert resp.status_code == 200
        keys = {row['key'] for row in resp.data}
        assert 'device_offline' in keys
        assert 'tenant_created' in keys

    def test_tenant_admin_forbidden(self):
        """A tenant admin cannot access the platform registry."""
        tenant = make_tenant('CrudTenantT')
        client = APIClient()
        client.force_authenticate(user=make_user('crud-t@example.com', tenant))
        resp = client.get(EVENT_TYPES_URL)
        assert resp.status_code == 403

    def test_unauthenticated_forbidden(self):
        """An unauthenticated request is rejected."""
        resp = APIClient().get(EVENT_TYPES_URL)
        assert resp.status_code == 401

    def test_platform_admin_can_update(self):
        """A That Place Admin can edit severity and the message template."""
        client = APIClient()
        client.force_authenticate(user=make_platform_admin('crud-upd@example.com'))
        event_type = NotificationEventType.objects.get(key='device_offline')

        resp = client.patch(
            f'{EVENT_TYPES_URL}{event_type.pk}/',
            {'severity': 'critical', 'message_template': 'Offline: {device_name}'},
        )
        assert resp.status_code == 200
        event_type.refresh_from_db()
        assert event_type.severity == 'critical'
        assert event_type.message_template == 'Offline: {device_name}'

    def test_invalid_channel_rejected(self):
        """default_channels is validated against the supported channels."""
        client = APIClient()
        client.force_authenticate(user=make_platform_admin('crud-bad@example.com'))
        event_type = NotificationEventType.objects.get(key='device_offline')

        resp = client.patch(
            f'{EVENT_TYPES_URL}{event_type.pk}/',
            {'default_channels': ['sms']},
            format='json',
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Infrastructure emitters — helpers
# ---------------------------------------------------------------------------


def make_device(tenant, serial='S23-DEV', **extra):
    """Create an active Device for the given tenant."""
    device_type, _ = DeviceType.objects.get_or_create(
        slug='s23-emitter-dt',
        defaults={
            'name': 'S23 Emitter Device Type',
            'connection_type': DeviceType.ConnectionType.MQTT,
            'is_push': True,
            'default_offline_threshold_minutes': 60,
            'command_ack_timeout_seconds': 30,
        },
    )
    site = Site.objects.create(tenant=tenant, name=f'Site {serial}')
    return Device.objects.create(
        tenant=tenant,
        site=site,
        device_type=device_type,
        name=f'Device {serial}',
        serial_number=serial,
        status=Device.Status.ACTIVE,
        **extra,
    )


def _make_cert_pem(days):
    """Return a self-signed PEM certificate string expiring in ~`days` days.

    A 12-hour buffer is added so the whole-day count floors to exactly `days`.
    """
    from datetime import datetime, timedelta
    from datetime import timezone as dt_timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 's23-test-cert')])
    now = datetime.now(dt_timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days, hours=12))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


# ---------------------------------------------------------------------------
# mqtt_broker_connectivity_failure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMqttBrokerEmitter:
    """An unexpected MQTT disconnect notifies That Place Admins."""

    def test_disconnect_emits_event(self):
        """A non-clean disconnect emits mqtt_broker_connectivity_failure."""
        from apps.ingestion.mqtt_client import ThatPlaceMQTTClient
        admin = make_platform_admin('mqtt-a@example.com')
        ThatPlaceMQTTClient._notify_broker_disconnect('reason 7')
        assert Notification.objects.filter(
            user=admin, event_type='mqtt_broker_connectivity_failure',
        ).exists()

    def test_disconnect_cooldown_suppresses_repeat(self):
        """A second disconnect inside the cooldown window does not re-emit."""
        from apps.ingestion.mqtt_client import ThatPlaceMQTTClient
        admin = make_platform_admin('mqtt-b@example.com')
        ThatPlaceMQTTClient._notify_broker_disconnect('reason 7')
        ThatPlaceMQTTClient._notify_broker_disconnect('reason 7')
        assert Notification.objects.filter(
            user=admin,
            event_type='mqtt_broker_connectivity_failure',
            channel='in_app',
        ).count() == 1


# ---------------------------------------------------------------------------
# third_party_api_provider_failure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProviderOutageEmitter:
    """A provider-wide outage notifies That Place Admins."""

    def _provider_with_statuses(self, statuses):
        """Create a provider whose data sources have the given poll statuses."""
        from apps.integrations.models import (
            DataSource,
            DataSourceDevice,
            ThirdPartyAPIProvider,
        )
        provider = ThirdPartyAPIProvider.objects.create(
            name='OutageCo',
            slug='outageco',
            base_url='https://api.example.com',
            auth_type='api_key_header',
            auth_param_schema=[],
            discovery_endpoint={},
            detail_endpoint={},
            available_streams=[],
        )
        for i, status in enumerate(statuses):
            tenant = make_tenant(f'OutageTenant{i}')
            datasource = DataSource.objects.create(
                tenant=tenant, provider=provider, name=f'DS{i}', credentials={},
            )
            DataSourceDevice.objects.create(
                datasource=datasource,
                external_device_id=f'EXT-{i}',
                virtual_device=make_device(tenant, serial=f'outage-{i}'),
                active_stream_keys=[],
                last_poll_status=status,
            )
        return provider

    def test_provider_wide_outage_emits(self):
        """All data sources failing emits third_party_api_provider_failure."""
        from apps.integrations.tasks import _maybe_notify_provider_outage
        admin = make_platform_admin('outage-a@example.com')
        provider = self._provider_with_statuses(['error', 'auth_failure'])
        _maybe_notify_provider_outage(provider)
        assert Notification.objects.filter(
            user=admin, event_type='third_party_api_provider_failure',
        ).exists()

    def test_partial_failure_does_not_emit(self):
        """A provider with one healthy data source is not a platform outage."""
        from apps.integrations.tasks import _maybe_notify_provider_outage
        make_platform_admin('outage-b@example.com')
        provider = self._provider_with_statuses(['error', 'ok'])
        _maybe_notify_provider_outage(provider)
        assert not Notification.objects.filter(
            event_type='third_party_api_provider_failure',
        ).exists()


# ---------------------------------------------------------------------------
# certificate_expiry_warning
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCertificateExpiryEmitter:
    """The daily beat task warns on certificates nearing expiry."""

    def test_device_cert_near_expiry_emits(self):
        """A device cert 30 days from expiry emits certificate_expiry_warning."""
        from apps.ingestion.tasks import check_certificate_expiry
        admin = make_platform_admin('cert-a@example.com')
        tenant = make_tenant('CertNearT')
        make_device(tenant, serial='cert-30', mqtt_certificate=_make_cert_pem(30))

        check_certificate_expiry()

        assert Notification.objects.filter(
            user=admin, event_type='certificate_expiry_warning',
        ).exists()

    def test_cert_far_from_expiry_does_not_emit(self):
        """A device cert far from expiry produces no warning."""
        from apps.ingestion.tasks import check_certificate_expiry
        make_platform_admin('cert-b@example.com')
        tenant = make_tenant('CertFarT')
        make_device(tenant, serial='cert-90', mqtt_certificate=_make_cert_pem(90))

        check_certificate_expiry()

        assert not Notification.objects.filter(
            event_type='certificate_expiry_warning',
        ).exists()


# ---------------------------------------------------------------------------
# backend_pipeline_failure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPipelineFailureEmitter:
    """Celery task failures notify That Place Admins, deduplicated."""

    class _Sender:
        name = 'integrations.poll_datasource_devices'

    def test_task_failure_emits_event(self):
        """A failed task emits backend_pipeline_failure."""
        from apps.notifications.apps import _on_task_failure
        admin = make_platform_admin('pipe-a@example.com')
        _on_task_failure(sender=self._Sender(), exception=ValueError('boom'))
        assert Notification.objects.filter(
            user=admin, event_type='backend_pipeline_failure',
        ).exists()

    def test_notification_task_failure_is_skipped(self):
        """A failure in a notifications.* task does not emit (no feedback loop)."""
        from apps.notifications.apps import _on_task_failure

        class _NotifSender:
            name = 'notifications.emit_event'

        make_platform_admin('pipe-b@example.com')
        _on_task_failure(sender=_NotifSender(), exception=ValueError('boom'))
        assert not Notification.objects.filter(
            event_type='backend_pipeline_failure',
        ).exists()

    def test_task_failure_deduped_per_task(self):
        """Repeated failures of the same task emit only once per cooldown."""
        from apps.notifications.apps import _on_task_failure
        admin = make_platform_admin('pipe-c@example.com')
        _on_task_failure(sender=self._Sender(), exception=ValueError('a'))
        _on_task_failure(sender=self._Sender(), exception=ValueError('b'))
        assert Notification.objects.filter(
            user=admin,
            event_type='backend_pipeline_failure',
            channel='in_app',
        ).count() == 1
