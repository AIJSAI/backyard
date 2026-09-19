"""The credential surfaces are part of the product, and part of the design system.

django-allauth ships ~30 pages (sign-in, the password-reset family, email management,
the MFA/TOTP/recovery-code/WebAuthn set). Until the v3 design pass they rendered the
library's own unstyled layouts: no CSS at all, a literal "Menu:" bulleted list, and a
live "Sign Up" link on an invite-only instance. Sign-in is the first surface a family
member ever sees and the one they see most.

Three project-level overrides fix that — `allauth/layouts/{base,entrance,manage}.html`
plus `account/login.html` — and these tests pin what the overrides are FOR, so an
allauth upgrade that reshuffles its templates fails here instead of silently restoring
the unstyled page or the dead-end link.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

# Test-only login credential; kept out of the inline `password=` literal form.
_TEST_PW = "a-Strong-passphrase-9"


def _login_page() -> str:
    return Client().get(reverse("account_login")).content.decode()


def test_the_project_overrides_win_over_the_installed_package() -> None:
    # DIRS is searched before APP_DIRS, which is the whole mechanism: `core` sits after
    # `allauth` in INSTALLED_APPS, so without the project template root the library's
    # own layouts would load first.
    for name in (
        "allauth/layouts/base.html",
        "allauth/layouts/entrance.html",
        "allauth/layouts/manage.html",
        "account/login.html",
    ):
        origin = get_template(name).template.origin.name  # type: ignore[attr-defined]
        assert "site-packages" not in origin, f"{name} resolved to the package: {origin}"
        assert "src/templates" in origin, f"{name} resolved somewhere unexpected: {origin}"


def test_sign_in_inherits_the_design_system() -> None:
    html = _login_page()
    # A token from the app's stylesheet, and the page frame it lives in.
    assert "--paper" in html, "sign-in is not rendering the design system's tokens"
    assert 'id="main"' in html, "sign-in is not inside the app's page frame"
    # allauth's raw default shipped this; it must not come back.
    assert "<strong>Menu:</strong>" not in html


def test_sign_in_offers_no_signup_dead_end() -> None:
    # Signup is invite-only (S-101) and the adapter refuses it, so a "sign up" link is
    # a dead end handed to a new relative on the first screen of the product.
    html = _login_page()
    assert "sign up" not in html.lower()
    assert reverse("account_signup") not in html


def test_sign_in_says_what_to_do_without_an_invite() -> None:
    # Removing the link is only half the fix: someone who cannot get in needs to be
    # told what to do instead.
    assert "invite-only" in _login_page()


def test_the_entrance_shows_one_wordmark_not_two() -> None:
    # The entrance carries its own centred brand lockup, so it drops the site header.
    # Rendering both put "Backyard" on screen twice, which is what the first
    # application of the design did.
    html = _login_page()
    assert 'class="entrance"' in html, "the entrance wrapper is not rendering"
    assert '<header class="site">' not in html, "entrance should suppress the site header"


def test_the_entrance_wrapper_survives_a_leaf_content_block() -> None:
    # The mechanism worth pinning: every allauth leaf page defines `content`, so the
    # wrapper lives in `auth_shell` instead. Written around `content` it is silently
    # discarded — the page still styles correctly, so the loss is easy to miss.
    entrance = get_template("allauth/layouts/entrance.html").template.source  # type: ignore[attr-defined]
    assert "{% block auth_shell %}" in entrance
    base = get_template("allauth/layouts/base.html").template.source  # type: ignore[attr-defined]
    assert "{% block auth_shell %}{% block content %}{% endblock %}{% endblock %}" in base


def test_a_removed_relative_is_told_in_the_products_own_words() -> None:
    """The real path, not a mocked one: remove a member the way an admin does, then sign
    in with the password that still works.

    Removal deactivates the account and leaves the password alone (core/removal.py step 3
    — the revocation registry kills tokens, sessions and invites, never the password), so
    "type your old password" is exactly what a removed relative does, and allauth answers
    it by redirecting here. The stock page said "Account Inactive" and "This account is
    inactive.": the state of a row, with nothing about what happened or who to ask.

    No name is asserted as PRESENT on purpose. This page is reachable by anyone who is not
    signed in, so it names nobody — "the person who invited you" is the whole of it.
    """
    from core import removal
    from core.models import Member, Pod, PodMembership, Yard

    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username="cousinreed", password=_TEST_PW)
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)

    removal.remove_member(member, content=removal.KEEP)

    response = Client().post(
        reverse("account_login"),
        {"login": "cousinreed", "password": _TEST_PW},
        follow=True,
    )
    html = response.content.decode()

    assert response.status_code == 200
    assert "You are no longer part of this Backyard" in html
    assert "talk to the person who invited you" in html
    # The library's words, which is what the walk actually saw on screen.
    assert "This account is inactive." not in html
    assert "Account Inactive" not in html


# ---------------------------------------------------------------- the seams


def test_the_passkey_button_has_the_form_it_submits() -> None:
    """The regression that a green suite missed entirely.

    Overriding allauth's layout without declaring `extra_body` made Django silently
    discard the leaf's override — so `<form id="mfa_login">`, its CSRF token and the
    WebAuthn scripts never rendered, while the button that submits to that form still
    did. Clicking "Sign in with a passkey" did nothing at all: no error, no fallback.
    Settings name passkeys the PRIMARY credential (ADR-002), so this quietly demoted
    every member to the password fallback.

    Assert the observable side effect, not that the page merely renders.
    """
    html = _login_page()
    assert 'id="passkey_login"' in html, "the passkey button is gone"
    assert 'id="mfa_login"' in html, "passkey button submits to a form that does not exist"
    assert "data-allauth-onload" in html, "the WebAuthn onload config never rendered"
    assert "webauthn" in html.lower(), "the WebAuthn scripts never rendered"


def test_the_layout_declares_the_blocks_allauth_leaves_define() -> None:
    # Django discards a child block whose name NO ancestor declares. allauth leaf
    # pages define both of these; core/base.html must therefore declare both.
    base = get_template("core/base.html").template.source  # type: ignore[attr-defined]
    for block in ("{% block extra_head %}", "{% block extra_body %}"):
        assert block in base, f"core/base.html must declare {block} or allauth leaves lose it"


def test_framework_messages_reach_the_page() -> None:
    """allauth's own layout rendered `messages`; core/base.html never had a region,
    so overriding the layout removed the only one in the product. Password-changed,
    second-factor-added and second-factor-REMOVED confirmations were being generated
    and thrown away — and two paths (an expired verification link, a refused primary
    email deletion) have no other feedback channel at all, so they failed silently."""
    from django.contrib.messages import constants, get_messages  # noqa: F401
    from django.template import Context, Template

    rendered = Template("{% extends 'core/base.html' %}").render(
        Context({"messages": ["MESSAGE_REACHED_THE_PAGE"]})
    )
    assert "MESSAGE_REACHED_THE_PAGE" in rendered, "messages are generated and then discarded"


def test_the_messages_region_keeps_its_list_semantics() -> None:
    """`role="status"` must sit on a WRAPPER, never on the <ul> itself.

    An explicit role overrides an element's implicit one, so `<ul role="status">`
    stops being a list and every child becomes an orphaned `<li>` — axe reports a
    serious `listitem` violation and a screen reader stops announcing "list, N items".
    Shipped that way in the first cut of the messages fix and caught only by the broad
    axe sweep, on the MFA pages the earlier 8-surface sweep never reached.
    """
    from django.template import Context, Template

    rendered = Template("{% extends 'core/base.html' %}").render(
        Context({"messages": ["a message"]})
    )
    assert '<ul class="messages" role=' not in rendered, "role on the <ul> orphans its items"
    assert '<div role="status">' in rendered, "the messages live region is missing its wrapper"
    assert '<ul class="messages">' in rendered


# ------------------------------------------- the emailed password reset (walk item 26)
#
# The page an ordinary member reaches from "Forgot your password?" was the only surface in
# the product still rendering a stock allauth form at a relative: a field labelled New
# Password, Django's four bulleted validator rules, then New Password (again) with no
# reason given for the second box.
#
# The labels are written WITHOUT their trailing colon-and-quote on purpose. `make secrets`
# scans every commit with gitleaks, whose generic password-assignment rule matches that
# exact shape — and a scanner that had to tell prose from a credential would not be a
# scanner. Quoting a stock label is not worth a red required check on every open PR.
# Its sibling — core/recover.html, the no-login link an admin hands to somebody with no
# email address — has asked the same question in the family's own words for months. And the
# page after it said the same thing twice: allauth's "Password successfully changed." in the
# message strip, then "Your new password is saved" underneath it.
#
# These drive the REAL flow — ask for a reset, take the link out of the mail that arrives,
# open it, set a password — rather than rendering a template with a hand-built context. The
# link is a signed token tied to a session, the done page is a redirect target, and the
# message is raised by a view: none of that is reachable by rendering a template in isolation.

_RESET_EMAIL = "nana@example.com"


def _member_who_can_reset() -> None:
    """A member with an EmailAddress row, which is what allauth resolves a reset against."""
    from allauth.account.models import EmailAddress

    user = get_user_model().objects.create_user(
        username="nana", email=_RESET_EMAIL, password=_TEST_PW
    )
    EmailAddress.objects.create(user=user, email=_RESET_EMAIL, primary=True, verified=True)


def _walk_to_the_reset_form() -> tuple[Client, str, str]:
    """Ask for a reset, pull the link out of the mail, and open it the way a phone does.

    Returns the client (it holds the session allauth stashes the key in), the URL the form
    posts back to, and the HTML of the form page.
    """
    import re as _re

    from django.core import mail

    _member_who_can_reset()
    client = Client()
    mail.outbox.clear()
    client.post(reverse("account_reset_password"), {"email": _RESET_EMAIL})
    assert len(mail.outbox) == 1, "no reset mail was sent; the walk cannot start"

    # str() because django-stubs types a message body as `str | _StrPromise`: the mail
    # templates render through {% blocktrans %}, so the value can be a lazy string.
    found = _re.search(r"https?://\S+/password/reset/key/\S+", str(mail.outbox[0].body))
    assert found, mail.outbox[0].body
    # allauth's first GET stores the key in the session and redirects to a URL with the key
    # replaced by "set-password", so the secret never rides a Referer. Follow it: that
    # landing URL is the one the form posts back to.
    response = client.get(found.group(0), follow=True)
    assert response.status_code == 200
    return client, response.request["PATH_INFO"], response.content.decode()


def test_the_emailed_reset_form_asks_the_way_the_get_back_in_page_asks() -> None:
    _, _, html = _walk_to_the_reset_form()
    text = " ".join(html.split())

    assert "New password" in text and "New Password:" not in text
    assert (
        "Use something you will remember. Three or four unrelated words work well and are "
        "easy to type on a phone." in text
    ), "the field still gives a relative no idea what to type"
    assert "Type it again" in text and "New Password (again)" not in text
    assert (
        "This link works once. A password with a typo in it would lock you out again and "
        "you would have to ask for a new link, so we ask for it twice." in text
    ), "the second box is still asked for without a reason"
    # Django's password_validators_help_text_html(), four bullets of policy read before
    # anybody has typed anything. The rules still RUN — the test below proves it.
    assert "Your password can" not in text, "the stock validator bullets are back"


def test_the_emailed_reset_form_still_submits_and_still_validates() -> None:
    """The copy pass rendered the fields by hand instead of through `form.as_p`, so the
    thing to prove is that it did not quietly stop working: the field names are still the
    ones ResetPasswordKeyForm cleans, a weak password is still refused IN the person's own
    words, and a good one still signs them back in."""
    client, action, _ = _walk_to_the_reset_form()

    weak = client.post(action, {"password1": "123", "password2": "123"})
    assert weak.status_code == 200, "a refused password must re-render, not redirect"
    assert "too short" in weak.content.decode().lower(), (
        "the validators are not running — the fields are no longer reaching the form"
    )

    mismatch = client.post(action, {"password1": _TEST_PW, "password2": _TEST_PW + "x"})
    assert mismatch.status_code == 200
    assert "same password" in mismatch.content.decode().lower()

    good = client.post(action, {"password1": _TEST_PW, "password2": _TEST_PW}, follow=True)
    assert good.status_code == 200
    user = get_user_model().objects.get(username="nana")
    assert user.check_password(_TEST_PW), "the new password was never saved"


def test_the_page_after_the_reset_says_it_once() -> None:
    """allauth raised its own "Password successfully changed." on the POST, and
    core/base.html renders the message strip ABOVE the body — so the library's sentence was
    the first thing a locked-out relative read and this product's own was the echo."""
    client, action, _ = _walk_to_the_reset_form()

    done = client.post(action, {"password1": _TEST_PW, "password2": _TEST_PW}, follow=True)
    html = done.content.decode()

    assert done.request["PATH_INFO"] == reverse("account_reset_password_from_key_done")
    assert "Your new password is saved" in html  # non-vacuity: the page DID render
    assert "Password successfully changed" not in html, "the stock sentence is back"
    assert '<ul class="messages">' not in html, "the message strip is rendering an echo"


