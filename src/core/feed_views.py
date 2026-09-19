"""The feed and the composer (S-000, S-302, S-303, S-203).

The feed is the calm chronological surface: a member's visible posts, newest
first, that ends with a you-are-caught-up state (no infinite scroll, no counts).
The composer writes a post through the audience-integrity service (core/posting),
and enforces TM-3 here: the default audience is the poster's own pod (the
narrowest), and any send broader than the pod, or spanning more than one yard,
requires an explicit confirmation that names the audience and its member count.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import (
    commenting,
    drafts,
    media,
    moderation,
    notifications,
    permissions,
    pods,
    posting,
    profiles,
    reacting,
    scoping,
    staged_uploads,
    transcoding,
)
from .models import Comment, MediaAsset, Member, Pod, Post, Reaction

# Per-file upload ceiling at the application layer (the Caddy body cap is the edge
# control, TS-CA-4); a larger file is skipped rather than buffered and decoded.
_MAX_PHOTO_BYTES = 15 * 1024 * 1024
_MAX_PHOTOS = 20
# A handful of clips per post; each is size-, format-, and duration-capped by media
# (transcoding.MAX_VIDEO_*). Unlike a photo, a rejected video fails the whole compose
# with a clear message rather than being silently dropped (S-402).
_MAX_VIDEOS = 4

# A family text post, not an essay. Bounds the stored size of a single post so a
# crafted request cannot park megabytes of text behind the composer (the wider
# ceiling is Django's DATA_UPLOAD_MAX_MEMORY_SIZE; this is the friendly limit).
_MAX_BODY = 5000
# A reply is shorter still.
_MAX_COMMENT = 2000
# Cap the rendered thread so a pathological number of replies cannot inflate every
# co-viewer's page (security review LOW-1). A real family thread never approaches
# this; if one ever did, the newest replies within the cap still render.
_MAX_THREAD = 500
# One screenful of history at a time. The feed is chronological and it ENDS (P1) — but it
# must end at the actual end, not at an arbitrary slice. Before this, the feed cut off at
# 100 posts and still said "You are all caught up", so a family past that count lost every
# earlier photograph from the UI while being told they had seen everything.
_PAGE_SIZE = 100
# Postgres bigint ceiling: a cursor id past this is not a real post, it is a probe.
_MAX_POST_ID = 2**63 - 1


@dataclass
class FeedItem:
    """A post as the feed shows it to one viewer: the post plus the viewer-relative
    facts the template needs. Kept as a typed value rather than attributes stapled
    onto the model instance, so the view stays type-checked."""

    post: Post
    is_own: bool
    is_editable: bool
    is_new: bool


def _sides_in_a_sentence(names: list[str]) -> str:
    """Sides of the family, joined the way a person writes them (R2-8).

    Seen on production: a post widened to two sides asked "Share with Mom's side, Dad's
    side?", then "everyone in Mom's side, Dad's side", then offered a button reading "Yes,
    share with Mom's side, Dad's side". A comma is how a list is punctuated, not how
    anybody says a sentence out loud — and this is the one screen in the product whose
    whole job is that the member reads it and understands who is about to see their
    photographs.

    One function because the confirmation says it three times and three hand-written joins
    would be three chances to fix two of them. Oxford comma for three or more, which is the
    form that cannot be misread as two items when the last one has an "and" in its own
    name.
    """
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def _acting_member(request: HttpRequest) -> Member:
    if not request.user.is_authenticated or request.user.pk is None:
        raise Http404
    member = Member.objects.filter(user_id=request.user.pk).first()
    if member is None:
        raise Http404
    return member


@login_required
def feed(request: HttpRequest) -> HttpResponse:
    """The chronological feed that ends, plus the composer form. Opening the feed
    advances the member's unread boundary (S-303).

    Paging back through the archive is NOT "opening the feed", so a cursor request
    leaves the unread boundary where it is: reading history must never silently mark
    the new posts above it as seen.
    """
    member = _acting_member(request)
    cursor = _parse_cursor(request.GET.get("before"))
    return _render_feed(request, member, advance_seen=cursor is None, cursor=cursor)


def _parse_cursor(raw: str | None) -> tuple[datetime.datetime, int] | None:
    """Decode a `before=<iso>_<id>` keyset cursor, or None for anything malformed.

    Leniently: a mangled cursor shows page one rather than erroring. The cursor names
    only a position in time, never an audience — the audience query below is unchanged,
    so a forged cursor can reorder nothing and reveal nothing.
    """
    if not raw or "_" not in raw:
        return None
    stamp, _, post_id = raw.rpartition("_")
    try:
        moment = datetime.datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if timezone.is_naive(moment):
        return None
    # Let the parse decide, rather than str.isdigit(): isdigit() is true for every
    # Numeric_Type=Digit codepoint (superscripts, subscripts) while int() accepts only
    # Nd decimals, and int() additionally refuses strings past 4300 digits — so both
    # divergences reached int() and returned a 500 on a one-click GET. Not _int either:
    # that raises Http404, and a mangled cursor must degrade to page one, not 404 the
    # member's own feed.
    try:
        last_id = int(post_id)
    except ValueError:
        return None
    if last_id <= 0 or last_id > _MAX_POST_ID:
        return None  # keeps a bignum out of the id__lt parameter
    return (moment, last_id)


def _render_feed(
    request: HttpRequest,
    member: Member,
    *,
    advance_seen: bool,
    errors: list[str] | None = None,
    staged_handle: str | None = None,
    # What they typed, carried back into the composer. The photos survived a rejected
    # compose and the WORDS did not — while the page said "Your uploaded photos are still
    # attached", which reads as a reassurance that everything survived.
    draft_body: str = "",
    staged_notice: str = "",
    cursor: tuple[datetime.datetime, int] | None = None,
) -> HttpResponse:
    """Render the feed: the member's visible posts newest-first, each marked as their
    own (and still editable) and as new-since-last-visit, with one unread boundary
    before the first already-seen post. On a real feed open (advance_seen) the
    member's last-seen marker moves to now; a re-render after a composer error does
    not advance it, so an error never silently marks the feed as read."""
    boundary = member.feed_last_seen_at
    if advance_seen:
        Member.objects.filter(pk=member.pk).update(feed_last_seen_at=timezone.now())

    # F5: a post somebody walked away from on the confirmation page is still theirs. The
    # caller's own draft wins — a compose that bounced for correction is carrying the very
    # words the member is looking at — so this only fills an otherwise empty composer, and
    # never on an archive page, where there is no composer to fill.
    pending = drafts.peek(request) if cursor is None else None
    restored_draft = False
    draft_pod_id: int | None = None
    if pending is not None and not draft_body and staged_handle is None:
        draft_body = pending.body
        staged_handle = pending.handle
        restored_draft = True
        # The pod comes back WITH the words, or the restore quietly changes who the post is
        # for: the select would otherwise fall back to the first pod this member can see, so
        # a note written for the four cousins is re-aimed at the whole household while the
        # page says "Your draft is still here". Re-validated here and never trusted
        # from the session — a pod the member has since left simply does not match, and the
        # composer opens on its ordinary default instead. compose() still re-checks it at
        # POST through require_visible_pod; this is the display half of the same rule.
        if (
            pending.pod_id is not None
            and scoping.visible_pods(member).filter(id=pending.pod_id).exists()
        ):
            draft_pod_id = pending.pod_id

    # Muted pods drop out of this member's feed only (S-205); the posts stay reachable
    # by direct link, so mute is a display choice, not an authorization change.
    visible = scoping.visible_posts(member).exclude(pod_id__in=pods.muted_pod_ids(member))
    if cursor is not None:
        # Keyset, not OFFSET: (created_at, id) strictly older than the cursor, so paging
        # stays cheap and cannot skip or repeat a post when a new one lands mid-read.
        moment, last_id = cursor
        visible = visible.filter(Q(created_at__lt=moment) | Q(created_at=moment, id__lt=last_id))
    page_query = (
        visible.select_related("author", "pod", "link_preview", "link_preview__image_asset")
        .prefetch_related(
            Prefetch(
                "media",
                # The post's own gallery only: a LINK_PREVIEW asset is a re-hosted card
                # image, rendered by the preview card, not as an uploaded photo (S-301).
                queryset=MediaAsset.objects.filter(deleted_at__isnull=True).exclude(
                    media_kind=MediaAsset.LINK_PREVIEW
                ),
                to_attr="live_media",
            )
        )
        .order_by("-created_at", "-id")[: _PAGE_SIZE + 1]
    )
    # One extra row is fetched purely to answer "is there more?" without a COUNT.
    page = list(page_query)
    has_older = len(page) > _PAGE_SIZE
    feed_posts = page[:_PAGE_SIZE]
    items = [
        FeedItem(
            post=post,
            is_own=post.author_id == member.id,
            is_editable=post.author_id == member.id and posting.within_edit_window(post),
            is_new=boundary is not None and post.created_at > boundary,
        )
        for post in feed_posts
    ]
    first_seen_id: int | None = None
    if any(item.is_new for item in items):
        first_seen_id = next((item.post.id for item in items if not item.is_new), None)

    return render(
        request,
        "core/feed.html",
        {
            "member": member,
            "items": items,
            "pods": scoping.visible_pods(member),
            "yards": scoping.visible_yards(member),
            "first_seen_id": first_seen_id,
            # The quiet on-the-day banner (S-903): a feed element only, resolved
            # through the one date resolver, so it honors per-field visibility.
            # No push notification for dates exists anywhere (S-305).
            "todays_dates": profiles.upcoming_dates(member, start=timezone.localdate(), days=1),
            # A yard/instance admin sees a per-post takedown affordance (S-713); the
            # posts rendered here are already the ones they can see, so the affordance is
            # exactly scoped to what they may act on.
            "is_moderator": permissions.is_admin(member),
            # BY-02: this member has no way to reset their own password. Shown once,
            # quietly, until they dismiss it or add an address.
            "show_email_prompt": _needs_an_email(member),
            "errors": errors or [],
            # The end-cap is only honest when the tail is genuinely reached; otherwise the
            # member gets a way back into the archive instead of a false "all caught up".
            "has_older": has_older,
            "older_cursor": (
                f"{feed_posts[-1].created_at.isoformat()}_{feed_posts[-1].id}"
                if has_older and feed_posts
                else None
            ),
            "is_archive_page": cursor is not None,
            # Carried so a compose that bounced for correction keeps its uploads (the
            # files themselves cannot survive the round trip; the handle can).
            "staged_handle": staged_handle,
            "draft_body": draft_body,
            # The audience half of the restore (see above); the template preselects it.
            "draft_pod_id": draft_pod_id,
            "staged_notice": staged_notice,
            # Drives the "Your draft is still here / Discard Draft" row, which is
            # the ONLY way a member can drop a draft from the feed — it has to sit outside
            # the composer's own <form>, because forms do not nest.
            "restored_draft": restored_draft,
            # Said in words beside the one media control, so the limits are readable with
            # the enhancement script off, and named from the constants rather than typed
            # into the template where they would drift the first time either moved.
            "max_photos": _MAX_PHOTOS,
            "max_videos": _MAX_VIDEOS,
        },
    )


def _needs_an_email(member: Member) -> bool:
    """Has this member no address on file at all, and not yet waved the prompt away?

    BY-02/BY-03. Email is optional at join (S-101) and members who joined before the form
    even had the box have neither an `EmailAddress` row nor `User.email` — so
    `Forgot your password?` cannot reach them, and `ACCOUNT_PREVENT_ENUMERATION` correctly
    makes the reset page say "sent" either way, which means they find out they are locked
    out at the worst possible moment.

    BOTH stores are checked because allauth reads both: it resolves a reset against a
    verified `EmailAddress` and falls back to `USER_MODEL_EMAIL_FIELD` when none matched
    (allauth/account/utils.py), so either one being set is a recovery path and neither
    being set is none.
    """
    from allauth.account.models import EmailAddress

    if member.user is None or member.email_prompt_dismissed_at is not None:
        return False
    if member.user.email:
        return False
    return not EmailAddress.objects.filter(user=member.user).exists()


@login_required
def compose_cancel(request: HttpRequest) -> HttpResponse:
    """Abandon a wide send and release its staged uploads immediately.

    Cancel used to be a bare link back to the feed, so the photographs sat on disk until
    the sweep collected them — and the compose comment claimed the cancel path released
    them, which was simply untrue. POST, so a link prefetch cannot destroy an upload.
    """
    _acting_member(request)
    if request.method != "POST":
        raise Http404
    staged_uploads.discard(request, request.POST.get("staged_uploads") or None)
    # An EXPLICIT cancel is one of the only two events that release the held draft (F5,
    # core/drafts.py): everything else that leaves the confirmation keeps it.
    drafts.clear(request)
    return redirect("feed")


@transaction.non_atomic_requests
@login_required
def compose(request: HttpRequest) -> HttpResponse:
    """Create a post. POST only. Enforces TM-3 confirm-on-widen and, through the
    posting service, the audience-integrity invariant.

    Marked non-atomic (the project sets ATOMIC_REQUESTS): create_post wraps its own writes
    in an explicit transaction, and the best-effort photo/video ingests are independent, so a
    dropped photo never rolls back the post. The SSRF-sensitive link-preview fetch that
    originally motivated this (security review HIGH-3) now runs on the worker, not in the
    request at all (S-725, TS-CO-4)."""
    member = _acting_member(request)
    if request.method != "POST":
        raise Http404

    body = request.POST.get("body", "").strip()
    # The composer defaults to the poster's own pod; the pod must be theirs.
    pod = scoping.require_visible_pod(member, _int(request.POST.get("pod_id", "")))
    # The optional audience field is parsed leniently: a stray non-integer value is
    # skipped rather than failing the whole post, and a well-formed but foreign yard
    # id is dropped by the visible_yards filter below, so neither can widen the reach.
    yard_ids = _int_ids(request.POST.getlist("audience_yards"))
    audience_yards = list(scoping.visible_yards(member).filter(id__in=yard_ids)) if yard_ids else []
    # An ad-hoc pod's posts stay in the pod (S-204): never widen, never confirm.
    if pod.kind == Pod.ADHOC:
        audience_yards = []

    errors: list[str] = []
    if not body:
        errors.append("Write something to post.")
    elif len(body) > _MAX_BODY:
        errors.append(f"Post must be {_MAX_BODY} characters or fewer.")

    # Videos are validated (size, format, duration) BEFORE the post is created, so an
    # over-cap or unplayable clip rejects the whole compose with a clear message and
    # never lands as a post with a silently-missing video (S-402). Photos, by contrast,
    # are best-effort and attached after creation.
    picked_photos, picked_videos = _split_media(request.FILES.getlist("media"))
    video_raws, video_errors = _validate_videos(request.FILES.getlist("videos") + picked_videos)
    errors.extend(video_errors)
    photo_raws, media_notices = _read_photos(request.FILES.getlist("photos") + picked_photos)

    # A second pass through the composer (the TM-3 confirmation) arrives with an EMPTY
    # request.FILES — a plain form cannot carry files — so the bytes come back from
    # staging instead. Claiming here, before the widening branch, means the cancel path
    # below also releases them.
    staged_handle = request.POST.get("staged_uploads") or None
    if staged_handle:
        claimed = staged_uploads.claim(request, staged_handle)
        # The caps are re-applied to the MERGED list, not just to this request's upload.
        # Without that, looping the error path (which re-stages every time) accumulated 20
        # more photos per round onto one post — 20N photos, 4N clips, past every per-post
        # ceiling, with every raw held in memory at once against a 768 MB container.
        photo_raws = (claimed.photos + photo_raws)[:_MAX_PHOTOS]
        video_raws = (claimed.videos + video_raws)[:_MAX_VIDEOS]
        if claimed.missing:
            # A claim that came up short is the original defect one boundary further on:
            # the sweep can cross the TTL while the member hesitates over the confirmation.
            # Say it rather than posting quietly without them.
            media_notices.append(
                f"{claimed.missing} file{'s' if claimed.missing > 1 else ''} expired "
                f"before you confirmed. Attach {'them' if claimed.missing > 1 else 'it'} again."
            )

    # TM-3: any audience broader than the poster's own pod (a yard send, or more
    # than one yard) must be explicitly confirmed with its name and member count.
    widening = bool(audience_yards)
    confirmed = request.POST.get("confirm_wide") == "yes"
    if widening and not confirmed and not errors:
        reach = scoping.visible_members(member).filter(pods__yards__in=audience_yards).distinct()
        # Hold the media server-side across the hop. Without this the confirmation page
        # was where photos went to die: it is an ordinary form with no file inputs, so
        # the re-POST carried nothing and the post was created empty.
        handle = staged_uploads.stage(request, photos=photo_raws, videos=video_raws)
        # ...and hold the WORDS on the same terms (F5). The photos survived this hop and
        # the paragraph did not, so leaving the confirmation any way other than answering
        # it threw the post away — on the one screen a person deliberately pauses on.
        drafts.hold(request, body=body, pod_id=pod.id, handle=handle)
        return render(
            request,
            "core/compose_confirm.html",
            {
                "body": body,
                "pod": pod,
                "audience_yards": audience_yards,
                "audience_names": _sides_in_a_sentence([y.name for y in audience_yards]),
                "member_count": reach.count(),
                "staged_handle": handle,
                "staged_photo_count": len(photo_raws),
                "staged_video_count": len(video_raws),
            },
        )

    if errors:
        # The compose is going back for correction and the bytes must not be lost in the
        # meantime, so re-stage them and carry the handle through the re-rendered form.
        handle = staged_uploads.stage(request, photos=photo_raws, videos=video_raws)
        drafts.hold(request, body=body, pod_id=pod.id, handle=handle)
        return _render_feed(
            request,
            member,
            advance_seen=False,
            errors=errors,
            staged_handle=handle,
            draft_body=body,
            staged_notice=(
                "Your photos are still attached. Fix the error above and post again."
                if handle
                else ""
            ),
        )

    post = posting.create_post(author=member, pod=pod, audience_yards=audience_yards, body=body)
    # A link in the body gets a best-effort preview card, fetched on the WORKER (S-725,
    # TS-CO-4): the SSRF-sensitive outbound fetch runs off the edge-facing web process,
    # on the worker's own network segment. The card appears once the worker attaches it
    # (like a video transcode); the post shows the bare link until then.
    from .tasks import attach_link_preview

    attach_link_preview.defer(post_id=post.id)
    media_notices.extend(_attach_photos(photo_raws, post=post))
    _attach_videos(video_raws, post=post)
    # The draft has become the post it was a draft of (F5).
    drafts.clear(request)
    # SAY IT WORKED. Tapping Post reloaded the feed with no message of any kind, and the
    # new post lands ~1700px below the fold on a phone, so nothing visibly changed —
    # while the product cheerfully announced "Successfully signed in as …", the least
    # important event it knows about. A relative with no confirmation taps Post twice.
    messages.success(request, "Posted.")
    # Anything the post did NOT get is said out loud on the feed the member lands on.
    # Silence here is the failure mode: a post appears, looks fine, and is missing photos
    # nobody will ever mention.
    for notice in media_notices:
        messages.warning(request, notice)
    return redirect("feed")


@login_required
def edit_post(request: HttpRequest, post_id: int) -> HttpResponse:
    """Edit one's own post within the edit window (S-302). The post is resolved
    through the guard, so a post the member cannot see is a byte-identical 404; a
    post they can see but did not write is a 403."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if post.author_id != member.id:
        raise PermissionDenied

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        errors: list[str] = []
        if not body:
            errors.append("Write something to post.")
        elif len(body) > _MAX_BODY:
            errors.append(f"Post must be {_MAX_BODY} characters or fewer.")
        if not errors:
            posting.edit_post(actor=member, post=post, body=body)
            return redirect("feed")
        return render(request, "core/edit_post.html", {"post": post, "errors": errors})

    if not posting.within_edit_window(post):
        raise PermissionDenied  # the feed hides the edit link by now; enforce it here too
    return render(request, "core/edit_post.html", {"post": post, "errors": []})


