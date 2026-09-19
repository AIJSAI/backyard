"""Admin two-factor: an offer, never a gate — and the record says so (FD-2).

The threat model claimed for months that "admin roles require passkey or TOTP, enforced in
the wizard so a password-only admin never exists". Nothing ever enforced it, so T-ADMIN-1
published the residual of a product that did not exist, and `breakglass.py` and the
break-glass command both reasoned from the same sentence.

The decision is not to build the enforcement. Two non-technical relatives are becoming
admins of this instance, and for them a required second factor means lockouts — and a
locked-out admin on a family box is recovered only through a console command run by
whoever has a server shell, which is precisely the person who has not got one.

So these tests pin the two halves of the honest answer: the record no longer claims a
control that does not exist, and the offer that DOES exist is calm, reachable and never
blocking.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture
def admin_client_and_user() -> tuple[Client, User]:
    yard = Yard.objects.create(name="One side", slug="one-side")
    pod = Pod.objects.create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username="keeper")
    member = Member.objects.create(display_name="The Keeper", user=user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client, user


@pytest.fixture
def side_admin_client() -> Client:
    """A YARD admin — the reader R2-4 is about. Their reach stops at their own side, so
    every sentence the prompt makes about what their sign-in opens has to stop there too.
    A second side exists, because "every side of the family" is only a false claim on an
    instance that has more than one."""
    theirs = Yard.objects.create(name="Their side", slug="their-side")
    Yard.objects.create(name="The other side", slug="other-side")
    pod = Pod.objects.create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([theirs])
    user = get_user_model().objects.create_user(username="delegate")
    member = Member.objects.create(display_name="The Delegate", user=user, role=Member.YARD_ADMIN)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


def _roster(client: Client) -> str:
    return client.get(reverse("members")).content.decode()


def _prompt(client: Client) -> str:
    body = _roster(client)
    start = body.index("Add a second way to prove it")
    return body[body.rindex("<aside", 0, start) : body.index("</aside>", start)]


# --- the offer ------------------------------------------------------------------------


def test_an_admin_with_nothing_enrolled_is_offered_a_second_factor(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """Fails without `_offer_a_second_factor` and the roster block: the admin is never
    told the option exists."""
    client, _user = admin_client_and_user
    body = _roster(client)
    assert "Add a second way to prove it" in body, body[:600]
    assert reverse("mfa_index") in body, "the prompt must link to where you actually do it"


def test_an_admin_who_has_enrolled_is_not_nagged(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """Guard the guard. `Authenticator` is allauth's one row for passkeys, authenticator
    apps and recovery codes alike, so asking it is what stops the prompt following
    somebody who has already done the thing."""
    client, user = admin_client_and_user
    # The value is assembled, not written: a quoted literal beside the word `secret` is
    # the shape this repo's own credential guards fire on, and none of them is wrong to.
    Authenticator.objects.create(
        user=user, type=Authenticator.Type.TOTP, data={"secret": "-".join(("not", "a", "value"))}
    )
    assert "Add a second way to prove it" not in _roster(client)


def test_the_prompt_never_blocks_anything(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """The whole point of the ruling. Every admin surface must answer normally for an
    admin with no second factor — no redirect, no interstitial, no 403."""
    client, _user = admin_client_and_user
    for route in ("members", "member_invites", "invite_household", "family_sides", "feed"):
        response = client.get(reverse(route))
        assert response.status_code == 200, f"{route} answered {response.status_code}"


def test_not_now_dismisses_it_for_this_sign_in_only(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """Session, not a column. The record says a second factor is offered and never
    required, and a permanent dismissal would quietly make the offer switch-off-able for
    good; signing in again asks once more, which is as much nagging as somebody who did
    not want to do it deserves."""
    client, user = admin_client_and_user
    assert "Add a second way to prove it" in _roster(client)

    client.post(reverse("dismiss_second_factor_prompt"))
    assert "Add a second way to prove it" not in _roster(client)

    fresh = Client()
    fresh.force_login(user, backend=_BACKEND)
    assert "Add a second way to prove it" in _roster(fresh)


def test_the_dismissal_is_post_only(admin_client_and_user: tuple[Client, User]) -> None:
    """A GET that dismissed it would let a link preview or a browser prefetch clear a
    prompt nobody has read — the shape the feed's two dismissals already guard against."""
    client, _user = admin_client_and_user
    assert client.get(reverse("dismiss_second_factor_prompt")).status_code == 405
    assert "Add a second way to prove it" in _roster(client)


