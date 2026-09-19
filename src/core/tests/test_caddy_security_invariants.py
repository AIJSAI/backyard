"""The production Caddyfile's security invariants, asserted instead of commented (G7).

`caddy/Caddyfile.prod` is one of the seven paths that reach the running box, and every
security property of the edge was enforced by a comment telling the next person not to
change it. Four of those comments exist because somebody already got it wrong once:

* **`admin off`.** Caddy's admin API is a full configuration-rewrite endpoint. It binds
  localhost by default, which on a shared compose network is not the reassurance it sounds
  like, and nothing on this box has any use for it.
* **No `log` directive.** Request lines carry bearer tokens in their paths -- `/t/`, `/d/`,
  `/join/`, `/media/`, `/digest/*`, `/break-glass/`, `/get-back-in/` (threat model
  TS-EDGE-LOG) -- so an access log is a token log. `--access-logfile -` was dropped from
  gunicorn for exactly this reason; adding `log` at the edge would put it straight back.
* **No global `Referrer-Policy`.** The app sets it per surface. A global `no-referrer` here
  makes browsers send `Origin: null` on same-origin form POSTs, Django's CSRF check rejects
  them, and every form in the product breaks in a real browser while every test still passes
  (TS-DJ-10).
* **The health port stays inside.** `:8000` answers the container healthcheck and nothing
  else, and the production overlay publishes 80 and 443 only. Publishing 8000 would put a
  plain-HTTP listener on the internet in front of the same app.

Plus the two response-header properties that were found live: `-Server` and `-Via` (Caddy
re-announced itself in `Via:` after `Server` was stripped), and `nosniff`.

Read as TEXT with comments removed, which is load-bearing in both directions: this file's own
cautions quote `log`, `Referrer-Policy` and `admin off` while explaining why they must not
appear, so a naive scan fires on the warning -- the failure mode that gets a guard deleted
rather than fixed. `test_each_invariant_can_actually_fail` mutates the real file in memory and
requires every check below to go red, so none of them can be satisfied by prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_CADDYFILE = _ROOT / "caddy" / "Caddyfile.prod"
_PROD_OVERLAY = _ROOT / "docker-compose.prod.yml"


def _directives(text: str) -> str:
    """The Caddyfile with `#` comments removed, one directive per line.

    A comment runs from an unquoted `#` to end of line. Only whole-line and trailing-after-
    whitespace comments are stripped, which is every comment this file has, and is the form
    that cannot accidentally cut a URL fragment out of the middle of a `respond` body.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(kept)


def _caddyfile() -> str:
    return _directives(_CADDYFILE.read_text(encoding="utf-8"))


def _assert_admin_is_off(config: str) -> None:
    assert re.search(r"^\s*admin\s+off\s*$", config, re.M), (
        "`admin off` is gone from caddy/Caddyfile.prod. Caddy then exposes its admin API, "
        "which can rewrite the whole edge configuration at runtime, to anything that can "
        "reach the container -- and on the compose network that is every sibling."
    )


def _assert_no_log_directive(config: str) -> None:
    offending = [line for line in config.splitlines() if re.match(r"^\s*log\b(?!\w)", line.strip())]
    assert not offending, (
        "caddy/Caddyfile.prod has a `log` directive: " + "; ".join(offending) + ".\n"
        "Request paths on this instance ARE bearer tokens (/t/, /d/, /join/, /media/, "
        "/digest/, /break-glass/, /get-back-in/), so an access log at the edge is a file of "
        "live credentials -- TS-EDGE-LOG, the same reason gunicorn's access log was dropped."
    )


def _assert_no_global_referrer_policy(config: str) -> None:
    offending = [line.strip() for line in config.splitlines() if "Referrer-Policy" in line]
    assert not offending, (
        "caddy/Caddyfile.prod sets Referrer-Policy at the edge: " + "; ".join(offending) + ".\n"
        "The app owns this header per surface. A global `no-referrer` makes browsers send "
        "`Origin: null` on same-origin form POSTs and Django's CSRF check rejects them, so "
        "join, invite, new-elder, digest confirm and break-glass all break in a real browser "
        "while every test still passes."
    )


