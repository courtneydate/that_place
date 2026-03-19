from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0003_provider_poll_interval_min_validator'),
    ]

    operations = [
        migrations.AddField(
            model_name='thirdpartyapiprovider',
            name='max_requests_per_second',
            field=models.PositiveIntegerField(
                null=True,
                blank=True,
                help_text='Provider API rate limit (requests/second). Leave blank for no rate limiting.',
            ),
        ),
    ]
