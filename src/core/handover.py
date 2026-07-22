"""Shared credential-handover helpers for the admin surfaces that mint a one-time
link and hand it over (the elder token, S-104; the household invite, S-201).

- ``qr_svg``: an inline SVG QR of a handover URL, with no raster, script, or
  network dependency, so the printable artifact embeds directly. The only input is
  our own CSPRNG token inside the configured BASE_URL, never user text, so the SVG
  path geometry carries nothing to escape.
- ``fresh_intent`` / ``consume_intent``: a single-use session nonce so a browser
  refresh (a replayed POST) re-renders WITHOUT minting again. The raw token never
  goes in the session, only the nonce does, so the token still appears exactly
  once, in the POST response that mints it.
"""

from __future__ import annotations

import io
import secrets

import qrcode  # type: ignore[import-untyped]  # qrcode ships no stubs
import qrcode.image.svg  # type: ignore[import-untyped]
from django.http import HttpRequest


def qr_svg(url: str) -> str:
    """An inline SVG QR for a handover URL. Caller wraps it in mark_safe; the
    content is qrcode's own path geometry from our CSPRNG-token URL, never text."""
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode()


def fresh_intent(request: HttpRequest, key: str) -> str:
    """A new single-use nonce for the NEXT mint action, stored under ``key`` in the
    session. Set it AFTER any consume so it never clobbers the one just submitted."""
    intent = secrets.token_urlsafe(16)
    request.session[key] = intent
    return intent


def consume_intent(request: HttpRequest, key: str, submitted: str | None) -> bool:
    """True iff ``submitted`` matches the stored nonce; deletes it so a refreshed
    POST replays a spent nonce and does not mint again (single use)."""
    expected = request.session.get(key)
    if not submitted or submitted != expected:
        return False
    del request.session[key]
    return True