def _assert_the_fingerprint_headers_are_stripped(config: str) -> None:
    for header in ("-Server", "-Via"):
        assert re.search(rf"^\s*{re.escape(header)}\s*$", config, re.M), (
            f"caddy/Caddyfile.prod no longer strips `{header[1:]}`. Both are needed and the "
            "second was found live: `Server` was removed and Caddy went on announcing itself "
            "in `Via: 1.1 Caddy` on every response."
        )


def _assert_nosniff_is_asserted_at_the_edge(config: str) -> None:
    assert re.search(r"^\s*X-Content-Type-Options\s+nosniff\s*$", config, re.M), (
        "caddy/Caddyfile.prod no longer sets `X-Content-Type-Options nosniff`. It is the one "
        "header this edge asserts as defense in depth behind the app's own, and it is what "
        "stops a served media file being sniffed into active content."
    )


def _site_block(config: str, address: str) -> str | None:
    """The body of one top-level site block, or None if it is gone."""
    found = re.search(rf"^{re.escape(address)}\s*\{{(.*?)^\}}", config, re.M | re.S)
    return found.group(1) if found else None


def _top_level_directives(body: str) -> list[tuple[str, str | None]]:
    """(head, inner) for each directive at the top level of a site block.

    Brace-aware, so a nested `handle { … }` is ONE entry carrying its own body rather than
    three stray lines. `inner` is None for a directive that opens no block.

    This exists because a substring check cannot answer the question that matters about
    these two blocks. "Is `abort` somewhere in `:443`?" is satisfied by a file that aborts
    one path and serves everything else -- which is the opposite of what the block is for,
    and it is the shape a well-meaning edit reaches for first.
    """
    found: list[tuple[str, str | None]] = []
    depth = 0
    head = ""
    inner: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        opens, closes = line.count("{"), line.count("}")
        if depth == 0:
            if opens:
                head = line[: line.index("{")].strip()
                inner = []
                depth = opens - closes
                if depth == 0:
                    found.append((head, ""))
            else:
                found.append((line, None))
            continue
        depth += opens - closes
        if depth == 0:
            found.append((head, "\n".join(inner)))
        else:
            inner.append(line)
    return found


def _assert_the_default_host_is_aborted(config: str) -> None:
    fallback = _site_block(config, ":443")
    assert fallback is not None, (
        "the `:443 { … }` block is gone from caddy/Caddyfile.prod. Without it a request whose "
        "Host does not match the site block is answered by Caddy's implicit fallback: an "
        "empty 200 carrying a bare `Server: Caddy` and none of the headers above -- the one "
        "response that skipped every security header was also the one advertising what "
        "served it."
    )
    # The WHOLE block, not a substring of it. `abort` moved under a path matcher, with a
    # `respond` or a `reverse_proxy` left as the default, satisfies "the word abort appears
    # here" while answering every unmatched Host again.
    directives = _top_level_directives(fallback)
    assert directives == [("abort", None)], (
        "the `:443` fallback block is no longer exactly one `abort`; it now reads "
        f"{directives}. An unmatched Host must reach NOTHING: this block carries no "
        "certificate and none of the site block's headers, so anything it answers is the one "
        "response on this edge with no security headers at all."
    )


def _assert_the_health_port_serves_only_health(config: str) -> None:
    block = _site_block(config, ":8000")
    assert block is not None, (
        "the `:8000 { … }` block is gone from caddy/Caddyfile.prod. It is the container "
        "healthcheck's target, and it is what lets one healthcheck line in docker-compose.yml "
        "mean the same thing in the local and production stacks."
    )
    directives = _top_level_directives(block)
    assert directives == [
        ("handle /healthz", "reverse_proxy web:8000"),
        ("handle", "abort"),
    ], (
        f"the `:8000` block no longer serves /healthz and nothing else; it reads {directives}. "
        "Both halves are pinned because either one alone is satisfiable by the wrong file: a "
        "catch-all `handle` that proxies rather than aborts turns the internal, "
        "certificate-less health listener into a second unencrypted front door onto the app."
    )


