"""The product is not a person, and nothing it says shouts, dashes or trails off.

Two rules from the owner's critique of 2026-09-19, both of which he stated as absolutes.

PERSPECTIVE. "Who is us? That doesn't make sense." Backyard is a page a family runs, not a
company writing to them, so there is no "we", no "us", no "our" — not on a screen and not
in an e-mail. The reader is "you"; a person is named by first name or by role. His own
rewrite is the calibration: "Tell us the name your family will see" became "Enter your
name."

PUNCTUATION. No exclamation marks, no em dashes, no ellipses. A mainstream product writes
a full stop and starts the next sentence.

SCOPE. Visible text only, and e-mail subjects and bodies. Code identifiers, comments,
operator documentation and test names are not covered and must not be — "we" belongs in a
comment explaining a decision, and an em dash belongs in this docstring. The stripping is
`copy_scan.py`, shared with the vocabulary and capitalisation guards so all three see the
same page.

The templates allauth ships are not ours; this product's own templates are.

RUN IT ON ONE FILE. Parametrised by template: `pytest -k "welcome_email.html"`.
"""

from __future__ import annotations

import pathlib

import pytest

from core.tests.copy_scan import template_key, templates, visible_text, voice_offences

_TEMPLATES = templates()
_KEYS = [template_key(path) for path in _TEMPLATES]

# `[!]` is the weekly health e-mail's marker beside a line that wants the family admin's
# attention — a flag in a fixed-width report, not a raised voice. Removed before the check
# rather than allowlisting the whole file, so a real exclamation mark in that e-mail is
# still caught.
_REPORT_FLAG = "[!]"


@pytest.mark.parametrize("path", _TEMPLATES, ids=_KEYS)
def test_no_template_speaks_in_the_first_person_or_shouts(path: pathlib.Path) -> None:
    key = template_key(path)
    hits = voice_offences(visible_text(path.read_text()).replace(_REPORT_FLAG, ""))
    assert not hits, f"{key} is not written in the product's voice:\n  " + "\n  ".join(hits)


def test_the_guard_is_not_vacuous() -> None:
    """Prove each half can fail, and that the stripping underneath it is real."""
    assert voice_offences(visible_text("<p>We have sent one email to that address.</p>"))
    assert voice_offences(visible_text("<p>Tell us the name your family will see</p>"))
    assert voice_offences(visible_text("<p>every email we send has a link</p>"))
    assert voice_offences(visible_text("<p>Let's get you started</p>"))
    assert voice_offences(visible_text("<h1>You are in!</h1>"))
    assert voice_offences(visible_text("<p>One thing — check your spam folder.</p>"))
    assert voice_offences(visible_text("<p>One thing &mdash; check your spam folder.</p>"))
    assert voice_offences(visible_text("<p>Sending…</p>"))
    assert voice_offences(visible_text("<p>Sending...</p>"))
    # ...and the words that merely CONTAIN one of them do not trip it.
    assert not voice_offences(visible_text("<p>This week, four people posted.</p>"))
    assert not voice_offences(visible_text("<p>Because the link was used already.</p>"))
    assert not voice_offences(visible_text("<p>Your household will see this.</p>"))
    # ...and neither does anything a person never reads.
    assert not voice_offences(visible_text("{% comment %}we keep this{% endcomment %}"))
    assert not voice_offences(visible_text("{# our reasoning — see ADR-002 #}"))
    assert not voice_offences(visible_text("<style>.us { margin: 0 }</style>"))
    assert not voice_offences(visible_text("<script>// we set this…</script>"))


def test_the_sweep_actually_sees_the_product() -> None:
    """Guard the guard. A broken glob scans nothing and passes."""
    names = {p.name for p in _TEMPLATES}
    assert len(names) > 30, f"only {len(names)} templates found; the globs are wrong"
    for expected in ("feed.html", "join.html", "base_message.txt"):
        assert expected in names, f"{expected} was not scanned"


@pytest.mark.django_db
def test_the_email_updates_message_is_written_in_the_products_voice() -> None:
    """An e-mail is the surface where "we" hides longest, because it reads like a letter
    and a letter has a sender. This one has no sender; it is a page, mailed."""
    import datetime

    from django.utils import timezone

    from core import digest, digest_links
    from core.models import DigestIssue, Member, Pod, PodMembership, Post, Yard

    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Cousin Reed")
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
    assert "A photo from the weekend" in built.text  # non-vacuity
    for part, name in ((built.subject, "subject"), (built.text, "text body")):
        assert not voice_offences(str(part)), f"the email update's {name}: {part[:200]!r}"
    assert not voice_offences(visible_text(built.html)), "the email update's HTML"


@pytest.mark.django_db
def test_the_address_confirmation_email_is_written_in_the_products_voice() -> None:
    from django.core import mail

    from core import digesting
    from core.models import Member, Pod, PodMembership, Yard

    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Cousin Reed")
    PodMembership.objects.create(member=member, pod=pod)
    mail.outbox.clear()

    digesting.subscribe(member, address="cousin@example.com", cadence="weekly")

    message = mail.outbox[0]
    assert "confirm" in message.body.lower()  # non-vacuity
    assert not voice_offences(str(message.subject)), message.subject
    assert not voice_offences(str(message.body)), message.body
