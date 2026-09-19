"""BY-01: the admin-issued "get back in" link, and everything it must refuse.

The gap: email is optional at join (S-101), so a member who gave none has no
`Forgot your password?` path at all — and `ACCOUNT_PREVENT_ENUMERATION` correctly makes
the reset page say "sent" either way, so they find out they are locked out at the worst
possible moment. No admin control existed; the only cure was `manage.py changepassword`
at a server shell, and `docs/runbooks/setting-up-your-side.md` told the delegate to "ask
whoever runs the server".

This is a password-setting bearer credential handed to a non-technical relative to text
to another relative, so the negatives are the point and they come first: who may issue
one, and every way a link must stop working. The positive path is at the bottom.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from core import elder_tokens, recovery, removal
from core.models import Member, Pod, PodMembership, RecoveryToken, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_OLD_PW = "old-Passphrase-9"
_NEW_PW = "correct-horse-battery-staple-42"


def _member(pods: list[Pod], *, name: str, role: str = Member.MEMBER, login: bool = True) -> Member:
    user = User.objects.create_user(username=name.lower().replace(" ", "-"), password=_OLD_PW)
    member = Member.objects.create(display_name=name, user=user if login else None, role=role)
    for pod in pods:
        PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


class World:
    """Two sides of a family, a bridging household, and one admin of each kind."""

    def __init__(self) -> None:
        self.maternal = Yard.objects.create(name="Maternal", slug="maternal")
        self.paternal = Yard.objects.create(name="Paternal", slug="paternal")
        self.here = Pod.objects.create(name="Our house")
        self.here.yards.set([self.maternal])
        self.far = Pod.objects.create(name="Their house")
        self.far.yards.set([self.paternal])
        self.bridge = Pod.objects.create(name="The bridging household")
        self.bridge.yards.set([self.maternal, self.paternal])

        self.boss = _member([self.here], name="Instance Admin", role=Member.INSTANCE_ADMIN)
        self.delegate = _member([self.here], name="Yard Admin", role=Member.YARD_ADMIN)
        self.peer = _member([self.here], name="Peer Admin", role=Member.YARD_ADMIN)
        self.relative = _member([self.here], name="Nana", role=Member.MEMBER)
        self.far_cousin = _member([self.far], name="Far Cousin", role=Member.MEMBER)
        self.bridger = _member([self.bridge], name="Bridger", role=Member.MEMBER)


@pytest.fixture
def world() -> World:
    return World()


def _issue_url(target: Member) -> str:
    return reverse("issue_recovery", args=[target.pk])


def _mint(target: Member, *, by: Member) -> str:
    """Mint through the service, for the token tests that are not about the view."""
    return recovery.issue(target, issued_by=by)


# --- who may not issue one ---------------------------------------------------------


def _without_nonces(body: bytes) -> bytes:
    """The 404 page with its per-request CSP nonce normalised away.

    base.html emits `<script nonce="...">` for a signed-in viewer, so two renders of the
    identical page differ by construction. Comparing raw bytes here would assert the CSP
    is working, not that the two refusals are indistinguishable. The unauthenticated
    surface — where the enumeration question actually lives — is compared raw, in
    test_every_dead_link_answers_identically.
    """
    return re.sub(rb'nonce="[^"]*"', b'nonce="x"', body)


def test_a_yard_admin_cannot_issue_across_the_family(world: World) -> None:
    """The other side is a 404, indistinguishable from a member who does not exist
    (S-202). A yard admin must never learn that Far Cousin is here, let alone reset
    them."""
    response = _client_for(world.delegate).get(_issue_url(world.far_cousin))
    assert response.status_code == 404
    missing = _client_for(world.delegate).get(reverse("issue_recovery", args=[999_999]))
    assert _without_nonces(response.content) == _without_nonces(missing.content), (
        "the refusal is an existence oracle"
    )


def test_a_yard_admin_cannot_issue_for_a_bridging_member(world: World) -> None:
    """T-AUTH-G2. Bridger also belongs to the side this admin does not control, so
    resetting their password would be a lever into the other yard."""
    assert _client_for(world.delegate).get(_issue_url(world.bridger)).status_code == 403


@pytest.mark.parametrize("target_name", ["peer", "boss"])
def test_a_yard_admin_cannot_issue_for_another_admin(world: World, target_name: str) -> None:
    """No privilege inversion: taking over a peer yard admin's or the instance admin's
    account is the most valuable thing this control could be turned into."""
    target: Member = getattr(world, target_name)
    assert _client_for(world.delegate).get(_issue_url(target)).status_code == 403


def test_a_plain_member_cannot_issue_for_anyone(world: World) -> None:
    client = _client_for(world.relative)
    assert client.get(_issue_url(world.delegate)).status_code == 403
    other = _member([world.here], name="Another Cousin")
    assert client.get(_issue_url(other)).status_code == 403


@pytest.mark.parametrize("actor_name", ["boss", "delegate"])
def test_nobody_issues_one_for_themselves(world: World, actor_name: str) -> None:
    """`can_manage_member` denies self-administration at every role, and it must hold
    here too: a recovery link an admin mints for themselves is a password reset with no
    second party in it. An admin's own path is break-glass, which needs server shell."""
    actor: Member = getattr(world, actor_name)
    assert _client_for(actor).get(_issue_url(actor)).status_code == 403


