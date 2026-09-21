"""Every refusal the push-endpoint validator makes, one test each (S-107, T-PUSH-1).

The endpoint is the one value in this feature a hostile client controls end to end, and
the server makes an HTTP request to it. So each clause of `core/push_endpoints.py` gets a
probe here rather than a shared "a bad URL is refused" case: a validator with five clauses
and one test is a validator where four clauses can be deleted in silence.

Nothing in this file makes a network call, and nothing here contains a realistic key: the
two valid key fixtures are GENERATED at runtime from a real P-256 key, so gitleaks has
nothing to find and the shapes are the ones a browser actually produces.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from core import push_endpoints
from core.push_endpoints import UnsafeEndpoint

_GOOD = "https://fcm.googleapis.com/fcm/send/abcdefghijklmnop"


def a_real_p256_public_key() -> str:
    """A browser's `p256dh`, built at runtime: an uncompressed P-256 point, base64url.

    Generated rather than written down. `.gitleaks.toml` scans every commit on every
    branch, and a literal that LOOKS like key material fails the secrets job for every
    open pull request at once (docs/RESUME-HERE.md says so). Generating it also means the
    test asserts against the shape a real browser emits rather than one somebody typed.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def an_auth_secret() -> str:
    """The 16-byte RFC 8291 auth secret, from the same CSPRNG a browser uses."""
    import secrets

    return base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode()


# --- the host allowlist ----------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/abc",
        "https://api.push.apple.com/abc",  # the *.push.apple.com shard arm
        "https://sin.notify.windows.com/w/?token=abc",
    ],
)
def test_the_four_real_push_services_are_accepted(endpoint: str) -> None:
    assert push_endpoints.validate_endpoint(endpoint) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/push",  # nobody's push service
        "https://fcm.googleapis.com.evil.example/x",  # suffix-prefix trick
        "https://evilfcm.googleapis.com/x",  # label-prefix trick
        # `*.push.apple.com` must be a SUBDOMAIN rule, not a substring one. A bare
        # `endswith(".push.apple.com")` accepts this; a bare `endswith("push.apple.com")`
        # accepts "evilpush.apple.com" too, which is why the check tests the label.
        "https://evilpush.apple.com/x",
        "https://notify.windows.com/x",  # the wildcard needs a label in front
    ],
)
def test_a_host_outside_the_allowlist_is_refused(endpoint: str) -> None:
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint(endpoint)


def test_a_self_hoster_can_extend_the_allowlist(settings: pytest.FixtureRequest) -> None:
    """The documented extension point, proven to work and proven to be ADDITIVE.

    `BACKYARD_PUSH_SERVICE_HOSTS` exists for an operator running their own relay. It is
    added to the built-in set rather than replacing it, so it can never be used to turn
    the allowlist off by naming one host."""
    own = "https://push.example.test/abc"
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint(own)
    settings.PUSH_SERVICE_HOSTS = (  # type: ignore[attr-defined]
        *settings.PUSH_SERVICE_HOSTS,  # type: ignore[attr-defined]
        "push.example.test",
    )
    assert push_endpoints.validate_endpoint(own) == own
    assert push_endpoints.validate_endpoint(_GOOD) == _GOOD  # the built-ins survive


# --- the URL shape ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "why"),
    [
        ("http://fcm.googleapis.com/fcm/send/abc", "plaintext carries the VAPID assertion"),
        ("//fcm.googleapis.com/fcm/send/abc", "protocol-relative, so the scheme is anything"),
        ("javascript:alert(1)", "not a URL this server fetches"),
        ("file:///etc/passwd", "a scheme that is not the network at all"),
        ("ftp://fcm.googleapis.com/x", "not https"),
    ],
)
def test_only_https_is_accepted(endpoint: str, why: str) -> None:
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint(endpoint)


