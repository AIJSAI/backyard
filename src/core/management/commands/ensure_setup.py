"""Print the first-run setup secret when no admin exists yet (threat model TM-8).

Run by the container entrypoint on every boot. If an admin already exists it
deletes any stale token and does nothing. Otherwise it mints a fresh secret,
stores only its hash, and prints the plaintext to the server console. The secret
rotates on each boot until it is consumed, so a stale value from an old log line
never works.
"""

from __future__ import annotations

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand

from core.models import SetupToken

User = get_user_model()


class Command(BaseCommand):
    help = "Print the first-run setup secret if no admin exists yet."

    def handle(self, *args: Any, **options: Any) -> None:
        if User.objects.filter(is_superuser=True).exists():
            SetupToken.objects.all().delete()
            self.stdout.write("An admin already exists; the setup wizard is closed.")
            return

        secret = secrets.token_urlsafe(32)
        token = SetupToken.objects.order_by("id").first()
        if token is None:
            SetupToken.objects.create(token_hash=make_password(secret))
        else:
            token.token_hash = make_password(secret)
            token.save(update_fields=["token_hash"])

        line = "=" * 68
        self.stdout.write("")
        self.stdout.write(line)
        self.stdout.write("  BACKYARD FIRST-RUN SETUP")
        self.stdout.write("  Open /setup/ and paste this one-time secret:")
        self.stdout.write(f"    {secret}")
        self.stdout.write(line)
        self.stdout.write("")
