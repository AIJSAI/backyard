"""Core models for Backyard.

The domain is pods and yards (docs/research/2026-07-20-founder-knowledge-capture.md):
a pod is a household or an ad-hoc group, a yard is one side of a family with its
own backyard feed, and a pod can belong to more than one yard so the founding
household can bridge both sides. That multi-yard pod is modeled from the first
migration on purpose; retrofitting it later would be the migration we refuse to
need. Yard is the isolation boundary the S-202 suite enforces (docs/security/
threat-model.md TM-1, TM-2).
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models


def _media_token() -> str:
    """An unguessable URL handle for a media asset or one of its derivatives. Each
    derivative gets its own, so a thumbnail id is never derivable from its source
    (TM-9). token_urlsafe(32) yields ~43 URL-safe characters, over 256 bits."""
    return secrets.token_urlsafe(32)


class Yard(models.Model):
    """One side of a family, with its own shared backyard feed.

    The isolation boundary: a member of one yard must never see or infer the
    existence of another yard's content (S-202). Yards are created by the
    first-run wizard and by admins, never self-serve.
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    # Which fixture generator, if any, created this yard. Empty means a real person did.
    # Yard could have been scoped by slug — and the old wipe did exactly that — but then
    # the wipe had two selection rules, one per model, and the second one (`Pod`) had no
    # identifier to use. One rule across all three is the point.
    seeded_by = models.CharField(max_length=32, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Pod(models.Model):
    """A household or an ad-hoc group. Scopes every post.

    A pod belongs to one or more yards. The bridging household belongs to both;
    every other pod belongs to exactly one. Pods are the unit a post is scoped
    to, and pod membership, not yard membership, is what grants a member sight of
    a pod's own content.
    """

    HOUSEHOLD = "household"
    ADHOC = "adhoc"
    KIND_CHOICES = [(HOUSEHOLD, "Household"), (ADHOC, "Ad-hoc group")]

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=HOUSEHOLD)
    # A pod in more than one yard is the bridge; this M2M carries that from day one.
    yards = models.ManyToManyField(Yard, related_name="pods")
    # The member who created an ad-hoc pod and may set its house rule and add members
    # (S-204). Null for household pods, which admins create.
    owner = models.ForeignKey(
        "Member", null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_pods"
    )
    # A one-sentence house rule shown at the top of an ad-hoc pod (S-204). Optional.
    house_rule = models.CharField(max_length=200, blank=True)
    # Which fixture generator, if any, created this pod. Empty means a real person made it.
    #
    # This exists because the demo wipe could not be written safely without it. Every
    # destructive cascade in this schema passes through Pod -- posts, comments, media,
    # reactions, invites, memberships, mutes, weekly metrics -- and Pod carried no stable
    # identifier at all: no slug, no unique key, only a free-text `name` a member can edit.
    # Yard has a unique slug and User has a username, which is why the wipe could scope
    # those two lines and had to fall back to `Pod.objects.all().delete()` for this one.
    #
    # Empty is the default, so every row that exists today and every pod a family makes
    # from now on is un-wipeable by construction. It fails closed.
    seeded_by = models.CharField(max_length=32, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Member(models.Model):
    """A person in the family.

    Account-holders link to a Django user; supervised children and (in a later
    wave) token-only elders may hold a Member without a standard login, which is
    why `user` is nullable. `token_generation` is the ADR-003 revocation anchor:
    every credential a member holds carries it, and one bump kills them all at
    once (TM-1). Roles are the small documented set from S-701.
    """

    MEMBER = "member"
    POD_OWNER = "pod_owner"
    YARD_ADMIN = "yard_admin"
    INSTANCE_ADMIN = "instance_admin"
    SUPERVISED = "supervised"
    ROLE_CHOICES = [
        (MEMBER, "Member"),
        (POD_OWNER, "Pod owner"),
        (YARD_ADMIN, "Yard admin"),
        (INSTANCE_ADMIN, "Instance admin"),
        (SUPERVISED, "Supervised member"),
    ]
    # S-907. The roster used to render these five names and nothing else, so the
    # relative being handed the admin controls had to be TOLD, out of band, what
    # picking one would do. One sentence each, in the member's own words rather than
    # the matrix's vocabulary ("side of the family", not "yard").
    #
    # This is the single source the roster reads. It is bound to reality in two
    # directions by test_role_descriptions.py: each sentence's claim is exercised
    # against permissions.py (so a description cannot promise what the code refuses),
    # and against docs/security/permission-matrix.md (so the prose and the doc cannot
    # drift apart silently).
    ROLE_DESCRIPTIONS = {
        MEMBER: "Posts and replies. No say over anyone else.",
        # Both affirmative halves of this sentence used to be false, in the copy shown
        # beside the control that grants the role. It said "Sets their household's house
        # rule and invites people into it" — `pods.set_house_rule` raises "A household pod
        # has no house rule", and `permissions.can_issue_invite` returns False for this
        # role. NO authorization predicate anywhere reads it.
        #
        # The capability people mean by "pod owner" is real, but it is the `Pod.owner`
        # FOREIGN KEY on an AD-HOC pod, held by whoever created it — any plain member. The
        # ROLE is a label. `docs/retro/2026-07-22-phase-2-retro.md` already ruled "Activate
        # pod_owner? No", and it is no longer offered by the roster; the constant stays for
        # the rows that already carry it.
        POD_OWNER: (
            "The same as a member. Setting a house rule and adding people comes from "
            "creating an ad-hoc group, not from this label."
        ),
        YARD_ADMIN: (
            "Manages members, but only on their own side of the family. "
            "Cannot touch an admin, or anyone who also belongs to the other side."
        ),
        INSTANCE_ADMIN: "Manages anyone, on either side. This is the whole instance.",
        SUPERVISED: "A managed account with no login of its own. Their parent edits it.",
    }

    # PROTECT, not SET_NULL: deleting the auth User looks like offboarding but revokes
    # nothing (the Member keeps their pods and token_generation). Removal must go through
    # the S-702 revocation path, which detaches this link explicitly after revoking;
    # PROTECT makes the shortcut impossible (security review MEDIUM-1, TM-1).
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="member",
    )
    display_name = models.CharField(max_length=100)
    # The name the kids actually call them (Nana, Uncle Jim), shown beside the
    # legal name (S-901). Optional.
    kinship_name = models.CharField(max_length=50, blank=True)

    # Profile (S-901, S-902). Birthday stores month and day; year is optional and age
    # is never displayed anywhere. Contact fields are optional, each carrying its own
    # per-field visibility scoped to the member's pods or yards (S-902); a member sees
    # and changes exactly who sees each field.
    HIDDEN = "hidden"
    POD = "pod"
    YARD = "yard"
    FIELD_VISIBILITY_CHOICES = [
        (HIDDEN, "No one"),
        (POD, "People in my pods"),
        (YARD, "People in my yards"),
    ]
    birthday_month = models.PositiveSmallIntegerField(null=True, blank=True)
    birthday_day = models.PositiveSmallIntegerField(null=True, blank=True)
    birthday_year = models.PositiveSmallIntegerField(null=True, blank=True)
    # Dates are per-field visible like contact data, never auto-broadcast (S-903,
    # T-MINOR-6). Ordinary members default to YARD, the documented decision
    # (threat model design tension 6) that matches the directory's original reach;
    # supervised members are narrowed to POD at creation and by migration 0013.
    birthday_visibility = models.CharField(
        max_length=8, choices=FIELD_VISIBILITY_CHOICES, default=YARD
    )
    anniversary_month = models.PositiveSmallIntegerField(null=True, blank=True)
    anniversary_day = models.PositiveSmallIntegerField(null=True, blank=True)
    anniversary_year = models.PositiveSmallIntegerField(null=True, blank=True)
    anniversary_visibility = models.CharField(
        max_length=8, choices=FIELD_VISIBILITY_CHOICES, default=YARD
    )
    phone = models.CharField(max_length=40, blank=True)
    phone_visibility = models.CharField(
        max_length=8, choices=FIELD_VISIBILITY_CHOICES, default=HIDDEN
    )
    contact_email = models.EmailField(blank=True)
    contact_email_visibility = models.CharField(
        max_length=8, choices=FIELD_VISIBILITY_CHOICES, default=HIDDEN
    )
    address = models.CharField(max_length=255, blank=True)
    address_visibility = models.CharField(
        max_length=8, choices=FIELD_VISIBILITY_CHOICES, default=HIDDEN
    )

    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=MEMBER)
    is_supervised = models.BooleanField(default=False)
    # The parent who manages a supervised account, and the only party who can
    # recover or convert it (S-703, TM-10). Null for ordinary members.
    managing_parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supervised_members",
    )
    # Bumped by the TM-1 revocation handler; every derived credential is checked
    # against it, so removal or regeneration kills all of a member's access at once.
    token_generation = models.PositiveIntegerField(default=1)
    # When the member last opened their feed. The feed uses it to draw one
    # unread boundary (S-303) between what is new since that visit and what they
    # already saw; it is advanced on each feed open. Null until the first visit.
    feed_last_seen_at = models.DateTimeField(null=True, blank=True)
    # S-906. Null means "has never dismissed the orientation", which is how a
    # brand-new member is recognised. Deliberately NOT derived from
    # feed_last_seen_at: that advances on the first feed render, so an orientation
    # keyed to it would vanish the moment someone tapped Pods and came back — before
    # they had read it. Existing members are backfilled at migration time, so this
    # only ever appears for people who arrive after it ships.
    orientation_dismissed_at = models.DateTimeField(null=True, blank=True)
    pods: models.ManyToManyField[Pod, PodMembership] = models.ManyToManyField(
        Pod, through="PodMembership", related_name="members"
    )
    # Which fixture generator, if any, created this member. Empty means a real person.
    #
    # Pod alone would not be enough. Elders and supervised children have `user = NULL`, so
    # they cannot be identified by username the way the seed's three logins can -- and the
    # old wipe's `exclude(user__username="james")` therefore swept up every real elder and
    # every real child. Worse, it was keyed to a string literal: on an instance whose
    # superuser is named anything else, nothing was excluded and the founder's own Member
    # row went with the rest. Marking the row removes both problems.
    seeded_by = models.CharField(max_length=32, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name


class PodMembership(models.Model):
    """A member's membership in a pod.

    A member can belong to several pods (their household plus any ad-hoc pods);
    a pod has many members. The member's visible yards are the union of the yards
    of every pod they belong to, which is how the bridging household sees both
    sides. This is the join the authorization guard reads (core/scoping.py).
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="pod_memberships")
    pod = models.ForeignKey(Pod, on_delete=models.CASCADE, related_name="memberships")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["member", "pod"], name="unique_member_pod"),
        ]

    def __str__(self) -> str:
        return f"{self.member} in {self.pod}"


class PodMute(models.Model):
    """A member's private mute of a pod (S-205). Muting silently hides that pod's
    posts from the muter's feed and nobody else; it is a personal display choice, not
    a membership or authorization change, so the muted posts stay reachable by direct
    link and the mute is invisible to everyone else. Leaving a pod is a separate,
    equally quiet act (deleting the PodMembership) with no broadcast.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="pod_mutes")
    pod = models.ForeignKey(Pod, on_delete=models.CASCADE, related_name="mutes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["member", "pod"], name="unique_member_pod_mute"),
        ]

    def __str__(self) -> str:
        return f"{self.member} muted {self.pod}"


