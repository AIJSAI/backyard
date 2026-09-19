"""Choice LABELS only — the words a person reads, never a stored value.

The copy pass of 2026-09-19. Every label below renders straight at a relative through
`get_FOO_display`: the role badge and the role select on the roster, the three options in
the control that decides who sees somebody's phone number, the sends column on the email
panel, the quarantine queue's reason. A template scan cannot see any of them, which is why
`core/tests/test_one_word_per_concept.py` reads the model's choices directly.

STATE ONLY. Not one VALUE moved — `yard_admin`, `instance_admin`, `hidden`, `pod`, `yard`,
`handed_to_relay` and the rest are what the database stores and what every permission
predicate compares against, and renaming one would be a migration of live rows rather than
a copy pass. `manage.py sqlmigrate core 0031_labels_a_relative_reads` emits BEGIN and
COMMIT and nothing between them; verified before this file was committed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0030_invite_can_grant_the_side_admin_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="digestdelivery",
            name="status",
            field=models.CharField(
                choices=[
                    ("handed_to_relay", "Sent"),
                    ("rejected", "Rejected"),
                    ("dsn_quarantined", "Bounced"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="inboundquarantine",
            name="reason",
            field=models.CharField(
                choices=[
                    ("from_mismatch", "Sender address did not match the member"),
                    ("no_separator", "Reply separator not found"),
                    ("malformed", "Malformed or oversized message"),
                    ("rate_limited", "Too many replies too fast"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="address_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "Everyone")],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="anniversary_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "Everyone")],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="birthday_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "Everyone")],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="contact_email_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "Everyone")],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="phone_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "Everyone")],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="role",
            field=models.CharField(
                choices=[
                    ("member", "Member"),
                    ("pod_owner", "Group Owner"),
                    ("yard_admin", "Side Admin"),
                    ("instance_admin", "Family Admin"),
                    ("supervised", "Child Account"),
                ],
                default="member",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="pod",
            name="kind",
            field=models.CharField(
                choices=[("household", "Household"), ("adhoc", "Group")],
                default="household",
                max_length=16,
            ),
        ),
    ]
