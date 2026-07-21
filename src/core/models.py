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

from django.conf import settings
from django.db import models


class Yard(models.Model):
    """One side of a family, with its own shared backyard feed.

    The isolation boundary: a member of one yard must never see or infer the
    existence of another yard's content (S-202). Yards are created by the
    first-run wizard and by admins, never self-serve.
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
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
    pods: models.ManyToManyField[Pod, PodMembership] = models.ManyToManyField(
        Pod, through="PodMembership", related_name="members"
    )
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
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

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
    image_url = models.URLField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Preview for post {self.post_id}: {self.url}"


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
