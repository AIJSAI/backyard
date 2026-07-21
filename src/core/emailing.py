"""The outbound email substrate (wave 4, S-501 foundation).

Every email Backyard sends goes through this module, which is the enforcement
point for three transport-independent rules:

- Links are minted from the configured BASE_URL, never from a request Host header
  (TS-DJ-14): this product is email-centric, and a Host-poisoned link in a digest
  or invite is the classic Django emailed-link attack. absolute_url takes no
  request object on purpose.
- User-authored text reaches headers only stripped of control characters
  (T-EMAIL-8): a kinship name with a CRLF in it must never split a header. Bodies
  and HTML go through Django's mail library and the autoescaping template engine.
- Every plain-text body carries the standing footer (T-EMAIL-G3), so no genuine
  Backyard email ever asks for a link or password and a phish that does reads
  wrong next to every real one. The fixed sender identity is DEFAULT_FROM_EMAIL,
  validated at boot (config/email_guard.py).

The transport behind this seam is settings.EMAIL_BACKEND: console on the local
compose stack, locmem in tests, a real provider when the founder picks one.
"""

from __future__ import annotations

import unicodedata

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

STANDING_FOOTER = "Backyard will never ask for your link or password by email."


def absolute_url(path: str) -> str:
    """An absolute URL for an outbound email link, minted from BASE_URL only.

    `path` must be site-absolute (start with "/"), which keeps a crafted relative
    or protocol-relative value from escaping the configured origin. Control
    characters and whitespace are refused outright (security review of #34 LOW):
    a minted URL may one day sit in a header position (List-Unsubscribe), and this
    module's contract is that nothing user-shaped reaches one un-vetted.
    """
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("email links are minted from site-absolute paths only")
    if any(ch.isspace() or unicodedata.category(ch) == "Cc" for ch in path):
        raise ValueError("email link paths carry no whitespace or control characters")
    return f"{settings.BASE_URL}{path}"


def strip_control(text: str) -> str:
    """User-authored text with every control character removed (T-EMAIL-8).

    Applied to anything that reaches a header position (subjects, display names in
    address headers). Unicode category Cc covers CR, LF, NUL, and escape codes.
    """
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cc")


def send_family_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
) -> None:
    """Send one email to one recipient through the configured backend.

    The subject is control-stripped and single-line; the plain-text body gets the
    standing footer appended, and an HTML alternative is refused unless it already
    carries the footer (security review of #34 MEDIUM: mail clients render the
    HTML part instead of the text part, so template discipline alone would let the
    anti-phish property silently rot). One recipient per send: a comma-smuggled
    second address dies here rather than at the SMTP transport.
    """
    if "," in to:
        raise ValueError("one recipient per send; a digest is never a group email")
    if html is not None and STANDING_FOOTER not in html:
        raise ValueError("an HTML alternative must carry the standing footer (T-EMAIL-G3)")
    message = EmailMultiAlternatives(
        subject=strip_control(subject),
        body=f"{text.rstrip()}\n\n--\n{STANDING_FOOTER}\n",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    if html is not None:
        message.attach_alternative(html, "text/html")
    message.send()
