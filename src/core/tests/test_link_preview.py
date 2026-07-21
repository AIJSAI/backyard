"""Link previews (S-301): the SSRF-hardened fetch/parse and tracking-param strip.

The security core is the fetcher (threat model TS-PP-5/TS-PP-6): only http(s) on
80/443, resolve-then-check every address so private/loopback/link-local/reserved/
CGNAT/multicast/mapped forms are rejected, pin the connection to the validated IP,
never auto-follow a redirect, re-validate every hop, and parse with the tolerant
stdlib HTML parser into a fixed length-capped allowlist. These tests hit each
control directly; the live repro exercises a real fetch and a real internal block.
"""

from __future__ import annotations

import socket

import pytest

from core import link_preview
from core.models import Member, Pod, PodMembership, Post, Yard

# --- IP range validation (the SSRF core) ---


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # private
        "192.168.1.1",  # private
        "172.16.0.1",  # private
        "169.254.169.254",  # link-local (cloud metadata)
        "0.0.0.0",  # unspecified  # noqa: S104
        "100.64.0.1",  # CGNAT
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 ULA
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "ff02::1",  # IPv6 multicast
    ],
)
def test_check_ip_blocks_non_global(addr: str) -> None:
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._check_ip(addr)


@pytest.mark.parametrize("addr", ["93.184.216.34", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946"])
def test_check_ip_allows_global(addr: str) -> None:
    link_preview._check_ip(addr)  # does not raise


def test_resolve_and_pin_rejects_when_any_address_is_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*_a: object, **_k: object) -> list[object]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._resolve_and_pin("rebind.example", 80)


def test_fetch_once_blocks_a_direct_internal_literal() -> None:
    # No network: getaddrinfo of a literal IP returns it, and _check_ip rejects it.
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._fetch_once("http://127.0.0.1/")


def test_fetch_preview_returns_none_for_an_internal_target() -> None:
    assert link_preview.fetch_preview("http://169.254.169.254/latest/meta-data/") is None


# --- URL validation ---


def test_validate_url_rejects_bad_scheme() -> None:
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._validate_url("ftp://example.com/x")


def test_validate_url_rejects_nonstandard_port() -> None:
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._validate_url("http://example.com:8080/")


def test_validate_url_rejects_userinfo() -> None:
    with pytest.raises(link_preview.PreviewUnavailable):
        link_preview._validate_url("http://user:pass@example.com/")


def test_validate_url_accepts_plain_http_and_https() -> None:
    assert link_preview._validate_url("http://example.com/a?b=1") == (
        "http",
        "example.com",
        80,
        "/a?b=1",
    )
    assert link_preview._validate_url("https://example.com") == ("https", "example.com", 443, "/")


# --- redirect handling ---


def test_redirect_is_followed_but_revalidated_each_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_preview follows a redirect by re-calling _fetch_once (the validating
    function) on the target, so a 302 to an internal address is rejected there."""
    calls: list[str] = []

    def fake_fetch_once(url: str) -> tuple[int, str | None, bytes]:
        calls.append(url)
        if len(calls) == 1:
            return (302, "http://10.0.0.1/meta", b"")
        raise link_preview.PreviewUnavailable("hop blocked")  # the real _fetch_once would too

    monkeypatch.setattr(link_preview, "_fetch_once", fake_fetch_once)
    assert link_preview.fetch_preview("http://example.com/") is None
    assert calls == ["http://example.com/", "http://10.0.0.1/meta"]


def test_too_many_redirects_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_redirect(url: str) -> tuple[int, str | None, bytes]:
        return (302, "https://example.com/next", b"")

    monkeypatch.setattr(link_preview, "_fetch_once", always_redirect)
    assert link_preview.fetch_preview("https://example.com/") is None


# --- tracking-param strip (S-301) ---


def test_strip_removes_utm_and_click_ids_but_keeps_the_rest() -> None:
    got = link_preview.strip_tracking_params("https://x.com/a?utm_source=fb&id=5&fbclid=z&q=hi")
    assert got == "https://x.com/a?id=5&q=hi"


def test_strip_is_case_insensitive() -> None:
    assert (
        link_preview.strip_tracking_params("https://x.com/a?UTM_Source=x&keep=1")
        == "https://x.com/a?keep=1"
    )


def test_strip_leaves_clean_urls_unchanged() -> None:
    assert link_preview.strip_tracking_params("https://x.com/a?id=5") == "https://x.com/a?id=5"
    assert link_preview.strip_tracking_params("https://x.com/a") == "https://x.com/a"


def test_first_url_in() -> None:
    assert link_preview.first_url_in("hey http://a.com/x and more") == "http://a.com/x"
    assert link_preview.first_url_in("no url here") is None


# --- HTML parse (the fixed allowlist) ---


def test_parse_prefers_open_graph() -> None:
    html = (
        b"<html><head><title>fallback</title>"
        b'<meta property="og:title" content="OG Title">'
        b'<meta property="og:description" content="OG Desc">'
        b'<meta property="og:image" content="/img/card.png">'
        b"</head><body>ignored</body></html>"
    )
    preview = link_preview._parse(html, final_url="https://ex.com/p")
    assert preview is not None
    assert preview.title == "OG Title"
    assert preview.description == "OG Desc"
    assert preview.image_url == "https://ex.com/img/card.png"  # relative image resolved


def test_parse_falls_back_to_title_and_meta_description() -> None:
    html = b'<head><title>Just a Title</title><meta name="description" content="Meta desc"></head>'
    preview = link_preview._parse(html, final_url="https://ex.com/")
    assert preview is not None
    assert preview.title == "Just a Title"
    assert preview.description == "Meta desc"


def test_parse_returns_none_without_any_title() -> None:
    assert (
        link_preview._parse(b"<head><meta name=x content=y></head>", final_url="https://ex.com/")
        is None
    )


def test_parse_clips_an_overlong_title() -> None:
    html = b'<head><meta property="og:title" content="' + b"a" * 1000 + b'"></head>'
    preview = link_preview._parse(html, final_url="https://ex.com/")
    assert preview is not None
    assert len(preview.title) == 300


# --- attach_to_post integration ---


@pytest.fixture
def a_post() -> Post:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Pod")
    pod.yards.set([yard])
    author = Member.objects.create(display_name="Author")
    PodMembership.objects.create(member=author, pod=pod)
    return Post.objects.create(
        author=author, pod=pod, body="look http://x.com/a?utm_source=fb&id=5"
    )


@pytest.mark.django_db
def test_attach_stores_a_fetched_preview(a_post: Post, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        link_preview,
        "fetch_preview",
        lambda url: link_preview.Preview(
            url=url, title="Fetched", description="Desc", image_url=""
        ),
    )
    preview = link_preview.attach_to_post(a_post)
    assert preview is not None
    assert preview.title == "Fetched"
    assert preview.url == "http://x.com/a?id=5"  # tracking stripped from the stored URL


@pytest.mark.django_db
def test_attach_degrades_to_a_bare_link_when_fetch_fails(
    a_post: Post, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_preview, "fetch_preview", lambda url: None)
    preview = link_preview.attach_to_post(a_post)
    assert preview is not None
    assert preview.title == ""
    assert preview.url == "http://x.com/a?id=5"  # still stored, still cleaned


@pytest.mark.django_db
def test_attach_does_nothing_without_a_url() -> None:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    author = Member.objects.create(display_name="A")
    PodMembership.objects.create(member=author, pod=pod)
    post = Post.objects.create(author=author, pod=pod, body="no links here, just words")
    assert link_preview.attach_to_post(post) is None
