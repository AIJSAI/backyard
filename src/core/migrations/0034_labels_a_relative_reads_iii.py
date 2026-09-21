"""Choice LABELS only — the words a person reads, never a stored value.

One label: the role a relative reads as "Side Admin" is "Admin" (2026-09-20). One of the
two people being handed these controls belongs to a household on both sides of the family,
so her reach already covers both and "Side Admin" was the wrong word for her; the other
manages one side. "Admin" is honest for both, because an admin's reach is the ordinary
members they can see. It also stops the roster naming a second side to a relative who has
no screen showing one.

STATE ONLY. `yard_admin` is untouched — it is what the database stores, what every
permission predicate compares against, and what the `invite_grants_only_the_side_admin_role`
CHECK constraint holds an invite to. `manage.py sqlmigrate core
0034_labels_a_relative_reads_iii` emits BEGIN, a `-- (no-op)` comment and COMMIT, with no
statement of any kind between them — the same output 0031 and 0032 produce, and verified
before this file was committed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_a_member_can_add_a_profile_photo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="member",
            name="role",
            field=models.CharField(
                choices=[
                    ("member", "Member"),
                    ("pod_owner", "Group Owner"),
                    ("yard_admin", "Admin"),
                    ("instance_admin", "Family Admin"),
                    ("supervised", "Child Account"),
                ],
                default="member",
                max_length=16,
            ),
        ),
    ]
