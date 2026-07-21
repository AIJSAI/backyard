"""Per-field visibility for family dates (S-903), plus the anniversary fields.

Ordinary members default to YARD, which matches how far the birthday already
reached (the whole directory); existing supervised members are narrowed to POD in
the same migration, the T-MINOR-6 default the creation path now sets.
"""

from __future__ import annotations

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def _narrow_supervised_dates(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    member = apps.get_model("core", "Member")
    member.objects.filter(is_supervised=True).update(
        birthday_visibility="pod", anniversary_visibility="pod"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_mediaasset"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="birthday_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "People in my pods"),
                    ("yard", "People in my yards"),
                ],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="member",
            name="anniversary_month",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="member",
            name="anniversary_day",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="member",
            name="anniversary_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="member",
            name="anniversary_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "People in my pods"),
                    ("yard", "People in my yards"),
                ],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.RunPython(_narrow_supervised_dates, migrations.RunPython.noop),
    ]
