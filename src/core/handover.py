"""Shared credential-handover helpers for the admin surfaces that mint a one-time
link and hand it over (the elder token, S-104; the household invite, S-201).

- ``qr_svg``: an inline SVG QR of a handover URL, with no raster, script, or
  network dependency, so the printable artifact embeds directly. Callers pass a URL
  that may contain user text (the authenticator-app label is the member's own e-mail
  address); qrcode renders it as path geometry and never as characters, so nothing
  in the URL reaches the markup.
- ``fresh_intent`` / ``consume_intent``: a single-use session nonce so a browser
  refresh (a replayed POST) re-renders WITHOUT minting again. The raw token never
  goes in the session, only the nonce does, so the token still appears exactly
  once, in the POST response that mints it.
"""

from __future__ import annotations

import io
import secrets
from urllib.parse import urlsplit

import qrcode  # type: ignore[import-untyped]  # qrcode ships no stubs
import qrcode.image.svg  # type: ignore[import-untyped]
from django.http import Http404, HttpRequest, HttpResponse
from django.utils.safestring import mark_safe


def int_or_404(value: str) -> int:
    """Parse a form/query int or raise the bare 404: a non-numeric id is an unknown
    resource, not a server error. Shared by the admin surfaces (no existence oracle)."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise Http404 from exc


def apply_token_body_headers(response: HttpResponse) -> HttpResponse:
    """The TM-5 hygiene set for an admin hand-over page that carries a raw bearer token
    in its BODY (not its URL): the household invite (S-201), the elder link (S-104), the
    new-elder flow (S-213), and the resend result (S-212).

    ``no-store`` defends against a bfcache/history restore of the walked-away-from admin
    screen. ``Referrer-Policy`` is ``same-origin``, deliberately NOT ``no-referrer``:
    these pages host a same-origin POST form (create / regenerate / re-mint), and under
    ``no-referrer`` the browser sends ``Origin: null`` on that POST, which Django's CSRF
    Origin check rejects — so the hand-over form could never be submitted from a real
    browser (curl and the test client send no Origin, which is why this stayed latent).
    ``same-origin`` gives the identical cross-origin guarantee (zero third-party Referer
    or Origin) while sending the same-origin Origin the CSRF check needs. The token-in-URL
    surfaces (/t/, /d/, /media/) keep ``no-referrer``: there the token rides the URL and
    must never leak through a navigation's Referer.
    """
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def qr_svg(url: str) -> str:
    """An inline SVG QR for a handover URL. Caller wraps it in mark_safe; the
    content is qrcode's own path geometry from our CSPRNG-token URL, never text."""
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode()


def link_artifacts(link: str) -> dict[str, object]:
    """The hand-over values every mint surface shows once — the one-time link, its inline
    printable QR, and the host that link actually opens at — so a caller merges them into
    its template context. ``mark_safe`` over ``qr_svg`` output lives in exactly TWO audited
    places, here and ``core.adapters.MFAAdapter.build_totp_svg``, and both rest on the same
    property, which is about the RENDERER and not the input: qrcode's SvgPathImage emits
    only path geometry, so no character of the encoded URL reaches the markup. (This one's
    input is our CSPRNG token inside BASE_URL; the authenticator-app one embeds the
    member's own e-mail address, which is why the property has to be the renderer's.)

    ``link_host`` is read back off the minted link rather than off settings, so what the
    page states is what was actually put in the QR. It is the only feedback an admin gets
    that BACKYARD_BASE_URL is right: every link here is built from it, a wrong value mints
    a link that looks perfectly normal, and the failure lands on whoever was texted it.
    The netloc, not the bare hostname — the port is what was wrong on the design walk.
    """
    return {
        "minted_link": link,
        # The netloc minus any userinfo: the port is the part that was wrong on the design
        # walk and must show, but `https://localhost@evil.example` would otherwise print
        # a sentence that READS as localhost while the link opens somewhere else entirely.
        "link_host": urlsplit(link).netloc.rpartition("@")[2],
        "qr_svg": mark_safe(qr_svg(link)),  # noqa: S308  # nosec
    }


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
