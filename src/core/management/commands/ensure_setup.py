"""Hand over the first-run setup secret when no admin exists yet (threat model TM-8).

Run by the container entrypoint on every boot. If an admin already exists it deletes any
stale token and the hand-over file, and does nothing else. Otherwise it mints a fresh
secret, stores only its hash, and writes the plaintext to a 0600 file on the data volume.
The secret rotates on each boot until it is consumed, so a stale value never works.

IT IS NOT PRINTED, and that is the change (G10). It used to go to stdout under a banner,
and `docker-compose.yml` sets the json-file logging driver — so every boot before the
first admin exists wrote a live instance-takeover credential into a file on disk that
`docker compose logs` replays to anyone who can run it, and that log rotation keeps for
three files of 10 MB. The window is bounded (the token dies when an admin is created) but
bounded is not the same as absent, and the Docker log is the one place operators are
trained to paste from.

What is printed is the PATH. A self-hoster following the README runs one documented
command to read it; the file is removed the moment setup completes, and again on the next
boot after that.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from core.models import SetupToken

User = get_user_model()


def handover_path() -> Path:
    """Where the plaintext secret is handed over. One reader, so the command that writes
    it and the view that deletes it cannot disagree about the location."""
    return Path(settings.SETUP_HANDOVER_FILE)


def write_handover(secret: str) -> Path:
    """Write the secret to a file only the container's own user can read.

    Unlinked first, then created with `O_EXCL` and mode 0600: `O_CREAT` IGNORES the mode
    argument for a file that already exists, so writing over yesterday's file would have
    kept yesterday's permissions — and on a volume restored from a backup or copied with a
    loose umask, those can be world-readable. Creating it fresh makes the mode a fact
    rather than a hope.
    """
    path = handover_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        handle.write(f"{secret}\n")
    return path


def clear_handover() -> None:
    """Remove the hand-over file. Called when setup completes and on every later boot.

    Never raises: this runs on the success path of the first-run wizard, and a family
    whose instance refused to finish setting up because a file could not be deleted would
    be a worse outcome than the file lingering until the next boot clears it.
    """
    try:
        handover_path().unlink(missing_ok=True)
    except OSError:  # pragma: no cover - a read-only volume, which nothing else survives
        pass


class Command(BaseCommand):
    help = "Hand over the first-run setup secret if no admin exists yet."

    def handle(self, *args: Any, **options: Any) -> None:
        if User.objects.filter(is_superuser=True).exists():
            SetupToken.objects.all().delete()
            clear_handover()
            self.stdout.write("An admin already exists; the setup wizard is closed.")
            return

        secret = secrets.token_urlsafe(32)
        token = SetupToken.objects.order_by("id").first()
        if token is None:
            SetupToken.objects.create(token_hash=make_password(secret))
        else:
            token.token_hash = make_password(secret)
            token.save(update_fields=["token_hash"])

        try:
            path = write_handover(secret)
        except OSError as exc:
            # Loud, and a refusal rather than a fallback to printing it: falling back
            # would quietly restore the exact behaviour this change removes, on the one
            # instance where something is already wrong.
            raise CommandError(
                f"Could not write the first-run setup secret to {handover_path()}: {exc}. "
                "That path must be on a writable volume (it is /data by default, the same "
                "volume the secret key lives on); set SETUP_HANDOVER_FILE to move it."
            ) from exc

        line = "=" * 68
        self.stdout.write("")
        self.stdout.write(line)
        self.stdout.write("  BACKYARD FIRST-RUN SETUP")
        self.stdout.write("  Open /setup/ and paste the one-time secret kept in this file:")
        self.stdout.write(f"    {path}")
        self.stdout.write("  Read it with:  make setup-secret")
        self.stdout.write("  It is deleted as soon as the first admin exists.")
        self.stdout.write(line)
        self.stdout.write("")