@login_required
def delete_post(request: HttpRequest, post_id: int) -> HttpResponse:
    """Delete one's own post (S-302). GET confirms, stating plainly that copies
    already sent in an email update cannot be recalled; POST performs the soft delete.
    Same guard rules as edit: 404 if not visible, 403 if visible but not yours."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if post.author_id != member.id:
        raise PermissionDenied

    if request.method == "POST":
        posting.delete_post(actor=member, post=post)
        media.purge_post_media(post)  # hard-delete the photo files too (T-MEDIA-6)
        # The walk found the feed simply re-rendering with the post gone, which reads as
        # "did that work?" on a phone where the post was already below the fold. The same
        # calm flash the composer uses, for the same reason: the product says it worked.
        messages.success(request, "Post deleted.")
        return redirect("feed")
    return render(request, "core/delete_confirm.html", {"post": post})


# What a phone names a clip, for the one case where the browser declares no content type
# at all. Lowercased suffixes; the check is a routing hint, never a validation.
_VIDEO_SUFFIXES = (".mov", ".mp4", ".m4v", ".qt")


def _split_media(files: list[UploadedFile]) -> tuple[list[UploadedFile], list[UploadedFile]]:
    """Route ONE picker's files to the photo gate or the video gate.

    The composer is a single control now (owner direction 4: "Add Photos Or A Video",
    `accept="image/*,video/*"`), because two stacked pickers made a place to say something
    read as an upload form, and because "Files" is the wrong word on a phone. Both kinds
    therefore arrive under one field name and something has to decide which is which.

    `photos` and `videos` stay the server's own two fields: they map to two genuinely
    different gates (Pillow decode-and-re-encode versus ISOBMFF magic plus ffprobe), and a
    caller that already knows what it is sending should say so. `media` is the browser's
    one-control convenience on top of them.

    Both signals used here — the declared content type and the filename — are
    client-controlled, so this is ROUTING and never validation. A file that lies about
    itself is rejected by the gate it lands in: an HTML polyglot called `.mov` fails the
    magic check, and a real clip declared as an image fails to decode.
    """
    photos: list[UploadedFile] = []
    videos: list[UploadedFile] = []
    for uploaded in files:
        declared = (uploaded.content_type or "").lower()
        name = (uploaded.name or "").lower()
        if declared.startswith("video/") or name.endswith(_VIDEO_SUFFIXES):
            videos.append(uploaded)
        else:
            photos.append(uploaded)
    return photos, videos


def _read_photos(files: list[UploadedFile]) -> tuple[list[bytes], list[str]]:
    """Read uploaded photos into bounded raw bytes, and SAY what was dropped.

    Every drop here used to be a silent `continue`: over the 20-per-post cap, over the
    size ceiling, or undecodable. Someone selected 40 photos from a birthday, tapped
    Post, watched the post appear, and 20 of them were simply gone — real family data
    loss with a success message on top. HEIC makes it worse: the browser-canvas
    conversion falls through to "let the server decide" when `createImageBitmap` fails,
    and the server's decision was that same silent drop.

    Reading happens BEFORE any post exists so the same bytes can be staged across the
    TM-3 confirmation hop; the ingest gate still runs at attach time.
    """
    notices: list[str] = []
    submitted = len(files)
    if submitted > _MAX_PHOTOS:
        dropped = submitted - _MAX_PHOTOS
        # The same sentence the picker's script says for the same event
        # (core/_composer_media.html `couldNotAdd`), so a member who meets the ceiling in
        # the browser and one who meets it on the way in read one wording, not two.
        notices.append(
            f"{dropped} photo{'s' if dropped > 1 else ''} could not be added. "
            f"A post can carry {_MAX_PHOTOS} photos."
        )
    raws: list[bytes] = []
    too_large = 0
    for uploaded in files[:_MAX_PHOTOS]:
        if uploaded.size is not None and uploaded.size > _MAX_PHOTO_BYTES:
            too_large += 1  # fast path when the size is known
            continue
        raw = uploaded.read()
        if len(raw) > _MAX_PHOTO_BYTES:
            too_large += 1  # backstop for an unknown size (security review LOW-2)
            continue
        raws.append(raw)
    if too_large:
        notices.append(
            f"{too_large} photo{'s were' if too_large > 1 else ' was'} too large to add. "
            f"Each photo must be {_MAX_PHOTO_BYTES // (1024 * 1024)} MB or smaller."
        )
    return raws, notices


def _attach_photos(
    raws: list[bytes], *, post: Post | None = None, comment: Comment | None = None
) -> list[str]:
    """Re-encode and attach staged photo bytes to a just-created post or reply (S-401,
    S-404).

    Each passes the ingest gate (media.ingest_photo), which strips metadata and rejects
    anything that does not decode to an allowed image. A rejection is not fatal to the
    post — but it is now reported rather than dropped in silence.
    """
    rejected = 0
    for raw in raws:
        try:
            media.ingest_photo(post=post, comment=comment, raw=raw)
        except media.MediaRejected:
            rejected += 1
    if not rejected:
        return []
    if rejected == 1:
        return ["1 photo could not be added. The file was not an image Backyard can read."]
    return [f"{rejected} photos could not be added. The files were not images Backyard can read."]


def _validate_videos(files: list[UploadedFile]) -> tuple[list[bytes], list[str]]:
    """Read and fully validate uploaded videos (size, ISOBMFF magic, duration) BEFORE any
    post is created, so a bad clip rejects the compose upfront with a member-facing
    message rather than silently (S-402). Returns the validated raw bytes and any errors;
    the caller aborts creation if there are errors."""
    raws: list[bytes] = []
    errors: list[str] = []
    cap = transcoding.MAX_VIDEO_BYTES
    for uploaded in files[:_MAX_VIDEOS]:
        # Reject on the declared size BEFORE reading the file into memory (security
        # review HIGH-1): an oversized clip must not be buffered into the web process
        # (mem_limit'd) only to be rejected after. validate_video re-checks len(raw) as
        # a backstop for an unknown declared size.
        if uploaded.size is not None and uploaded.size > cap:
            errors.append(f"Video must be {cap // (1024 * 1024)} MB or smaller.")
            continue
        raw = uploaded.read()
        try:
            media.validate_video(raw)
        except media.MediaRejected as exc:
            errors.append(str(exc))
            continue
        raws.append(raw)
    return raws, errors


def _attach_videos(
    raws: list[bytes], *, post: Post | None = None, comment: Comment | None = None
) -> None:
    """Store each validated video as a PENDING asset and enqueue its transcode (S-402).
    The bytes are already validated, so ingest here only strips and stores; the worker
    (concurrency 1, TS-PP-2) produces the served rendition and poster."""
    from .tasks import transcode_video

    for raw in raws:
        asset = media.ingest_video(post=post, comment=comment, raw=raw)
        transcode_video.defer(asset_id=asset.id)


def _int(value: str) -> int:
    """Parse a required, single, trusted id (the pod). A missing or malformed value
    is a byte-identical 404, never a distinguishable 500 (S-202 parity)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404 from None