def test_the_signed_in_password_change_keeps_its_only_confirmation() -> None:
    """The other half of the suppression, and the reason it is a branch rather than an
    empty file. allauth raises the SAME message from the signed-in password change, where
    the view redirects back to the same form and that message is the only sign anything
    happened. Switching it off there would trade a duplicated sentence on one page for a
    silent success on another."""
    _member_who_can_reset()
    client = Client()
    client.force_login(
        get_user_model().objects.get(username="nana"),
        backend="django.contrib.auth.backends.ModelBackend",
    )
    new = _TEST_PW + "-and-then-some"

    response = client.post(
        reverse("account_change_password"),
        {"oldpassword": _TEST_PW, "password1": new, "password2": new},
        follow=True,
    )
    assert response.status_code == 200
    assert "Password successfully changed" in response.content.decode(), (
        "the signed-in password change lost the only confirmation it has"
    )


def test_the_vendored_login_template_has_not_drifted_upstream() -> None:
    """`src/templates/account/login.html` is allauth's markup minus the signup
    paragraph. The dependency pin allows every 65.x, and allauth actively reshapes
    this template across minors — so an upgrade could add a hidden field or change
    the form action while our frozen copy keeps serving the old markup on the
    sign-in page, silently. Break loudly instead."""
    import hashlib
    import pathlib

    import allauth

    pkg = pathlib.Path(allauth.__file__).parent / "templates" / "account" / "login.html"
    digest = hashlib.sha256(pkg.read_bytes()).hexdigest()
    assert digest == "bc38debd2f3c65608dc72f102170055a9c5fadbe0db7400d35eda03fd796c339", (
        "django-allauth's account/login.html changed upstream. Re-vendor "
        "src/templates/account/login.html from the new version, re-apply the "
        "signup-paragraph removal, and update this pin."
    )


