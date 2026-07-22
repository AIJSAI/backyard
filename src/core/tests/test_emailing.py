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

from config.email_guard import env_flag, validate_email_transport
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
        html=f"<p>A quiet week.</p><footer>{emailing.STANDING_FOOTER}</footer>",
    )
    sent = mail.outbox[-1]
    assert isinstance(sent, EmailMultiAlternatives)
    assert sent.to == ["nana@example.com"]
    assert sent.from_email == "backyard@localhost"  # the fixed identity (T-EMAIL-G3)
    assert emailing.STANDING_FOOTER in sent.body  # the standing footer, every mail
    assert sent.alternatives and sent.alternatives[0][1] == "text/html"


@pytest.mark.parametrize("bad", ["/x\r\ny/", "/ x/", "/x y/", "/x y/", "/x\x00y/"])
def test_absolute_url_rejects_control_and_whitespace(bad: str) -> None:
    """Security review of #34 LOW: a minted URL may one day sit in a header
    position, so nothing whitespace- or control-shaped gets into one."""
    with pytest.raises(ValueError):
        emailing.absolute_url(bad)


def test_html_without_the_footer_is_refused() -> None:
    """Security review of #34 MEDIUM: clients render the HTML part instead of the
    text part, so the footer must be enforced there too, at the seam."""
    with pytest.raises(ValueError, match="standing footer"):
        emailing.send_family_email(
            to="one@example.com", subject="s", text="t", html="<p>no footer here</p>"
        )
    emailing.send_family_email(
        to="one@example.com",
        subject="s",
        text="t",
        html=f"<p>fine</p><footer>{emailing.STANDING_FOOTER}</footer>",
    )  # carrying the footer passes


def test_a_comma_smuggled_second_recipient_is_refused() -> None:
    with pytest.raises(ValueError, match="one recipient"):
        emailing.send_family_email(
            to="victim@example.com, attacker@example.com", subject="s", text="t"
        )


# --- boot guard (TS-PP-9): exercised directly, so the rule is never vacuous ---


def test_boot_guard_refuses_an_unknown_backend() -> None:
    """Security review of #34 LOW: exemption-by-default would let a future Anymail
    backend arrive outside the guard; unknown strings refuse to boot instead."""
    with pytest.raises(RuntimeError, match="Unknown EMAIL_BACKEND"):
        validate_email_transport(
            backend="anymail.backends.postmark.EmailBackend",
            host="",
            use_tls=False,
            use_ssl=False,
            default_from="a@b.c",
        )


def test_env_flag_reads_common_truthy_spellings() -> None:
    """Security review of #34 LOW: EMAIL_USE_TLS=true must mean ON."""
    assert all(env_flag(v) for v in ("1", "true", "True", "YES", "on", " true "))
    assert not any(env_flag(v) for v in ("0", "false", "off", "", "no"))


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


# --- the Anymail Resend backend (wave 4): HTTPS transport, its own validation ---

_RESEND = "anymail.backends.resend.EmailBackend"


def test_boot_guard_accepts_anymail_resend_fully_configured() -> None:
    """The Resend backend sends over HTTPS, so the cleartext/host checks do not
    apply; it needs its API key, the inbound webhook signing secret (TS-PP-8),
    and the one fixed sender identity."""
    validate_email_transport(
        backend=_RESEND,
        host="",
        use_tls=False,
        use_ssl=False,
        default_from="digests@mail.backyard.family",
        resend_api_key="re_live_key",
        resend_inbound_secret="whsec_live",
    )  # must not raise


def test_boot_guard_refuses_anymail_resend_without_api_key() -> None:
    with pytest.raises(RuntimeError, match="RESEND_API_KEY is empty"):
        validate_email_transport(
            backend=_RESEND,
            host="",
            use_tls=False,
            use_ssl=False,
            default_from="digests@mail.backyard.family",
            resend_inbound_secret="whsec_live",
        )


def test_boot_guard_refuses_anymail_resend_without_inbound_secret() -> None:
    """TS-PP-8: the inbound reply webhook is publicly mounted, so booting the
    Resend backend without its signing secret would leave a forgeable endpoint."""
    with pytest.raises(RuntimeError, match="RESEND_INBOUND_SECRET is empty"):
        validate_email_transport(
            backend=_RESEND,
            host="",
            use_tls=False,
            use_ssl=False,
            default_from="digests@mail.backyard.family",
            resend_api_key="re_live_key",
        )


def test_boot_guard_refuses_anymail_resend_without_a_sender() -> None:
    with pytest.raises(RuntimeError, match="DEFAULT_FROM_EMAIL"):
        validate_email_transport(
            backend=_RESEND,
            host="",
            use_tls=False,
            use_ssl=False,
            default_from="",
            resend_api_key="re_live_key",
            resend_inbound_secret="whsec_live",
        )