def _int_ids(values: list[str]) -> list[int]:
    """Parse the optional multi-value audience field, skipping any value that is not
    an integer. Unlike a required id, one stray checkbox value should be ignored, not
    fatal; a foreign but well-formed id is still dropped later by the visible_yards
    filter, so this never widens the audience past the author's own yards."""
    out: list[int] = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


@login_required
def post_detail(request: HttpRequest, post_id: int) -> HttpResponse:
    """A post and its replies (S-202: the post resolves through the guard, so a post
    the member cannot see is a byte-identical 404). Comments are scoped by the same
    query, so only replies on a visible post render."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    return _render_post_detail(request, member, post)


def _render_post_detail(
    request: HttpRequest, member: Member, post: Post, errors: list[str] | None = None
) -> HttpResponse:
    comments = (
        scoping.visible_comments(member)
        .filter(post=post)
        .select_related("author")
        # S-404. Prefetched rather than let the template walk `comment.media.all()`:
        # that relation includes SOFT-DELETED assets, so a purged-then-restored row or a
        # per-asset delete would render bytes the audience query has already excluded.
        # The same `deleted_at` filter and LINK_PREVIEW exclusion the post's gallery uses.
        .prefetch_related(
            Prefetch(
                "media",
                queryset=MediaAsset.objects.filter(deleted_at__isnull=True).exclude(
                    media_kind=MediaAsset.LINK_PREVIEW
                ),
                to_attr="live_media",
            )
        )[:_MAX_THREAD]
    )
    # Reactions show WHO reacted, grouped by kind, never a count (S-304). Capped for
    # symmetry with the comment path so a pathologically large yard cannot inflate the
    # render (security review LOW-1); one-per-member keeps this well under the cap.
    reactions = (
        scoping.visible_reactions(member).filter(post=post).select_related("member")[:_MAX_THREAD]
    )
    by_kind: dict[str, list[str]] = {}
    my_reaction: str | None = None
    for reaction in reactions:
        by_kind.setdefault(reaction.kind, []).append(reaction.member.display_name)
        if reaction.member_id == member.id:
            my_reaction = reaction.kind
    reactor_groups = [
        {"kind": kind, "label": label, "names": by_kind[kind]}
        for kind, label in Reaction.KIND_CHOICES
        if kind in by_kind
    ]
    return render(
        request,
        "core/post_detail.html",
        {
            "member": member,
            "post": post,
            "comments": comments,
            "errors": errors or [],
            "reactor_groups": reactor_groups,
            "my_reaction": my_reaction,
            "reaction_kinds": Reaction.KIND_CHOICES,
            "media_list": post.media.filter(deleted_at__isnull=True).exclude(
                media_kind=MediaAsset.LINK_PREVIEW
            ),
            # Admins get the takedown affordance on this (visible) post and its comments
            # (S-713); the thread only renders items the member can see.
            "is_moderator": permissions.is_admin(member),
            # The reply form's one media control says its limits in words; same constants
            # as the composer's, so the two can never disagree.
            "max_photos": _MAX_PHOTOS,
            "max_videos": _MAX_VIDEOS,
        },
    )


@login_required
def react(request: HttpRequest, post_id: int) -> HttpResponse:
    """Set, change, or clear the member's reaction to a post they can see (S-304).
    POST only; resolved through the guard, so a post the member cannot see is a 404
    and an unknown reaction kind is a 404."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if request.method != "POST":
        raise Http404
    kind = request.POST.get("kind", "")
    if kind not in reacting.VALID_KINDS:
        raise Http404
    reacting.toggle_reaction(member=member, post=post, kind=kind)
    return redirect("post_detail", post_id=post.id)


