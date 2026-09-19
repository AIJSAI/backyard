"""Choice LABELS only — the words a person reads, never a stored value.

The second pass of the copy walk of 2026-09-19, after the three judges read the screens:

* the widest contact-visibility choice, "Everyone", which a relative can read as the
  public web on the one control that governs their phone number, their email address and
  their home address. "All Members" names who it actually means, and stays parallel with
  "No One" and "My Household".
* the quarantine queue's four reasons, three of which were a mail server talking on a page
  a new Family Admin is told to check. "Reply separator not found" names an object that
  exists nowhere else in the product.

STATE ONLY. Not one VALUE moved — `yard`, `no_separator`, `from_mismatch`, `malformed` and
`rate_limited` are what the database stores and what every predicate compares against.
`manage.py sqlmigrate core 0032_labels_a_relative_reads_ii` emits BEGIN and COMMIT and
nothing between them; verified before this file was committed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_labels_a_relative_reads"),
    ]

    operations = [
        migrations.AlterField(
            model_name="inboundquarantine",
            name="reason",
            field=models.CharField(
                choices=[
                    ("from_mismatch", "Sent from an address that is not theirs"),
                    ("no_separator", "Could not tell the reply from the quoted email"),
                    ("malformed", "The email was damaged or too large"),
                    ("rate_limited", "Too many replies in a row"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="address_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "All Members")],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="anniversary_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "All Members")],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="birthday_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "All Members")],
                default="yard",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="contact_email_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "All Members")],
                default="hidden",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="member",
            name="phone_visibility",
            field=models.CharField(
                choices=[("hidden", "No One"), ("pod", "My Household"), ("yard", "All Members")],
                default="hidden",
                max_length=8,
            ),
        ),
    ]
