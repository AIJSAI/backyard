"""S-404: photos and clips on a reply, so a wedding is one thread.

Threads existed and replies were text-only: `Comment` had author/post/body/via_email and
`MediaAsset` had a foreign key to `Post` alone, so a family could not put their own
wedding photographs under the wedding post.

The interesting assertions here are the NEGATIVE ones, and they are the reason this story
is security-sensitive rather than cosmetic:

  * reply media must inherit the COMMENT's audience — which inherits the post's — so a
    photo on a reply must be unreachable from another side of the family;
  * a soft-deleted or taken-down reply must take its photos out of every surface AND off
    the disk (T-MEDIA-6);
  * a digest token must not widen into a general reply-media credential.

Every one of those would look perfectly correct to the person who posted the reply.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import commenting, media, moderation, removal, scoping
from core.models import Comment, MediaAsset, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db

_PW = "aX9!mnpq2ffz"


def _png(colour: tuple[int, int, int] = (10, 90, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), colour).save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    pod: Pod  # in maternal
    far_pod: Pod  # in paternal
    author: Member  # posted, in pod
    replier: Member  # in pod
    stranger: Member  # in far_pod, must never see any of it
    post: Post


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([maternal])
    far_pod = Pod.objects.create(name="The Ferraras")
    far_pod.yards.set([paternal])

    def member(name: str, home: Pod, *, login: str | None = None) -> Member:
        user = None
        if login:
            from django.contrib.auth import get_user_model

            user = get_user_model().objects.create_user(username=login, password=_PW)
        m = Member.objects.create(display_name=name, user=user)
        PodMembership.objects.create(member=m, pod=home)
        return m

    author = member("Wedding Author", pod, login="author")
    replier = member("Cousin", pod, login="cousin")
    stranger = member("Other Side", far_pod, login="stranger")
    post = Post.objects.create(author=author, pod=pod, body="The wedding was lovely.")
    return World(maternal, paternal, pod, far_pod, author, replier, stranger, post)


def _client(member: Member) -> Client:
    user = member.user
    assert user is not None, f"{member.display_name} has no login; the fixture must give it one"
    client = Client()
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    return client


# ---------------------------------------------------------------- the feature exists


def test_a_reply_can_carry_photos(world: World) -> None:
    response = _client(world.replier).post(
        reverse("add_comment", args=[world.post.id]),
        {
            "body": "Here are mine.",
            "photos": [
                SimpleUploadedFile("a.png", _png(), content_type="image/png"),
                SimpleUploadedFile("b.png", _png((90, 40, 20)), content_type="image/png"),
            ],
        },
    )
    assert response.status_code == 302
    comment = Comment.objects.get(author=world.replier)
    assets = comment.media.all()
    assert len(assets) == 2, "the reply's photos did not attach"
    assert all(a.post_id is None for a in assets), "reply media leaked onto the post"
    # Re-encoded to our own JPEG, never the client's claim (TM-9) — the same gate a
    # post's photo passes, because it is literally the same ingest function.
    assert {a.content_type for a in assets} == {"image/jpeg"}
    assert all(a.image.name for a in assets)


def test_a_photo_only_reply_is_a_real_reply(world: World) -> None:
    """ "Write a reply" in front of someone who just picked three wedding photos would be
    a lie, so the body is required only when nothing is attached."""
    response = _client(world.replier).post(
        reverse("add_comment", args=[world.post.id]),
        {"body": "", "photos": [SimpleUploadedFile("a.png", _png(), content_type="image/png")]},
    )
    assert response.status_code == 302
    comment = Comment.objects.get(author=world.replier)
    assert comment.body == ""
    assert comment.media.count() == 1


def test_an_empty_reply_with_nothing_attached_is_still_refused(world: World) -> None:
    response = _client(world.replier).post(
        reverse("add_comment", args=[world.post.id]), {"body": "   "}
    )
    assert response.status_code == 200  # re-rendered with the error
    assert "Write a reply, or add a photo." in response.content.decode()
    assert not Comment.objects.filter(author=world.replier).exists()


def test_the_thread_renders_a_reply_own_photos(world: World) -> None:
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    html = _client(world.author).get(reverse("post_detail", args=[world.post.id])).content.decode()
    assert reverse("serve_media", args=[asset.thumbnail_token]) in html


# ---------------------------------------------------------------- exactly one owner


def test_the_database_refuses_an_asset_with_two_owners(world: World) -> None:
    """Enforced in the DATABASE, not by convention: an asset with both owners would have
    two audiences, and every reader and purge branches on which one is set."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        MediaAsset.objects.create(post=world.post, comment=comment, content_type="image/jpeg")


