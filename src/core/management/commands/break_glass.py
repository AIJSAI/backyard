"""Break-glass admin recovery (S-805, T-AUTH-G1): a console-only reset path.

An admin who loses their second factor cannot recover through any web or email
flow, by design, because a web "recover admin" form is exactly the front door
mandatory admin 2FA closes. Instead this command, run by whoever has server
shell (the same trust anchor as the first-run setup secret), prints a
short-lived one-time reset URL for one named admin.

The token is Django's PasswordResetTokenGenerator: time-limited by
PASSWORD_RESET_TIMEOUT and one-time by construction (it hashes the user's current
password, so the moment the reset changes the password the token stops working).
No token is ever minted by a web request; this command is the only source.

"Admin" means the INSTANCE_ADMIN role (S10), the same predicate the view uses, not
the Django superuser flag — a relative promoted through the S-707 succession path
holds the role and not the flag.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.breakglass import break_glass_tokens, is_recoverable_admin

User = get_user_model()


class Command(BaseCommand):
    help = "Print a short-lived one-time admin password-reset URL to the console (S-805)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("username", help="the admin username to recover")

    def handle(self, *args: Any, **options: Any) -> None:
        username = options["username"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(
                f"No account named {username!r}. Break-glass recovers an existing instance "
                "admin; it never creates one."
            ) from exc
        # The same predicate the view resolves with (S10), so the command cannot print a
        # URL the view would 404. Keyed on the INSTANCE_ADMIN role rather than
        # `is_superuser`: `assign_role` promotes a relative to instance admin by writing
        # `Member.role` alone, so the second admin the succession path exists to create was
        # refused here while being, by every rule in the product, an instance admin.
        if not is_recoverable_admin(user):
            raise CommandError(
                f"{username!r} is not an instance admin. Break-glass recovers an existing "
                "instance admin; it never creates one and never promotes anybody."
            )

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = break_glass_tokens.make_token(user)
        path = f"/break-glass/{uid}/{token}/"

        self.stdout.write(
            "\n".join(
                [
                    "",
                    f"Break-glass reset for admin '{username}'.",
                    "Open this once, soon (it expires), on the instance:",
                    f"    {path}",
                    "",
                    "It stops working the moment the password is reset. It resets the password "
                    "only, not your second factor: sign in with a recovery code (or re-enroll) "
                    "after. If you have no second admin, add one after recovering (deploy docs).",
                    "",
                ]
            )
        )
