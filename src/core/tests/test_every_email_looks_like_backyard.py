"""Every e-mail a person receives looks like Backyard, and says one thing twice.

The owner opened a real password reset from his own site on 2026-09-19 and asked whether
the e-mails should not be branded too. They should: only the weekly Email Updates message
had the product's look — the house mark, the white card, the green — and it was the ONE
mail most relatives never see. The address confirmation (the first thing this software
ever sends anybody), the password reset, the "no such account" reply, the Email Updates
confirmation and the reply notification all arrived as bare plain text.

WHAT THESE TESTS HOLD, and why each one is here rather than left to a careful reader:

* Every message is multipart with an HTML alternative drawn in the shared shell
  (core/email/_layout.html). A mail client renders the HTML part, so the HTML part is the
  message for almost everybody.
* The standing anti-phishing line is in the HTML part of ALL of them. Three of these are
  composed by django-allauth, which never calls core.emailing.send_family_email — the
  seam that appends the line and refuses an HTML part without it — so for those three
  nothing but this test stands between the layout and a silent loss of the property.
* The TEXT parts are byte-identical to what they were before the HTML existed. Those
  sentences were reviewed one at a time across three pull requests and several of them are
  security copy; an HTML pass is not the place for any of them to move.
* A member-controlled display name arrives as text, not as markup, in the two messages
  that carry one.
* The action link appears in the button and in the fallback line under it, and nowhere
  else: a reset link is a live credential, and a mail that prints it in a third place
  (a tracking pixel, a logo's src) hands it to whatever loads that URL.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from core import commenting, digesting, emailing, health_email, notifications
from core.models import DigestSubscription, Member, Pod, PodMembership, Post, Yard
from core.tests.comment_stripping import without_comments
from core.tests.copy_scan import TEMPLATE_ROOTS

pytestmark = pytest.mark.django_db
User = get_user_model()

_PW = "-".join(("a", "throwaway", "phrase", "for", "tests"))
# Link-shaped, and built by join because gitleaks reads every ref in this repository and a
# credential-shaped literal on any branch fails the secrets gate for every open PR.
_KEY = "-".join(("abc", "def", "ghi"))
_CONFIRM_LINK = f"http://localhost:8000/accounts/confirm-email/{_KEY}/"
_RESET_LINK = f"http://localhost:8000/accounts/password/reset/key/{_KEY}/"
_UPDATES_LINK = f"http://localhost:8000/digest/confirm/{_KEY}/"

# The two marks the shared shell draws: the house, and the wordmark beside it.
_HOUSE = 'fill="#1e5c46"'
_WORDMARK = "&nbsp;Backyard</span>"
_FALLBACK = "If the button does not work, copy this link:"
# The painted cell the bulletproof button sits in. Keyed on `bgcolor` rather than on the
# link's own style, because the wordmark beside the house is an inline-block too.
_BUTTON_CELL = 'bgcolor="#1e5c46"'
_BUTTON_LINK = re.compile(r'<a href="([^"]+)" style="display:inline-block[^"]*">([^<]+)</a>')


# --- the shape every one of them has ---------------------------------------------------


def _html_of(message: mail.EmailMessage) -> str:
    """The HTML part of a message, with the marks of the shared shell asserted on it."""
    assert isinstance(message, EmailMultiAlternatives), f"{message.subject!r} is text only"
    assert len(message.alternatives) == 1, message.alternatives
    body, mime = message.alternatives[0][0], message.alternatives[0][1]
    assert mime == "text/html"
    html = str(body)
    assert _HOUSE in html, "no house mark: this message is not drawn in the shared shell"
    assert _WORDMARK in html, "no wordmark"
    assert emailing.STANDING_FOOTER in html, "the standing anti-phishing line is missing"
    return html


def _button(html: str) -> tuple[str, str]:
    """(link, label) of the one action button, which is the one <a> the shell styles."""
    found = _BUTTON_LINK.findall(html)
    assert len(found) == 1, f"expected exactly one action button, found {found}"
    link, label = found[0]
    return str(link), str(label)


def _mail_templates() -> list[pathlib.Path]:
    """Every HTML mail template, in both roots: the app's own `core/email/` and the
    django-allauth overrides under `account/email/`."""
    return sorted(path for root in TEMPLATE_ROOTS for path in root.rglob("email/*.html"))


def _a_household() -> Pod:
    """The one household these tests put everybody in. `get_or_create`, so a test that
    needs two members builds one family rather than colliding on the side's slug."""
    yard, _ = Yard.objects.get_or_create(slug="moms-side", defaults={"name": "Mom's side"})
    pod, _ = Pod.objects.get_or_create(name="The Whitfields", defaults={"kind": Pod.HOUSEHOLD})
    pod.yards.set([yard])
    return pod


