"""Member removal (S-702): the lifecycle flow that revokes, then tears down.

Removal is the T-REMOVE-1 path: a removed member (a removed ex, a departed
relative) loses every credential AND their membership, in one atomic act. The
order is load-bearing and enforced here structurally, which is the fix the
revocation review's H-1 finding asked for:

  1. revoke_member_credentials FIRST, while the member's PodMembership rows still
     exist, because invite voiding resolves the yard scope from live memberships
     (revoking after teardown would silently miss reachable invites, reopening
     T-AUTH-G3).
  2. THEN tear down the memberships.
  3. THEN deactivate the User, so password login dies (the credential class the
     revocation registry names but the generic handler does not touch, because
     voluntary leave and regeneration must not deactivate an account).

The Member row is kept (deactivated), not deleted, so their authored content can
stay attributable if that is what the admin chooses.

S-702's second criterion — "Admin explicitly chooses: keep content attributed,
anonymize, or delete" — was deferred here to "the feed and media waves" and never
built, while the story sat at `passing`. Removal was a single POST with no
decision in it at all. The three outcomes are now explicit and required:

* KEEP — the content stays, attributed. The family's history is unchanged; this
  is right for someone who simply left.
* ANONYMIZE — the content stays, the person does not. Their name becomes a
  neutral placeholder and every contact field and date is cleared, so the thread
  still reads but no longer points at a named individual.
* DELETE — their posts and comments are soft-deleted and their media purged from
  disk. For the case this exists for: someone whose presence in the archive is
  itself the harm.

DELETE is soft at the row level and HARD for media bytes, matching how a member
deleting their own post already behaves (T-MEDIA-6): a photograph must not
survive on disk after someone has been told it is gone.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import models, transaction
from django.utils import timezone

from . import pods
from .models import Comment, MediaAsset, Member, Pod, PodMembership, Post
from .revocation import revoke_member_credentials

KEEP = "keep"
ANONYMIZE = "anonymize"
DELETE = "delete"
# The LABELS are what an admin reads beside three radio buttons, so they are short and
# parallel: same verb first, same shape, no clause explaining itself. They render inside a
# <label>, which the product capitalises.
CONTENT_CHOICES: tuple[tuple[str, str], ...] = (
    (KEEP, "Keep Their Posts"),
    (ANONYMIZE, "Keep Their Posts, Without Their Name"),
    (DELETE, "Delete Their Posts, Replies And Photos"),
)
_VALID = {choice for choice, _label in CONTENT_CHOICES}

# What an anonymized member is called afterwards. Deliberately not blank: a byline that
# renders as nothing reads like a bug, and the family should be able to tell that someone
# was here and chose to leave no name.
ANONYMOUS_NAME = "A family member"


class UnknownContentChoice(ValueError):
    """The caller did not make one of the three explicit choices."""


@dataclass(frozen=True)
class DeletionPreview:
    """Exactly what `remove_member(..., content=DELETE)` would destroy, counted now.

    The confirm step (NB-5) has to STATE what will be destroyed, and a sentence written
    by hand would drift from `_delete_content` the first time that function grew a clause
    — which is how `others_photos` came to be a field rather than a footnote. It is the
    one most likely to surprise the admin: deleting somebody's post purges the photos on
    OTHER people's replies to it too (purge_post_media takes `comment__post`), because the
    files would otherwise stay on the volume with their rows gone.

    `link_images` is the same lesson learned twice: the purge takes every asset on the
    post, `media_kind` and all, so a member whose only stored file was the re-hosted
    og:image of a link they shared (S-301) was shown a page that said nothing was erased
    while a file left the disk.
    """

    posts: int
    replies: int
    photos: int
    others_photos: int
    link_images: int


def preview_deletion(member: Member) -> DeletionPreview:
    """Count what a content=DELETE removal would destroy, straight from the querysets
    `_delete_content` uses, so the confirm page cannot promise a different act."""
    posts = Post.objects.filter(author=member, deleted_at__isnull=True)
    comments = Comment.objects.filter(author=member, deleted_at__isnull=True)
    # The three routes a file leaves the disk by, matching purge_post_media (the post's
    # own gallery plus every reply's) and purge_comment_media (their own replies).
    on_their_posts = models.Q(post__in=posts)
    on_replies_to_their_posts = models.Q(comment__post__in=posts)
    on_their_replies = models.Q(comment__in=comments)
    doomed = MediaAsset.objects.filter(
        on_their_posts | on_replies_to_their_posts | on_their_replies
    )
    # Split by kind rather than filtered down to one, because the purge takes EVERY asset
    # on the post — `purge_post_media` does not look at `media_kind` — and the page has to
    # describe the act it performs. Kept as two numbers, not one: a re-hosted link card is
    # not something anyone in this family would call a photograph, and folding it into the
    # count that carries the whole decision would overstate the loss just as badly as
    # leaving it out understated it.
    gallery = doomed.filter(media_kind__in=(MediaAsset.PHOTO, MediaAsset.VIDEO))
    return DeletionPreview(
        posts=posts.count(),
        replies=comments.count(),
        photos=gallery.distinct().count(),
        # Replies to their posts written by somebody else: the surprising half of the count.
        others_photos=MediaAsset.objects.filter(
            on_replies_to_their_posts, media_kind__in=(MediaAsset.PHOTO, MediaAsset.VIDEO)
        )
        .exclude(comment__author=member)
        .distinct()
        .count(),
        link_images=doomed.filter(media_kind=MediaAsset.LINK_PREVIEW).distinct().count(),
    )


def remove_member(member: Member, *, content: str) -> None:
    """Remove a member: revoke everything, detach, deactivate, and apply the content
    choice. Atomic — a half-applied removal is worse than none.

    `content` is REQUIRED and has no default. A default would quietly re-create the
    original defect: removal that silently keeps everything because nobody was asked.
    """
    if content not in _VALID:
        raise UnknownContentChoice(f"content must be one of {sorted(_VALID)}, not {content!r}")
    with transaction.atomic():
        # 1. Revoke while memberships are still live (H-1 ordering contract).
        revoke_member_credentials(member)
        # 2. Detach from every pod, then hand on anything they owned.
        #
        # Ownership follows membership (`pods.succeed_owner`). Without this, removing
        # somebody who owned an ad-hoc pod leaves it frozen: `pod.owner_id != actor.id` is
        # the only gate on its house rule and member list, and a removed member is no longer
        # a member — so nobody left in the group can manage it, permanently. That is the
        # same state `leave_pod` and the demo wipe already close, reached by the third route,
        # which is the one an admin actually uses.
        owned = list(Pod.objects.filter(owner=member, kind=Pod.ADHOC))
        PodMembership.objects.filter(member=member).delete()
        for pod in owned:
            pods.succeed_owner(pod)
        # 3. Kill password login. Removal-only: leave and regeneration keep the account.
        user = member.user
        if user is not None:
            user.is_active = False
            user.save(update_fields=["is_active"])
        # 4. The content choice, inside the same transaction as the revocation.
        if content == ANONYMIZE:
            _anonymize(member)
        elif content == DELETE:
            _delete_content(member)


def _anonymize(member: Member) -> None:
    """Strip the person from content that stays. The rows remain, so threads still read."""
    member.display_name = ANONYMOUS_NAME
    member.kinship_name = ""
    member.phone = ""
    member.contact_email = ""
    member.address = ""
    member.birthday_month = member.birthday_day = member.birthday_year = None
    member.anniversary_month = member.anniversary_day = member.anniversary_year = None
    member.save(
        update_fields=[
            "display_name",
            "kinship_name",
            "phone",
            "contact_email",
            "address",
            "birthday_month",
            "birthday_day",
            "birthday_year",
            "anniversary_month",
            "anniversary_day",
            "anniversary_year",
        ]
    )


def _delete_content(member: Member) -> None:
    """Soft-delete their posts and comments; purge their media bytes from disk.

    Soft at the row level so the audit trail and the archive-compatibility guarantees
    hold, HARD for media: a photograph must not survive on disk once someone has been
    told it is gone (T-MEDIA-6), which is exactly how a member deleting their own post
    already behaves.
    """
    from . import media
    from .models import Comment, Post

    now = timezone.now()
    posts = Post.objects.filter(author=member, deleted_at__isnull=True)
    for post in posts:
        media.purge_post_media(post)
    posts.update(deleted_at=now)
    # Their REPLIES on other people's posts carry media too (S-404), and those posts are
    # not theirs to delete — so the loop above never reaches them. Without this, a removed
    # member's reply photographs stay on the volume after they have been told their
    # content is gone, and the revocation-completeness promise (S-702, T-MEDIA-6) is only
    # true of the content they happened to author at the top level.
    comments = Comment.objects.filter(author=member, deleted_at__isnull=True)
    for comment in comments:
        media.purge_comment_media(comment)
    comments.update(deleted_at=now)
