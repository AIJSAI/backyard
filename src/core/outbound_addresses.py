"""The one address validator every outbound fetch in this product shares.

Two things in Backyard open a socket to somewhere else: the link-preview fetcher
(`link_preview`, member-supplied URLs) and the domain-expiry lookup (`domain_expiry`,
an RDAP query). The first has carried the full SSRF gate since S-301; the second had a
scheme check and nothing else, while `rdap.org` is a REDIRECTOR whose hop target is
chosen by a third party. So the URL the second one actually connects to was as
attacker-influenced as the first one's, with none of the defence.

This module is that defence, lifted out of `link_preview` unchanged so there is exactly
one answer to "may we connect to this address" rather than two that can drift. The rules,
from TS-PP-5/6:

* resolve the hostname ONCE and reject if ANY resolved address is not globally routable
  (private, loopback, link-local, reserved, CGNAT, multicast, unspecified);
* for IPv6, decode any embedded IPv4 (mapped, 6to4, NAT64, IPv4-compatible/SIIT) and
  re-check it, because `ip.is_global` answers True for several of those forms even when
  the embedded address is internal;
* then connect to the ONE validated IP, so a re-resolve cannot rebind to an internal
  address between the check and the connect.

`BlockedAddress` is the single failure shape. Each caller translates it into its own
vocabulary (`PreviewUnavailable`, `DomainLookupFailed`) at its own boundary, so neither
caller has to know about the other's exceptions.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket


class BlockedAddress(Exception):
    """The destination is not a globally routable unicast address, or will not resolve."""


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


def embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 an IPv6 address embeds (mapped, 6to4, NAT64, IPv4-compatible/SIIT),
    or None. These forms can route to an internal IPv4 while ip.is_global is True.

    DEFENCE IN DEPTH on Python 3.13, measured rather than assumed. Every embedding form
    below is ALREADY refused by `check_ip` with this decode reverted, but not by the same
    clause, and not by the one the original comment named. On 3.13.12:

      ::ffff:169.254.169.254   is_global False, is_private True, is_link_local True
      2002:a9fe:a9fe::1        is_global False, is_private True
      64:ff9b::a9fe:a9fe       is_global TRUE  — caught only by is_reserved
      ::ffff:0:a9fe:a9fe       is_global TRUE  — caught only by is_reserved
      ::a9fe:a9fe              is_global TRUE  — caught only by is_reserved

    So `is_global` alone does NOT answer the NAT64 and SIIT forms; what answers them
    today is that the stdlib marks those whole prefixes reserved. That is a property of
    CPython's tables rather than of anything this repo controls, which is why the decode
    stays — and it is what makes a refusal legible, because the reason then names the
    IPv4 the address really reaches instead of "reserved".
    `test_outbound_fetches_share_one_address_gate` pins the table above, so a future
    interpreter that loosens one of those rows fails here rather than in production.
    """
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    for net in _V4_EMBEDDING_PREFIXES:
        if ip in net:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def check_ip(raw: str) -> None:
    """Raise BlockedAddress unless the address is a globally routable unicast address.

    Rejects every non-global category (private, loopback, link-local, reserved, CGNAT,
    unspecified, multicast) and, for IPv6, decodes any embedded IPv4 and re-checks it,
    so an IPv6 form that routes to an internal IPv4 cannot slip past is_global (HIGH-2).
    """
    # A value that is not an address at all is BlockedAddress too, not ValueError: both
    # callers catch only the former and translate it into "no card" / "no expiry", so a
    # malformed host would have propagated as an unhandled 500 out of a link preview.
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise BlockedAddress(f"not an IP address: {raw!r}") from exc
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = embedded_ipv4(ip)
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
        raise BlockedAddress(f"blocked address {raw}")


def resolve_and_pin(host: str, port: int) -> str:
    """Resolve the host once, reject if ANY resolved address is not globally
    routable, and return one validated IP to pin the connection to."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedAddress(f"cannot resolve {host}") from exc
    if not infos:
        raise BlockedAddress(f"cannot resolve {host}")
    pinned: str | None = None
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = str(sockaddr[0])
        check_ip(ip)  # every resolved address must pass; one bad address rejects all
        if pinned is None:
            pinned = ip
    if pinned is None:  # unreachable: infos was non-empty, but keep it explicit
        raise BlockedAddress(f"cannot resolve {host}")
    return pinned


class PinnedHTTPSConnection(http.client.HTTPSConnection):
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


class PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP to a pre-validated IP; the Host header stays the original hostname."""

    def __init__(self, host: str, *, pinned_ip: str, **kwargs: object) -> None:
        super().__init__(host, **kwargs)  # type: ignore[arg-type]
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), timeout=self.timeout)