def _a_member(display_name: str, *, username: str | None = None) -> Member:
    user = User.objects.create_user(username=username, password=_PW) if username else None
    member = Member.objects.create(display_name=display_name, user=user)
    PodMembership.objects.create(member=member, pod=_a_household())
    return member


# --- the three django-allauth composes -------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_address_confirmation_a_new_relative_gets_is_branded() -> None:
    """The first thing this software ever sends most people, and the one that decides
    whether the next one goes to spam. Sent by joining with an address, which is the only
    way a relative triggers it; `transaction=True` because join defers the send to commit.

    It also proves the SIGNUP variant resolves to this product's HTML: allauth renders the
    `email_confirmation_signup` prefix at join and ships no .html for it at all, so
    without src/templates/account/email/email_confirmation_signup_message.html this is the
    one mail that would still have gone out as bare text.
    """
    from core.invites import mint_invite

    pod = _a_household()
    _invite, raw = mint_invite(pod, None)
    mail.outbox.clear()

    response = Client().post(
        reverse("join", args=[raw]),
        {
            "display_name": "Cousin Reed",
            "username": "cousinreed",
            "password": "aX9!mnpq2ffz",
            "email": "cousin@example.com",
        },
    )
    assert response.status_code == 302, response.status_code

    assert len(mail.outbox) == 1, [m.subject for m in mail.outbox]
    message = mail.outbox[0]
    assert message.subject == "Confirm Your Email Address"
    html = _html_of(message)
    link, label = _button(html)
    assert label == "Confirm Email Address"
    assert "/accounts/confirm-email/" in link
    assert _FALLBACK in html
    assert "Somebody added this address to a Backyard account." in html


def test_the_password_reset_is_branded_and_prints_its_link_twice_and_no_more() -> None:
    """The message the owner was reading when he asked the question.

    The link is a live credential: it signs the holder in far enough to set a password. It
    belongs in the button (where a person presses it) and in the fallback line (where a
    person whose client refuses to draw buttons can copy it), and in no third place.
    """
    member = _a_member("Rose Whitfield", username="rose")
    assert member.user is not None
    EmailAddress.objects.create(
        user=member.user, email="rose@example.com", primary=True, verified=True
    )
    mail.outbox.clear()

    Client().post(reverse("account_reset_password"), {"email": "rose@example.com"})

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "Reset Your Password"
    html = _html_of(message)
    link, label = _button(html)
    assert label == "Set A New Password"
    assert "/accounts/password/reset/key/" in link
    assert f"{_FALLBACK}<br><span" in html, "the link is not in plain sight under the button"
    assert html.count(link) == 2, "the reset link is somewhere a third party could load it"
    assert str(message.body).count(link) == 1, "the text part changed how often it prints it"
    assert "You sign in as rose." in html


