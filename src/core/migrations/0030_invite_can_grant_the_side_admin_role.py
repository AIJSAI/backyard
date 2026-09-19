"""An invite can carry the side-admin role for its first redeemer (R2-6, T-INVITE-2).

ADDITIVE AND NULLABLE, and it changes no existing row. `grants_role` defaults to NULL,
which is "this link grants membership and nothing else" — so every invite already in the
table, and every one minted by code that does not know about this column, behaves exactly
as it did before and after.

The CHECK constraint is the point of the migration rather than a decoration on it. This
column decides whether a bearer link can confer AUTHORITY, so the value it may hold is
capped in the database: NULL, or `yard_admin`. `instance_admin` is not a legal value at
any layer — the family admin reaches every side of the family, and the only route into
that role is one named person promoting another on the roster, where there is a face
behind the act. The service refuses to write anything else and the redeem path refuses to
apply anything else, so a row edited by hand at a shell still cannot escalate; this is the
layer that stops it being written in the first place.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_role_labels_a_relative_can_read"),
    ]

    operations = [
        migrations.AddField(
            model_name="invite",
            name="grants_role",
            field=models.CharField(blank=True, default=None, max_length=16, null=True),
        ),
        migrations.AddConstraint(
            model_name="invite",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("grants_role__isnull", True), ("grants_role", "yard_admin"), _connector="OR"
                ),
                name="invite_grants_only_the_side_admin_role",
            ),
        ),
    ]
