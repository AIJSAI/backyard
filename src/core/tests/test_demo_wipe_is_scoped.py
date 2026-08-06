"""The demo wipe must delete the demo family and leave the real one standing.

No test covered the wipe at all. That is the whole reason it was able to be

    Pod.objects.all().delete()

for as long as it was — an unscoped delete documented in four places as the last step
before the first real invite, with nothing anywhere asserting what it touched.

Every test here is built the same way: a REAL family and a FIXTURE family in the same
database, wiped once, then both counted. A check that only asserts "the demo is gone" would
pass on `DELETE FROM everything`, which is exactly the bug.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User as AuthUser
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from PIL import Image

from core import demo_data, media
from core.models import (
    Comment,
    InboundQuarantine,
    Invite,
    MediaAsset,
    Member,
    Pod,
    PodMembership,
    Post,
    Reaction,
    Yard,
)

User = get_user_model()

MARKER = demo_data.SEED_MARKER


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (12, 34, 56)).save(buf, format="JPEG")
    return buf.getvalue()


@dataclass
class Family:
    """One complete family, typed, so assertions below read as `real.elder` rather than as
    a dict lookup with a `type: ignore` on every line."""

    yard: Yard
    pod: Pod
    author: Member
    elder: Member
    user: AuthUser
    post: Post
    comment: Comment
    asset: MediaAsset
    invite: Invite


def _family(*, marker: str, tag: str) -> Family:
    """One complete family — yard, pod, two members, post, reply, photo, reaction, invite.

    `marker` is what makes it fixture or real: the empty string is what every row a real
    person creates carries, because `seeded_by` defaults to blank.
    """
    yard = Yard.objects.create(name=f"{tag} side", slug=f"{tag}-side", seeded_by=marker)
    pod = Pod.objects.create(name=f"{tag} house", seeded_by=marker)
    pod.yards.set([yard])

    user = User.objects.create_user(username=f"{tag}-user")
    author = Member.objects.create(display_name=f"{tag} Author", user=user, seeded_by=marker)
    PodMembership.objects.create(member=author, pod=pod)

    # A member with NO auth user: an elder or a supervised child. The old wipe's
    # `exclude(user__username=...)` kept NULL rows in the delete set, so every real one of
    # these was destroyed on any instance. This is the row that proves the marker fixed it.
    elder = Member.objects.create(display_name=f"{tag} Nana", seeded_by=marker)
    PodMembership.objects.create(member=elder, pod=pod)

    post = Post.objects.create(author=author, pod=pod, body=f"{tag} post")
    post.audience_yards.set([yard])
    asset = media.ingest_photo(post=post, raw=_jpeg())
    comment = Comment.objects.create(post=post, author=elder, body=f"{tag} reply")
    Reaction.objects.create(member=elder, post=post)
    invite = Invite.objects.create(
        pod=pod,
        token_digest=f"digest-{tag}",
        created_by=author,
        expires_at=timezone.now() + timedelta(days=7),
    )

    assert asset is not None, "fixture setup: ingest_photo returned nothing"
    return Family(
        yard=yard,
        pod=pod,
        author=author,
        elder=elder,
        user=user,
        post=post,
        comment=comment,
        asset=asset,
        invite=invite,
    )


@pytest.fixture
def two_families() -> dict[str, Family]:
    return {
        "real": _family(marker="", tag="real"),
        "demo": _family(marker=MARKER, tag="demo"),
    }


@pytest.mark.django_db
def test_the_wipe_removes_the_fixture_family(two_families: dict[str, Family]) -> None:
    """Denominator. If this fails, every survival assertion below is vacuous — a wipe that
    deletes nothing trivially preserves the real family."""
    removed = demo_data.wipe(MARKER)
    assert removed, "the wipe deleted nothing, so the checks below prove nothing"

    demo = two_families["demo"]
    assert not Yard.objects.filter(pk=demo.yard.pk).exists()
    assert not Pod.objects.filter(pk=demo.pod.pk).exists()
    assert not Member.objects.filter(pk=demo.author.pk).exists()
    assert not Member.objects.filter(pk=demo.elder.pk).exists()
    assert not Post.objects.filter(pk=demo.post.pk).exists()
    assert not Comment.objects.filter(pk=demo.comment.pk).exists()
    assert not User.objects.filter(pk=demo.user.pk).exists()


@pytest.mark.django_db
def test_the_wipe_leaves_the_real_family_completely_intact(
    two_families: dict[str, Family],
) -> None:
    """The assertion the old wipe would have failed on its first line.

    Every row is checked individually rather than by a count, so a failure names what was
    destroyed instead of saying a number changed.
    """
    demo_data.wipe(MARKER)

    real = two_families["real"]
    assert Yard.objects.filter(pk=real.yard.pk).exists(), "a real yard was deleted"
    assert Pod.objects.filter(pk=real.pod.pk).exists(), "a real pod was deleted"
    assert Member.objects.filter(pk=real.author.pk).exists(), "a real member was deleted"
    assert Member.objects.filter(pk=real.elder.pk).exists(), "a real ELDER was deleted"
    assert User.objects.filter(pk=real.user.pk).exists(), "a real auth account was deleted"
    assert Post.objects.filter(pk=real.post.pk).exists(), "a real post was deleted"
    assert Comment.objects.filter(pk=real.comment.pk).exists(), "a real reply was deleted"
    assert MediaAsset.objects.filter(pk=real.asset.pk).exists(), "a real photo was deleted"
    assert Reaction.objects.filter(post=real.post).exists(), "a real reaction was deleted"
    assert Invite.objects.filter(pk=real.invite.pk).exists(), "a real invite was voided"


@pytest.mark.django_db
def test_the_real_family_keeps_its_pod_memberships(
    two_families: dict[str, Family],
) -> None:
    """The lockout. `Pod.objects.all().delete()` cascaded `PodMembership`, so the founder
    kept a Member row and belonged to zero pods — and therefore zero yards, no feed, no
    directory, and no self-service way back that did not mint him a second account."""
    demo_data.wipe(MARKER)

    author = two_families["real"].author
    assert PodMembership.objects.filter(member=author).exists(), (
        "the real member is in no pod after the wipe, which is the founder-lockout defect: "
        "a member in no pod resolves nobody, including themselves"
    )


@pytest.mark.django_db(transaction=True)
def test_the_wipe_takes_the_fixture_photos_off_the_disk_and_leaves_the_real_ones(
    two_families: dict[str, Family],
) -> None:
    """Files, not just rows. Run against a REAL commit (`transaction=True`) on purpose.

    `media._purge` defers the unlink to `transaction.on_commit`, which never runs inside
    the rollback-per-test transaction. Capturing the callbacks and invoking them by hand
    would assert that a callback was registered, not that the bytes left the volume — and
    "the bytes left the volume" is the entire claim.

    There is no `post_delete` signal on `MediaAsset`, a queryset `.delete()` never calls
    `Model.delete()`, and Django has not removed `FileField` files on model delete since
    1.3 — so the old wipe left every photograph and every video source on the volume with
    no row pointing at it. Unreachable, unpurgeable, invisible.
    """
    demo_asset = two_families["demo"].asset
    real_asset = two_families["real"].asset
    assert demo_asset is not None and real_asset is not None
    demo_image = demo_asset.image
    real_image = real_asset.image
    assert demo_image.storage.exists(demo_image.name), "fixture setup: the file should exist"

    demo_data.wipe(MARKER)

    assert not demo_image.storage.exists(demo_image.name), (
        "the fixture photograph's row is gone but its bytes are still on the volume"
    )
    assert real_image.storage.exists(real_image.name), "a real photograph was deleted from disk"


@pytest.mark.django_db
def test_the_wipe_kills_fixture_sessions_and_keeps_real_ones(
    two_families: dict[str, Family],
) -> None:
    """A deleted member's cookie must stop authenticating.

    The old wipe cleared no sessions at all, so a browser holding one kept signing in
    against whatever `User` row survived.
    """
    from django.test import Client

    demo_user = two_families["demo"].user
    real_user = two_families["real"].user
    backend = "django.contrib.auth.backends.ModelBackend"
    for user in (demo_user, real_user):
        client = Client()
        client.force_login(user, backend=backend)
    assert Session.objects.count() == 2, "fixture setup: two live sessions"

    demo_data.wipe(MARKER)

    survivors = {s.get_decoded().get("_auth_user_id") for s in Session.objects.all()}
    assert str(real_user.pk) in survivors, "a real member's session was destroyed"
    assert str(demo_user.pk) not in survivors, (
        "a deleted member's session survived, so their cookie still authenticates"
    )


@pytest.mark.django_db
def test_the_admin_moderation_queue_survives_the_member_it_records(
    two_families: dict[str, Family],
) -> None:
    """`InboundQuarantine.member` was CASCADE on a nullable FK, so deleting members
    destroyed the instance admin's record of the mail that was refused — the one table
    whose job is to outlive what it is a record of."""
    demo_author = two_families["demo"].author
    row = InboundQuarantine.objects.create(
        reason=InboundQuarantine.REASON_CHOICES[0][0],
        from_header="someone@example.test",
        member=demo_author,
    )

    demo_data.wipe(MARKER)

    row.refresh_from_db()
    assert row.member_id is None, "the quarantine row should detach, not vanish"


@pytest.mark.django_db
def test_a_real_member_whose_only_pod_is_a_fixture_pod_stops_the_wipe() -> None:
    """The founder-lockout defect, stated as an invariant instead of as one username.

    A member in no pod belongs to no yard and resolves nobody, including themselves — no
    feed, no directory, and no self-service route back (`/setup/` is closed once a
    superuser exists, Django admin is not mounted, `create_adhoc_pod` needs a yard they no
    longer have, and `join()` redirects an authenticated user without joining). So the wipe
    refuses rather than doing that to anybody.

    This is not hypothetical housekeeping: it is what `Pod.objects.all().delete()` did to
    the founder every single time, and the old code had no way to notice.
    """
    yard = Yard.objects.create(name="Fixture", slug="fixture", seeded_by=MARKER)
    pod = Pod.objects.create(name="Fixture house", seeded_by=MARKER)
    pod.yards.set([yard])
    real = Member.objects.create(display_name="A Real Person")  # unmarked
    PodMembership.objects.create(member=real, pod=pod)

    with pytest.raises(demo_data.DemoDataError, match="left in no pod"):
        demo_data.wipe(MARKER)

    assert Member.objects.filter(pk=real.pk).exists(), "it deleted despite refusing"
    assert Pod.objects.filter(pk=pod.pk).exists(), "it deleted despite refusing"

    # Give them a household of their own and the same wipe proceeds — so the refusal is a
    # real condition on the data, not a permanent block.
    own = Pod.objects.create(name="Their own house")
    own.yards.set([Yard.objects.create(name="Real", slug="real-side")])
    PodMembership.objects.create(member=real, pod=own)
    demo_data.wipe(MARKER)
    assert not Pod.objects.filter(pk=pod.pk).exists(), "the fixture pod should be gone now"
    assert Member.objects.filter(pk=real.pk).exists()


@pytest.mark.django_db
def test_preview_changes_nothing(two_families: dict[str, Family]) -> None:
    before = (Pod.objects.count(), Member.objects.count(), Post.objects.count())
    planned = demo_data.preview(MARKER)
    assert planned, "preview reported nothing to delete, so it is measuring the wrong thing"
    after = (Pod.objects.count(), Member.objects.count(), Post.objects.count())
    assert before == after, "preview deleted rows"


@pytest.mark.django_db
def test_the_command_refuses_without_yes(two_families: dict[str, Family]) -> None:
    """`BACKYARD_DEMO_WIPE=1` was one environment variable and no confirmation."""
    with pytest.raises(CommandError, match="Refusing to delete without --yes"):
        call_command("wipe_demo_data")
    assert Pod.objects.filter(seeded_by=MARKER).exists(), "it deleted despite refusing"


@pytest.mark.django_db
def test_the_command_dry_run_reports_and_deletes_nothing(
    two_families: dict[str, Family],
) -> None:
    from io import StringIO

    out = StringIO()
    call_command("wipe_demo_data", "--dry-run", stdout=out)
    printed = out.getvalue()
    assert "core.Pod" in printed and "Nothing was deleted" in printed
    assert Pod.objects.filter(seeded_by=MARKER).exists()


@pytest.mark.django_db(transaction=True)
def test_the_real_seed_script_is_fully_wipeable_and_leaves_the_founder_standing() -> None:
    """Run `scripts/demo_seed.py` for real, wipe, and see what is left.

    This is the launch-day operation, end to end, and it is the guard that stops the marker
    drifting. Asserting the marker at the source level — "every `Member.objects.create(` in
    the seed passes `seeded_by`" — is the substring-for-a-structural-property mistake this
    repo keeps finding in its own gates, and it would have missed the real case:
    `supervised.create_supervised_member` builds the Member itself, so the child came out
    unmarked and would have survived as an orphan whose parent no longer exists.
    """
    from pathlib import Path

    seed = Path(__file__).resolve().parents[3] / "scripts" / "demo_seed.py"
    namespace: dict[str, object] = {"__name__": "__demo_seed__", "__file__": str(seed)}
    exec(compile(seed.read_text(), str(seed), "exec"), namespace)  # noqa: S102

    seeded_members = Member.objects.count()
    assert seeded_members > 4, f"the seed created only {seeded_members} members; did it run?"
    assert Pod.objects.count() >= 4, "the seed did not create its pods"

    removed = demo_data.wipe(MARKER)
    assert removed, "the seed's output was not wipeable at all"

    # Exactly one member left: the founder, still in a pod, still an instance admin.
    #
    # Compared by count and by role rather than by name. Spelling the founder's name here
    # would put the author's real surname into shipping source, which
    # `test_privacy_line_holds.py` forbids — it belongs in git authorship and the copyright
    # notice, nowhere else. (It caught this line.)
    survivors = list(Member.objects.all())
    assert len(survivors) == 1, (
        f"the wipe left {[m.display_name for m in survivors]} behind. Anything beyond the "
        "founder is fixture data the seed created without the marker — it will sit in a "
        "real family's directory forever, and nothing will ever remove it."
    )
    founder = survivors[0]
    assert founder.seeded_by == "", "the founder's own row must never carry the marker"
    assert founder.role == Member.INSTANCE_ADMIN
    assert PodMembership.objects.filter(member=founder).exists(), (
        "the founder survived the wipe with no pod membership, which is the lockout: no "
        "feed, no directory, and no self-service route back to his own family"
    )
    surviving_pod = founder.pods.first()
    assert surviving_pod is not None and surviving_pod.yards.exists(), (
        "the founder's surviving pod is in no yard, which strands him just as thoroughly"
    )
    assert not Yard.objects.filter(seeded_by=MARKER).exists(), "a seeded yard survived"
    assert not Pod.objects.filter(seeded_by=MARKER).exists(), "a seeded pod survived"
    assert not Post.objects.exists(), "a seeded post survived the wipe"
    assert not MediaAsset.objects.exists(), "a seeded photograph's row survived the wipe"


@pytest.mark.django_db
def test_an_unmarked_instance_is_told_so_rather_than_wiped() -> None:
    """An instance seeded before the marker existed has unmarked fixture rows. The command
    must say that plainly instead of falling back to something broader — falling back is
    what the old code did."""
    from io import StringIO

    Pod.objects.create(name="Unmarked house")
    out = StringIO()
    call_command("wipe_demo_data", "--yes", stdout=out)
    assert "Nothing is marked" in out.getvalue()
    assert Pod.objects.count() == 1, "an unmarked pod was deleted"
