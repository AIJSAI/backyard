"""ADR-004 item 4: the S-202 isolation matrix is generated from the model registry, so a
new model cannot silently skip yard isolation.

Every core model must be CONSCIOUSLY classified: either a member read surface that the
S-202 isolation suite exercises (`_ISOLATION_COVERED`), or infra / credential / admin-only
data with no cross-yard-leakable member read path (`_ISOLATION_EXEMPT`, each carrying the
reason it is not a surface). A new model that is neither fails the build, so the
enumerative control stops depending on a human remembering to add a case — the gap the
Phase-2 retro flagged as never having shipped. The guard proves itself non-vacuous (the
parents[N] lesson): a synthetic unclassified model MUST trip it, tested from both sides.

The classification is the conscious record; the S-202 isolation suite itself
(test_isolation + the per-type media/comment/reaction/directory cases) remains the separate
merge gate that must actually exercise every `_ISOLATION_COVERED` model's cross-yard 404.
"""

from __future__ import annotations

from django.apps import apps

# Member-visible read surfaces with an independent read path: the S-202 isolation suite
# asserts each returns a byte-identical 404 across a yard boundary (existence + content).
_ISOLATION_COVERED: frozenset[str] = frozenset(
    {"Yard", "Pod", "Member", "PodMembership", "Post", "Comment", "Reaction", "MediaAsset"}
)

# No cross-yard-leakable member read path; each exempt with the reason it is not a surface.
_ISOLATION_EXEMPT: dict[str, str] = {
    "LinkPreview": "rendered via its post only; no read route of its own (image is covered)",
    "SetupToken": "first-run secret, deleted once an admin exists; no member content",
    "ElderToken": "hashed token credential; elder-feed isolation is the visible_posts path",
    "DigestToken": "a digest deep-link credential; /d/ isolation is the visible_posts path",
    "DigestSubscription": "per-member digest infra; admin views scope it via visible_members",
    "DigestIssue": "internal per-(member,yard) send record; builder's visible_posts isolates it",
    "DigestDelivery": "internal transport-status record; admin views yard-scope it",
    "Invite": "an invite credential/ledger scoped by can_issue_invite, not a content read surface",
    "InviteRedemption": "internal who-joined ledger, shown only through the scoped invite",
    "ReplyAddress": "a per-member reply-by-email credential, not member-visible content",
    "InboundLedger": "internal Message-ID idempotency ledger; never rendered",
    "InboundQuarantine": "instance-admin-only pre-attribution mail hold (T-OP-G2); no yard scoping",
    "NotificationPreference": "a member's own push setting; never cross-member-visible",
    "PodMute": "a member's own feed-display mute (S-205); a display filter, not a read surface",
    "YardWeekMetrics": "instance-admin-only counts-only aggregate (S-705); no per-person content",
    "PodWeekMetrics": "instance-admin-only counts-only aggregate (S-705); no per-person content",
    "MemberWeekPresence": "instance-admin-only KPI presence input (S-705); an aggregate",
    "BackupRun": (
        "instance-level ops record (S-806): a timestamp and a byte count, "
        "no member data at all, no read route"
    ),
    "DomainStatus": (
        "instance-level ops record (S-806): the instance's OWN domain expiry, "
        "no member data, no read route"
    ),
}


def _classification_gap(
    registry: set[str], covered: set[str], exempt: set[str]
) -> tuple[set[str], set[str]]:
    """Return (unclassified, stale): registry models classified nowhere, and classified
    names no longer in the registry (so the classification cannot go stale-green either way)."""
    classified = covered | exempt
    return registry - classified, classified - registry


def test_every_core_model_is_classified_for_yard_isolation() -> None:
    registry = {m.__name__ for m in apps.get_app_config("core").get_models()}
    unclassified, stale = _classification_gap(
        registry, set(_ISOLATION_COVERED), set(_ISOLATION_EXEMPT)
    )
    assert not unclassified, (
        f"New core model(s) {sorted(unclassified)} must be added to the S-202 isolation "
        f"matrix (_ISOLATION_COVERED, with cross-yard 404 tests) or _ISOLATION_EXEMPT (with a "
        f"reason) — ADR-004 item 4: a model may not silently skip yard isolation."
    )
    assert not stale, (
        f"Classified model(s) {sorted(stale)} are no longer in the registry; drop them from "
        f"the isolation classification so it cannot go stale-green."
    )