def test_an_elder_and_a_supervised_child_are_not_offered_one(world: World) -> None:
    """Neither has a password to reset: an elder holds a no-login token link (TM-10) and
    a supervised account belongs to its parent. A 404, not a 403, because the control is
    never rendered for them — this is the belt behind the roster's gate."""
    elder = Member.objects.create(display_name="Great Nana")
    PodMembership.objects.create(member=elder, pod=world.here)
    child = Member.objects.create(
        display_name="Small Cousin", is_supervised=True, managing_parent=world.relative
    )
    PodMembership.objects.create(member=child, pod=world.here)

    client = _client_for(world.boss)
    assert client.get(_issue_url(elder)).status_code == 404
    assert client.get(_issue_url(child)).status_code == 404
    # ...and the service refuses too, so a caller that skips the view gets nothing.
    for target in (elder, child):
        with pytest.raises(recovery.RecoveryRefused):
            recovery.issue(target, issued_by=world.boss)


def test_the_roster_offers_the_control_exactly_where_the_view_allows(world: World) -> None:
    """A link that 403s is a link that lies. The roster's gate and the view's must agree,
    which is the defect `Elder link` already shipped once."""
    page = _client_for(world.delegate).get(reverse("members")).content.decode()
    assert _issue_url(world.relative) in page, "the one member they CAN help is not offered"
    for out_of_reach in (world.peer, world.boss, world.bridger, world.delegate):
        assert _issue_url(out_of_reach) not in page


# --- every way a link must stop working --------------------------------------------


def test_an_unknown_link_is_a_bare_404(world: World) -> None:
    assert Client().get(reverse("recover", args=["not-a-real-token"])).status_code == 404


def test_an_expired_link_is_dead_and_changes_nothing(world: World) -> None:
    raw = _mint(world.relative, by=world.boss)
    RecoveryToken.objects.filter(member=world.relative).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    url = reverse("recover", args=[raw])
    assert Client().get(url).status_code == 404
    assert Client().post(url, {"password": _NEW_PW}).status_code == 404
    assert world.relative.user is not None
    world.relative.user.refresh_from_db()
    assert world.relative.user.check_password(_OLD_PW)


def test_the_window_is_two_days_not_the_three_day_reset_default(world: World) -> None:
    """A link read out over the phone is used this evening. Pinned because the number is
    the difference between 'stale link' and 'credential sitting in a text thread'."""
    _mint(world.relative, by=world.boss)
    token = RecoveryToken.objects.get(member=world.relative)
    assert recovery.TTL_HOURS == 48
    assert timedelta(hours=47) < token.expires_at - token.created_at < timedelta(hours=49)


def test_a_link_works_once(world: World) -> None:
    raw = _mint(world.relative, by=world.boss)
    url = reverse("recover", args=[raw])
    assert Client().post(url, {"password": _NEW_PW}).status_code == 302
    # Second use, with a password of its own, is refused and does not take.
    second = "a-fine-passphrase-1234"
    assert Client().post(url, {"password": second}).status_code == 404
    assert world.relative.user is not None
    world.relative.user.refresh_from_db()
    assert world.relative.user.check_password(_NEW_PW)
    assert not world.relative.user.check_password(second)


def test_issuing_a_new_link_kills_the_previous_one(world: World) -> None:
    """The admin re-reads it out because the first text did not arrive. Whoever holds the
    earlier copy must not still be able to use it."""
    first = _mint(world.relative, by=world.boss)
    second = _mint(world.relative, by=world.delegate)
    assert first != second
    assert Client().get(reverse("recover", args=[first])).status_code == 404
    assert Client().get(reverse("recover", args=[second])).status_code == 200


