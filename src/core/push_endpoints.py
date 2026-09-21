"""What a push endpoint is allowed to be, and how it appears in a log (S-107).

THIS IS THE MAIN RISK IN THE WHOLE FEATURE. A Web Push subscription endpoint is a URL
the BROWSER produces and the client POSTs to us, and the server then makes an HTTP
request to it. Left unchecked that is a server-side request forgery primitive standing
behind a family member's login: a crafted `endpoint` would have the app fetch the
container's own metadata service, the Postgres port on the private network, the bundled
Caddy on the edge network, or any internal address a relative's compromised phone can
name (threat model T-PUSH-1). Unlike the link-preview fetcher, which is already
IP-pinning and global-address-rejecting, this request carries a body we generated and a
credential (the VAPID JWT) in its headers.

So the rule here is an ALLOWLIST OF HOSTS, not a denylist of addresses. The set of push
services a browser can mint an endpoint on is small, known, and named in
`settings.PUSH_SERVICE_HOSTS` with the note on how a self-hoster extends it. Everything
else is refused, which means a new internal address, a new cloud metadata endpoint or a
DNS-rebound name is refused without anybody having to think of it first.

Checked TWICE, and both are load-bearing. At SUBSCRIBE time, so a bad row never reaches
the database and the member is told. At SEND time, on the outbound session itself
(`push.py`), because a row can outlive the allowlist it was written under: an operator
who removes a host from BACKYARD_PUSH_SERVICE_HOSTS, or a row edited at a database
shell, must not become an outbound request. The second check sits on
`requests.Session.request`, so it sees the URL that is actually about to be fetched.

THE ENDPOINT IS A CAPABILITY. Whoever holds it can send a notification to that device
until the browser rotates it, which is exactly the property `config/log_redaction.py`
protects our own token-bearing URLs for (TS-EDGE-LOG). It is never logged whole: every
message in this feature passes it through `redact` first, which keeps the host (the one
part an operator debugging a delivery failure needs) and drops the path.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

from config.push_guard import decode_base64url

# Caps, applied before anything is parsed. A push endpoint from the four real services is
# 100-250 characters; the keys are fixed-length by construction (a P-256 point and a
# 16-byte secret). These are bounds on what a hostile client can make the server hold and
# echo, not a description of a legitimate value.
MAX_ENDPOINT_LENGTH = 500
MAX_P256DH_LENGTH = 200
MAX_AUTH_LENGTH = 40
# RFC 8291: the client's key is a P-256 point in uncompressed form, and the auth secret is
# 16 bytes. Checked as SHAPE, so a value that cannot possibly encrypt is refused at the
# door rather than at 3am in a worker log.
_P256DH_BYTES = 65
_AUTH_BYTES = 16
_UNCOMPRESSED_POINT = 0x04

# Base64url with no padding and nothing else. `+` and `/` are the standard alphabet, not
# the URL-safe one a browser emits, and a value carrying them is either the wrong encoding
# or somebody probing.
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+=*$")


class UnsafeEndpoint(ValueError):
    """The client-supplied subscription is not something this server will POST to."""


def _hostname_allowed(hostname: str) -> bool:
    """Exact match, or a `*.suffix` entry matching one or more labels in front of it."""
    for pattern in settings.PUSH_SERVICE_HOSTS:
        if pattern.startswith("*."):
            suffix = pattern[1:]  # ".push.apple.com"
            # `endswith` alone would accept "evilpush.apple.com" for "*.push.apple.com"
            # because the dot is part of the suffix -- it is not, and the label test below
            # is what makes it a subdomain rule rather than a substring one.
            if hostname.endswith(suffix) and hostname[: -len(suffix)]:
                return True
        elif hostname == pattern:
            return True
    return False


def validate_endpoint(raw: str) -> str:
    """Return the endpoint if this server may POST to it, else raise UnsafeEndpoint.

    Every clause is a refusal somebody could otherwise reach:

    * length, before parsing, so a megabyte of URL is not parsed at all;
    * https only -- a plaintext endpoint would carry the VAPID assertion in the clear;
    * no userinfo (`https://fcm.googleapis.com@attacker.example/`), which is the oldest
      way to make a URL read as one host and resolve as another;
    * no explicit port, so an allowlisted hostname cannot be pointed at :22 or :5432 --
      and note this is a real reachability difference, not cosmetics, because the worker
      resolves the same DNS name as everything else on its network;
    * no IP literal in any form, including the IPv6 bracket form and the decimal and
      hexadecimal spellings `ipaddress` normalises;
    * and the host allowlist, which is the control the rest defends.
    """
    endpoint = raw.strip()
    if not endpoint:
        raise UnsafeEndpoint("The subscription is missing its endpoint.")
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise UnsafeEndpoint("That subscription endpoint is too long.")
    try:
        parts = urlsplit(endpoint)
    except ValueError as exc:  # a malformed IPv6 literal raises here rather than parsing
        raise UnsafeEndpoint("That subscription endpoint is not a URL.") from exc
    if parts.scheme != "https":
        raise UnsafeEndpoint("A subscription endpoint must be https.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise UnsafeEndpoint("A subscription endpoint must not carry a user name.")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeEndpoint("That subscription endpoint has no valid port.") from exc
    if port is not None:
        raise UnsafeEndpoint("A subscription endpoint must not name a port.")
    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise UnsafeEndpoint("That subscription endpoint names no host.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass  # a name, which is the only thing that can match the allowlist below
    else:
        raise UnsafeEndpoint("A subscription endpoint must name a push service, not an address.")
    if not _hostname_allowed(hostname):
        raise UnsafeEndpoint("That is not a push service this Backyard sends to.")
    # NORMALISED, never returned as typed. Scheme and host are case-INSENSITIVE (RFC 3986)
    # and the unique index is not, so returning the raw string lets
    # `https://FCM.googleapis.com/x` and `https://fcm.googleapis.com/x` be two rows for one
    # phone -- which is precisely the "a device that changed hands sits on two members'
    # lists" case the unique constraint exists to make impossible. The PATH is left alone:
    # it is case-sensitive and it IS the registration's identity.
    return urlunsplit(("https", hostname, parts.path, parts.query, parts.fragment))


def _validate_key(raw: str, *, what: str, max_length: int, expected_bytes: int) -> str:
    value = raw.strip()
    if not value:
        raise UnsafeEndpoint(f"The subscription is missing its {what} key.")
    if len(value) > max_length or not _BASE64URL.match(value):
        raise UnsafeEndpoint(f"The subscription's {what} key is not base64url.")
    try:
        decoded = decode_base64url(value)
    except ValueError as exc:
        raise UnsafeEndpoint(f"The subscription's {what} key is not base64url.") from exc
    if len(decoded) != expected_bytes:
        raise UnsafeEndpoint(f"The subscription's {what} key is the wrong length.")
    return value


def validate_p256dh(raw: str) -> str:
    """The device's public key: a P-256 point in uncompressed form (RFC 8291)."""
    value = _validate_key(
        raw, what="p256dh", max_length=MAX_P256DH_LENGTH, expected_bytes=_P256DH_BYTES
    )
    if decode_base64url(value)[0] != _UNCOMPRESSED_POINT:
        raise UnsafeEndpoint("The subscription's p256dh key is not an uncompressed point.")
    return value


def validate_auth(raw: str) -> str:
    """The device's 16-byte authentication secret (RFC 8291)."""
    return _validate_key(raw, what="auth", max_length=MAX_AUTH_LENGTH, expected_bytes=_AUTH_BYTES)


def redact(endpoint: str) -> str:
    """An endpoint as a log line may carry it: the host, and `[redacted]` for the rest.

    The same trade `config/log_redaction.py` makes for our own capability URLs -- the
    operator keeps the one fact that helps ("Apple is refusing these") and the log never
    holds a working send capability for a relative's phone. Deliberately not a hash: a
    hash would be a stable identifier for one family member's device across every log
    line, which is a worse artefact to keep than nothing.
    """
    try:
        host = urlsplit(endpoint).hostname or "?"
    except ValueError:
        return "[redacted]"
    return f"https://{host}/[redacted]"