_INVARIANTS = {
    "admin off": _assert_admin_is_off,
    "no log directive": _assert_no_log_directive,
    "no global Referrer-Policy": _assert_no_global_referrer_policy,
    "Server and Via stripped": _assert_the_fingerprint_headers_are_stripped,
    "nosniff at the edge": _assert_nosniff_is_asserted_at_the_edge,
    "unmatched Host is aborted": _assert_the_default_host_is_aborted,
    "health port serves only health": _assert_the_health_port_serves_only_health,
}

# (invariant, a name for the case, an edit to the real file that must break it). The
# replacement is applied to the file's TEXT, so each mutation is a plausible edit rather than
# a synthetic string -- the difference between proving the check fires and proving a regex
# matches.
#
# The last four are the ones a substring check could not see. Each keeps the word the old
# check looked for and moves it somewhere that changes what the block does, which is the
# shape a well-meaning edit takes: "abort the health path, serve the rest".
_MUTATIONS = (
    ("admin off", "admin-endpoint-reopened", "\tadmin off", "\tadmin localhost:2019"),
    ("no log directive", "access-log-added", "\tservers {", "\tlog\n\tservers {"),
    (
        "no global Referrer-Policy",
        "global-referrer-policy-added",
        "\t\tX-Content-Type-Options nosniff",
        "\t\tX-Content-Type-Options nosniff\n\t\tReferrer-Policy no-referrer",
    ),
    ("Server and Via stripped", "via-header-restored", "\t\t-Via", "\t\t"),
    ("nosniff at the edge", "nosniff-dropped", "\t\tX-Content-Type-Options nosniff", "\t\t"),
    (
        "unmatched Host is aborted",
        "fallback-answers-again",
        ":443 {\n\tabort\n}",
        ":443 {\n\trespond 200\n}",
    ),
    (
        # `abort` still present, under a path matcher, with a default that replies: the exact
        # file the old substring check called clean.
        "unmatched Host is aborted",
        "fallback-aborts-one-path-and-serves-the-rest",
        ":443 {\n\tabort\n}",
        ":443 {\n\thandle /healthz {\n\t\tabort\n\t}\n\trespond 200\n}",
    ),
    (
        "health port serves only health",
        "health-catch-all-emptied",
        "\thandle {\n\t\tabort\n\t}",
        "\thandle {\n\t\t\n\t}",
    ),
    (
        # The catch-all proxies instead of aborting: a second, certificate-less front door
        # onto the app, with `handle /healthz` still there to satisfy the old check.
        "health port serves only health",
        "health-catch-all-proxies-the-app",
        "\thandle {\n\t\tabort\n\t}",
        "\thandle {\n\t\treverse_proxy web:8000\n\t}",
    ),
    (
        # A third path opened beside the two that belong there.
        "health port serves only health",
        "health-block-grows-a-third-route",
        "\thandle {\n\t\tabort\n\t}",
        "\thandle /metrics {\n\t\treverse_proxy web:8000\n\t}\n\thandle {\n\t\tabort\n\t}",
    ),
)


def test_the_production_caddyfile_is_where_we_think() -> None:
    """Denominator. Every check below reads one file; if it moved they would all pass
    against an empty string rather than failing for the reason that matters."""
    assert _CADDYFILE.is_file(), f"no production Caddyfile at {_CADDYFILE}"
    config = _caddyfile()
    assert len(config) > 500, (
        f"{_CADDYFILE.name} reduces to {len(config)} bytes of directives; that is not this file"
    )


@pytest.mark.parametrize("invariant", sorted(_INVARIANTS))
def test_a_caddy_security_invariant_still_holds(invariant: str) -> None:
    _INVARIANTS[invariant](_caddyfile())


