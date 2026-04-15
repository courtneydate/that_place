"""Django admin registrations for the feeds app."""
from django.contrib import admin

from .models import (
    FeedChannel,
    FeedChannelRuleIndex,
    FeedProvider,
    FeedReading,
    ReferenceDataset,
    ReferenceDatasetRow,
    TenantDatasetAssignment,
    TenantFeedSubscription,
)

admin.site.register(FeedProvider)
admin.site.register(FeedChannel)
admin.site.register(FeedReading)
admin.site.register(TenantFeedSubscription)
admin.site.register(FeedChannelRuleIndex)
admin.site.register(ReferenceDataset)
admin.site.register(ReferenceDatasetRow)
admin.site.register(TenantDatasetAssignment)
