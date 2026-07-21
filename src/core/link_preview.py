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

Deferred honestly to wave 3 (media): the og:image is captured but not rendered,
because rendering it means either hotlinking (the tracking-beacon and IP-disclosure
leak TS-PP-6 forbids) or re-hosting, and re-hosting needs the media store wave 3
builds. Until then a card shows the title, the description, and the source domain.

No third-party HTTP client or HTML parser is added: the stdlib gives the redirect
and IP-pinning control these controls require and keeps the supply chain small.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit, urlunsplit

if TYPE_CHECKING:
    from .models import LinkPreview, Post

_TIMEOUT = 3.0  # seconds, per connect and per recv
_TOTAL_BUDGET = 8.0  # seconds, whole fetch across all hops; the per-recv timeout
# resets on every chunk, so a slow trickle needs a wall-clock ceiling too (HIGH-3)
_MAX_BYTES = 512 * 1024  # only the head matters; cap the whole read anyway
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


# IPv6 prefixes that embed an IPv4 address in their low 32 bits. On Python 3.13
# ip.is_global returns True for NAT64 (64:ff9b::/96) and the IPv4-compatible/SIIT
# forms even when the embedded IPv4 is internal, so an attacker who controls DNS can
# publish an AAAA of 64:ff9b::<metadata-v4> and, on a NAT64 network, reach the cloud
# metadata endpoint (security review HIGH-2). Decode the embedded v4 and re-check it.
_V4_EMBEDDING_PREFIXES = (
    ipaddress.IPv6Network("::/96"),  # IPv4-compatible (deprecated)
    ipaddress.IPv6Network("::ffff:0:0/96"),  # IPv4-mapped (also via .ipv4_mapped)
    ipaddress.IPv6Network("::ffff:0:0:0/96"),  # SIIT ::ffff:0:<v4>
    ipaddress.IPv6Network("64:ff9b::/96"),  # NAT64 well-known prefix
    ipaddress.IPv6Network("64:ff9b:1::/48"),  # NAT64 local-use prefix
)


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 an IPv6 address embeds (mapped, 6to4, NAT64, IPv4-compatible/SIIT),
    or None. These forms can route to an internal IPv4 while ip.is_global is True."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    for net in _V4_EMBEDDING_PREFIXES:
        if ip in net:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _check_ip(raw: str) -> None:
    """Raise PreviewUnavailable unless the address is a globally routable unicast
    address. Rejects every non-global category (private, loopback, link-local,
    reserved, CGNAT, unspecified, multicast) and, for IPv6, decodes any embedded
    IPv4 (mapped, 6to4, NAT64, IPv4-compatible) and re-checks it, so an IPv6 form
    that routes to an internal IPv4 cannot slip past is_global (HIGH-2)."""
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(raw)
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            ip = embedded
    if (
        ip.is_multicast
        or ip.is_unspecified
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_private
        or not ip.is_global
    ):
        raise PreviewUnavailable(f"blocked address {raw}")


def _resolve_and_pin(host: str, port: int) -> str:
    """Resolve the host once, reject if ANY resolved address is not globally
    routable, and return one validated IP to pin the connection to."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise PreviewUnavailable(f"cannot resolve {host}") from exc
    if not infos:
        raise PreviewUnavailable(f"cannot resolve {host}")
    pinned: str | None = None
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = str(sockaddr[0])
        _check_ip(ip)  # every resolved address must pass; one bad address rejects all
        if pinned is None:
            pinned = ip
    if pinned is None:  # unreachable: infos was non-empty, but keep it explicit
        raise PreviewUnavailable(f"cannot resolve {host}")
    return pinned


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a pre-validated IP with correct SNI and certificate check for the
    original hostname, so the TCP connect cannot be rebound to another address."""

    def __init__(self, host: str, *, pinned_ip: str, **kwargs: object) -> None:
        super().__init__(host, **kwargs)  # type: ignore[arg-type]
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), timeout=self.timeout)
        # self._context is the SSLContext set by HTTPSConnection.__init__; SNI and
        # cert validation use self.host (the real hostname), the TCP peer is the IP.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP to a pre-validated IP; the Host header stays the original hostname."""

    def __init__(self, host: str, *, pinned_ip: str, **kwargs: object) -> None:
        super().__init__(host, **kwargs)  # type: ignore[arg-type]
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), timeout=self.timeout)


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


def _read_capped(resp: http.client.HTTPResponse, deadline: float) -> bytes:
    """Read at most _MAX_BYTES, giving up if the total deadline passes. The socket
    timeout bounds each recv but resets on every chunk, so a slow trickle needs this
    wall-clock ceiling (security review HIGH-3)."""
    chunks: list[bytes] = []
    total = 0
    while total < _MAX_BYTES:
        if time.monotonic() > deadline:
            raise PreviewUnavailable("read deadline exceeded")
        chunk = resp.read(min(65536, _MAX_BYTES - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _fetch_once(url: str, deadline: float) -> tuple[int, str | None, bytes]:
    """One validated, IP-pinned, non-redirecting GET. Returns (status, location,
    body). Body is empty unless the response is 2xx text/html within the size cap."""
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
        conn.request("GET", path, headers={"User-Agent": _USER_AGENT, "Accept": "text/html"})
        resp = conn.getresponse()
        status = resp.status
        location = resp.getheader("Location")
        if status >= 300:
            resp.read(0)
            return status, location, b""
        content_type = (resp.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "text/html":
            raise PreviewUnavailable(f"content type {content_type!r} not html")
        body = _read_capped(resp, deadline)
        return status, None, body
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise PreviewUnavailable(str(exc)) from exc
    finally:
        conn.close()


def fetch_preview(url: str) -> Preview | None:
    """Fetch and parse a link preview for a member-supplied URL, or None on any
    failure (graceful fallback). Follows up to a few redirects, re-validating every
    hop from scratch so no hop can reach an internal address."""
    current = url
    deadline = time.monotonic() + _TOTAL_BUDGET
    try:
        for _hop in range(_MAX_REDIRECTS + 1):
            if time.monotonic() > deadline:
                return None
            status, location, body = _fetch_once(current, deadline)
            if status >= 300:
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            return _parse(body, final_url=current)
        return None  # too many redirects
    except PreviewUnavailable:
        return None


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


def attach_to_post(post: Post) -> LinkPreview | None:
    """Best-effort: if the post body contains a URL, store its tracking-stripped form
    and, when one can be safely fetched, a title/description card. Called by the
    compose view after the post is created, so the write service stays pure and free
    of network I/O. A URL with no fetchable preview still stores the cleaned link, so
    the card degrades to a bare link (graceful fallback); no URL means no row."""
    from .models import LinkPreview

    raw = first_url_in(post.body)
    if not raw:
        return None
    clean = strip_tracking_params(raw)
    if len(clean) > _MAX_URL_LEN:
        return None  # a URL past the column width gets no card, never a 500
    preview = fetch_preview(clean)
    return LinkPreview.objects.create(
        post=post,
        url=clean,
        title=preview.title if preview else "",
        description=preview.description if preview else "",
        # og:image is captured for wave 3 only; cap it to the column width defensively.
        image_url=(preview.image_url[:_MAX_URL_LEN] if preview else ""),
    )
