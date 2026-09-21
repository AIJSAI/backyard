"""The web-push configuration, validated at boot (the `email_guard` shape).

Web push is OFF unless the operator sets a VAPID key pair. That is the default a
self-hoster gets, and it costs them nothing: the Settings page says notifications are
not set up on this Backyard, no subscribe route accepts anything, and no send path
exists to take. Nobody has to generate a key to run a family network.

What is NOT allowed is a HALF-configured instance, and that is why this file exists at
boot rather than at send time. A public key with no private key renders a subscribe
button that mints a device row the server can never push to; a private key with no
public key renders a button with nothing to hand `PushManager.subscribe`. Either way
the relative taps Turn On Notifications, the phone says yes, and nothing ever arrives —
a silent failure on the one feature whose whole job is to break silence. The same
reasoning as `validate_email_transport`: required configuration is checked where the
process starts, not where it is used.

The SUBJECT is required whenever the pair is set, and that is not pedantry. RFC 8292
makes `sub` a mandatory JWT claim, and Apple's push service refuses a token without a
usable one — so an instance with keys and no subject works on Android and fails on
every iPhone in the family, which is the half of the audience this feature was built
for. Better to refuse at boot than to ship a feature that is broken only for the people
holding iPhones.

No key material is ever logged or echoed here: a refusal names the VARIABLE, never its
value.
"""

from __future__ import annotations

import base64
import binascii

# A P-256 public point in uncompressed form is 65 bytes (0x04 || X || Y); the private
# scalar is 32. Both are carried base64url-encoded without padding, which is the form
# `PushManager.subscribe` wants for `applicationServerKey` and the form
# `generate_vapid_keys` prints.
_PUBLIC_KEY_BYTES = 65
_PRIVATE_KEY_BYTES = 32
_UNCOMPRESSED_POINT = 0x04


class PushConfigError(RuntimeError):
    """The instance is half-configured for web push: refuse to boot rather than go quiet."""


def decode_base64url(value: str) -> bytes:
    """Decode unpadded base64url, or raise ValueError.

    Shared with the endpoint validator, which applies the same shape check to the keys a
    BROWSER hands us. One decoder, so what the operator's key must look like and what a
    client's key must look like cannot drift apart.
    """
    text = value.strip()
    if not text:
        raise ValueError("empty")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not base64url") from exc


def _refuse(message: str) -> None:
    raise PushConfigError(
        f"{message} Generate a pair with `python manage.py generate_vapid_keys`, or unset "
        "BACKYARD_VAPID_PUBLIC_KEY, BACKYARD_VAPID_PRIVATE_KEY and BACKYARD_VAPID_SUBJECT "
        "to run without notifications. See docs/runbooks/self-host.md."
    )


def validate_vapid(*, public_key: str, private_key: str, subject: str) -> bool:
    """Return whether web push is configured, refusing to boot on a half-set pair."""
    if not public_key and not private_key:
        # Off, and deliberately silent about it: this is the ordinary self-hoster.
        return False
    if not private_key:
        _refuse("BACKYARD_VAPID_PUBLIC_KEY is set but BACKYARD_VAPID_PRIVATE_KEY is not.")
    if not public_key:
        _refuse("BACKYARD_VAPID_PRIVATE_KEY is set but BACKYARD_VAPID_PUBLIC_KEY is not.")
    if not subject:
        _refuse(
            "BACKYARD_VAPID_SUBJECT is required when the VAPID keys are set. It is the "
            "mailto: address a push service contacts about this instance, and Apple's "
            "refuses a notification without one."
        )
    if not subject.startswith("mailto:") or "@" not in subject:
        _refuse(f"BACKYARD_VAPID_SUBJECT must be a mailto: address, not {subject.split(':')[0]!r}.")

    try:
        public_bytes = decode_base64url(public_key)
    except ValueError:
        _refuse("BACKYARD_VAPID_PUBLIC_KEY is not base64url.")
    else:
        if len(public_bytes) != _PUBLIC_KEY_BYTES or public_bytes[0] != _UNCOMPRESSED_POINT:
            _refuse(
                "BACKYARD_VAPID_PUBLIC_KEY is not a P-256 public key in uncompressed form "
                f"({_PUBLIC_KEY_BYTES} bytes beginning 0x04)."
            )
    try:
        private_bytes = decode_base64url(private_key)
    except ValueError:
        _refuse("BACKYARD_VAPID_PRIVATE_KEY is not base64url.")
    else:
        if len(private_bytes) != _PRIVATE_KEY_BYTES:
            _refuse(
                "BACKYARD_VAPID_PRIVATE_KEY is not a P-256 private key "
                f"({_PRIVATE_KEY_BYTES} bytes)."
            )
    return True
