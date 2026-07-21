"""Reply-address capabilities (S-502, TM-4): mint, resolve, and the kill clocks.

A digest's per-post reply address is a bearer capability in the local part:
`reply-<raw>@<sending domain>`, >=128-bit CSPRNG, SHA-256 at rest, minted per
(member, post, issue). Attribution comes from resolving it and from NOTHING
else — never the From: header (that is only a consistency check downstream).

Three kill clocks, independent by construction:
1. Supersession (T-EMAIL-2): minting a member's next issue stamps their older
   live addresses superseded_at. A superseded address keeps working through the
   reply grace window — elders answer three-week-old digests — then dies. The
   grace length is a founder-batch number; the proposed default lives here.
2. Voiding (TM-1 / S-502 "revoked on any membership change"): voided_at is
   stamped by the revocation registry on removal, and by pod-leave for posts
   the member can no longer see. Voided is dead immediately, grace or no grace.
3. Generation (ADR-003): minted_generation must equal the member's current
   token_generation on every resolve, so one bump kills every address at once.

An address that fails any clock resolves exactly like one that never existed
(ReplyAddressInvalid carries nothing): the bounce for "no such thread" and
"not your thread" is built downstream from one branch-free path.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.utils import timezone

from .models import DigestIssue, Member, Pod, ReplyAddress

# Proposed default, recorded for founder ratification at the wave boundary:
# addresses from a superseded digest keep working this long after supersession.
REPLY_GRACE = datetime.timedelta(days=30)

_LOCAL_PREFIX = "reply-"


class ReplyAddressInvalid(Exception):
    """Unknown, superseded-beyond-grace, voided, or generation-killed. Carries
    nothing on purpose: every failure shape must be indistinguishable."""


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_for_issue(issue: DigestIssue, post_ids: list[int]) -> dict[int, str]:
    """Mint one address per post for this issue and supersede the member's older
    live addresses (starting their grace clock). Returns {post_id: local part};
    the raw values live only in the email this issue produces."""
    now = timezone.now()
    ReplyAddress.objects.filter(
        member=issue.member, superseded_at__isnull=True, voided_at__isnull=True
    ).exclude(issue=issue).update(superseded_at=now)
    minted: dict[int, str] = {}
    for post_id in post_ids:
        raw = secrets.token_urlsafe(32)  # 256 bits
        ReplyAddress.objects.create(
            member=issue.member,
            post_id=post_id,
            issue=issue,
            local_part_digest=_digest(_LOCAL_PREFIX + raw),
            minted_generation=issue.member.token_generation,
        )
        minted[post_id] = _LOCAL_PREFIX + raw
    return minted


def resolve(local_part: str) -> ReplyAddress:
    """The live capability behind a local part, or ReplyAddressInvalid.

    All three clocks run on every resolve; the order never leaks (the exception
    is shapeless either way).
    """
    if not local_part:
        raise ReplyAddressInvalid
    address = (
        ReplyAddress.objects.select_related("member", "post")
        .filter(local_part_digest=_digest(local_part))
        .first()
    )
    if address is None:
        raise ReplyAddressInvalid
    if address.voided_at is not None:
        raise ReplyAddressInvalid
    if address.minted_generation != address.member.token_generation:
        raise ReplyAddressInvalid
    if address.superseded_at is not None and address.superseded_at <= timezone.now() - REPLY_GRACE:
        raise ReplyAddressInvalid
    return address


def void_for_member(member: Member) -> int:
    """Kill every reply capability the member holds, immediately (TM-1)."""
    return ReplyAddress.objects.filter(member=member, voided_at__isnull=True).update(
        voided_at=timezone.now()
    )


def void_for_pod_leave(member: Member, pod: Pod) -> int:
    """A member who left a pod can no longer see its posts, so their reply
    capabilities for those posts die with the membership (S-502: revoked on ANY
    membership change). The write path's own audience re-check is the second
    lock; this keeps the row state honest too."""
    return ReplyAddress.objects.filter(member=member, post__pod=pod, voided_at__isnull=True).update(
        voided_at=timezone.now()
    )
