"""Role LABELS a relative can read. State-only: this migration runs no SQL.

`choices` lives in Django's model state, not in Postgres — there is no CHECK constraint
and no enum type behind these columns — so every operation here is a no-op against the
database. It exists because Django compares the model to the migration state on every
`makemigrations`, and without it the next person to touch this app gets a spurious
"your models have changes that are not yet reflected in a migration" and has to work out
whether it is theirs.

WHAT CHANGED, and why the values did not:

  yard_admin      "Yard admin"     -> "Side admin"
  instance_admin  "Instance admin" -> "Family admin"
  pod_owner       "Pod owner"      -> "Group owner"

The 2026-09-19 walk found this product's internal nouns on the roster badge, in the role
select and in "What the roles mean" — the one screen where a relative is handed the admin
controls, and there is no screen anywhere defining a yard, an instance or a pod. The
STORED values are untouched: they are what every permission predicate in permissions.py
compares against and what every live row already holds, so renaming them would be a data
migration and a rewrite of the authorization layer to fix a copy problem.

The five `*_visibility` fields are here for the same state-only reason and are NOT part of
this change: their labels were reworded in an earlier pass without a migration, so the
drift was already sitting in the tree. Folded in rather than left behind, because a
separate empty migration for somebody else's no-op is worse than a sentence explaining it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0028_household_change_record"),
    ]

    operations = [
        migrations.AlterField(
            model_name="member",
            name="address_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "My household"),
                    ("yard", "Everyone in my family"),
                ],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="anniversary_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "My household"),
                    ("yard", "Everyone in my family"),
                ],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="birthday_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "My household"),
                    ("yard", "Everyone in my family"),
                ],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="contact_email_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "My household"),
                    ("yard", "Everyone in my family"),
                ],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="phone_visibility",
            field=models.CharField(
                choices=[
                    ("hidden", "No one"),
                    ("pod", "My household"),
                    ("yard", "Everyone in my family"),
                ],
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
                    ("pod_owner", "Group owner"),
                    ("yard_admin", "Side admin"),
                    ("instance_admin", "Family admin"),
                    ("supervised", "Child account"),
                ],
                default="member",
                max_length=16,
            ),
        ),
    ]
