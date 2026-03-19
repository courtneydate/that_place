import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0002_add_token_refresh_url_to_provider'),
    ]

    operations = [
        migrations.AlterField(
            model_name='thirdpartyapiprovider',
            name='default_poll_interval_seconds',
            field=models.PositiveIntegerField(
                default=300,
                validators=[django.core.validators.MinValueValidator(30)],
                help_text='How often to poll each connected device (seconds). Minimum: 30s, default: 5 minutes (300s).',
            ),
        ),
    ]
