"""Device model signals.

Manages MQTT credential lifecycle when a Device's status changes.
Only Scout-type devices (MQTT connection, no gateway_device) receive
MQTT credentials — bridged devices communicate via their parent Scout.

Ref: SPEC.md § Feature: Device Registration & Provisioning
     security_risks.md § SR-01
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Device, DeviceType

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Device)
def handle_device_status_change(
    sender, instance: Device, created: bool, update_fields, **kwargs
) -> None:
    """Provision or revoke MQTT credentials on device status transitions.

    Provision when status becomes ACTIVE and no credentials have been set yet.
    The auth mode (password vs certificate) is read from instance.mqtt_auth_mode.

    Revoke when status becomes DEACTIVATED or REJECTED and credentials exist.

    Only applies to MQTT-type Scout devices (gateway_device is None).
    API-connected and bridged devices are silently skipped.
    """
    if instance.device_type.connection_type != DeviceType.ConnectionType.MQTT:
        return
    if instance.gateway_device_id is not None:
        return

    # Deferred import to avoid circular dependency at module load time.
    from apps.ingestion.mqtt_credentials import MQTTCredentialService

    status = instance.status
    already_provisioned = bool(instance.mqtt_password or instance.mqtt_certificate)

    if status == Device.Status.ACTIVE and not already_provisioned:
        service = MQTTCredentialService()
        result = service.provision_device(instance)

        if result is None:
            return

        if result['mode'] == 'certificate':
            Device.objects.filter(pk=instance.pk).update(
                mqtt_certificate=result['certificate_pem'],
                mqtt_private_key=result['private_key_pem'],
            )
            instance.mqtt_certificate = result['certificate_pem']
            instance.mqtt_private_key = result['private_key_pem']
        else:
            Device.objects.filter(pk=instance.pk).update(
                mqtt_password=result['password'],
            )
            instance.mqtt_password = result['password']

    elif status in (Device.Status.DEACTIVATED, Device.Status.REJECTED):
        if already_provisioned:
            service = MQTTCredentialService()
            service.revoke_device(instance)
