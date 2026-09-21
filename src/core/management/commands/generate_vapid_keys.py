"""Print one new VAPID key pair, in the form .env wants (S-107).

    python manage.py generate_vapid_keys

Web push signs every notification with an application-server key pair (RFC 8292). The
pair identifies THIS Backyard to the push services; it is not a per-member secret and it
never touches the database.

IT PRINTS AND NOTHING ELSE. It does not write .env, it does not touch the database, and
it does not log — and each of those is deliberate rather than unfinished:

* writing .env would mean a command that edits the file the operator's secrets live in,
  on a box where the wrong path silently truncates something;
* logging it would put a private key in the container log, which is the exact defect the
  first-run setup secret already had once (settings.SETUP_HANDOVER_FILE says so at
  length): docker-compose's json-file driver writes stdout to disk, and `docker compose
  logs` replays it. `self.stdout.write` goes to the operator's terminal when they run it
  by hand, which is the documented path in docs/runbooks/self-host.md.

ROTATING THE PAIR INVALIDATES EVERY SUBSCRIPTION. A device's registration is bound to the
application-server key it was created with, so after a rotation every push is refused and
every relative has to tap Turn On Notifications again. The runbook says this beside the
command; it is said here too, because an operator reading `--help` is exactly the person
about to do it.
"""

from __future__ import annotations

import base64
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64(raw: bytes) -> str:
    """base64url with the padding stripped, which is the form every Web Push tool uses."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pair() -> tuple[str, str]:
    """A fresh P-256 pair as (public, private), base64url.

    The public half is the 65-byte uncompressed point a browser is handed as
    `applicationServerKey`; the private half is the 32-byte scalar. Built with
    `cryptography`, which is already a declared dependency and is what signs the encrypted
    backups — no new code path for key generation, and the same library the validator in
    config/push_guard.py checks the result against.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64(public), _b64(private)


class Command(BaseCommand):
    help = (
        "Print a new VAPID key pair for web push, in .env form. Writes nothing and logs "
        "nothing. Rotating the pair invalidates every existing device subscription."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        public, private = generate_pair()
        self.stdout.write("BACKYARD_VAPID_PUBLIC_KEY=" + public)
        self.stdout.write("BACKYARD_VAPID_PRIVATE_KEY=" + private)
        self.stdout.write("BACKYARD_VAPID_SUBJECT=mailto:you@example.com")
        self.stderr.write(
            "Paste these three lines into .env, set the subject to a real address, and "
            "restart web and worker. Replacing an existing pair signs every relative's "
            "device out of notifications: they turn them on again from Settings."
        )