class Post(models.Model):
    """A post in the feed: a short text update or link (photos land in wave 3),
    scoped to an audience.

    The audience is the poster's own pod (the narrowest default, TM-3) or one or
    more yards the poster belongs to (S-203). A yard-scoped post lists those yards
    in `audience_yards`; a pod-only post lists none, and reaches only the pod's
    members (an ad-hoc pod post never leaks to the wider yard, S-204).

    Isolation (TM-2, S-202): a post never reaches a member who shares neither its
    pod (pod-only) nor one of its audience yards. That rule lives once, in the
    audience-resolution module (core/scoping.visible_posts), which the feed, the
    digest, and search all consume; there is no second implementation to drift.
    Delete is a soft delete here so the feed and digest both stop showing it
    through the same query; a hard purge of media derivatives lands with media.

    AUDIENCE-INTEGRITY INVARIANT (security review of PR #21, MEDIUM #4): the model
    itself does not constrain audience_yards or pod to the author's scope, and the
    read query faithfully honors whatever is set. So the composer that writes a
    Post MUST enforce, in its service and with tests, that every audience_yards
    entry is in the author's yards (scoping.member_yard_ids) and pod is one of the
    author's pods (scoping.member_pod_ids). Without that, an author could publish
    into a yard they do not belong to. This is a hard requirement for the composer
    increment (S-203), not an option.
    """

    author = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="posts")
    pod = models.ForeignKey(Pod, on_delete=models.CASCADE, related_name="posts")
    audience_yards = models.ManyToManyField(Yard, blank=True, related_name="posts")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # A moderator takedown (S-713) sets deleted_at like an author self-delete, so the one
    # audience query treats the post as gone everywhere, AND records who moderated it — the
    # accountability trail a takedown needs (an author self-delete leaves this null, so the
    # two are distinguishable and a future restore/audit surface has what it needs).
    # SET_NULL, not CASCADE: removing the moderator later must not erase the tombstone.
    moderated_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderated_posts",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self) -> str:
        return f"Post by {self.author} at {self.created_at:%Y-%m-%d %H:%M}"