def test_the_no_such_account_reply_is_branded_and_offers_nothing_to_press() -> None:
    """Sent to an address nothing here knows (ACCOUNT_PREVENT_ENUMERATION, so the page
    cannot say so). There is nothing to reset and signup is closed, so a button would
    point at a refusal: allauth's context for this mail carries `signup_url` and
    core.adapters deliberately does not map it onto the action."""
    mail.outbox.clear()

    Client().post(reverse("account_reset_password"), {"email": "nobody@example.com"})

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "Reset Your Password", "the subjects must stay identical"
    html = _html_of(message)
    assert "No account here has confirmed this address" in html
    assert _BUTTON_CELL not in html, "this message has nothing to press"
    assert _FALLBACK not in html
    assert "/accounts/signup/" not in html


# --- the three this product composes ---------------------------------------------------


def test_the_email_updates_confirmation_is_branded_and_still_content_free() -> None:
    """T-EMAIL-6: this message is composed from constants and the minted link only, so no
    name, household or post fragment can reach an address nobody has acknowledged. The
    HTML part is handed the same one value and nothing else."""
    member = _a_member("Cousin Reed")
    mail.outbox.clear()

    digesting.subscribe(member, address="cousin@example.com", cadence="weekly")

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "Confirm This Address For Email Updates"
    html = _html_of(message)
    link, label = _button(html)
    assert label == "Confirm Email Address"
    assert "/digest/confirm/" in link
    assert _FALLBACK in html
    for leak in ("Cousin Reed", "The Whitfields", "Mom's side"):
        assert leak not in html, f"the confirmation e-mail carries {leak!r}"


def test_the_reply_notification_is_branded_and_names_both_switches() -> None:
    """Its way out is the only lever an address-only member has — there is no settings
    page behind a sign-in they do not have — so the link that turns it off is in the HTML
    part as it is in the text part."""
    author = _a_member("Priya Whitfield")
    replier = _a_member("Sam Whitfield")
    post = Post.objects.create(author=author, pod=author.pod_memberships.get().pod, body="Camp")
    notifications.set_reply_notification(author, enabled=True)
    DigestSubscription.objects.create(
        member=author, address="priya@example.com", confirmed_at=timezone.now()
    )
    mail.outbox.clear()

    notifications.notify_reply(commenting.create_comment(author=replier, post=post, body="Lovely"))

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "Sam Whitfield Replied To Your Post"
    html = _html_of(message)
    link, label = _button(html)
    assert label == "Read The Reply"
    assert link.endswith(f"/posts/{post.pk}/")
    assert "You are receiving this because Reply Notifications is on." in html
    assert "/digest/unsubscribe/" in html, "the way out is missing from the part most clients show"
    assert "Lovely" not in html, "the nudge must carry no reply text"


def test_the_weekly_health_report_keeps_its_columns_in_a_monospace_block() -> None:
    """S-806, and the one message that goes to the family admin rather than to a family.

    The HTML part is the SAME report, dropped into a monospace block: the lines are a
    fixed-width table with a `[!]` flag in the first column, and a second HTML rendering
    of those fields is how the flag comes to sit in the wrong column in the part most
    clients show.
    """
    admin = Member.objects.create(display_name="The Admin", role=Member.INSTANCE_ADMIN)
    DigestSubscription.objects.create(
        member=admin,
        address="admin@example.com",
        enabled=True,
        confirmed_at=timezone.now(),
        unsubscribe_token_digest="x" * 64,
    )
    mail.outbox.clear()

    result = health_email.send_health_emails()

    assert result.sent == 1
    message = mail.outbox[0]
    html = _html_of(message)
    assert "<pre" in html and "white-space:pre-wrap" in html
    assert "Last backup:" in html, "the report itself is missing from the HTML part"
    # The text part is the report plus the standing line core.emailing appends to every
    # body; the HTML part carries that line in the footer instead, so the comparison is
    # against everything above the "--" separator. Escaped, because the block is
    # autoescaped like the rest of the template.
    report = str(message.body).split("\n\n--\n")[0].strip()
    assert escape(report) in html, "the HTML part is not the same report"
    assert _BUTTON_CELL not in html, "an ops report has nothing to press"