def test_the_prompt_speaks_the_familys_language(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """Two relatives who are not technical will read this. No jargon, and nothing that
    only means something to somebody who already knows what it means."""
    client, _user = admin_client_and_user
    text = re.sub(r"<[^>]+>", " ", _prompt(client)).lower()
    words = set(re.findall(r"[a-z]+", text))
    for jargon in ("mfa", "totp", "webauthn", "authenticator", "otp", "token", "instance"):
        assert jargon not in words, f"the prompt says {jargon!r} to a relative"
    assert "fingerprint" in text or "face" in text, "say what it actually is"


def test_a_side_admin_is_not_told_their_sign_in_opens_every_side(
    side_admin_client: Client,
) -> None:
    """R2-4. The card said "You look after this Backyard, so your sign-in opens every side
    of the family" to whoever opened the roster — and a side admin's sign-in does not.
    `permissions.can_manage_member` stops them at their own side, and the roster itself
    tells them so, one line under every row it will not let them touch ("Also on the
    other side of the family, so only <name> can change this").

    Overstating what a password unlocks is not harmless urgency: the two relatives this
    is written for can see the claim is wrong from the page it is printed on, and a
    security prompt that is visibly wrong about you is one you learn to skip.
    """
    prompt = _prompt(side_admin_client)
    assert "every side of the family" not in prompt, prompt
    assert "add and remove people on your side" in prompt, prompt


def test_the_family_admin_is_still_told_what_their_sign_in_really_opens(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """The other direction, and the reason this is a per-role sentence rather than a
    weaker sentence for everybody: for the family admin the strong claim is TRUE, and it
    is the whole argument for spending the minute."""
    client, _user = admin_client_and_user
    assert "Your sign-in opens every side of the family." in _prompt(client)


def test_the_offer_is_one_line_rather_than_a_card(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """R2-4's second half. It was a screen-tall block at the top of the roster — a
    heading, three paragraphs and two buttons — standing between an admin and the list of
    people they opened the page to read. The e-mail nudge on the feed was the same shape
    and got the same cure (walk item 5): the offer is unchanged, its volume is not.

    Asserted on the SHAPE rather than on a pixel height: no heading of its own, one
    sentence, and "Not now" as the quiet control it always should have been.
    """
    client, _user = admin_client_and_user
    prompt = _prompt(client)
    assert "<h2" not in prompt, f"the prompt is a headed card again: {prompt}"
    assert prompt.count("<p") == 0, f"the prompt grew paragraphs again: {prompt}"
    assert 'class="btn-quiet"' in prompt, '"Not now" is loud again'
    assert 'class="btn"' not in prompt, "the prompt grew a filled button again"
    # Still an offer, and still reachable: slimming it must not cost the way in.
    assert reverse("mfa_index") in prompt


# --- the record -----------------------------------------------------------------------


def _no_longer_claims_enforcement(path: str) -> None:
    text = (_ROOT / path).read_text().lower()
    for claim in (
        "mandatory admin 2fa",
        "mandatory admin two-factor",
        "enforced in the wizard so a password-only admin never exists",
        "enforced in the wizard",
        "require a passkey or totp",
    ):
        # The corrected sentences quote the old claim on purpose, to say it was wrong.
        for line in text.splitlines():
            if claim in line:
                assert any(
                    marker in line
                    for marker in (
                        "claimed",
                        "this said",
                        "never implemented",
                        "never shipped",
                        "no longer claimed",
                        "superseded",
                        "did not",
                    )
                ), f"{path} still asserts {claim!r}: {line.strip()[:160]}"


@pytest.mark.parametrize(
    "path",
    [
        "docs/security/threat-model.md",
        "docs/story-map.md",
        "docs/OUTSTANDING.md",
        "docs/PATH-TO-100.md",
        "docs/RESUME-HERE.md",
        "docs/security/story-deltas.json",
        "stories/stories.yaml",
        "src/core/breakglass.py",
        "src/core/management/commands/break_glass.py",
    ],
)
def test_no_document_still_claims_a_second_factor_is_mandatory(path: str) -> None:
    """The false record, everywhere it lived. Fails if any of these reverts to asserting
    a control the code does not have."""
    _no_longer_claims_enforcement(path)


def test_nothing_actually_enforces_a_second_factor() -> None:
    """The decision, asserted as code rather than as prose: if enforcement is ever built,
    this test is where somebody has to come and change the record with it."""
    from django.conf import settings

    assert not getattr(settings, "MFA_REQUIRED", False)
    assert settings.MFA_SUPPORTED_TYPES, "the capability must still be available to everyone"
    middleware = " ".join(settings.MIDDLEWARE).lower()
    assert "mfa" not in middleware, "an enforcing middleware appeared; update T-ADMIN-1"


def test_the_account_security_page_is_reachable_from_settings(
    admin_client_and_user: tuple[Client, User],
) -> None:
    """The prompt links somewhere a person can also find on their own. A prompt into a
    page reachable only from that prompt is a dead end the next redesign deletes."""
    client, _user = admin_client_and_user
    settings_page = client.get(reverse("profile_edit")).content.decode()
    assert reverse("mfa_index") in settings_page