class Comment(models.Model):
    """A reply under a post (born in wave 2 alongside posts, ahead of its
    email-reply ingress in wave 4, S-502).

    A comment has no audience of its own: it is visible to exactly the audience of
    its post, so it inherits the post's scope through the single audience query
    (scoping.visible_comments filters on scoping.visible_posts). There is no second
    audience path to drift (TM-2). Anyone who can see the post may comment; delete
    is author-only and soft, mirroring the post lifecycle. Deleting or narrowing a
    post takes its comments with it, because they resolve through the post.
    """

    author = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="comments")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField()
    # Comments that arrived by email carry a visible badge (S-502): a reader can
    # always tell a typed reply from an emailed one, which is also the social
    # backstop against a forged reply reading as in-person (T-TOKEN-8).
    via_email = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # A moderator takedown (S-713) records who moderated the comment, exactly like Post:
    # deleted_at hides it through the one query, moderated_by is the accountability trail
    # (null for an author self-delete). SET_NULL keeps the tombstone if the moderator goes.
    moderated_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderated_comments",
    )

    class Meta:
        # Oldest first: a comment thread reads top to bottom under its post.
        ordering = ["created_at"]
        indexes = [models.Index(fields=["post", "created_at"])]

    def __str__(self) -> str:
        return f"Comment by {self.author} on post {self.post_id}"