def test_the_database_refuses_an_orphan_asset(world: World) -> None:
    """An owner-less row would be unreachable by the audience query AND unreachable by
    every purge — bytes on the volume that nothing can ever remove."""
    with pytest.raises(IntegrityError), transaction.atomic():
        MediaAsset.objects.create(content_type="image/jpeg")


def test_the_ingest_refuses_before_writing_a_file(world: World) -> None:
    """The service refuses zero-or-two as well as the constraint, because an ingest that
    reached the database with both set would already have written bytes to disk."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="x")
    before = MediaAsset.objects.count()
    with pytest.raises(media.MediaRejected):
        media.ingest_photo(post=world.post, comment=comment, raw=_png())
    with pytest.raises(media.MediaRejected):
        media.ingest_photo(raw=_png())
    assert MediaAsset.objects.count() == before


# ---------------------------------------------------------------- isolation


def test_reply_media_is_unreachable_from_the_other_side_of_the_family(world: World) -> None:
    """The assertion that makes this story security-sensitive. A reply photo that leaked
    across the yard boundary would look perfectly correct to whoever posted it."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())

    assert asset in scoping.visible_media(world.author)
    assert asset in scoping.visible_media(world.replier)
    assert asset not in scoping.visible_media(world.stranger), "reply media crossed yards"

    for token in (asset.token, asset.thumbnail_token):
        url = reverse("serve_media", args=[token])
        assert _client(world.author).get(url).status_code == 200
        # Byte-identical 404, never a 403: nothing may reveal that it exists (S-202).
        assert _client(world.stranger).get(url).status_code == 404


def test_narrowing_the_posts_audience_takes_the_reply_own_photos_with_it(world: World) -> None:
    """Reply media inherits the comment's audience, which inherits the post's — so it
    must follow the post, not a copy of the post's audience made at attach time."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    assert asset in scoping.visible_media(world.author)

    # Move the post to a pod the author is no longer in: the same lever S-202 tests.
    orphan_pod = Pod.objects.create(name="Somewhere else")
    orphan_pod.yards.set([world.paternal])
    Post.objects.filter(pk=world.post.pk).update(pod=orphan_pod)

    assert asset not in scoping.visible_media(world.author), (
        "the reply's photo outlived its post's audience"
    )


# ---------------------------------------------------------------- deletion and purge


def _stored_names(asset: MediaAsset) -> list[str]:
    return [f.name for f in (asset.image, asset.thumbnail, asset.source, asset.video) if f.name]


# Every purge below runs inside django_capture_on_commit_callbacks. The file removal is
# deliberately deferred to transaction commit (a rollback must not leave a live row
# pointing at a deleted file), and a test transaction never commits — so without this the
# assertions would pass on the ROW disappearing while the bytes stayed on the volume,
# which is the exact defect they exist to catch.


def test_deleting_a_reply_purges_its_photos_from_disk(
    world: World, django_capture_on_commit_callbacks: object
) -> None:
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    names = _stored_names(asset)
    storage = asset.image.storage
    assert names and all(storage.exists(n) for n in names)

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        commenting.delete_comment(actor=world.replier, comment=comment)

    assert not MediaAsset.objects.filter(pk=asset.pk).exists(), "the row survived"
    assert not any(storage.exists(n) for n in names), "the files survived the delete"


def test_a_takedown_purges_a_reply_own_photos(
    world: World, django_capture_on_commit_callbacks: object
) -> None:
    """S-713's promise is that a takedown hard-purges the content's photos; a reply can
    now carry them."""
    admin = Member.objects.create(display_name="Admin", role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=world.pod)
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    names = _stored_names(asset)
    storage = asset.image.storage

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        moderation.take_down_comment(moderator=admin, comment=comment)

    assert not MediaAsset.objects.filter(pk=asset.pk).exists()
    assert not any(storage.exists(n) for n in names)


def test_deleting_the_POST_purges_its_replies_photos_too(
    world: World, django_capture_on_commit_callbacks: object
) -> None:
    """Deleting a post cascades its comments away. Without this the rows would vanish with
    them while the FILES stayed on the volume forever — unreachable and unpurgeable."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    names = _stored_names(asset)
    storage = asset.image.storage

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        media.purge_post_media(world.post)

    assert not MediaAsset.objects.filter(pk=asset.pk).exists()
    assert not any(storage.exists(n) for n in names), "reply files outlived their post"


