"""Look up the instance domain's expiry over RDAP (S-806, threat row T-OP-G4).

T-OP-G4: *"The instance domain lapses and a squatter re-registers it, harvesting elder
tokens from every bookmark and QR and standing up a phishing surface plus the family's
MX."* A bearer URL cannot be bound to the new-versus-old host, so renewal discipline plus
detection is the entire control, and this is the detection half.

WORKER ONLY. This is the second outbound fetch in the product after the link-preview
fetcher, and it lives under the same rule (S-725, TS-CO-4): the edge process makes no
outbound connections. Unlike the link fetcher the URL here is NOT user-shaped — it is
derived from the instance's own configured BASE_URL and nothing else — so there is no SSRF
surface to defend, but it still runs off the edge because a hanging registry must not hold
a web worker.

Every failure degrades the FIELD, never the email: an operator hearing nothing at all from
their instance is exactly the T-MON-1 condition, so a registry outage must not silence the
one message that would tell them the disk is full.
"""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request

from django.utils import timezone

from .health import instance_domain
from .models import DomainStatus

# rdap.org is a redirector to the authoritative registry for the TLD. Same source the
# project already cites as evidence of the domain's registration in PATH-TO-100.
_RDAP = "https://rdap.org/domain/{domain}"
_TIMEOUT_SECONDS = 15
_MAX_BYTES = 512 * 1024  # a domain record is a few KB; refuse to buffer a hostile stream
_UA = "backyard-health/1.0 (self-hosted family instance)"


class DomainLookupFailed(Exception):
    """The registry did not give us a usable expiry."""


def _parse_expiry(payload: dict[str, object]) -> datetime.datetime:
    """Pull the expiry out of an RDAP response.

    RDAP nests it in `events` as an `eventAction` of "expiration", which is the field the
    registries agree on; the various `*Date` top-level keys are registrar-specific and are
    deliberately not trusted here.
    """
    events = payload.get("events")
    if not isinstance(events, list):
        raise DomainLookupFailed("no events in the RDAP response")
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("eventAction", "")).lower() != "expiration":
            continue
        raw = event.get("eventDate")
        if not isinstance(raw, str):
            continue
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainLookupFailed(f"unparseable expiry {raw!r}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        return parsed
    raise DomainLookupFailed("no expiration event in the RDAP response")


def fetch_expiry(domain: str) -> datetime.datetime:
    """The domain's expiry, or raise DomainLookupFailed. Network call; worker only."""
    request = urllib.request.Request(  # noqa: S310 - fixed https scheme, no user input
        _RDAP.format(domain=domain),
        headers={"Accept": "application/rdap+json", "User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            raw = response.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DomainLookupFailed(f"registry unreachable: {exc}") from exc
    if len(raw) > _MAX_BYTES:
        raise DomainLookupFailed("RDAP response too large")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise DomainLookupFailed("RDAP response was not JSON") from exc
    if not isinstance(payload, dict):
        raise DomainLookupFailed("RDAP response was not an object")
    return _parse_expiry(payload)


def refresh() -> DomainStatus:
    """Refresh the cached expiry for this instance's own domain.

    On failure the row keeps its LAST GOOD expiry and records the error, so the health
    email can say "expires in 200 days, last checked 20 days ago" rather than throwing away
    a true answer because today's lookup timed out.
    """
    domain = instance_domain()
    status, _ = DomainStatus.objects.get_or_create(domain=domain)
    try:
        expires_at = fetch_expiry(domain)
    except DomainLookupFailed as exc:
        status.error = str(exc)[:200]
        status.save(update_fields=["error"])
        return status
    status.expires_at = expires_at
    status.checked_at = timezone.now()
    status.error = ""
    status.save(update_fields=["expires_at", "checked_at", "error"])
    return status
