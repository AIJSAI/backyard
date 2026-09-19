"""Both outbound fetches refuse an internal address, by the same code (S18).

The link-preview fetcher has rejected private, loopback and link-local destinations since
S-301. The domain-expiry lookup had an HTTPS-only redirect policy and nothing else — while
`rdap.org` is a REDIRECTOR, so the address it actually connects to on the second hop is
chosen by a third party, which is the same threat model as a member's pasted URL with none
of the defence. A redirect to `https://169.254.169.254/` or to a name resolving inside the
compose network was accepted.

These tests pin two things: the validator is ONE implementation (so the two callers cannot
drift), and the domain lookup really refuses before it connects.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from typing import Any

import pytest

from core import domain_expiry, link_preview, outbound_addresses

_INTERNAL = [
    "127.0.0.1",
    "10.0.0.5",
    "192.168.1.1",
    "169.254.169.254",  # the cloud metadata endpoint
    "172.17.0.2",  # a docker bridge address: the compose network this instance runs on
    "::1",
    "fe80::1",
    "::ffff:169.254.169.254",  # IPv4-mapped form of the metadata endpoint
    "64:ff9b::a9fe:a9fe",  # NAT64 form of the same
]


# --- one validator, not two ----------------------------------------------------------


@pytest.mark.parametrize("addr", _INTERNAL)
def test_the_shared_validator_blocks_internal_addresses(addr: str) -> None:
    with pytest.raises(outbound_addresses.BlockedAddress):
        outbound_addresses.check_ip(addr)


@pytest.mark.parametrize("addr", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_the_shared_validator_allows_global_addresses(addr: str) -> None:
    outbound_addresses.check_ip(addr)  # does not raise


def test_the_link_fetcher_delegates_rather_than_carrying_a_second_copy() -> None:
    """`link_preview._check_ip` must BE the shared rule, translated. A second copy is how
    one of the two outbound fetchers comes to be the one that was never updated."""
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._check_ip("169.254.169.254")
    assert link_preview._PinnedHTTPSConnection is outbound_addresses.PinnedHTTPSConnection


# --- the domain lookup, which is the one that had no gate ----------------------------


def _resolving_to(addr: str) -> Any:
    """A getaddrinfo stand-in that answers with one address, the way a hostile or
    misconfigured DNS answer would."""
    family = (
        socket.AF_INET6
        if isinstance(ipaddress.ip_address(addr), ipaddress.IPv6Address)
        else socket.AF_INET
    )

    def fake(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (addr, port))]

    return fake


@pytest.mark.parametrize("addr", ["127.0.0.1", "169.254.169.254", "172.17.0.2"])
def test_the_domain_lookup_refuses_an_internal_destination(
    monkeypatch: pytest.MonkeyPatch, addr: str
) -> None:
    """Fails without `_ValidatedHTTPSHandler` in `domain_expiry._build_opener`: the
    handler would open a socket to the address instead of refusing it.

    The refusal is asserted through the PUBLIC entry point, so it covers the wiring (the
    opener really uses the validating handler) and not only the handler in isolation.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _resolving_to(addr))
    with pytest.raises(domain_expiry.DomainLookupFailed) as caught:
        domain_expiry.fetch_expiry("example.family")
    assert "refusing to fetch" in str(caught.value), caught.value


def test_the_domain_lookup_refuses_before_it_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordering is the whole point for a redirector: rejecting a private address
    AFTER the hop has been followed is not a control. Nothing may reach the socket."""
    monkeypatch.setattr(socket, "getaddrinfo", _resolving_to("169.254.169.254"))

    def refuse_to_connect(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a socket was opened to a blocked address")

    monkeypatch.setattr(socket, "create_connection", refuse_to_connect)
    with pytest.raises(domain_expiry.DomainLookupFailed):
        domain_expiry.fetch_expiry("example.family")


def test_the_validating_handler_is_the_one_the_opener_carries() -> None:
    """Guard the guard: a stock HTTPSHandler in the opener would make every test above
    pass for the wrong reason on a machine with no network."""
    # typeshed does not declare OpenerDirector.handlers; it is the list every
    # add_handler call appends to, and it is the only way to see what the opener got.
    handlers = domain_expiry._OPENER.handlers  # type: ignore[attr-defined]
    assert any(isinstance(h, domain_expiry._ValidatedHTTPSHandler) for h in handlers), handlers
    assert not any(type(h) is urllib.request.HTTPSHandler for h in handlers), (
        "the stock HTTPS handler is still installed alongside the validating one"
    )


def test_a_redirect_to_a_non_https_scheme_is_still_refused() -> None:
    """The property that was already here stays here: this test exists so the S18 change
    cannot quietly drop it."""
    policy = domain_expiry._HttpsOnlyRedirects()
    request = urllib.request.Request("https://rdap.org/domain/example.family")
    with pytest.raises(urllib.error.URLError):
        policy.redirect_request(request, None, 302, "Found", None, "ftp://elsewhere/x")