def test_the_registry_guard_is_non_vacuous() -> None:
    # A synthetic unclassified model trips it; a fully-classified registry does not.
    unclassified, stale = _classification_gap({"Post", "GhostModel"}, {"Post"}, set())
    assert unclassified == {"GhostModel"} and not stale
    unclassified2, _ = _classification_gap({"Post", "Ghost"}, {"Post"}, {"Ghost"})
    assert not unclassified2  # exempt classification also satisfies it
    # A classified-but-absent name is caught as stale, so a deleted model cannot linger.
    _, stale2 = _classification_gap({"Post"}, {"Post", "Removed"}, set())
    assert stale2 == {"Removed"}


# --- the redaction filter must cover every credential-bearing route, by ENUMERATION ---


def test_every_credential_bearing_route_is_covered_by_log_redaction() -> None:
    """Walk the real URL resolver and fail on any registered route that captures a
    credential-shaped value but is not in _CAPABILITY_ROUTES.

    The two existing redaction tests assert that routes ALREADY in the list get redacted --
    a self-confirming shape that can never discover an omission. It missed
    `accounts/password/reset/key/<uidb36>-<key>`, so a wrapped or truncated reset link 404'd
    and `django.request` logged an account-takeover credential in plaintext. This test is the
    mechanism the threat model's own TS-EDGE-LOG residual asked for ("redaction is only as
    good as its filter... re-run as routes change") and which was never built.
    """
    import re
    from collections.abc import Iterator

    from django.urls import get_resolver

    from config.log_redaction import _TOKEN_SEGMENT

    # Matched against the CAPTURED PARAMETER NAME, never the surrounding path text.
    # Matching the whole pattern flagged `accounts/2fa/webauthn/keys/<int:pk>/remove/`
    # because the word "keys" appears in the path, while the captured value is a primary
    # key. A guard that cries wolf on pks is one somebody switches off.
    credential_like = re.compile(r"(?i)(token|key|uidb|secret|code)")
    # A pk is an object id, not a capability. `int` converters are never credentials.
    NOT_A_CREDENTIAL_CONVERTER = ("int:",)

    def walk(resolver: object, prefix: str = "") -> Iterator[str]:
        for pattern in resolver.url_patterns:  # type: ignore[attr-defined]
            text = prefix + str(getattr(pattern, "pattern", ""))
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern, text)
            else:
                yield text

    def credential_captures(raw: str) -> list[str]:
        """Capture names in this pattern that name a credential, in BOTH syntaxes.

        re_path() renders a named group as `(?P<key>...)`; path() renders a converter as
        `<str:token>`. Handling only the first made this guard vacuous for every
        path()-style route -- which is all of /t/, /d/, /media/ and /join/, i.e. exactly
        the surfaces it exists to protect. Proven at the time by deleting "t" from
        _CAPABILITY_ROUTES and watching this test still pass.
        """
        names = re.findall(r"\(\?P<([^>]+)>", raw)
        for converter in re.findall(r"<([^>]+)>", raw):
            if converter.startswith(NOT_A_CREDENTIAL_CONVERTER):
                continue
            names.append(converter.split(":")[-1])
        return [n for n in names if credential_like.search(n)]

    patterns = list(walk(get_resolver()))
    assert len(patterns) > 50, f"resolver walk found only {len(patterns)} patterns"
    # Guard the guard: if the shapes above ever stop matching, this test must not quietly
    # become an empty loop. The token surfaces alone put this well above zero.
    assert sum(bool(credential_captures(p)) for p in patterns) >= 5, (
        "the resolver walk recognised almost no credential captures -- the pattern "
        "syntax probably changed and this guard has gone vacuous"
    )

    uncovered = []
    for raw in patterns:
        if not credential_captures(raw):
            continue
        sample = "/" + re.sub(r"\(\?P<[^>]+>[^)]*\)", "LIVECREDENTIAL", raw)
        sample = re.sub(r"<[^>]+>", "LIVECREDENTIAL", sample)
        sample = re.sub(r"\[[^\]]*\][+*?]?", "x", sample).replace("^", "").replace("$", "")
        sample = sample.replace("\\", "")
        if "LIVECREDENTIAL" in _TOKEN_SEGMENT.sub(
            lambda m: f"/{m.group('route')}/[redacted]", sample
        ):
            uncovered.append(raw)

    assert not uncovered, (
        "these registered routes carry a credential and are NOT redacted from logs:\n  "
        + "\n  ".join(uncovered)
    )