@pytest.mark.parametrize(
    ("invariant", "case", "find", "replace"),
    [pytest.param(*row, id=row[1]) for row in _MUTATIONS],
)
def test_each_invariant_can_actually_fail(
    invariant: str, case: str, find: str, replace: str
) -> None:
    """Break the thing, and require the guard to notice.

    Without this, every check above is one typo away from matching nothing and passing
    forever -- which is this repository's most-repeated defect, and the reason several of its
    gates turned out never to have run.
    """
    original = _CADDYFILE.read_text(encoding="utf-8")
    assert find in original, (
        f"the {case!r} mutation no longer applies: {find!r} is not in the Caddyfile, so "
        "this proof is measuring nothing. Re-point it at the current text."
    )
    broken = _directives(original.replace(find, replace, 1))
    with pytest.raises(AssertionError):
        _INVARIANTS[invariant](broken)


def test_every_invariant_has_a_mutation_that_breaks_it() -> None:
    """The denominator for the proofs above. An invariant with no mutation beside it is one
    nobody has watched fail, which is the state every gate in this repository turned out to
    be in the first time somebody checked."""
    proven = {invariant for invariant, _, _, _ in _MUTATIONS}
    unproven = sorted(set(_INVARIANTS) - proven)
    assert not unproven, (
        f"{unproven} are asserted above with nothing proving the assertion can fail. Add a "
        "mutation to _MUTATIONS that breaks each one in the real file's text."
    )


def test_the_block_reader_sees_structure_a_substring_check_cannot() -> None:
    """The parser the two block rules rest on, proven on the shape that fooled the old one.

    A file that aborts one path and replies to everything else contains the word `abort`,
    which is all the previous check asked for. Read as structure it is plainly a different
    block, and that difference is what the rules above now assert.
    """
    assert _top_level_directives("\tabort\n") == [("abort", None)]
    assert _top_level_directives("\thandle /healthz {\n\t\treverse_proxy web:8000\n\t}\n") == [
        ("handle /healthz", "reverse_proxy web:8000")
    ]

    sneaky = "\thandle /healthz {\n\t\tabort\n\t}\n\trespond 200\n"
    assert "abort" in sneaky, "the fixture must keep the word the old check looked for"
    assert _top_level_directives(sneaky) == [
        ("handle /healthz", "abort"),
        ("respond 200", None),
    ], "a path-matched abort beside a default `respond` must not read as a bare abort"


def test_the_comments_that_warn_about_these_directives_are_not_read_as_directives() -> None:
    """The file has to survive explaining itself.

    Its header says "Do NOT add `header Referrer-Policy no-referrer` here" and "Do NOT add a
    `log` directive here". Both are the correct instruction; a scan that cannot tell them from
    the thing they forbid fails the build for saying the true thing.
    """
    original = _CADDYFILE.read_text(encoding="utf-8")
    assert "Referrer-Policy" in original and "log` directive" in original, (
        "the cautions this test exists to survive are gone from the Caddyfile, so it now "
        "proves nothing -- and the next person has no comment telling them why either"
    )
    config = _caddyfile()
    _assert_no_log_directive(config)
    _assert_no_global_referrer_policy(config)


def test_the_production_overlay_publishes_no_port_but_80_and_443() -> None:
    """The health listener is internal because nothing maps it, not because it is shy.

    `:8000` in the Caddyfile is a plain-HTTP listener carrying no certificate. It is safe
    only while the overlay publishes 80 and 443 and nothing else; a third mapping here puts
    an unencrypted front door on the same application.
    """
    overlay = _PROD_OVERLAY.read_text(encoding="utf-8")
    caddy = overlay[overlay.index("  caddy:") :]
    published = re.findall(r'^\s+-\s+"(\d+):\d+"', caddy, re.M)
    assert published == ["80", "443"], (
        f"docker-compose.prod.yml publishes {published} from the caddy service. Only 80 and "
        "443 belong on the host: the Caddyfile's :8000 block is plain HTTP for the container "
        "healthcheck, and mapping it would serve the instance unencrypted."
    )
