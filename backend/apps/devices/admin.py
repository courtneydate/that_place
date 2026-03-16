"""Devices admin registration."""
from django.contrib import admin

from .models import Device, DeviceType, Site

admin.site.register(Site)
admin.site.register(DeviceType)
admin.site.register(Device)
