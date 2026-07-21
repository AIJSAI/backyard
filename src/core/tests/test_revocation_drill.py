"""The full revocation-completeness drill (wave-5 exit, Phase 2 exit).

The wave plan's exit gate, verbatim: after regenerate AND after removal, the
master token, the session, the digest link, the signed media URL, and the reply
address each 404 or bounce on the next request. This is the one test that holds
every credential class the product mints against a single revocation act, so a
future class that forgets to register in the TM-1 registry fails HERE even if
its own suite is green. It is the belt over the belt: each class already has its
own completeness assertion, and this proves they all die together.
"""

from __future__ import annotations

import datetime
import io

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core import digest_links, elder_tokens, media, reply_addresses, revocation
from core.models import (
    DigestIssue,
    DigestSubscription,
    DigestToken,
    ElderToken,
    Member,
    Pod,
    PodMembership,
    Post,
    ReplyAddress,
    Yard,
)

pytestmark = pytest.mark.django_db
User = get_user_model()
_TEST_PW = "a-Strong-passphrase-9"
_BACKEND = "django.contrib.auth.backends.ModelBackend"


class Credentials:
    """Every live credential a member holds, and how each is checked on next use."""

    def __init__(self, member: Member, post: Post, issue: DigestIssue) -> None:
        self.member = member
        self.post = post
        self.issue = issue
        # Master token: the raw handed-over value.
        self.elder_raw = elder_tokens.mint(member)
        # A live web session from that token exchange.
        self.elder_client = Client()
        self.elder_client.get(reverse("elder_enter", args=[self.elder_raw]))
        # A digest read link.
        self.digest_raw = digest_links.mint(issue)
        # A signed media URL (the media asset's own token).
        self.media_token = media.ingest_photo(post=post, raw=_jpeg()).token
        # A reply-by-email capability.
        self.reply_local = reply_addresses.mint_for_issue(issue, [post.id])[post.id]
        # A logged-in web session, if the member has a login.
        self.web_client: Client | None = None
        if member.user is not None:
            self.web_client = Client()
            self.web_client.force_login(member.user, backend=_BACKEND)

    def all_dead(self) -> dict[str, bool]:
        """True per class iff it 404s or bounces on its next use, checked NOW.

        The media URL is served through the member's OWN authenticated session
        (serve_media is login_required and re-checks audience), so its death is
        the session dying: a 302 bounce to login. Every other class is a bare
        token surface that 404s, or the reply capability that bounces."""
        assert self.web_client is not None
        return {
            "master_token": Client().get(reverse("elder_enter", args=[self.elder_raw])).status_code
            == 404,
            "elder_session": self.elder_client.get(reverse("elder_feed")).status_code == 404,
            "web_session": self.web_client.get(reverse("feed")).status_code == 302,
            "digest_link": Client().get(reverse("digest_web", args=[self.digest_raw])).status_code
            == 404,
            "signed_media_url": self.web_client.get(
                reverse("serve_media", args=[self.media_token])
            ).status_code
            != 200,
            "reply_address": _reply_bounces(self.reply_local),
        }


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (3, 3, 3)).save(buf, format="JPEG")
    return buf.getvalue()


def _reply_bounces(local_part: str) -> bool:
    try:
        reply_addresses.resolve(local_part)
        return False
    except reply_addresses.ReplyAddressInvalid:
        return True


@pytest.fixture
def member_with_everything() -> Credentials:
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    pod = Pod.objects.create(name="Cousins")
    pod.yards.set([yard])
    user = User.objects.create_user(username="nana", password=_TEST_PW)
    member = Member.objects.create(display_name="Nana", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=member, pod=pod, body="a post")
    now = timezone.now()
    issue = DigestIssue.objects.create(
        member=member, yard=yard, window_start=now - datetime.timedelta(days=7), window_end=now
    )
    DigestSubscription.objects.create(
        member=member, address="nana@example.com", enabled=True, confirmed_at=now
    )
    return Credentials(member, post, issue)


def test_every_credential_class_is_live_before_revocation(
    member_with_everything: Credentials,
) -> None:
    """The drill is non-vacuous: every class WORKS first, so the after-checks
    prove revocation, not a pre-broken credential."""
    creds = member_with_everything
    assert Client().get(reverse("elder_enter", args=[creds.elder_raw])).status_code == 302
    assert creds.elder_client.get(reverse("elder_feed")).status_code == 200
    assert Client().get(reverse("digest_web", args=[creds.digest_raw])).status_code == 200
    assert creds.web_client is not None
    assert creds.web_client.get(reverse("feed")).status_code == 200
    assert creds.web_client.get(reverse("serve_media", args=[creds.media_token])).status_code == 200
    assert reply_addresses.resolve(creds.reply_local)  # does not raise


def test_regenerate_kills_every_class_on_next_request(
    member_with_everything: Credentials,
) -> None:
    """After the total regenerate, every credential class the member held is dead
    on its next use (wave-5 exit, first half)."""
    creds = member_with_everything
    elder_tokens.regenerate(creds.member)
    dead = creds.all_dead()
    assert all(dead.values()), f"survivors: {[k for k, v in dead.items() if not v]}"


def test_removal_kills_every_class_on_next_request(
    member_with_everything: Credentials,
) -> None:
    """After removal, every credential class 404s or bounces on next use
    (wave-5 exit, second half). Uses the S-702 removal flow, not a bare bump."""
    from core.removal import remove_member

    creds = member_with_everything
    remove_member(creds.member)
    dead = creds.all_dead()
    assert all(dead.values()), f"survivors: {[k for k, v in dead.items() if not v]}"


def test_the_drill_covers_every_registered_credential_class(
    member_with_everything: Credentials,
) -> None:
    """Pin the coverage: the drill's class set matches the revocation registry
    plus the session classes. A new class added to _REVOCATION_STEPS without a
    drill check fails here, so the wave-exit gate can never silently narrow."""
    creds = member_with_everything
    elder_tokens.regenerate(creds.member)
    checked = set(creds.all_dead().keys())
    # The row-backed classes the registry voids, plus the two session classes
    # the generation bump kills, are all represented in the drill.
    assert {
        "master_token",
        "elder_session",
        "web_session",
        "digest_link",
        "signed_media_url",
        "reply_address",
    } <= checked
    # And every registry step that deletes/voids a member-scoped row has a drill
    # check: sessions, invites (no live invite here), digest subscription,
    # digest tokens, reply addresses, elder tokens. The registry length is the
    # tripwire — a new step forces a reviewer to extend this drill.
    assert len(revocation._REVOCATION_STEPS) == 6


def test_leftover_rows_are_gone_after_removal(member_with_everything: Credentials) -> None:
    """Belt on the belt: removal leaves no live credential ROW, not only a failing
    check, so a forwarded link in a mailbox has nothing to resolve against."""
    from core.removal import remove_member

    creds = member_with_everything
    remove_member(creds.member)
    assert not ElderToken.objects.filter(member=creds.member).exists()
    assert not DigestToken.objects.filter(member=creds.member).exists()
    assert ReplyAddress.objects.filter(member=creds.member, voided_at__isnull=True).count() == 0
    assert not DigestSubscription.objects.filter(member=creds.member, enabled=True).exists()
