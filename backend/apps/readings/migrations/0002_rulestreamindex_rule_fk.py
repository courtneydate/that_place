"""Convert RuleStreamIndex.rule_id (plain int placeholder) to a proper FK.

Existing RuleStreamIndex rows are deleted first — they were placeholder entries
with no real rules to reference. The rules app is now in place so a proper FK
relationship can be established.

Ref: SPEC.md § Data Model — RuleStreamIndex
"""
import django.db.models.deletion
from django.db import migrations, models


def delete_placeholder_index_rows(apps, schema_editor):
    """Remove all RuleStreamIndex rows before converting the column type.

    All existing rows were created with placeholder integer rule_id values
    (no real Rule objects existed before Sprint 14). Deleting them here is
    safe — the index will be rebuilt by the rules app as rules are created.
    """
    RuleStreamIndex = apps.get_model('readings', 'RuleStreamIndex')
    RuleStreamIndex.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('readings', '0001_initial'),
        ('rules', '0001_initial'),
    ]

    operations = [
        # 1. Clear placeholder rows before changing the column
        migrations.RunPython(delete_placeholder_index_rows, migrations.RunPython.noop),

        # 2. Remove the old unique_together that references rule_id
        migrations.AlterUniqueTogether(
            name='rulestreamindex',
            unique_together=set(),
        ),

        # 3. Remove the old integer placeholder column
        migrations.RemoveField(
            model_name='rulestreamindex',
            name='rule_id',
        ),

        # 4. Add the proper FK column
        migrations.AddField(
            model_name='rulestreamindex',
            name='rule',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='stream_index_entries',
                to='rules.rule',
            ),
        ),

        # 5. Restore the unique constraint using the new FK column
        migrations.AlterUniqueTogether(
            name='rulestreamindex',
            unique_together={('stream', 'rule')},
        ),
    ]
