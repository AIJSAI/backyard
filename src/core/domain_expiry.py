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


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to https.

    rdap.org is a REDIRECTOR: it answers with a 302 to whichever registry serves the TLD
    (for .family, rdap.identitydigital.services). So the second URL in this exchange is
    chosen by a third party, not by us — which is exactly the case bandit's B310 warns
    about. Python's default handler already refuses `file:`, but it permits `ftp:`, and a
    redirect we follow to a scheme we never intended is a real hole rather than a
    theoretical one.

    Restricting it here makes the property true by CONSTRUCTION instead of true by
    argument in a comment, which is the difference between a control and a nosec.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError(f"refusing a redirect to a non-HTTPS scheme: {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def _build_opener() -> urllib.request.OpenerDirector:
    """An opener that can speak HTTPS and nothing else.

    Built from a bare OpenerDirector rather than `build_opener`, which was the first
    attempt: `build_opener` ADDS the defaults on top of whatever you hand it, so that
    opener still carried FileHandler, FTPHandler, HTTPHandler and DataHandler. The comment
    claiming "no extra transports" was simply false, and the test asserting it is what
    found that out.

    Only these four: HTTPS, the https-only redirect policy, and the two error handlers
    redirect processing needs. No proxy handler either — an opener that honoured http_proxy
    would route this lookup through whatever the environment said.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPSHandler(),
        _HttpsOnlyRedirects(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
    ):
        opener.add_handler(handler)
    return opener


_OPENER = _build_opener()


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
    url = _RDAP.format(domain=domain)
    if not url.startswith("https://"):  # pragma: no cover - _RDAP is a literal
        raise DomainLookupFailed("the RDAP endpoint must be https")
    request = urllib.request.Request(  # noqa: S310 - https literal, opener is https-only
        url, headers={"Accept": "application/rdap+json", "User-Agent": _UA}
    )
    try:
        # _OPENER, not urlopen: it installs no proxy or unknown-scheme handler and refuses
        # a redirect to anything but https (see _HttpsOnlyRedirects). bandit's B310 is about
        # exactly this risk and the restriction above is the answer to it.
        with _OPENER.open(request, timeout=_TIMEOUT_SECONDS) as response:
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