@login_required
def notification_settings(request: HttpRequest) -> HttpResponse:
    """The member's push preferences (S-305): a single opt-in, replies to my posts,
    off by default. There is no other option to offer."""
    member = _acting_member(request)
    if request.method == "POST":
        enabled = request.POST.get("notify_on_reply") == "on"
        notifications.set_reply_notification(member, enabled=enabled)
        # The save redirected back to this same form and said NOTHING, so the screen
        # simply re-rendered and the only honest reading was "did that take?" — the same
        # defect walk item 27 found on the profile form, which is a few lines from here
        # and already fixed. The confirmation every other save in the product gives.
        messages.success(request, "Saved.")
        return redirect("notification_settings")
    return render(
        request, "core/notification_settings.html", {"pref": notifications.preference_for(member)}
    )


@login_required
@require_POST
def dismiss_email_prompt(request: HttpRequest) -> HttpResponse:
    """BY-02: the member has seen the add-an-email prompt and does not want it again.

    POST-only, because a link preview or a prefetch must not clear the one thing a member
    has not read yet — the same class of mistake the compose-cancel route guards. Kept
    on the member row rather than in the session so it stays dismissed on their phone and
    their laptop, and after they sign out — a prompt that comes back is a nag.
    """
    member = _acting_member(request)
    Member.objects.filter(pk=member.pk, email_prompt_dismissed_at__isnull=True).update(
        email_prompt_dismissed_at=timezone.now()
    )
    return redirect("feed")


