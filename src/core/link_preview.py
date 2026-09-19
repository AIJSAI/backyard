"""SSRF-hardened link-preview fetch and parse (S-301, threat model TS-PP-5/TS-PP-6).

A member can paste a URL and get a title-and-description card, but a server-side
fetch of a member-supplied URL is an SSRF primitive, so this module is the "its own
review" ADR-002 flagged. The controls, straight from TS-PP-5/6:

- Only http/https, only ports 80/443, no userinfo in the URL.
- Resolve the hostname once; reject if ANY resolved address is not globally
  routable (private, loopback, link-local, reserved, CGNAT, multicast, unspecified,
  or an IPv4-mapped IPv6 form of any of those), then connect to that PINNED IP, so a
  later re-resolve cannot rebind to an internal address between the check and the
  connect. Resolving-then-checking also normalizes decimal and octal IP literals,
  which getaddrinfo turns into the real address before the range check runs.
- Do not follow redirects automatically; re-run the full validation on each hop,
  capped to a few hops, because a public URL can 302 to http://169.254.169.254.
- Cap the response time and size; require a text/html content type.
- Parse with the tolerant stdlib HTML parser, which does no XML entity or DTD
  expansion (no billion-laughs), extracting only a fixed, length-capped allowlist
  of meta tags.

The og:image is RE-HOSTED, never hotlinked (S-301, TS-PP-6): hotlinking a remote image
would beacon every viewer's IP and load time to the target, so the image is re-fetched
through this same SSRF-hardened path, re-encoded through the media store (which strips
its metadata and defuses any polyglot), and served only through the access-checked media
view. A card with no fetchable/decodable image degrades to title + description + domain.

No third-party HTTP client or HTML parser is added: the stdlib gives the redirect
and IP-pinning control these controls require and keeps the supply chain small.

The address half of that gate now lives in `core.outbound_addresses` and is SHARED with
the domain-expiry lookup (S18), which was the other outbound fetch in the product and had
a scheme check and nothing else — while `rdap.org` is a redirector, so its hop target is
third-party-chosen exactly like a member's pasted URL. One validator, two callers, each
translating the one failure shape into its own vocabulary at its own boundary.
"""

from __future__ import annotations

import http.client
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import outbound_addresses

if TYPE_CHECKING:
    from .models import LinkPreview, Post

_TIMEOUT = 3.0  # seconds, per connect and per recv
_TOTAL_BUDGET = 8.0  # seconds, whole fetch across all hops; the per-recv timeout
# resets on every chunk, so a slow trickle needs a wall-clock ceiling too (HIGH-3)
_MAX_BYTES = 512 * 1024  # only the head matters; cap the whole read anyway
# The re-hosted preview image (S-301) can be larger than a document head, but is still
# bounded so a hostile server cannot stream an unbounded body into the web tier; Pillow's
# decompression-bomb limit (media._MAX_PIXELS) is the second, decode-time ceiling.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443}
_TITLE_MAX = 300
_DESC_MAX = 600
# The LinkPreview.url / image_url columns are URLField(max_length=2000). A post body
# can hold a URL longer than that, and Model.objects.create does not truncate, so an
# over-long URL would raise a DataError and 500 the compose POST. Guard it here: a
# pathological URL simply gets no card.
_MAX_URL_LEN = 2000
_USER_AGENT = "BackyardLinkPreview/1.0 (+self-hosted family network)"

# Tracking parameters stripped from stored URLs (S-301). Prefix match on "utm_"
# plus a small set of well-known click identifiers.
_TRACKING_EXACT = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "gclsrc",
        "msclkid",
        "mc_eid",
        "mc_cid",
        "igshid",
        "vero_id",
        "yclid",
    }
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class PreviewUnavailable(Exception):
    """Any reason a preview could not be produced. Callers treat it as no card."""


@dataclass(frozen=True)
class Preview:
    url: str
    title: str
    description: str
    image_url: str  # captured but NOT rendered until wave 3 re-hosting (TS-PP-6)


def first_url_in(text: str) -> str | None:
    """The first http(s) URL in a post body, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def strip_tracking_params(url: str) -> str:
    """Remove utm_* and well-known click-id parameters from a URL (S-301), preserving
    order and every other parameter. Malformed URLs are returned unchanged."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = []
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0]
        low = key.lower()
        if low.startswith("utm_") or low in _TRACKING_EXACT:
            continue
        kept.append(pair)
    return urlunsplit(parts._replace(query="&".join(kept)))


def _check_ip(raw: str) -> None:
    """`outbound_addresses.check_ip` in this module's vocabulary.

    The rules moved to `core.outbound_addresses` so the domain-expiry lookup could stop
    being the one outbound fetch in the product with no private-range rejection (S18).
    This wrapper stays because the translation to `PreviewUnavailable` belongs here: the
    caller treats every reason as "no card", and the validator has no business knowing
    that.
    """
    try:
        outbound_addresses.check_ip(raw)
    except outbound_addresses.BlockedAddress as exc:
        raise PreviewUnavailable(str(exc)) from exc