class LinkPreview(models.Model):
    """A card for the first URL in a post (S-301). The stored URL has tracking
    parameters stripped; title and description come from a safely-fetched preview
    when one is available and are blank otherwise, so the card degrades to a bare
    link (graceful fallback). image_url is captured but not rendered until wave 3
    re-hosts it, because hotlinking a remote image is the tracking-beacon and
    IP-disclosure leak TS-PP-6 forbids. A preview inherits its post's audience by
    living on the post; it is never fetched or shown outside the post.
    """

    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name="link_preview")
    url = models.URLField(max_length=2000)
    title = models.CharField(max_length=300, blank=True)
    description = models.CharField(max_length=600, blank=True)
    # The remote og:image URL, captured for the record and as the re-host source. It is
    # NEVER rendered (hotlinking is the TS-PP-6 beacon/IP-disclosure leak); the card shows
    # image_asset instead, a copy re-fetched SSRF-safely and re-encoded through the media
    # store, served only through the access-checked media view.
    image_url = models.URLField(max_length=2000, blank=True)
    # The re-hosted preview image (S-301): a LINK_PREVIEW-kind MediaAsset on the same post,
    # so it inherits the post's audience and rides purge_post_media on delete. Null when the
    # target had no og:image, or it could not be safely fetched/decoded (graceful fallback).
    image_asset = models.OneToOneField(
        "MediaAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="link_preview_image_of",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Preview for post {self.post_id}: {self.url}"


class MediaAsset(models.Model):
    """A photo or a short video attached to a post (S-401, S-402). Re-encoded and
    metadata-stripped at ingest (TM-9), stored off any web-served path, and served
    only through the access-checked media view that inherits the post's audience
    (S-403, T-MEDIA-1).

    Two independently unguessable tokens are the only handles a URL ever uses, and a
    derivative token is never derivable from the source (TM-9). Their meaning is by
    kind: for a PHOTO, `token` serves the full image and `thumbnail_token` the
    thumbnail; for a VIDEO, `token` serves the transcoded H.264 rendition and
    `thumbnail_token` the poster frame. content_type is pinned from the produced
    format at ingest, never the client's claim (TS-PP-4). Soft delete stops the
    serving path (the view checks it); the hard purge of the files themselves is
    T-MEDIA-6, covering every derivative including the retained source.

    A video is born PENDING: ingest stores a metadata-stripped `source` (never served)
    and the worker transcodes it to `video` + a poster in `thumbnail`, flipping
    transcode_status to DONE (or FAILED on a clip the hardened ffmpeg refuses). The
    feed renders the state so a member never hits a mystery failure (S-402).
    """

    PHOTO = "photo"
    VIDEO = "video"
    # A re-hosted link-preview og:image (S-301). Stored and served exactly like a PHOTO
    # (token -> image, image/jpeg) so it rides the one access-checked media path, but it
    # is NOT part of the post's own gallery, so the feed and post views exclude it.
    LINK_PREVIEW = "link"
    MEDIA_KIND_CHOICES = [(PHOTO, "Photo"), (VIDEO, "Video"), (LINK_PREVIEW, "Link preview")]

    # A photo has nothing to transcode, so it is born DONE; only a video walks
    # PENDING -> DONE|FAILED. The template reads this to render the clip's state.
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    TRANSCODE_STATUS_CHOICES = [(PENDING, "Pending"), (DONE, "Done"), (FAILED, "Failed")]

    # S-404. An asset hangs off EXACTLY ONE of a post or a comment, enforced by a
    # database constraint rather than by convention, because both the audience query
    # and the purge branch on which one is set: a row with neither would be
    # unreachable and unpurgeable, and a row with both would have two audiences.
    #
    # A comment carries no audience of its own — it inherits its post's — so comment
    # media inherits the COMMENT's audience and therefore the post's, through the same
    # single query. There is deliberately no second audience path to drift (TM-2).
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="media", null=True, blank=True
    )
    comment = models.ForeignKey(
        "Comment", on_delete=models.CASCADE, related_name="media", null=True, blank=True
    )
    media_kind = models.CharField(max_length=5, choices=MEDIA_KIND_CHOICES, default=PHOTO)
    token = models.CharField(max_length=43, unique=True, default=_media_token)
    thumbnail_token = models.CharField(max_length=43, unique=True, default=_media_token)
    image = models.ImageField(upload_to="media/full/", blank=True)
    thumbnail = models.ImageField(upload_to="media/thumb/", blank=True)
    # Video only: the metadata-stripped original (retained for re-transcode and member
    # export, T-MEDIA-6; never served) and the transcoded, re-encoded H.264 rendition.
    source = models.FileField(upload_to="media/source/", blank=True)
    video = models.FileField(upload_to="media/video/", blank=True)
    transcode_status = models.CharField(
        max_length=7, choices=TRANSCODE_STATUS_CHOICES, default=DONE
    )
    content_type = models.CharField(max_length=32)
    alt_text = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["post", "created_at"]),
            models.Index(fields=["comment", "created_at"]),
        ]
        constraints = [
            # Exactly one owner. Enforced in the DATABASE, not in a service function:
            # every reader and every purge decides by branching on which FK is set, so
            # neither "orphan" (unreachable, unpurgeable bytes) nor "both" (two
            # audiences for one asset) may exist at all.
            models.CheckConstraint(
                condition=models.Q(post__isnull=False, comment__isnull=True)
                | models.Q(post__isnull=True, comment__isnull=False),
                name="mediaasset_exactly_one_owner",
            )
        ]

    def __str__(self) -> str:
        where = f"post {self.post_id}" if self.post_id else f"reply {self.comment_id}"
        return f"{self.get_media_kind_display()} {self.token[:8]} on {where}"

    @property
    def owning_post_id(self) -> int:
        """The post whose audience this asset inherits, whichever way it is attached.

        The check constraint guarantees exactly one owner, so this cannot legitimately
        fail — but it raises rather than returning None if the invariant is ever
        broken, because a caller that silently got None would compute an EMPTY
        audience and read as "nobody may see this" instead of "this row is corrupt".
        """
        if self.post_id is not None:
            return self.post_id
        comment = self.comment
        if comment is not None:
            return int(comment.post_id)
        raise ValueError(f"media {self.token[:8]} has no owner; the constraint was bypassed")