@login_required
def add_comment(request: HttpRequest, post_id: int) -> HttpResponse:
    """Reply to a post the member can see (S-502 substrate). POST only. The post is
    resolved through the guard first, so a reply to a post outside the member's
    audience is a 404, and the service re-checks visibility as defense in depth."""
    member = _acting_member(request)
    post = scoping.require_visible_post(member, post_id)
    if request.method != "POST":
        raise Http404

    body = request.POST.get("body", "").strip()
    errors: list[str] = []
    # S-404: a reply carries photos and clips exactly as a post does — the SAME readers,
    # the same caps, the same ingest gate. A second set of limits here would drift from
    # the composer's the first time either moved.
    picked_photos, picked_videos = _split_media(request.FILES.getlist("media"))
    video_raws, video_errors = _validate_videos(request.FILES.getlist("videos") + picked_videos)
    errors.extend(video_errors)
    photo_raws, media_notices = _read_photos(request.FILES.getlist("photos") + picked_photos)

    if not body and not photo_raws and not video_raws:
        # A reply that is only a photograph is a real reply, so the body is required only
        # when nothing is attached. "Write a reply" in front of someone who just picked
        # three wedding photos would be a lie.
        errors.append("Write a reply or add a photo.")
    elif len(body) > _MAX_COMMENT:
        errors.append(f"Reply must be {_MAX_COMMENT} characters or fewer.")
    if errors:
        return _render_post_detail(request, member, post, errors + media_notices)

    comment = commenting.create_comment(author=member, post=post, body=body)
    media_notices.extend(_attach_photos(photo_raws, comment=comment))
    _attach_videos(video_raws, comment=comment)
    # Same silence as the composer had, same cure (C4): a reply lands below whatever
    # thread is already there, so on a long one nothing visibly happened.
    messages.success(request, "Reply posted.")
    if media_notices:
        # Same posture as the composer: a partial attach is REPORTED, never dropped in
        # silence. The reply itself already landed, so these are notices, not errors.
        for notice in media_notices:
            messages.warning(request, notice)
    return redirect("post_detail", post_id=post.id)


