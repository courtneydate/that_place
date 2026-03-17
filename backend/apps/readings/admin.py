"""Admin registration for readings models."""
from django.contrib import admin

from .models import RuleStreamIndex, Stream, StreamReading


@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = ('key', 'device', 'data_type', 'display_enabled', 'created_at')
    list_filter = ('data_type', 'display_enabled')
    search_fields = ('key', 'label', 'device__serial_number')
    readonly_fields = ('device', 'key', 'data_type', 'created_at')


@admin.register(StreamReading)
class StreamReadingAdmin(admin.ModelAdmin):
    list_display = ('stream', 'value', 'timestamp', 'ingested_at')
    list_filter = ('stream__data_type',)
    search_fields = ('stream__key', 'stream__device__serial_number')
    readonly_fields = ('stream', 'value', 'timestamp', 'ingested_at')


@admin.register(RuleStreamIndex)
class RuleStreamIndexAdmin(admin.ModelAdmin):
    list_display = ('stream', 'rule_id')
    readonly_fields = ('stream', 'rule_id')