class Reaction(models.Model):
    """A named reaction to a post (S-304). Reactions show WHO reacted, never a count
    or a leaderboard: there is deliberately no tally field, and the UI lists reactors
    by name. A member holds at most one reaction per post (picking a new kind replaces
    it; removing it deletes the row). A reaction inherits its post's audience, so the
    reactor list is scoped by the same query and never leaks across a yard.
    """

    HEART = "heart"
    LAUGH = "laugh"
    WOW = "wow"
    HUG = "hug"
    SAD = "sad"
    KIND_CHOICES = [
        (HEART, "Love"),
        (LAUGH, "Ha"),
        (WOW, "Wow"),
        (HUG, "Hug"),
        (SAD, "Sad"),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="reactions")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["member", "post"], name="one_reaction_per_member_post"),
        ]

    def __str__(self) -> str:
        return f"{self.member} reacted {self.kind} to post {self.post_id}"


class NotificationPreference(models.Model):
    """A member's push preferences (S-305), which are a negative guarantee. The only
    opt-in that exists is replies to my own posts, and it defaults OFF, so a member
    is pushed nothing unless they explicitly ask, and even then only for replies to
    them. There is deliberately no all-activity firehose field: the absence is the
    feature, and a test asserts this model grows no such option.
    """

    member = models.OneToOneField(
        Member, on_delete=models.CASCADE, related_name="notification_preference"
    )
    # The one and only push opt-in. Off by default (zero push for every event type).
    notify_on_reply = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Notification preference for {self.member} (reply={self.notify_on_reply})"