def test_re_issuing_after_a_redemption_produces_a_working_link(world: World) -> None:
    """The row is reused, and it carries `used_at` from last time. A fresh link that
    resolves as already spent would make the control work exactly once per member,
    forever — which is the failure nobody would find until the second time it mattered."""
    first = _mint(world.relative, by=world.boss)
    assert Client().post(reverse("recover", args=[first]), {"password": _NEW_PW}).status_code == 302
    again = _mint(world.relative, by=world.boss)
    assert Client().get(reverse("recover", args=[again])).status_code == 200


@pytest.mark.parametrize("act", ["removal", "regenerate"])
def test_the_revocation_act_kills_an_outstanding_link(world: World, act: str) -> None:
    """TM-1: one revocation act kills every credential class the member holds. A live
    recovery link in somebody's messages is exactly the kind of survivor that makes a
    removal untrue."""
    raw = _mint(world.relative, by=world.boss)
    if act == "removal":
        removal.remove_member(world.relative, content=removal.KEEP)
    else:
        elder_tokens.regenerate(world.relative)
    assert Client().get(reverse("recover", args=[raw])).status_code == 404
    assert not RecoveryToken.objects.filter(member=world.relative).exists(), "the row survived"


def test_opening_the_link_does_not_consume_it(world: World) -> None:
    """A link preview, a mail scanner, or the relative reading it before they are at a
    keyboard must not burn their only way back in. Only the explicit POST consumes."""
    raw = _mint(world.relative, by=world.boss)
    url = reverse("recover", args=[raw])
    for _ in range(3):
        assert Client().get(url).status_code == 200
    assert RecoveryToken.objects.get(member=world.relative).used_at is None
    assert Client().post(url, {"password": _NEW_PW}).status_code == 302


def test_a_rejected_password_does_not_burn_the_link(world: World) -> None:
    """Django's validators trip on the obvious passwords, and on a phone that is the
    first attempt as often as not. Burning the link there would lock them out for good."""
    raw = _mint(world.relative, by=world.boss)
    url = reverse("recover", args=[raw])
    response = Client().post(url, {"password": "123"})
    assert response.status_code == 200
    assert b"too short" in response.content.lower() or b"common" in response.content.lower()
    assert RecoveryToken.objects.get(member=world.relative).used_at is None
    assert Client().post(url, {"password": _NEW_PW}).status_code == 302


def test_every_dead_link_answers_identically(world: World) -> None:
    """Unknown, expired, spent and revoked must be indistinguishable, or the page is an
    oracle for which of a family's members has an outstanding reset."""
    spent = _mint(world.relative, by=world.boss)
    Client().post(reverse("recover", args=[spent]), {"password": _NEW_PW})

    expired_for = _member([world.here], name="Expired Cousin")
    expired = _mint(expired_for, by=world.boss)
    RecoveryToken.objects.filter(member=expired_for).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    revoked_for = _member([world.here], name="Revoked Cousin")
    revoked = _mint(revoked_for, by=world.boss)
    elder_tokens.regenerate(revoked_for)

    bodies = {
        Client().get(reverse("recover", args=[raw])).content
        for raw in ("never-minted-at-all", spent, expired, revoked)
    }
    assert len(bodies) == 1, "the four dead shapes render differently"


def test_the_raw_token_is_never_stored(world: World) -> None:
    raw = _mint(world.relative, by=world.boss)
    token = RecoveryToken.objects.get(member=world.relative)
    assert raw not in token.token_digest
    assert len(raw) >= 43, "shorter than 256 bits of token_urlsafe"
    assert len(token.token_digest) == 64  # SHA-256 hex


def test_minting_refuses_an_insecure_production_base_url(world: World) -> None:
    """T-EDGE-1, the same promise the elder link keeps: a password-setting capability is
    never minted into a URL that would carry it in the clear."""
    with override_settings(BASE_URL="http://backyard.example.com"):
        with pytest.raises(recovery.RecoveryRefused):
            recovery.issue(world.relative, issued_by=world.boss)
    with override_settings(BASE_URL="https://backyard.example.com"):
        assert recovery.issue(world.relative, issued_by=world.boss)


def test_issuing_is_rate_limited(world: World) -> None:
    """A walked-away-from admin session must not be able to turn the whole roster into a
    pile of live password-setting links."""
    client = _client_for(world.boss)
    statuses = []
    for _ in range(12):
        page = client.get(_issue_url(world.relative))
        intent = page.context["intent"] if page.status_code == 200 else ""
        statuses.append(client.post(_issue_url(world.relative), {"intent": intent}).status_code)
    assert 429 in statuses


# --- the path that has to work -----------------------------------------------------


