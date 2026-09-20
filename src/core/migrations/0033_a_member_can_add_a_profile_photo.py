"""One new table: the face a member shows instead of their initials (S-901).

ADDITIVE ONLY. Nothing on an existing table changes, nothing is backfilled, and every
member alive at deploy simply has no row — which is exactly the state that draws the
initials disc the product has always drawn. A deploy that runs this and a rollback that
does not are both correct, because no existing reader knows about it.

The two tokens are unique and defaulted from the same generator every media handle uses
(`core.models._media_token`), so a profile photo's URL is as unguessable as a
photograph's, and its small rendition's handle is not derivable from its large one
(TM-9). CASCADE from Member is the row half of the lifecycle; the FILES are purged by
`media.purge_profile_photo`, which every removal path calls, because Django has not
deleted FileField files on model delete since 1.3.
"""

import django.db.models.deletion
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_labels_a_relative_reads_ii"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfilePhoto",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "token",
                    models.CharField(default=core.models._media_token, max_length=43, unique=True),
                ),
                (
                    "thumbnail_token",
                    models.CharField(default=core.models._media_token, max_length=43, unique=True),
                ),
                ("image", models.ImageField(blank=True, upload_to="media/avatar/")),
                ("thumbnail", models.ImageField(blank=True, upload_to="media/avatar-small/")),
                ("content_type", models.CharField(max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "member",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="profile_photo",
                        to="core.member",
                    ),
                ),
            ],
        ),
    ]