class Invite(models.Model):
    """A household or member invite: a bearer credential held to the TM-5 bar.

    The raw token is at least 128 bits from a CSPRNG, shown once at creation, and
    stored only as a SHA-256 digest (lookups are by digest, so no per-row password
    hashing is needed; the token itself is high-entropy and unguessable). Invites
    expire by default, carry a use cap sized to a household, are revocable, and
    every join from one is recorded so an admin can see exactly who an invite
    minted (S-201, T-INVITE-1, T-YARD-G1). Loading an invite URL never consumes
    it; joining is an explicit POST (S-101).

    Revocation runs through the TM-1 registry (core/revocation.py): revoking a
    member voids the invites they created, and removal voids every invite that
    reaches the member's pods.
    """

    pod = models.ForeignKey(Pod, on_delete=models.CASCADE, related_name="invites")
    token_digest = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="invites_created"
    )
    expires_at = models.DateTimeField()
    max_uses = models.PositiveSmallIntegerField(default=8)
    use_count = models.PositiveSmallIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invite to {self.pod} ({self.use_count}/{self.max_uses})"


class InviteRedemption(models.Model):
    """Who joined from which invite, when: the join-visibility record S-201's
    hardening requires ("the admin can see, per invite, exactly who joined from it
    and when")."""

    invite = models.ForeignKey(Invite, on_delete=models.CASCADE, related_name="redemptions")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="invite_redemptions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.member} joined via invite {self.invite_id}"


class BackupRun(models.Model):
    """One completed backup (S-806, T-MON-1).

    Nothing recorded that a backup had ever run, so "last-backup age" — the first field
    T-MON-1's health email asks for — was not answerable at all. A dead backup cron was
    indistinguishable from a healthy one, which is precisely the "nothing is watching"
    condition that gives every other threat unlimited dwell time.

    Written by the backup command AFTER the archive is complete, never before: a row
    written on entry would make a crashed backup look like a successful one, which is
    worse than no row at all.
    """

    finished_at = models.DateTimeField(auto_now_add=True)
    byte_count = models.BigIntegerField()
    encrypted = models.BooleanField()

    class Meta:
        ordering = ["-finished_at"]

    def __str__(self) -> str:
        kind = "encrypted" if self.encrypted else "PLAINTEXT"
        return f"{kind} backup of {self.byte_count} bytes at {self.finished_at:%Y-%m-%d %H:%M}"


class DomainStatus(models.Model):
    """The instance domain's expiry, refreshed on the worker (S-806, T-OP-G4).

    A lapsed domain hands every printed QR and bookmarked elder link to a squatter, and a
    bearer URL cannot be bound to the new-versus-old host — so renewal discipline plus
    detection is the whole control. This row is the detection half.

    Cached rather than looked up when the email is built: an outbound lookup inside the
    send path would make a registry outage a missing health email, which is the one moment
    the operator most needs to hear from the instance. `checked_at` and `error` make a
    STALE answer visible as stale instead of passing an old number off as current.
    """

    domain = models.CharField(max_length=253, unique=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name_plural = "domain statuses"

    def __str__(self) -> str:
        return (
            f"{self.domain} expires {self.expires_at:%Y-%m-%d}" if self.expires_at else self.domain
        )


class DigestSubscription(models.Model):
    """A member's digest enrollment (S-501): where, how often, and whether at all.

    The confirm-before-first-content rule (T-EMAIL-6) lives in `confirmed_at`: no
    digest carrying family content is ever sent while it is null, which kills the
    typo'd-enrollment path (a stranger's mailbox gets one content-free confirmation
    and nothing else, ever). The confirm and unsubscribe tokens are bearer
    capabilities held to the Invite bar: >=128-bit CSPRNG raw values shown once,
    SHA-256 digests at rest, voided by the TM-1 revocation registry. Disabling a
    subscription flips `enabled` only; it never touches PodMembership (unsubscribe
    is about email, membership severing is S-702's job, and nothing here does both).
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CADENCE_CHOICES = [(DAILY, "Daily"), (WEEKLY, "Weekly"), (MONTHLY, "Monthly")]

    member = models.OneToOneField(
        Member, on_delete=models.CASCADE, related_name="digest_subscription"
    )
    address = models.EmailField()
    cadence = models.CharField(max_length=8, choices=CADENCE_CHOICES, default=WEEKLY)
    enabled = models.BooleanField(default=True)
    # T-EMAIL-6: family content flows only after the address holder acknowledged
    # a content-free confirmation. Reset whenever the address changes.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_token_digest = models.CharField(max_length=64, blank=True)
    unsubscribe_token_digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        state = "confirmed" if self.confirmed_at else "unconfirmed"
        return f"Digest for {self.member} ({self.cadence}, {state})"


class DigestIssue(models.Model):
    """One digest actually assembled for one (member, yard) over one window.

    Per-yard on purpose: a multi-yard member gets separate per-yard emails, and no
    single issue ever fuses two yards (S-501 hardening, T-YARD-9). Rows are created
    by the send path at send time; their existence is what the cadence clock reads.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="digest_issues")
    yard = models.ForeignKey(Yard, on_delete=models.CASCADE, related_name="digest_issues")
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "yard", "window_start"],
                name="digest_issue_once_per_member_yard_window",
            )
        ]

    def __str__(self) -> str:
        return f"Digest issue for {self.member} / {self.yard} at {self.window_end}"