def test_a_yard_admin_gets_their_relative_back_in(world: World) -> None:
    """End to end, as the two of them would do it: the admin opens the row, makes the
    link, reads it out; the relative sets a password and signs in with it."""
    admin_client = _client_for(world.delegate)
    page = admin_client.get(_issue_url(world.relative))
    assert page.status_code == 200
    minted = admin_client.post(_issue_url(world.relative), {"intent": page.context["intent"]})
    assert minted.status_code == 200

    link = minted.context["minted_link"]
    assert link.startswith("http")
    # The raw value appears once, in the body of the page that minted it, and that page
    # carries the hand-over hygiene headers (TM-5).
    assert minted["Cache-Control"] == "no-store"
    assert minted["X-Robots-Tag"] == "noindex, nofollow"

    path = link[link.index("/get-back-in/") :]
    assert Client().post(path, {"password": _NEW_PW}).status_code == 302
    assert Client().login(username="nana", password=_NEW_PW)


def test_redeeming_ends_their_other_sessions(world: World) -> None:
    """T-RECOV-1. "I think someone else is in my account" is one of the two reasons this
    link gets asked for, so the reset has to end whatever that person is holding."""
    stolen = _client_for(world.relative)
    assert stolen.get(reverse("feed")).status_code == 200

    raw = _mint(world.relative, by=world.boss)
    Client().post(reverse("recover", args=[raw]), {"password": _NEW_PW})

    assert stolen.get(reverse("feed")).status_code == 302  # bounced to sign-in


def test_the_row_records_who_issued_it_for_whom_and_when(world: World) -> None:
    """The whole accountability trail, on the row itself (no general audit log exists and
    one is not being invented here). It must SURVIVE redemption, or the record of who
    handed out a password-setting link disappears the moment it is used."""
    raw = _mint(world.relative, by=world.delegate)
    Client().post(reverse("recover", args=[raw]), {"password": _NEW_PW})

    token = RecoveryToken.objects.get(member=world.relative)
    assert token.issued_by == world.delegate
    assert token.member == world.relative
    assert token.created_at is not None
    assert token.used_at is not None


def test_a_refreshed_mint_page_does_not_silently_replace_the_link(world: World) -> None:
    """The single-use intent nonce, same guard as the elder hand-over: re-posting the
    page the admin is still reading the link off must not revoke it under them."""
    client = _client_for(world.boss)
    page = client.get(_issue_url(world.relative))
    first = client.post(_issue_url(world.relative), {"intent": page.context["intent"]})
    raw_link = first.context["minted_link"]

    replayed = client.post(_issue_url(world.relative), {"intent": page.context["intent"]})
    assert replayed.context.get("minted") is None, "a replayed POST minted again"
    path = raw_link[raw_link.index("/get-back-in/") :]
    assert Client().get(path).status_code == 200, "the handed-over link was revoked"


def test_the_member_page_says_whose_link_it_is(world: World) -> None:
    """Somebody handed a link by text should be able to tell it is theirs and not a
    relative's sent to the wrong thread."""
    raw = _mint(world.relative, by=world.boss)
    body = Client().get(reverse("recover", args=[raw])).content.decode()
    assert "Nana" in body
    assert "password" in body.lower()


def test_the_recover_page_carries_the_token_surface_headers(world: World) -> None:
    """TM-5. The token rides the URL here, so the page must be no-store and noindex — and
    Referrer-Policy is `same-origin`, deliberately NOT `no-referrer`: this page POSTs a new
    password back to its own URL, and under no-referrer the browser sends `Origin: null`,
    which Django's CSRF check rejects. That is the failure handover.py documents, and it
    stays latent in tests because the test client sends no Origin at all."""
    raw = _mint(world.relative, by=world.boss)
    response = Client().get(reverse("recover", args=[raw]))
    assert response["Cache-Control"] == "no-store"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "same-origin"
    # The 404 for a dead link carries the same set: a cacheable, indexable refusal still
    # names a token-bearing URL.
    dead = Client().get(reverse("recover", args=["never-minted"]))
    assert dead["Cache-Control"] == "no-store"
    assert dead["Referrer-Policy"] == "same-origin"


def test_the_token_is_redacted_from_request_logs(world: World) -> None:
    """TS-EDGE-LOG. A relative typing a long link out of a text message gets it wrong, the
    404 lands in `django.request` at WARNING, and the operator reading the container log
    would be holding a live password-setting credential for a family member."""
    import logging

    from config.log_redaction import RedactCapabilityPaths

    raw = _mint(world.relative, by=world.boss)
    record = logging.LogRecord(
        "django.request", logging.WARNING, __file__, 1, "Not Found: /get-back-in/%s/", (raw,), None
    )
    RedactCapabilityPaths().filter(record)
    assert raw not in record.getMessage()
    assert "[redacted]" in record.getMessage()
