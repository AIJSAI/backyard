"""The one notification opt-in actually sends something now (S-305).

The audit's finding: `notify_on_reply` was written by the settings page and read by
nothing. The member ticked "Tell me when someone replies to my post", waited, and got
silence indistinguishable from nobody having replied — the worst kind of failure, because
there is no way to tell it from working correctly.

S-305 is a NEGATIVE guarantee and these tests defend it from both sides: the nudge must
fire when it was asked for, and must not fire in every case where it was not.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.db import connection
from django.utils import timezone

from core import commenting, emailing, notifications
from core.models import DigestSubscription, Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db


@pytest.fixture
def world() -> dict[str, object]:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    author = Member.objects.create(display_name="Priya")
    replier = Member.objects.create(display_name="Sam")
    for member in (author, replier):
        PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=author, pod=pod, body="Camp dump, finally")
    return {"yard": yard, "pod": pod, "author": author, "replier": replier, "post": post}


def _opt_in(member: Member, *, confirmed: bool = True) -> DigestSubscription:
    notifications.set_reply_notification(member, enabled=True)
    return DigestSubscription.objects.create(
        member=member,
        address=f"{member.display_name.lower()}@example.com",
        confirmed_at=timezone.now() if confirmed else None,
    )


def _reply(world: dict[str, object], body: str = "Lovely!") -> None:
    """Create the reply, then run the nudge the way the worker does.

    The send is deferred to the worker on commit (a synchronous SMTP conversation inside
    the member's write transaction could cost them the reply when gunicorn times out), so
    these tests drive `notify_reply` directly — the same function the task calls, with the
    same live re-resolution. `test_create_comment_defers_the_nudge_and_never_sends_inline`
    below is what pins the wiring between the two.
    """
    replier, post = world["replier"], world["post"]
    assert isinstance(replier, Member) and isinstance(post, Post)
    comment = commenting.create_comment(author=replier, post=post, body=body)
    notifications.notify_reply(comment)


def test_an_opted_in_author_is_told_when_someone_replies(world: dict[str, object]) -> None:
    """The whole point. Before this, no sending path read the preference at all."""
    author = world["author"]
    assert isinstance(author, Member)
    subscription = _opt_in(author)
    mail.outbox.clear()

    _reply(world)

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [subscription.address]
    assert "Sam replied to your post" in sent.subject


def test_the_nudge_carries_no_reply_text(world: dict[str, object]) -> None:
    """A notification that quoted the reply would be a second content path around the
    audience query, and there is exactly one. It says THAT someone replied, not what."""
    author = world["author"]
    assert isinstance(author, Member)
    _opt_in(author)
    mail.outbox.clear()

    _reply(world, body="the secret is under the third flowerpot")

    assert "third flowerpot" not in mail.outbox[0].body


def test_silence_is_the_default(world: dict[str, object]) -> None:
    """No opt-in, no mail — the guarantee, asserted rather than assumed."""
    author = world["author"]
    assert isinstance(author, Member)
    DigestSubscription.objects.create(
        member=author, address="priya@example.com", confirmed_at=timezone.now()
    )
    mail.outbox.clear()
    _reply(world)
    assert mail.outbox == []


def test_an_unconfirmed_address_is_never_mailed(world: dict[str, object]) -> None:
    """The digest double opt-in (T-EMAIL-6) is the only thing that verifies an address
    here. A reply nudge must never be the first message to an unverified inbox."""
    author = world["author"]
    assert isinstance(author, Member)
    _opt_in(author, confirmed=False)
    mail.outbox.clear()
    _reply(world)
    assert mail.outbox == []


def test_an_unsubscribed_address_is_never_nudged(world: dict[str, object]) -> None:
    """The one-click unsubscribe in the digest must silence THIS too.

    unsubscribe() deliberately leaves confirmed_at intact and only flips `enabled`, so
    gating on confirmation alone meant the capability stopped the digest and not the
    nudge. For an address-only member — the elder with no login to reach the settings
    page — that link is the only lever they have, so the mail became unstoppable.
    """
    from core import digesting

    author = world["author"]
    assert isinstance(author, Member)
    subscription = _opt_in(author)
    raw = digesting.rotate_unsubscribe_token(subscription)
    digesting.unsubscribe(raw)
    mail.outbox.clear()

    _reply(world)

    assert mail.outbox == []


def test_the_nudge_carries_its_own_way_out(world: dict[str, object]) -> None:
    """Every message must carry an unsubscribe route. Without one the only lever was a
    settings page behind a login, which an address-only member does not have."""
    author = world["author"]
    assert isinstance(author, Member)
    _opt_in(author)
    mail.outbox.clear()
    _reply(world)
    assert "/digest/unsubscribe/" in mail.outbox[0].body


def test_no_address_at_all_is_not_an_error(world: dict[str, object]) -> None:
    """Opted in, but never subscribed to the digest: nothing to send to, and the reply
    itself must still succeed."""
    author, post = world["author"], world["post"]
    assert isinstance(author, Member) and isinstance(post, Post)
    notifications.set_reply_notification(author, enabled=True)
    mail.outbox.clear()
    _reply(world)
    assert mail.outbox == []
    assert post.comments.count() == 1


def test_replying_to_yourself_is_not_news(world: dict[str, object]) -> None:
    author, post = world["author"], world["post"]
    assert isinstance(author, Member) and isinstance(post, Post)
    _opt_in(author)
    mail.outbox.clear()
    comment = commenting.create_comment(author=author, post=post, body="adding one more thing")
    notifications.notify_reply(comment)
    assert mail.outbox == []


def test_a_replier_who_left_the_yard_is_not_named(world: dict[str, object]) -> None:
    """Re-resolved live at send time: if the replier is no longer someone the author can
    see, the author is not told their name."""
    author, replier, post = world["author"], world["replier"], world["post"]
    assert isinstance(author, Member) and isinstance(replier, Member)
    assert isinstance(post, Post)
    _opt_in(author)
    comment = commenting.create_comment(author=replier, post=post, body="Lovely!")
    PodMembership.objects.filter(member=replier).delete()
    mail.outbox.clear()

    assert notifications.notify_reply(comment) is False
    assert mail.outbox == []


def test_a_transport_failure_never_costs_the_member_their_reply(
    world: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reply is the member's writing; the nudge is a courtesy. A broken mail server
    must not roll back or reject the comment."""
    author, post = world["author"], world["post"]
    assert isinstance(author, Member) and isinstance(post, Post)
    _opt_in(author)

    def _explode(**_kwargs: object) -> None:
        raise OSError("smtp is down")

    monkeypatch.setattr(emailing, "send_family_email", _explode)
    _reply(world)
    assert post.comments.count() == 1  # the reply landed anyway


def test_the_preference_model_still_grows_no_firehose(world: dict[str, object]) -> None:
    """S-305's original absence guarantee, re-asserted now that a send path exists: the
    single opt-in must not have quietly become the first of many."""
    from core.models import NotificationPreference

    fields = {f.name for f in NotificationPreference._meta.get_fields()}
    assert "notify_on_reply" in fields
    assert not {f for f in fields if f.startswith("notify_") and f != "notify_on_reply"}


def test_create_comment_defers_the_nudge_and_never_sends_inline(
    world: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, pinned: create_comment must DEFER, not send.

    An inline send ran a whole SMTP conversation inside the member's open write
    transaction (ATOMIC_REQUESTS). EMAIL_TIMEOUT bounds each socket operation but not
    their sum, so a degraded mail server outruns gunicorn's timeout, the worker is killed
    mid-view, the transaction rolls back — and the member loses the reply they wrote.
    Deferring on commit also stops mail going out for a comment that never committed.
    """
    from core import tasks

    author, replier, post = world["author"], world["replier"], world["post"]
    assert isinstance(author, Member) and isinstance(replier, Member)
    assert isinstance(post, Post)
    _opt_in(author)
    mail.outbox.clear()

    deferred: list[int] = []
    monkeypatch.setattr(
        tasks.notify_reply_task, "defer", lambda **kw: deferred.append(kw["comment_id"])
    )
    comment = commenting.create_comment(author=replier, post=post, body="Lovely!")
    for callback in connection.run_on_commit:
        callback[1]()

    assert deferred == [comment.pk]  # queued for the worker...
    assert mail.outbox == []  # ...and nothing sent from the request itself