class DigestDelivery(models.Model):
    """What the transport said about one issue: transport-level truth ONLY.

    Until the ADR-002 delivery-and-bounce matrix is measured for a chosen provider
    (the wave-4 gate), these statuses claim nothing the transport did not say:
    handed to the relay, rejected at submission, or a DSN held for the admin.
    Bounces only ever update this panel; nothing auto-suppresses a subscription
    (T-EMAIL-6: a forged DSN must not silently sever an elder).
    """

    HANDED_TO_RELAY = "handed_to_relay"
    REJECTED = "rejected"
    DSN_QUARANTINED = "dsn_quarantined"
    STATUS_CHOICES = [
        (HANDED_TO_RELAY, "Handed to relay"),
        (REJECTED, "Rejected at submission"),
        (DSN_QUARANTINED, "Bounce held for review"),
    ]

    issue = models.ForeignKey(DigestIssue, on_delete=models.CASCADE, related_name="deliveries")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Delivery of issue {self.issue_id}: {self.status}"


class DigestToken(models.Model):
    """A per-member, per-digest read link (ADR-003 rule 1, TM-5, T-EMAIL-3).

    The deep links inside one digest email all carry one of these: read-only,
    expiring, scoped to that issue's member and yard, never the master token. The
    raw value is >=128-bit CSPRNG, lives only inside the sent email, and is stored
    here as a SHA-256 digest (the Invite pattern). `minted_generation` is checked
    against Member.token_generation on every request (ADR-003 rule 3), so TTL is
    the freshness bound, never the revocation mechanism; revocation also deletes
    the rows outright through the TM-1 registry, belt and suspenders.
    """

    issue = models.ForeignKey(DigestIssue, on_delete=models.CASCADE, related_name="tokens")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="digest_tokens")
    token_digest = models.CharField(max_length=64, unique=True)
    minted_generation = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    # The pixel-free digest-open proxy (S-705, docs/metrics.md): stamped once on
    # the first successful resolve. Never a tracker: no per-open log exists,
    # only this one timestamp feeding weekly aggregate counts.
    first_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Digest token for issue {self.issue_id} (expires {self.expires_at})"


