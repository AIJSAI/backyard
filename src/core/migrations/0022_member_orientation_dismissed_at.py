"""S-906: the first-visit orientation, and the backfill that keeps it off existing feeds.

Adding a nullable "dismissed" column means every member alive at deploy time reads as
never-having-dismissed, so the whole family would open their feed the next morning to a
"you're in" block. Correct for a newcomer, noise for someone who has been posting for a
month. The backfill stamps everyone who already exists, so the orientation only ever
appears for people who arrive after this ships.

Reversible: the reverse leaves the stamps in place and simply drops the column, which is
what a rollback wants — re-applying must not resurrect the block for the same people.
"""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.utils import timezone


def stamp_existing_members(apps: Apps, schema_editor: BaseDatabaseSchemaEditor | None) -> None:
    """Everyone who exists now has already found their way around."""
    Member = apps.get_model("core", "Member")
    Member.objects.filter(orientation_dismissed_at__isnull=True).update(
        orientation_dismissed_at=timezone.now()
    )


def unstamp(apps: Apps, schema_editor: BaseDatabaseSchemaEditor | None) -> None:
    # Nothing to undo: the column goes with the reverse of AddField.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_comment_moderated_by_post_moderated_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="orientation_dismissed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(stamp_existing_members, unstamp),
    ]
