"""Control characters die at the WEB boundary too, not only the email one (S3).

The inbound-email path has stripped control characters out of a reply body since S-502
(`inbound._strip_control`), and the digest subject line has been stripped since #37. The
web path never was: a post composed in the browser, a reply typed under it, and a display
name saved from the profile editor all reached the database verbatim.

That matters because of where those strings are rendered NEXT. `core/email/digest.txt`
renders with autoescape off — it is a plain-text email — so a right-to-left override in a
display name reaches every recipient's mailbox as an active formatting character and
reverses the line it sits in. A NUL or an escape sequence in a post body reaches any
terminal an operator tails the logs in. Django's HTML autoescaping answers none of this:
these characters are not `<`, `&` or `"`.

Each test below names the mechanism it would fail without, so reverting that one line
fails exactly one assertion.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core import commenting, emailing, inbound, posting
from core.models import Member, Pod, PodMembership, Post, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()

# U+202E RIGHT-TO-LEFT OVERRIDE: a FORMAT character (category Cf), not a control
# character (category Cc). A category-Cc-only filter never saw it, which is why the
# helpers below test printability instead.
_RTL_OVERRIDE = "‮"
_CRAFTED_NAME = f"Nana{_RTL_OVERRIDE}\r\nBcc: everyone@example.com\x00"


@pytest.fixture
def author() -> Member:
    yard = Yard.objects.create(name="One side", slug="one-side")
    pod = Pod.objects.create(name="A household", kind=Pod.HOUSEHOLD)
    pod.yards.set([yard])
    user = User.objects.create_user(username="writer")
    member = Member.objects.create(display_name="Ann", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _pod_of(member: Member) -> Pod:
    pod = Pod.objects.filter(memberships__member=member).first()
    assert pod is not None
    return pod


# --- the shared helpers (emailing.strip_control*) ------------------------------------


def test_a_display_name_keeps_no_control_or_format_character() -> None:
    """emailing.strip_control is the label rule: one line, nothing invisible."""
    assert emailing.strip_control(_CRAFTED_NAME) == "NanaBcc: everyone@example.com"


def test_a_body_keeps_its_line_breaks_and_tabs_and_nothing_else() -> None:
    """emailing.strip_control_keep_breaks is the body rule."""
    assert (
        emailing.strip_control_keep_breaks(f"one\ntwo\tthree{_RTL_OVERRIDE}\x00\r")
        == "one\ntwo\tthree"
    )


def test_both_helpers_keep_the_joiner_a_family_emoji_is_spelled_with() -> None:
    """The zero-width joiner is a FORMAT character too, and it is how an emoji family
    is spelled. Stripping every non-printable without this exception turns one emoji
    into three in a product whose entire content is family messages."""
    family = "\U0001f468‍\U0001f469‍\U0001f467"
    assert emailing.strip_control(f"Us {family}") == f"Us {family}"
    assert emailing.strip_control_keep_breaks(f"Us {family}") == f"Us {family}"


def test_the_email_path_and_the_web_path_share_one_implementation() -> None:
    """`inbound._strip_control` is the rule the reply-by-email path has always applied.
    It must BE the web rule, not merely resemble it: two implementations of "which
    characters are safe" is how one of them comes to be wrong."""
    crafted = f"hello\nthere\t{_RTL_OVERRIDE}\x1b\x00"
    assert inbound._strip_control(crafted) == emailing.strip_control_keep_breaks(crafted)


# --- the web write paths -------------------------------------------------------------


def test_a_composed_post_body_is_stripped(author: Member) -> None:
    """Fails without the strip in `posting.create_post`."""
    post = posting.create_post(
        author=author,
        pod=_pod_of(author),
        audience_yards=[],
        body=f"Camp was good\n{_RTL_OVERRIDE}\x00",
    )
    post.refresh_from_db()
    assert post.body == "Camp was good\n"


def test_an_edited_post_body_is_stripped(author: Member) -> None:
    """Fails without the strip in `posting.edit_post` — the edit path is a second
    writer to the same column and was missed by the first cut of this change."""
    post = posting.create_post(author=author, pod=_pod_of(author), audience_yards=[], body="x")
    posting.edit_post(actor=author, post=post, body=f"fixed{_RTL_OVERRIDE}\x00")
    post.refresh_from_db()
    assert post.body == "fixed"


def test_a_reply_body_is_stripped(author: Member) -> None:
    """Fails without the strip in `commenting.create_comment`.

    No NUL in this one on purpose. Postgres refuses a NUL in a text column outright, so
    a crafted string containing one fails loudly with or without this change — which
    would make the NUL, not the bidi override, the thing being proved. U+202E stores
    perfectly happily and is the character that reaches the plain-text digest.
    """
    post = posting.create_post(author=author, pod=_pod_of(author), audience_yards=[], body="x")
    comment = commenting.create_comment(author=author, post=post, body=f"lovely\n{_RTL_OVERRIDE}")
    comment.refresh_from_db()
    assert comment.body == "lovely\n"


def test_a_saved_display_name_is_stripped(author: Member) -> None:
    """Fails without the pre_save receiver in `core.signals`.

    The receiver, not the profile view: a display name is written from FIVE places
    (the first-run wizard, invite redemption, the supervised-child form, the new-elder
    flow and the profile editor), and the one that matters for the digest is whichever
    one a future change forgets.
    """
    author.display_name = _CRAFTED_NAME
    author.kinship_name = f"Nana{_RTL_OVERRIDE}\x00"
    author.save(update_fields=["display_name", "kinship_name"])
    author.refresh_from_db()
    assert author.display_name == "NanaBcc: everyone@example.com"
    assert author.kinship_name == "Nana"


def test_a_name_written_by_any_other_creator_is_stripped_too() -> None:
    """The receiver covers `Member.objects.create`, which is how invite redemption,
    the wizard and the new-elder flow all write a name. No NUL here either: the bidi
    override alone must not survive."""
    member = Member.objects.create(display_name=f"Papa{_RTL_OVERRIDE}")
    member.refresh_from_db()
    assert member.display_name == "Papa"


def test_a_post_body_survives_ordinary_writing(author: Member) -> None:
    """Guard the guard: the strip must not eat the things a person really types."""
    body = "Two lines.\n\nAn ' apostrophe, an é, a — dash, and 🌻."
    post = posting.create_post(author=author, pod=_pod_of(author), audience_yards=[], body=body)
    post.refresh_from_db()
    assert post.body == body
    assert Post.objects.filter(pk=post.pk, body=body).exists()
