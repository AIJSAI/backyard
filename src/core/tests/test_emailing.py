"""The outbound email substrate (wave 4): links, headers, footer, boot guard.

These are the transport-independent guarantees every later email increment rides:
BASE_URL-only link minting (TS-DJ-14), control-character stripping into headers
(T-EMAIL-8), the standing footer on every plain-text body (T-EMAIL-G3), and the
refuse-to-boot rules for an unencrypted or under-configured SMTP transport
(TS-PP-9). Tests run on the locmem backend pytest-django installs.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives

from config.email_guard import validate_email_transport
from core import emailing

_SMTP = "django.core.mail.backends.smtp.EmailBackend"


# --- link minting (TS-DJ-14) ---


def test_absolute_url_mints_from_base_url_only() -> None:
    assert emailing.absolute_url("/d/some-token/") == "http://localhost:8000/d/some-token/"


@pytest.mark.parametrize("bad", ["d/token/", "https://evil.example/x", "//evil.example/x", ""])
def test_absolute_url_rejects_non_site_absolute_paths(bad: str) -> None:
    with pytest.raises(ValueError):
        emailing.absolute_url(bad)


# --- header hygiene (T-EMAIL-8) ---


def test_strip_control_removes_crlf_and_friends() -> None:
    crafted = "Nana\r\nBcc: everyone@example.com\x00\x1b"
    assert emailing.strip_control(crafted) == "NanaBcc: everyone@example.com"


def test_send_never_lets_a_crafted_subject_split_headers() -> None:
    emailing.send_family_email(
        to="one@example.com",
        subject="Hi from Nana\r\nX-Injected: yes",
        text="hello",
    )
    sent = mail.outbox[-1]
    assert "\r" not in sent.subject and "\n" not in sent.subject
    # The crafted text survives as inert subject characters, but no header of that
    # name ever materializes: the CRLF that would have split the line is gone.
    assert sent.message()["X-Injected"] is None


# --- the one send path ---


def test_send_family_email_uses_fixed_sender_and_footer() -> None:
    emailing.send_family_email(
        to="nana@example.com",
        subject="This week in the backyard",
        text="A quiet week.",
        html="<p>A quiet week.</p>",
    )
    sent = mail.outbox[-1]
    assert isinstance(sent, EmailMultiAlternatives)
    assert sent.to == ["nana@example.com"]
    assert sent.from_email == "backyard@localhost"  # the fixed identity (T-EMAIL-G3)
    assert emailing.STANDING_FOOTER in sent.body  # the standing footer, every mail
    assert sent.alternatives and sent.alternatives[0][1] == "text/html"


# --- boot guard (TS-PP-9): exercised directly, so the rule is never vacuous ---


def test_boot_guard_exempts_non_network_backends() -> None:
    validate_email_transport(
        backend="django.core.mail.backends.console.EmailBackend",
        host="",
        use_tls=False,
        use_ssl=False,
        default_from="",
    )  # must not raise: console never moves a byte off-host


def test_boot_guard_accepts_a_well_formed_smtp_transport() -> None:
    validate_email_transport(
        backend=_SMTP,
        host="smtp.example.com",
        use_tls=True,
        use_ssl=False,
        default_from="family@backyard.example",
    )


def test_boot_guard_refuses_cleartext_smtp() -> None:
    with pytest.raises(RuntimeError, match="TS-PP-9"):
        validate_email_transport(
            backend=_SMTP,
            host="smtp.example.com",
            use_tls=False,
            use_ssl=False,
            default_from="family@backyard.example",
        )


def test_boot_guard_refuses_missing_host_or_sender_and_tls_ssl_both() -> None:
    with pytest.raises(RuntimeError, match="EMAIL_HOST"):
        validate_email_transport(
            backend=_SMTP, host="", use_tls=True, use_ssl=False, default_from="a@b.c"
        )
    with pytest.raises(RuntimeError, match="DEFAULT_FROM_EMAIL"):
        validate_email_transport(
            backend=_SMTP,
            host="smtp.example.com",
            use_tls=True,
            use_ssl=False,
            default_from="",
        )
    with pytest.raises(RuntimeError, match="pick exactly one"):
        validate_email_transport(
            backend=_SMTP,
            host="smtp.example.com",
            use_tls=True,
            use_ssl=True,
            default_from="a@b.c",
        )
