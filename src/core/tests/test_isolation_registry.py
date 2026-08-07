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

from collections.abc import Callable
from typing import Any

import pytest
from django.apps import apps

from core import scoping
from core.models import (
    Comment,
    MediaAsset,
    Member,
    Pod,
    PodMembership,
    Post,
    Reaction,
    Yard,
)

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


# --- coverage, not classification: each covered model gets a probe that RUNS -------------
#
# `_ISOLATION_COVERED` was a claim about a suite somewhere else. The docstring at the top of
# this file says so plainly — "the S-202 isolation suite itself remains the separate merge
# gate that must actually exercise every `_ISOLATION_COVERED` model's cross-yard 404" — and
# nothing checked that it did. A model could be listed as covered with no cross-yard test
# anywhere, and the guard would pass on the strength of its own list.
#
# So the enumeration does the work now instead of describing it. Each probe returns
# `(own, far)`: whether the viewer reaches an object of that model in their OWN yard, and in
# a yard they are not in. `own` is the per-probe denominator — a probe that reaches nothing
# at all would otherwise "prove" isolation by being broken, which is the exact shape of the
# vacuous gates this repo keeps finding.

# (reachable in the viewer's own yard, reachable across the boundary).
_ProbeResult = tuple[bool, bool]


def _probe_yard(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_yards(viewer).values_list("pk", flat=True))
    return (near["yard"].pk in visible, far["yard"].pk in visible)


def _probe_pod(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_pods(viewer).values_list("pk", flat=True))
    return (near["pod"].pk in visible, far["pod"].pk in visible)


def _probe_member(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_members(viewer).values_list("pk", flat=True))
    return (near["member"].pk in visible, far["member"].pk in visible)


def _probe_podmembership(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    # PodMembership has no `visible_*` of its own: it is reached through the pods a viewer
    # can see, which is the only path a member surface uses.
    reachable = set(
        PodMembership.objects.filter(pod__in=scoping.visible_pods(viewer)).values_list(
            "pk", flat=True
        )
    )
    return (near["membership"].pk in reachable, far["membership"].pk in reachable)


def _probe_post(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_posts(viewer).values_list("pk", flat=True))
    return (near["post"].pk in visible, far["post"].pk in visible)


def _probe_comment(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_comments(viewer).values_list("pk", flat=True))
    return (near["comment"].pk in visible, far["comment"].pk in visible)


def _probe_reaction(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_reactions(viewer).values_list("pk", flat=True))
    return (near["reaction"].pk in visible, far["reaction"].pk in visible)


def _probe_mediaasset(viewer: Member, near: dict[str, Any], far: dict[str, Any]) -> _ProbeResult:
    visible = set(scoping.visible_media(viewer).values_list("pk", flat=True))
    return (near["media"].pk in visible, far["media"].pk in visible)


_PROBES: dict[str, Callable[[Member, dict[str, Any], dict[str, Any]], _ProbeResult]] = {
    "Yard": _probe_yard,
    "Pod": _probe_pod,
    "Member": _probe_member,
    "PodMembership": _probe_podmembership,
    "Post": _probe_post,
    "Comment": _probe_comment,
    "Reaction": _probe_reaction,
    "MediaAsset": _probe_mediaasset,
}


def _side(name: str, slug: str) -> dict[str, Any]:
    """One complete side of the family: yard, household, member, post, comment, reaction,
    photograph. Built twice, and the viewer only ever joins one of them."""
    yard = Yard.objects.create(name=name, slug=slug)
    pod = Pod.objects.create(name=f"{name} household")
    pod.yards.set([yard])
    member = Member.objects.create(display_name=f"{name} relative")
    membership = PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(pod=pod, author=member, body=f"{name} news")
    comment = Comment.objects.create(post=post, author=member, body=f"{name} reply")
    reaction = Reaction.objects.create(post=post, member=member, kind=Reaction.HEART)
    asset = MediaAsset.objects.create(post=post, media_kind=MediaAsset.PHOTO)
    return {
        "yard": yard,
        "pod": pod,
        "member": member,
        "membership": membership,
        "post": post,
        "comment": comment,
        "reaction": reaction,
        "media": asset,
    }


def test_every_covered_model_has_a_probe_that_runs() -> None:
    """The classification may not outrun the coverage.

    Adding a name to `_ISOLATION_COVERED` without a probe fails here, so "covered" cannot go
    back to meaning "somebody intends to test this".
    """
    assert set(_PROBES) == set(_ISOLATION_COVERED), (
        "the probe table and the covered classification disagree.\n"
        f"  classified covered, no probe: {sorted(set(_ISOLATION_COVERED) - set(_PROBES))}\n"
        f"  probed, not classified      : {sorted(set(_PROBES) - set(_ISOLATION_COVERED))}"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", sorted(_PROBES))
def test_a_covered_model_does_not_cross_a_yard_boundary(model_name: str) -> None:
    """S-202, executed per model rather than asserted about.

    `own` is this probe's denominator: a probe that reaches nothing would otherwise report
    perfect isolation while being broken, which is how a guard ends up proving its own
    inability to see.
    """
    near = _side("Maternal", "maternal")
    far = _side("Paternal", "paternal")
    viewer = Member.objects.create(display_name="The viewer")
    PodMembership.objects.create(member=viewer, pod=near["pod"])

    own, across = _PROBES[model_name](viewer, near, far)
    assert own, (
        f"the {model_name} probe cannot see the viewer's OWN yard either, so its "
        "cross-yard result below means nothing — the probe is broken, not the isolation"
    )
    assert not across, (
        f"a {model_name} in a yard the viewer is not in was reachable through the audience "
        "query. S-202: existence and content are both confidential across a yard boundary."
    )
