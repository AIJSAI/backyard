"""One new table and two new booleans: a relative hears when something happens (S-107).

ADDITIVE, FORWARD-ONLY. Nothing existing changes shape and nothing is backfilled, so
APPLYING this is cheap on a live database: `sqlmigrate` emits two `ADD COLUMN ... DEFAULT
true NOT NULL` followed by `DROP DEFAULT`, which PostgreSQL 18 takes as a metadata-only
change (`pg_attribute.atthasmissing` is set) -- measured at 0.9 ms on a 2,000,000-row
clone, with ACCESS EXCLUSIVE held for that long and no table rewrite.

IT IS NOT ROLLBACK-SAFE BY IMAGE ALONE, and the arrival-card migration says the same
thing about its own column for the same reason. Django DROPS the database default after
adding each column, so `push_new_posts` and `push_replies` end NOT NULL with no default.
Serving the PREVIOUS image against a database that has run this refuses every INSERT into
`core_notificationpreference` -- which is `notifications.preference_for`, i.e. the first
visit any member makes to Settings > Notifications (a GET), the Save on that form, and
`notifications.notify_reply` on the worker. A rollback has to un-apply this migration
(`manage.py migrate core <the migration before this one>`) as well as the image.

The two booleans default TRUE, which reads backwards next to `notify_on_reply`'s False
until you see what the switch is: these apply only to a device the member has
deliberately subscribed, so the subscribe IS the opt-in, and defaulting them off would
make a member turn notifications on twice. With no subscription row they mean nothing.

`endpoint` is unique across the instance, not per member: one browser profile has one
registration, so a phone that changed hands cannot sit on two members' device lists and
deliver one relative's post under another's name. CASCADE from Member covers the demo
wipe, whose receipt gets these rows with no special case (core/demo_data.py). It does NOT
cover removal: `removal.remove_member` deliberately keeps the Member row (deactivated) so
authored content stays attributable, so that flow deletes these rows explicitly -- read
step 5 of `remove_member` before changing either.

The uniqueness is a NAMED UniqueConstraint rather than `unique=True`, so Postgres builds
one index instead of two: `unique=True` on a text column also creates a
`varchar_pattern_ops` index for LIKE, and nothing here ever runs a LIKE on an endpoint.
The CHECK puts the https invariant in the database as well as in the validator, for the
day a row arrives from somewhere that is not `push_views.subscribe`.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0035_an_arrival_card_says_so"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="push_new_posts",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="push_replies",
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name="PushSubscription",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("endpoint", models.URLField(max_length=500)),
                ("p256dh", models.CharField(max_length=200)),
                ("auth", models.CharField(max_length=40)),
                ("label", models.CharField(blank=True, max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("failure_count", models.PositiveSmallIntegerField(default=0)),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="push_subscriptions",
                        to="core.member",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("endpoint",), name="one_row_per_browser_registration"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("endpoint__startswith", "https://")),
                        name="a_push_endpoint_is_https",
                    ),
                ],
            },
        ),
    ]