class ReplyAddress(models.Model):
    """A per-member, per-post reply capability (S-502, TM-4).

    The local part of a digest's reply address IS the credential: >=128-bit
    CSPRNG raw value living only inside that digest email, SHA-256 at rest.
    Attribution comes from this row alone; the From: header is only a
    consistency check that quarantines on mismatch and never attributes.

    Three independent kill clocks (each asserted separately in the suite):
    supersession — a newer issue's minting stamps superseded_at, and a
    superseded address dies after the reply grace window (T-EMAIL-2, forwarded
    digests expire); voiding — voided_at set by the TM-1 registry on removal
    and by pod-leave for posts no longer visible (S-502: revoked on ANY
    membership change); generation — minted_generation checked against the
    member's current one on every resolve (ADR-003). Satisfying one clock
    never masks another.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="reply_addresses")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reply_addresses")
    issue = models.ForeignKey(DigestIssue, on_delete=models.CASCADE, related_name="reply_addresses")
    local_part_digest = models.CharField(max_length=64, unique=True)
    minted_generation = models.PositiveIntegerField()
    superseded_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Reply address for member {self.member_id} post {self.post_id}"


class InboundLedger(models.Model):
    """Processed-mail idempotency (S-502): an IMAP re-poll of the same message
    never posts twice. Keyed on the Message-ID digest plus the capability it
    arrived on, so a replayed or duplicated fetch is a silent no-op."""

    message_id_digest = models.CharField(max_length=64)
    local_part_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["message_id_digest", "local_part_digest"],
                name="inbound_once_per_message_and_capability",
            )
        ]

    def __str__(self) -> str:
        return f"Inbound ledger entry {self.message_id_digest[:12]}"


class InboundQuarantine(models.Model):
    """Inbound mail held for the instance admin instead of posted (T-EMAIL-G2,
    T-EMAIL-1): From mismatch, a missing reply separator, a malformed or
    oversized message, or an over-rate sender. Rows hold email content, so the
    panel is instance-admin-only and rows are deleted once handled (T-OP-G2)."""

    FROM_MISMATCH = "from_mismatch"
    NO_SEPARATOR = "no_separator"
    MALFORMED = "malformed"
    RATE_LIMITED = "rate_limited"
    REASON_CHOICES = [
        (FROM_MISMATCH, "From did not match the member's address"),
        (NO_SEPARATOR, "Reply separator not found"),
        (MALFORMED, "Malformed or oversized message"),
        (RATE_LIMITED, "Too many replies too fast"),
    ]

    reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    from_header = models.CharField(max_length=254, blank=True)
    body_excerpt = models.TextField(blank=True)  # capped at write time
    # SET_NULL, not CASCADE. This table is the instance admin's moderation queue: it holds
    # the inbound mail that was refused and why. A nullable FK whose deletion destroys the
    # evidence is backwards — the queue's whole job is to survive the thing it is a record
    # of. `null=True` already says a row without a member is meaningful; CASCADE said the
    # opposite, and deleting members took the admin's record of their refused mail with it.
    member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="quarantined_mail"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Quarantined inbound mail ({self.reason})"


class YardWeekMetrics(models.Model):
    """One yard's weekly connection health (S-705): aggregates ONLY.

    Counts, never content and never per-person activity: the rollup stores how
    many, not who did what (the sole per-person datum lives on
    MemberWeekPresence as a yes/no, disclosed to the family in the docs). The
    anti-surveillance test pins these field sets exactly, so a
    surveillance-shaped column cannot arrive silently (docs/metrics.md
    anti-metrics: no time-on-site, no sessions, no streaks, ever).
    """

    yard = models.ForeignKey(Yard, on_delete=models.CASCADE, related_name="week_metrics")
    week_start = models.DateField()
    member_count = models.PositiveIntegerField()
    wcm = models.PositiveIntegerField()  # Weekly Connected Members
    posting_breadth = models.PositiveIntegerField()  # distinct pods that posted
    posts_in_week = models.PositiveIntegerField()
    posts_responded = models.PositiveIntegerField()  # reciprocity numerator
    catch_up_members = models.PositiveIntegerField()  # members with a feed visit
    digest_opens = models.PositiveIntegerField()  # first-use proxy, undercounted
    email_replies = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["yard", "week_start"], name="yard_metrics_once_per_week"
            )
        ]

    def __str__(self) -> str:
        return f"{self.yard} week {self.week_start}: WCM {self.wcm}/{self.member_count}"


class PodWeekMetrics(models.Model):
    """One pod's weekly posting count (S-705). A count, nothing else."""

    pod = models.ForeignKey(Pod, on_delete=models.CASCADE, related_name="week_metrics")
    week_start = models.DateField()
    post_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["pod", "week_start"], name="pod_metrics_once_per_week")
        ]

    def __str__(self) -> str:
        return f"{self.pod} week {self.week_start}: {self.post_count} posts"


class MemberWeekPresence(models.Model):
    """THE one per-person datum (S-705, verbatim): a yes/no weekly presence.

    The measured family is told about it in the docs. No timestamps of touches,
    no counts per person, no activity types — present or not, per week.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="week_presence")
    week_start = models.DateField()
    present = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["member", "week_start"], name="presence_once_per_week")
        ]

    def __str__(self) -> str:
        return f"{self.member} week {self.week_start}: {'present' if self.present else 'quiet'}"


class ElderToken(models.Model):
    """The elder path's master credential (S-102, TM-5, ADR-003).

    One live token per member: a long-lived tokenized URL that opens the
    large-text feed with no login. The default is NO expiry, recorded in
    ADR-003: months of use with no re-auth is the requirement, and revocation
    (the generation check plus row deletion through the TM-1 registry), not
    TTL, is what kills it. >=128-bit raw value, SHA-256 at rest, never issued
    to a supervised member (TM-10). The URL is exchanged for an httpOnly
    session cookie on first open (TM-5), so the token itself is not replayed
    on every request.
    """

    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="elder_token")
    token_digest = models.CharField(max_length=64, unique=True)
    minted_generation = models.PositiveIntegerField()
    expires_at = models.DateTimeField(null=True, blank=True)  # null = the no-expiry default
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Elder token for {self.member}"


class SetupToken(models.Model):
    """One-time secret gating the first-run wizard (threat model TM-8).

    Stored only as a password-style hash. Created at first boot when no admin
    exists, printed to the server console, and deleted the moment the first
    admin is created. The wizard's real gate is "zero admins exist", so this
    row is a convenience, not the security boundary.
    """

    token_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "setup token"

    def __str__(self) -> str:
        return f"SetupToken(created_at={self.created_at:%Y-%m-%d %H:%M})"