# --- what a member typed is text, never markup -----------------------------------------

_MARKUP_NAME = 'Sam <b>x</b> "Q"'


def test_a_display_name_that_is_markup_arrives_as_text_in_the_reply_notification() -> None:
    """The replier's name is member-controlled and reaches an HTML part, which is the
    whole reason that part is a template rather than an f-string."""
    author = _a_member("Priya Whitfield")
    replier = _a_member(_MARKUP_NAME)
    post = Post.objects.create(author=author, pod=author.pod_memberships.get().pod, body="Camp")
    notifications.set_reply_notification(author, enabled=True)
    DigestSubscription.objects.create(
        member=author, address="priya@example.com", confirmed_at=timezone.now()
    )
    mail.outbox.clear()

    notifications.notify_reply(commenting.create_comment(author=replier, post=post, body="Hi"))

    html = _html_of(mail.outbox[0])
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "&quot;Q&quot;" in html or "&#x27;" not in html  # the quote is escaped or inert


def test_a_display_name_that_is_markup_arrives_as_text_in_the_email_updates_message() -> None:
    """The same property on the one mail that carries whole posts, held here as well as in
    test_digest.py: both parts are rendered from the same builder and only one of them is
    autoescaped, so the escaping is a property of the HTML template alone."""
    import datetime

    from core import digest, digest_links
    from core.models import DigestIssue

    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Whitfields")
    pod.yards.set([yard])
    member = Member.objects.create(display_name=_MARKUP_NAME)
    PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=member, pod=pod, body="A photo from the weekend")
    post.audience_yards.set([yard])
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=timezone.now() - datetime.timedelta(days=7),
        window_end=timezone.now() + datetime.timedelta(minutes=1),
    )

    built = digest.build_digest(
        issue,
        digest_token=digest_links.mint(issue),
        unsubscribe_token="unsub-raw-value",
    )

    assert "A photo from the weekend" in built.html  # non-vacuity
    assert "<b>x</b>" not in built.html
    assert "&lt;b&gt;x&lt;/b&gt;" in built.html


def test_no_mail_template_turns_the_escaping_off() -> None:
    """The two ways a member's writing could reach a mailbox as live markup. The plain-text
    parts turn autoescaping off deliberately (an escaped apostrophe in a text mail is a
    defect); an .html part never may, and none of them needs `|safe` either."""
    offenders: list[str] = []
    for path in _mail_templates():
        # Comments out first: this file's own reasoning quotes both of these, and a guard
        # that reads a comment explaining a rule as a breach of it goes off within a week.
        source = without_comments(path.read_text())
        for hole in ("|safe", "autoescape off"):
            if hole in source:
                offenders.append(f"{path.name}: {hole}")
    assert not offenders, "an HTML mail template turns the escaping off:\n  " + "\n  ".join(
        offenders
    )


def test_the_scan_above_actually_reads_the_mail_templates() -> None:
    """Guard the guard: a glob that matches nothing reports a clean product."""
    found = {path.name for path in _mail_templates()}
    for expected in (
        "_layout.html",
        "digest.html",
        "digest_confirm.html",
        "reply_notification.html",
        "health.html",
        "email_confirmation_message.html",
        "password_reset_key_message.html",
        "unknown_account_message.html",
    ):
        assert expected in found, f"{expected} was not scanned"


# --- the sentences that were reviewed, byte for byte ------------------------------------
#
# Each of these was read and rewritten line by line in #209 and #211, and two of them carry
# security copy: what a confirmation link proves, and what an unknown-account reply may say
# without leaking whether an address has an account here. The HTML pass moved the SHAPE of
# these messages and none of their words, and this is what says so.

_CONFIRMATION_TEXT = (
    "Somebody added this address to a Backyard account.\n"
    "\n"
    "Confirm this address to use it for password reset. If it is your primary address and "
    "you turned on email updates at this address, they start once it is confirmed:\n"
    "\n"
    f"{_CONFIRM_LINK}\n"
    "\n"
    "You will be asked to sign in first if you are not already. If you did not ask for "
    "this, ignore this email.\n"
    "\n"
    "--\n"
    f"{emailing.STANDING_FOOTER}\n"
    "\n"
)

