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
from django.template.loader import get_template
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


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
    whole set rather than four names."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "templates"
    allowed = {
        "403_csrf.html",
        "404.html",
        "500.html",
        "account/login.html",
        "allauth/layouts/base.html",
        "allauth/layouts/entrance.html",
        "allauth/layouts/manage.html",
    }
    found = {str(p.relative_to(root)) for p in root.rglob("*.html")}
    assert found == allowed, f"unexpected project-root template(s): {found ^ allowed}"