def _resolve_and_pin(host: str, port: int) -> str:
    """`outbound_addresses.resolve_and_pin`, translated the same way."""
    try:
        return outbound_addresses.resolve_and_pin(host, port)
    except outbound_addresses.BlockedAddress as exc:
        raise PreviewUnavailable(str(exc)) from exc


_PinnedHTTPSConnection = outbound_addresses.PinnedHTTPSConnection
_PinnedHTTPConnection = outbound_addresses.PinnedHTTPConnection


def _validate_url(url: str) -> tuple[str, str, int, str]:
    """Return (scheme, host, port, path_with_query) or raise. Rejects non-http(s)
    schemes, non-80/443 ports, and any userinfo (user@host) in the authority."""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise PreviewUnavailable(f"scheme {parts.scheme!r} not allowed")
    if parts.username or parts.password:
        raise PreviewUnavailable("userinfo not allowed in URL")
    host = parts.hostname
    if not host:
        raise PreviewUnavailable("no host in URL")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise PreviewUnavailable(f"port {port} not allowed")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return parts.scheme, host, port, path


def _read_capped(resp: http.client.HTTPResponse, deadline: float, max_bytes: int) -> bytes:
    """Read at most max_bytes, giving up if the total deadline passes. The socket
    timeout bounds each recv but resets on every chunk, so a slow trickle needs this
    wall-clock ceiling (security review HIGH-3)."""
    chunks: list[bytes] = []
    total = 0
    while total < max_bytes:
        if time.monotonic() > deadline:
            raise PreviewUnavailable("read deadline exceeded")
        chunk = resp.read(min(65536, max_bytes - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _fetch_once(
    url: str,
    deadline: float,
    *,
    accept: str,
    content_type_ok: Callable[[str], bool],
    max_bytes: int,
) -> tuple[int, str | None, bytes]:
    """One validated, IP-pinned, non-redirecting GET. Returns (status, location,
    body). Body is empty unless the response is 2xx with an accepted content type
    within the size cap. The SSRF controls (scheme/port/userinfo validation and the
    resolve-then-pin) are identical for every caller; only the accepted content type
    and byte cap differ between the HTML head and the re-hosted image (S-301)."""
    if time.monotonic() > deadline:
        raise PreviewUnavailable("deadline exceeded")
    scheme, host, port, path = _validate_url(url)
    pinned_ip = _resolve_and_pin(host, port)

    conn: http.client.HTTPConnection
    if scheme == "https":
        conn = _PinnedHTTPSConnection(
            host,
            pinned_ip=pinned_ip,
            port=port,
            timeout=_TIMEOUT,
            context=ssl.create_default_context(),
        )
    else:
        conn = _PinnedHTTPConnection(host, pinned_ip=pinned_ip, port=port, timeout=_TIMEOUT)

    try:
        conn.request("GET", path, headers={"User-Agent": _USER_AGENT, "Accept": accept})
        resp = conn.getresponse()
        status = resp.status
        location = resp.getheader("Location")
        if status >= 300:
            resp.read(0)
            return status, location, b""
        content_type = (resp.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if not content_type_ok(content_type):
            raise PreviewUnavailable(f"content type {content_type!r} not accepted")
        body = _read_capped(resp, deadline, max_bytes)
        return status, None, body
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise PreviewUnavailable(str(exc)) from exc
    finally:
        conn.close()


def _fetch_following(
    url: str,
    *,
    accept: str,
    content_type_ok: Callable[[str], bool],
    max_bytes: int,
    deadline: float | None = None,
) -> tuple[str, bytes] | None:
    """Follow up to a few redirects, re-validating EVERY hop from scratch (a public
    URL can 302 to http://169.254.169.254), and return (final_url, body) of the first
    non-redirect response, or None. Every hop runs the same SSRF gate through
    _fetch_once, so a redirect can no more reach an internal address than the first
    request could. An explicit deadline lets a caller share ONE wall-clock budget
    across the page fetch and the follow-up image fetch, so the two together cannot
    block the request tier for more than _TOTAL_BUDGET (security review, S-301)."""
    current = url
    if deadline is None:
        deadline = time.monotonic() + _TOTAL_BUDGET
    try:
        for _hop in range(_MAX_REDIRECTS + 1):
            if time.monotonic() > deadline:
                return None
            status, location, body = _fetch_once(
                current,
                deadline,
                accept=accept,
                content_type_ok=content_type_ok,
                max_bytes=max_bytes,
            )
            if status >= 300:
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            return current, body
        return None  # too many redirects
    except PreviewUnavailable:
        return None


def fetch_preview(url: str, *, deadline: float | None = None) -> Preview | None:
    """Fetch and parse a link preview for a member-supplied URL, or None on any
    failure (graceful fallback)."""
    got = _fetch_following(
        url,
        accept="text/html",
        content_type_ok=lambda ct: ct == "text/html",
        max_bytes=_MAX_BYTES,
        deadline=deadline,
    )
    if got is None:
        return None
    final_url, body = got
    return _parse(body, final_url=final_url)


def fetch_image_bytes(url: str, *, deadline: float | None = None) -> bytes | None:
    """Fetch a preview's og:image through the same SSRF-hardened, IP-pinned,
    redirect-revalidating path as the HTML (S-301), or None. Accepts only an image
    content type and a larger-but-bounded body; the caller re-encodes the bytes
    through the media store, so what is fetched here is never served as-is."""
    got = _fetch_following(
        url,
        accept="image/*",
        content_type_ok=lambda ct: ct.startswith("image/"),
        max_bytes=_MAX_IMAGE_BYTES,
        deadline=deadline,
    )
    return got[1] if got is not None else None


class _HeadParser(HTMLParser):
    """Collects the fixed meta allowlist from a document head. Stops at </head> or
    <body>; does no entity or external resolution (stdlib HTMLParser), so a
    hostile document cannot expand into a billion-laughs DoS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title = ""
        self.og_description = ""
        self.og_image = ""
        self.meta_description = ""
        self.title = ""
        self._in_title = False
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag == "body":
            self._done = True
            return
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        prop = a.get("property", "").lower()
        name = a.get("name", "").lower()
        content = a.get("content", "")
        if prop == "og:title" and not self.og_title:
            self.og_title = content
        elif prop == "og:description" and not self.og_description:
            self.og_description = content
        elif prop == "og:image" and not self.og_image:
            self.og_image = content
        elif name == "description" and not self.meta_description:
            self.meta_description = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title and not self._done:
            self.title = data


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())  # collapse whitespace
    return text[:limit].strip()


def _parse(body: bytes, *, final_url: str) -> Preview | None:
    """Parse the fixed, length-capped meta allowlist. Returns None if there is
    nothing worth showing (no title of any kind)."""
    html = body.decode("utf-8", errors="replace")
    parser = _HeadParser()
    parser.feed(html)
    title = _clip(parser.og_title or parser.title, _TITLE_MAX)
    description = _clip(parser.og_description or parser.meta_description, _DESC_MAX)
    raw_image = parser.og_image.strip()
    # Resolve a relative og:image against the final URL for wave 3, when it will be
    # re-fetched through this same validator and re-hosted (it is not rendered now).
    image_url = urljoin(final_url, raw_image) if raw_image else ""
    if not title:
        return None
    return Preview(url=final_url, title=title, description=description, image_url=image_url)


def _rehost_preview_image(
    post: Post, row: LinkPreview, image_url: str, *, deadline: float | None = None
) -> None:
    """Best-effort re-host of a preview's og:image (S-301). Fetch it through the same
    SSRF gate as the HTML, re-encode it through the media store (metadata stripped,
    polyglot defused, content type pinned), attach it as the preview's image_asset.
    Any failure (unreachable, wrong type, oversize, undecodable, a storage/DB error)
    leaves the card with no image rather than raising: this runs AFTER the post is
    already committed, so a broken image must never 500 the compose or duplicate the
    post (security review LOW). The catch is deliberately broad for that reason."""
    from . import media

    try:
        raw_image = fetch_image_bytes(image_url, deadline=deadline)
        if not raw_image:
            return
        asset = media.ingest_link_preview_image(post=post, raw=raw_image)
        if asset is not None:
            row.image_asset = asset
            row.save(update_fields=["image_asset"])
    except Exception:  # noqa: BLE001 — best-effort post-commit enrichment; never break the post
        return


def attach_to_post(post: Post) -> LinkPreview | None:
    """Best-effort: if the post body contains a URL, store its tracking-stripped form
    and, when one can be safely fetched, a title/description card with a re-hosted
    image. Called by the compose view after the post is created, so the write service
    stays pure and free of network I/O. A URL with no fetchable preview still stores
    the cleaned link, so the card degrades to a bare link (graceful fallback); no URL
    means no row."""
    from .models import LinkPreview

    # Idempotent (S-725 review): this now runs on the at-least-once worker queue, so a
    # re-delivered job (a worker killed mid-run, deploy, or OOM) must neither re-run the
    # outbound SSRF fetch nor hit LinkPreview.post's OneToOne with a second create — a post
    # that already carries its card is done. Guard BEFORE the fetch.
    existing = LinkPreview.objects.filter(post=post).first()
    if existing is not None:
        return existing
    raw = first_url_in(post.body)
    if not raw:
        return None
    clean = strip_tracking_params(raw)
    if len(clean) > _MAX_URL_LEN:
        return None  # a URL past the column width gets no card, never a 500
    # ONE wall-clock budget shared across the page fetch and the follow-up image fetch,
    # so a member's compose cannot be blocked for more than _TOTAL_BUDGET total by a slow
    # or hostile target, even though it is two sequential network fetches (S-301).
    deadline = time.monotonic() + _TOTAL_BUDGET
    preview = fetch_preview(clean, deadline=deadline)
    row = LinkPreview.objects.create(
        post=post,
        url=clean,
        title=preview.title if preview else "",
        description=preview.description if preview else "",
        # The remote og:image URL is stored as the record + re-host source, capped to the
        # column width defensively; it is re-hosted below, never rendered directly.
        image_url=(preview.image_url[:_MAX_URL_LEN] if preview else ""),
    )
    if preview and preview.image_url:
        _rehost_preview_image(post, row, preview.image_url, deadline=deadline)
    return row
