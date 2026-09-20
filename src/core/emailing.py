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
from email.utils import formataddr
from urllib.parse import urlsplit, urlunsplit

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


def rebase_url(url: str) -> str:
    """One allauth-built absolute URL, re-minted on the configured BASE_URL (TS-DJ-14).

    django-allauth builds the address confirmation and the password reset link with
    `request.build_absolute_uri()`, so their origin is whatever Host header the request
    carried; every other link in this product comes from BASE_URL and takes no request at
    all. A credential link is the last place to keep two answers to "which site is this":
    an operator who widens DJANGO_ALLOWED_HOSTS (`*` boots today) behind an edge that
    passes the Host through would mail a relative a Backyard-branded button pointing
    wherever the requester asked, and the HTML part draws it as the one thing to press.

    Only the ORIGIN is replaced. Path, query and fragment carry the capability and are
    untouched, and `absolute_url`'s refusals still apply, so a path this module would not
    mint fails the send rather than becoming a link nobody vetted.
    """
    parts = urlsplit(url)
    return absolute_url(urlunsplit(("", "", parts.path or "/", parts.query, parts.fragment)))


def reply_domain() -> str:
    """The domain reply capabilities live under: the sending identity's own
    domain (T-EMAIL-G3's one fixed sender), so a reply address can never point
    anywhere the family's mail does not already go."""
    return settings.DEFAULT_FROM_EMAIL.rsplit("@", 1)[1]


# The zero-width joiner and non-joiner. They are FORMAT characters like the bidi
# overrides below, and they are kept anyway, because they are how an emoji family
# (👨‍👩‍👧) and several writing systems are spelled. Dropping every non-printable without
# this exception turns one emoji into three in a product whose whole content is family
# messages — a visible regression paid for no security.
_JOINERS = "‍‌"
# Newline and tab are the two control characters that ARE ordinary writing, so a body
# keeps them and a single-line label does not.
_BODY_KEPT = f"{_JOINERS}\n\t"


def from_address() -> str:
    """The From header every message this product sends carries.

    `"Backyard" <backyard@example.com>`, built here and nowhere else. Two callers: the
    send seam below, and core.adapters.AccountAdapter.get_from_email, which is how
    allauth's own mail (the address confirmation, the password reset) picks up the same
    identity — those bypass send_family_email entirely, and before this they were the two
    messages that arrived unnamed.

    The name is control-stripped for the same reason a subject is: it reaches a header
    position, and a newline in a header position is header injection. `formataddr` quotes
    and, where needed, RFC 2047-encodes the rest, so a name with a comma or an accent in
    it cannot break the address apart.
    """
    return formataddr((strip_control(settings.MAIL_FROM_NAME), settings.DEFAULT_FROM_EMAIL))


def strip_control(text: str) -> str:
    """User-authored text as a single-line label, with nothing invisible left in it
    (T-EMAIL-8).

    Applied to anything that reaches a header position (subjects, display names in
    address headers) and to every stored display and kinship name (core.signals).

    Tested with `str.isprintable()` rather than `unicodedata.category(ch) != "Cc"`,
    which is what this used to do. Category Cc is CR, LF, NUL and the escape codes —
    it does NOT include the bidi overrides and isolates (U+202A..U+202E, U+2066..U+2069),
    which are category Cf. Those are the ones that matter most here: `email/digest.txt`
    is a plain-text template and therefore renders with autoescape OFF, so a name
    carrying U+202E reversed the line it sat in for every recipient of the digest, and
    no amount of HTML escaping was ever going to touch it.
    """
    return "".join(ch for ch in text if ch in _JOINERS or ch.isprintable())


def strip_control_keep_breaks(text: str) -> str:
    """The same rule for BODY text, which keeps its newlines and tabs.

    This is the rule the reply-by-email path has applied since S-502; `inbound` now
    calls it rather than carrying a second copy. One implementation, because two
    answers to "which characters are safe to store" is how one of them comes to be
    wrong — and the wrong one is always the path nobody re-read.
    """
    return "".join(ch for ch in text if ch in _BODY_KEPT or ch.isprintable())


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
        from_email=from_address(),
        to=[to],
    )
    if html is not None:
        message.attach_alternative(html, "text/html")
    message.send()