@login_required
def delete_comment(request: HttpRequest, comment_id: int) -> HttpResponse:
    """Delete one's own comment (author-only, soft). POST only. Resolved through the
    guard, so a comment the member cannot see is a 404 and one they can see but did
    not write is a 403."""
    member = _acting_member(request)
    if request.method != "POST":
        raise Http404  # POST-only; a GET never reaches the guard, so GET is a uniform 404
    comment = scoping.require_visible_comment(member, comment_id)
    if comment.author_id != member.id:
        raise PermissionDenied
    post_id = comment.post_id
    commenting.delete_comment(actor=member, comment=comment)
    return redirect("post_detail", post_id=post_id)


@login_required
def take_down_post(request: HttpRequest, post_id: int) -> HttpResponse:
    """Moderator takedown of one post (S-713). Admins only. The post resolves through the
    MODERATOR's read guard, so a post they cannot see is a byte-identical 404 — a yard
    admin can never take down a pod-private post outside their visibility (the
    reach-vs-visibility rule; route those to the parent/pod post-v1). Distinct from the
    author-only self-delete: an admin may take down anyone's post that they can see.

    GET CONFIRMS, POST PERFORMS, since the 2026-09-19 walk. It was POST-only and fired on
    one tap: gone at once, photographs purged for good, no message, no undo — while the
    author's own delete route had asked for a second tap since the beginning. The check
    ORDER is unchanged and is the part that matters: admin first (403), then the read
    guard (404), so neither the confirm page nor the action tells a stranger whether a
    post exists.
    """
    member = _acting_member(request)
    if request.method not in ("GET", "POST"):
        raise Http404
    if not permissions.is_admin(member):
        raise PermissionDenied
    post = scoping.require_visible_post(member, post_id)
    if request.method == "GET":
        return render(
            request,
            "core/takedown_confirm.html",
            {"post": post, "author_name": post.author.display_name},
        )
    moderation.take_down_post(moderator=member, post=post)
    media.purge_post_media(post)  # a takedown hard-purges the post's photos too (T-MEDIA-6)
    messages.success(request, "Post taken down.")
    return redirect("feed")


@login_required
def take_down_comment(request: HttpRequest, comment_id: int) -> HttpResponse:
    """Moderator takedown of one comment (S-713). Admins only, scoped to the moderator's
    visibility: a comment on a post they cannot see is a byte-identical 404.

    GET confirms and POST performs, for the reason given on `take_down_post`: a reply is
    somebody's words too, and taking one down was the same one-tap, no-undo action.
    """
    member = _acting_member(request)
    if request.method not in ("GET", "POST"):
        raise Http404
    if not permissions.is_admin(member):
        raise PermissionDenied
    comment = scoping.require_visible_comment(member, comment_id)
    if request.method == "GET":
        return render(
            request,
            "core/takedown_confirm.html",
            {"comment": comment, "author_name": comment.author.display_name},
        )
    post_id = comment.post_id
    moderation.take_down_comment(moderator=member, comment=comment)
    messages.success(request, "Reply taken down.")
    return redirect("post_detail", post_id=post_id)
