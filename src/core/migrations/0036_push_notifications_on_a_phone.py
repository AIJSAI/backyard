"""One new table and two new booleans: a relative hears when something happens (S-107).

ADDITIVE ONLY. Nothing existing changes shape, nothing is backfilled, and an instance
that runs this and then rolls back is in exactly the state it was in before — no member
has a PushSubscription row until they tap Turn On Notifications, and no send path exists
at all unless the operator has set a VAPID key pair (config/push_guard.py).

The two booleans default TRUE, which reads backwards next to `notify_on_reply`'s False
until you see what the switch is: these apply only to a device the member has
deliberately subscribed, so the subscribe IS the opt-in, and defaulting them off would
make a member turn notifications on twice. With no subscription row they mean nothing.

`endpoint` is unique across the instance, not per member: one browser profile has one
registration, so a phone that changed hands cannot sit on two members' device lists and
deliver one relative's post under another's name. CASCADE from Member is the whole
lifecycle — removal deletes the rows with the person, and the demo wipe's receipt gets
them from the same cascade with no special case (core/demo_data.py).
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
                ("endpoint", models.URLField(max_length=500, unique=True)),
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
            },
        ),
    ]
