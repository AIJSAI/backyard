"""Read the TLS certificate the family's browsers are actually served (S-806, T-MON-1).

Caddy provisions and renews the certificate on its own, and it does both silently. So does
a failure: if renewal stops working, the first person to find out is a grandparent looking
at a full-page browser warning on a link she was told to trust, with nobody in the house
able to explain it. Nothing in the instance measured this — the health email had a field
for the DOMAIN's expiry, which is ten months out, and none for the certificate's, which is
ninety days at most.

WORKER ONLY, exactly like domain_expiry and for the same reason (S-725, TS-CO-4): the
edge-facing web process makes no outbound connections, and a handshake inside a request
would put a network round trip behind a URL anyone can poll. The worker refreshes the
cached row; everything else reads it.

The context VERIFIES, deliberately. A certificate this check cannot verify is a certificate
a browser cannot verify, which is the outage rather than a detail of it — so a verification
failure is reported as the field's reason, not smoothed over by reading the date anyway.
"""

from __future__ import annotations

import datetime
import socket
import ssl

from django.utils import timezone

from .health import instance_domain
from .models import CertificateStatus

_HTTPS_PORT = 443
_TIMEOUT_SECONDS = 10
# OpenSSL's notAfter format, e.g. "Oct 20 20:36:34 2026 GMT". Always UTC in practice; the
# %Z is consumed and ignored, so the timezone is attached explicitly below.
_NOT_AFTER_FORMAT = "%b %d %H:%M:%S %Y %Z"


class CertificateLookupFailed(Exception):
    """The instance could not read its own certificate."""


def fetch_not_after(domain: str, *, port: int = _HTTPS_PORT) -> datetime.datetime:
    """When the certificate served for `domain` expires. Network call; worker only."""
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection((domain, port), timeout=_TIMEOUT_SECONDS) as raw,
            context.wrap_socket(raw, server_hostname=domain) as tls,
        ):
            certificate = tls.getpeercert()
    except (OSError, ssl.SSLError, ValueError) as exc:
        raise CertificateLookupFailed(f"{type(exc).__name__}: {exc}") from exc
    not_after = (certificate or {}).get("notAfter")
    if not isinstance(not_after, str):
        raise CertificateLookupFailed("the certificate carried no expiry")
    return parse_not_after(not_after)


def parse_not_after(raw: str) -> datetime.datetime:
    """OpenSSL's notAfter string as an aware datetime.

    Separate from the handshake so it can be tested against a real certificate's real
    string. A format string that has drifted would not crash anything — it would leave the
    field reading NOT MEASURED forever, which looks like a lookup that keeps failing.
    """
    try:
        parsed = datetime.datetime.strptime(raw, _NOT_AFTER_FORMAT)
    except ValueError as exc:
        raise CertificateLookupFailed(f"unparseable expiry {raw!r}") from exc
    return parsed.replace(tzinfo=datetime.UTC)


def refresh() -> CertificateStatus:
    """Refresh the cached certificate expiry for this instance's own domain.

    On failure the row keeps its LAST GOOD expiry and records the error, the way
    domain_expiry does: "expires in 40 days, last checked 5 days ago" is a more useful thing
    to tell an operator than nothing, and the staleness is visible either way.
    """
    domain = instance_domain()
    status, _ = CertificateStatus.objects.get_or_create(domain=domain)
    try:
        expires_at = fetch_not_after(domain)
    except CertificateLookupFailed as exc:
        status.error = str(exc)[:200]
        status.save(update_fields=["error"])
        return status
    status.expires_at = expires_at
    status.checked_at = timezone.now()
    status.error = ""
    status.save(update_fields=["expires_at", "checked_at", "error"])
    return status
