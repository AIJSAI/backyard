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
