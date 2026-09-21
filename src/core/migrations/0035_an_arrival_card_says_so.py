"""Mark the arrival card as an arrival card (#208).

ADDITIVE, FORWARD-ONLY. One boolean on `core_post`, default False, so every post that
exists reads as an ordinary post and every reader that does not know about the column is
unaffected. Django drops the database default after backfilling it, so the column ends NOT
NULL with no default: running this and then serving the PREVIOUS image would refuse every
INSERT into `core_post`, joining included. A rollback un-applies this migration too, the
same as migration 0016's `via_email`.

THE BACKFILL, and exactly how an existing arrival card is identified. Not by its body:
`posting.ARRIVAL_BODY` is what `announce_arrival` writes, but its author may edit it for
fifteen minutes afterwards, so the text neither covers every arrival nor belongs only to
arrivals. It is identified by PROVENANCE instead, from the rows the join itself wrote.
`join._create_account` runs one transaction: `redeem_invite` inserts an InviteRedemption,
and the next statement inserts the card through `announce_arrival(member, invite.pod)`.
So an arrival card is a post that satisfies all four of:

  * its author is the member of an InviteRedemption (they joined from an invite);
  * its pod is that redemption's invite's pod (the household the link joined them to,
    which is the only pod `announce_arrival` is ever passed);
  * it carries no audience yards (the card is pod-scoped, never a broadcast);
  * it was written inside the same transaction as the redemption — `created_at` is
    `auto_now_add`, taken at each INSERT, so the gap is the microseconds between two
    statements. One second is the bound used here, and a member cannot write a real post
    inside it: they have not yet been redirected to the welcome, let alone the composer.

Anything outside that is left alone, which is the safe direction: an arrival card left
unmarked reads in Email Updates exactly as it did before this change, while a real post
marked by mistake would silently vanish from one.
"""

from __future__ import annotations

import datetime

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

# The window the two INSERTs of one join transaction fall in. Generous by four orders of
# magnitude against the gap it covers, and far tighter than the minutes a real first post
# would take.
_SAME_TRANSACTION = datetime.timedelta(seconds=1)


def _mark_the_cards_a_join_wrote(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    redemption_model = apps.get_model("core", "InviteRedemption")
    post_model = apps.get_model("core", "Post")
    for redemption in redemption_model.objects.select_related("invite").iterator():
        post_model.objects.filter(
            author_id=redemption.member_id,
            pod_id=redemption.invite.pod_id,
            audience_yards__isnull=True,
            created_at__gte=redemption.created_at,
            created_at__lt=redemption.created_at + _SAME_TRANSACTION,
        ).update(is_arrival=True)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_labels_a_relative_reads_iii"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="is_arrival",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(_mark_the_cards_a_join_wrote, migrations.RunPython.noop),
    ]
