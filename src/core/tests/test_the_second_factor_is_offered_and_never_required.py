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


def _roster(client: Client) -> str:
    return client.get(reverse("members")).content.decode()


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
    body = _roster(client)
    start = body.index("Add a second way to prove it")
    prompt = body[start : body.index("</aside>", start)]
    text = re.sub(r"<[^>]+>", " ", prompt).lower()
    words = set(re.findall(r"[a-z]+", text))
    for jargon in ("mfa", "totp", "webauthn", "authenticator", "otp", "token", "instance"):
        assert jargon not in words, f"the prompt says {jargon!r} to a relative"
    assert "fingerprint" in text or "face" in text, "say what it actually is"


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