def test_the_project_template_root_shadows_nothing_unintended() -> None:
    """DIRS is searched before app dirs, so ANY file added under src/templates/
    silently outranks the app's or a library's version of that name — including
    core/elder_feed.html, the tightest capability ceiling in the product. Pin the
    whole set rather than four names.

    The allauth overrides are COPY ONLY: every form, field name, action button and
    redirect field in them is the package's markup, and each file says in its own
    comment what it changed and why. Adding one to this set is a deliberate act, which
    is the point of pinning the set rather than a handful of names.

    .txt is included now as well as .html. The e-mail bodies allauth sends are templates
    too — the confirmation mail went out as "Hello from backyard.family! You're receiving
    this email because user james has given your email address to register an account" —
    and a glob that saw only .html could not have noticed one being shadowed.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "templates"
    allowed = {
        "403_csrf.html",
        "404.html",
        # The calm page a family link shows when it has been opened very many times in a
        # few minutes (S2). allauth's handler429 renders `429.html` BY NAME from the
        # project template root, so this is the only place it can live.
        "429.html",
        "500.html",
        # Copy-only overrides of allauth's own pages: Title Case, "Email:", dead-end
        # "contact us" endings, and an account-system voice on a family's app.
        "account/login.html",
        "account/logout.html",
        # The page a removed relative reaches by typing a password that is still correct.
        # allauth's own was "Account Inactive" / "This account is inactive." — a database
        # state read aloud to somebody's grandmother.
        "account/account_inactive.html",
        "account/email.html",
        "account/email_confirm.html",
        "account/verification_sent.html",
        "account/password_reset.html",
        "account/password_reset_done.html",
        "account/password_reset_from_key.html",
        "account/password_reset_from_key_done.html",
        "account/snippets/warn_no_email.html",
        "allauth/layouts/base.html",
        "allauth/layouts/entrance.html",
        "allauth/layouts/manage.html",
        # The e-mails, and the flash message allauth raises on sign-in.
        "account/messages/logged_in.txt",
        # Not copy: a SCOPED suppression. allauth raises one "password changed" message
        # from two flows, and on the emailed-reset page it printed the fact directly above
        # this product's own sentence saying it again. The file declines it for that one
        # flow and hands every other caller the library's sentence untouched — see the long
        # note inside it for why it is not simply empty.
        "account/messages/password_changed.txt",
        "account/email/base_message.txt",
        "account/email/base_notification.txt",
        "account/email/email_confirmation_subject.txt",
        "account/email/email_confirmation_message.txt",
        "account/email/password_reset_key_subject.txt",
        "account/email/password_reset_key_message.txt",
        "account/email/unknown_account_subject.txt",
        "account/email/unknown_account_message.txt",
    }
    found = {
        str(p.relative_to(root)) for pattern in ("*.html", "*.txt") for p in root.rglob(pattern)
    }
    assert found == allowed, f"unexpected project-root template(s): {found ^ allowed}"