def test_removing_a_member_purges_the_photos_on_their_replies(
    world: World, django_capture_on_commit_callbacks: object
) -> None:
    """S-702's revocation-completeness promise. Their replies live on OTHER people's
    posts, so the post loop never reaches them: without this, a removed member's
    photographs stay on the volume after they are told their content is gone."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    names = _stored_names(asset)
    storage = asset.image.storage

    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        removal.remove_member(world.replier, content=removal.DELETE)

    assert not MediaAsset.objects.filter(pk=asset.pk).exists()
    assert not any(storage.exists(n) for n in names)


def test_a_soft_deleted_reply_hides_its_photos_without_a_separate_rule(world: World) -> None:
    """Belt-and-braces on the audience query itself: even if a purge were skipped, the
    comment's own `deleted_at` inside `visible_comments` must remove its media from the
    one query — no second rule to forget."""
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())
    assert asset in scoping.visible_media(world.author)

    Comment.objects.filter(pk=comment.pk).update(deleted_at=comment.created_at)

    assert asset not in scoping.visible_media(world.author)
    url = reverse("serve_media", args=[asset.token])
    assert _client(world.author).get(url).status_code == 404


# ---------------------------------------------------------------- export


def test_the_export_includes_the_photos_on_their_replies(world: World) -> None:
    """ "Leaving takes your data" excluded every picture a member put under someone else's
    post — which for a family whose weddings live in threads could be most of it."""
    import json
    import zipfile

    from core.export import build_member_export

    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())

    with zipfile.ZipFile(io.BytesIO(build_member_export(world.replier))) as archive:
        index = json.loads(archive.read("media.json"))
        names = archive.namelist()

    assert any(entry.get("comment_id") == comment.id for entry in index), index
    assert f"media/{asset.token}.jpg" in names


# ---------------------------------------------------------------- the digest ceiling


def test_a_digest_token_cannot_widen_into_a_general_reply_media_credential(
    world: World,
) -> None:
    """The narrowing that exists so a digest token stays inside its own issue's slice.

    Filtering that ceiling on `post__in` alone — which is what it did before S-404 —
    would let the token fetch the photos on ANY reply that member can see, in any yard
    and any week: strictly more than the page the token was minted to render, and the
    exact widening `digest_post_view` documents as forbidden. Reintroducing it through
    the reply path would be invisible on the digest page itself, which is why this is
    asserted rather than assumed.
    """
    import datetime

    from django.utils import timezone

    from core import digest_links, viewers
    from core.models import DigestIssue

    # A second post in the same yard, OUTSIDE the issue's window, with a reply carrying
    # a photo. The member can see it; the digest token must not reach its bytes.
    now = timezone.now()
    older = Post.objects.create(author=world.author, pod=world.pod, body="Months ago")
    Post.objects.filter(pk=older.pk).update(created_at=now - datetime.timedelta(days=90))
    off_issue_reply = commenting.create_comment(
        author=world.replier, post=older, body="my photo from then"
    )
    off_issue_asset = media.ingest_photo(comment=off_issue_reply, raw=_png())

    in_issue_reply = commenting.create_comment(
        author=world.replier, post=world.post, body="mine from the wedding"
    )
    in_issue_asset = media.ingest_photo(comment=in_issue_reply, raw=_png())

    issue = DigestIssue.objects.create(
        member=world.author,
        yard=world.maternal,
        window_start=now - datetime.timedelta(days=7),
        window_end=now,
    )
    reader = viewers.Reader(member=world.author, digest_issue=issue)
    reachable = set(reader.visible_media().values_list("id", flat=True))

    assert in_issue_asset.id in reachable, "the issue's own reply photo is unreachable"
    assert off_issue_asset.id not in reachable, (
        "the digest token reached a reply photo outside its issue — the ceiling widened"
    )
    # And the member themselves, with a real session, still sees both.
    assert off_issue_asset in scoping.visible_media(world.author)
    del digest_links  # imported to document where issue_posts lives; not called directly


# ---------------------------------------------------------------- the other surfaces


def test_the_elder_page_shows_a_reply_own_photos_and_adds_no_way_out(world: World) -> None:
    """The wedding case fails on the surface it was written for if her grandchildren's
    reply photographs are invisible here.

    And it must stay a DEAD END: test_elder_wcag asserts every href on this page is the
    elder feed itself (S-601), so the photo is an <img src>, never wrapped in a link.
    Both halves asserted, because adding the picture is exactly the change that would
    tempt someone to make it tappable.
    """
    import re

    from core import elder_tokens

    elder = Member.objects.create(display_name="Nana", kinship_name="Nana")
    PodMembership.objects.create(member=elder, pod=world.pod)
    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())

    raw = elder_tokens.mint(elder)
    client = Client()
    client.get(reverse("elder_enter", args=[raw]))  # exchanges the token for a session
    html = client.get(reverse("elder_feed")).content.decode()

    assert reverse("serve_media", args=[asset.token]) in html, "her reply photo is missing"
    for href in re.findall(r'href="([^"]+)"', html):
        assert href == reverse("elder_feed"), f"the elder page gained a way out: {href}"


def test_the_digest_email_stays_text_only(world: World) -> None:
    """An explicit acceptance line, so it gets an explicit test rather than resting on
    "we did not add anything". A capability-token image URL in an email lands in every
    forwarded copy and every provider's image proxy cache; the web version is where the
    photographs live."""
    from core import digest

    comment = commenting.create_comment(author=world.replier, post=world.post, body="Mine:")
    asset = media.ingest_photo(comment=comment, raw=_png())

    import datetime

    from django.utils import timezone

    from core.models import DigestIssue

    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=world.author,
        yard=world.maternal,
        window_start=now - datetime.timedelta(days=7),
        window_end=now,
    )
    email = digest.build_digest(issue, digest_token="dtok", unsubscribe_token="utok")  # noqa: S106

    # Non-vacuity FIRST: prove the digest actually rendered this post, so a clean
    # assertion below means "no photo token in the email", not "no email".
    assert world.post.body in email.text, "the digest did not include the post at all"
    for token in (asset.token, asset.thumbnail_token):
        assert token not in email.text, "a capability-token image URL reached the email text"
        assert token not in email.html, "a capability-token image URL reached the email HTML"


def test_a_replys_clip_shows_its_poster_on_the_digest_web_view(world: World) -> None:
    """Reviewer catch on #100, pinned.

    The post gallery on that surface renders a completed video's POSTER still. The reply
    block handled only photos, so the same clip attached to a REPLY was silently invisible
    there — inconsistent with the post above it, and under-delivering the story's "photos
    and clips" line. Asserted on the rendered page, since the defect was a missing template
    branch that no model-level check would notice.
    """
    from django.template.loader import render_to_string

    comment = commenting.create_comment(author=world.replier, post=world.post, body="a clip")
    clip = MediaAsset.objects.create(
        comment=comment,
        media_kind=MediaAsset.VIDEO,
        transcode_status=MediaAsset.DONE,
        content_type="video/mp4",
    )
    # And one still transcoding: it must NOT render, exactly as on a post.
    pending = MediaAsset.objects.create(
        comment=comment,
        media_kind=MediaAsset.VIDEO,
        transcode_status=MediaAsset.PENDING,
        content_type="video/mp4",
    )

    html = render_to_string(
        "core/digest_post.html",
        {"post": world.post, "comments": [comment], "token": "dtok", "issue": None},
    )
    assert reverse("serve_media", args=[clip.thumbnail_token]) in html, (
        "the clip's still is missing"
    )
    assert reverse("serve_media", args=[pending.thumbnail_token]) not in html, (
        "a clip that is still transcoding rendered a broken image"
    )