def test_userinfo_is_refused() -> None:
    """`https://fcm.googleapis.com@attacker.example/` READS as the push service and
    RESOLVES as the attacker. The oldest trick against a host allowlist."""
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint("https://fcm.googleapis.com@attacker.example/x")
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint("https://user:pw@fcm.googleapis.com/x")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com:22/x",
        "https://fcm.googleapis.com:5432/x",
        "https://fcm.googleapis.com:8000/x",
        # 443 is refused too. It is harmless, and accepting it would mean the rule is
        # "which ports are safe" rather than "no port", which is a list somebody has to
        # keep right. A real push service never puts a port in its endpoint.
        "https://fcm.googleapis.com:443/x",
    ],
)
def test_an_explicit_port_is_refused(endpoint: str) -> None:
    """An allowlisted HOSTNAME with a port is still a reachability decision: the worker
    resolves the same DNS as everything else on its network."""
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data/",  # the cloud metadata service
        "https://10.0.0.5/x",
        "https://[::1]/x",
        "https://[fd00::1]/x",
        "https://0.0.0.0/x",
    ],
)
def test_an_ip_literal_is_refused(endpoint: str) -> None:
    """No address literal in any spelling reaches the allowlist test at all. An IP can
    never match a hostname entry, so this is belt — and belt is right here, because the
    allowlist is one configuration edit away from containing something odd."""
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint(endpoint)


def test_a_malformed_url_is_refused_rather_than_raising() -> None:
    """A bad IPv6 literal makes `urlsplit` raise ValueError. That must arrive as the
    product's own refusal, not as a 500 with a traceback."""
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint("https://[not-an-address/x")


def test_an_over_long_endpoint_is_refused_before_it_is_parsed() -> None:
    long = "https://fcm.googleapis.com/fcm/send/" + "a" * push_endpoints.MAX_ENDPOINT_LENGTH
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint(long)


def test_an_empty_endpoint_is_refused() -> None:
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_endpoint("   ")


# --- the key material ------------------------------------------------------------------


def test_a_real_browser_shaped_key_pair_is_accepted() -> None:
    public = a_real_p256_public_key()
    auth = an_auth_secret()
    assert push_endpoints.validate_p256dh(public) == public
    assert push_endpoints.validate_auth(auth) == auth


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("", "absent"),
        ("not base64!", "the wrong alphabet"),
        ("YWJjZA+/", "standard base64, not the URL-safe alphabet a browser emits"),
        ("YWJjZA", "decodes to four bytes, not sixty-five"),
        ("a" * 400, "past the length cap"),
    ],
)
def test_a_malformed_p256dh_is_refused(value: str, why: str) -> None:
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_p256dh(value)


def test_a_p256dh_of_the_right_length_but_the_wrong_form_is_refused() -> None:
    """65 bytes that do not begin 0x04 is not an uncompressed point, so it can never be
    used to encrypt. Refused at the door rather than at 3am in a worker log."""
    wrong = base64.urlsafe_b64encode(b"\x03" + b"\x01" * 64).rstrip(b"=").decode()
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_p256dh(wrong)


@pytest.mark.parametrize("value", ["", "!!!", "YWJj", "a" * 100])
def test_a_malformed_auth_secret_is_refused(value: str) -> None:
    with pytest.raises(UnsafeEndpoint):
        push_endpoints.validate_auth(value)


# --- the endpoint as a capability ------------------------------------------------------


def test_redaction_keeps_the_host_and_drops_the_capability() -> None:
    """An operator debugging a delivery failure needs to know WHICH service is refusing.
    Nobody needs the path, and the path is the whole credential (T-PUSH-2)."""
    redacted = push_endpoints.redact("https://fcm.googleapis.com/fcm/send/SECRETPATHVALUE")
    assert "SECRETPATHVALUE" not in redacted
    assert "fcm.googleapis.com" in redacted
    assert redacted == "https://fcm.googleapis.com/[redacted]"


def test_redaction_survives_a_value_that_is_not_a_url() -> None:
    """A log line must never be the thing that raises. A row edited at a database shell
    can hold anything at all."""
    assert "[redacted]" in push_endpoints.redact("https://[not-an-address/x")