_RESET_TEXT = (
    "Somebody asked to reset the password for this Backyard account.\n"
    "\n"
    "Set a new password:\n"
    "\n"
    f"{_RESET_LINK}\n"
    "\n"
    "You sign in as cousinreed.\n"
    "\n"
    "If you did not ask for this, ignore this email. Your password stays as it is.\n"
    "\n"
    "--\n"
    f"{emailing.STANDING_FOOTER}\n"
    "\n"
)

_UNKNOWN_TEXT = (
    "Somebody asked to reset a Backyard password using this address.\n"
    "\n"
    "No account here has confirmed this address, so there is nothing to reset. If this was "
    "you, try another address, or ask the person who invited you for a Sign-In Link.\n"
    "\n"
    "If you did not ask for this, ignore this email.\n"
    "\n"
    "--\n"
    f"{emailing.STANDING_FOOTER}\n"
    "\n"
)

_UPDATES_TEXT = (
    "Somebody asked for email updates from Backyard to be sent to this address.\n"
    "\n"
    "Confirm this address:\n"
    "\n"
    f"{_UPDATES_LINK}\n"
    "\n"
    "You will be asked to sign in first if you are not already. Nothing is sent until you "
    "confirm. If you did not ask for this, ignore this email; nothing else will be sent "
    "here."
)


@pytest.mark.parametrize(
    ("template", "context", "expected"),
    [
        (
            "account/email/email_confirmation_message.txt",
            {"activate_url": _CONFIRM_LINK},
            _CONFIRMATION_TEXT,
        ),
        (
            "account/email/password_reset_key_message.txt",
            {"password_reset_url": _RESET_LINK, "username": "cousinreed"},
            _RESET_TEXT,
        ),
        ("account/email/unknown_account_message.txt", {"signup_url": "/x/"}, _UNKNOWN_TEXT),
    ],
    ids=["confirmation", "password reset", "no such account"],
)
def test_the_text_part_is_still_the_one_that_was_reviewed(
    template: str, context: dict[str, str], expected: str
) -> None:
    assert render_to_string(template, context) == expected


def test_the_join_time_confirmation_says_the_same_as_the_ordinary_one() -> None:
    """allauth renders a different prefix at signup, and its .txt for that prefix includes
    ours. Pinned so the two can never drift into two different first impressions."""
    rendered = render_to_string(
        "account/email/email_confirmation_signup_message.txt", {"activate_url": _CONFIRM_LINK}
    )
    assert rendered.strip() == _CONFIRMATION_TEXT.strip()


def test_the_email_updates_confirmation_text_is_still_the_one_that_was_reviewed() -> None:
    """Composed in Python (core/digesting.py), so no template render can reach it."""
    assert digesting._CONFIRM_BODY.format(link=_UPDATES_LINK) == _UPDATES_TEXT
    assert digesting._CONFIRM_SUBJECT == "Confirm This Address For Email Updates"


def test_the_standing_line_in_the_shared_shell_is_the_constant_itself() -> None:
    """The three allauth messages never pass through core.emailing.send_family_email, so
    the seam that appends this line — and refuses an HTML part without it — does not run
    for them. The layout writes it out instead, and account/email/base_message.txt writes
    the same sentence into their text parts. One sentence, three spellings of it, and this
    is the only thing holding them together."""
    layout = pathlib.Path(str(TEMPLATE_ROOTS[0] / "core" / "email" / "_layout.html")).read_text()
    assert emailing.STANDING_FOOTER in layout
    assert emailing.STANDING_FOOTER in (
        pathlib.Path(str(TEMPLATE_ROOTS[1] / "account" / "email" / "base_message.txt")).read_text()
    )
