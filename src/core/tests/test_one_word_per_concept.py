"""One word per concept, held by a guard rather than by care.

THE TRUE STORY OF THIS FILE, because the first version of it told a shorter one.

A builder ruled a vocabulary on 2026-09-19 and wrote it into this guard: household, side
of the family, "the Family email", no-login link, this Backyard. It fixed a real defect —
the product had three words for a household and two for a side — and it was still a
builder choosing words for a family he is not in.

The OWNER read every string the product shows a person, later the same day, and overruled
it. He called the writing "quick junk filler", "AI fluff" and "really far from polished",
and the ruling that matters here is that "the Family email" is not the answer either:
"Never the word digest" AND "not the Family email either — pick something better." The
feature is **Email Updates**. He also asked for much less "family" everywhere ("Yes it's
family but let's not make it all family branded"), and struck out the filler, the idioms
and the reassurance he found on the first ten screens, by name.

So the vocabulary below is HIS, not the builder's, and the words this guard once
recommended as replacements are among the words it now bans. That is the whole reason the
docstring says so: a guard that quietly swapped one ruling for another would leave the next
reader thinking the first one had been wrong on its own terms, and it was not — it was
overruled.

The vocabulary, as ruled on 2026-09-19:

    household           never pod, never house
    side of the family  never yard
    Email Updates       never digest, never "the Family email"
    no-login link       never elder path, never token
    this Backyard       never instance

WHAT IS COVERED. Everything a person reads: a template's visible text, every model choice
LABEL (which a template scan cannot see, because the template only says `{{ ... }}`), the
role descriptions on the roster, and the subject and body of every e-mail this product can
send. The stripping all three copy guards share is `copy_scan.py`; the voice and the
capitalisation live in their own files beside this one.

RUN IT ON ONE FILE. The template sweep is parametrised by template, so a group working on
its own screens can run `pytest -k "welcome_email.html"` and see only its own.
"""

from __future__ import annotations

import pathlib

import pytest

from core.tests.copy_scan import (
    ALLOWED,
    BANNED,
    TEMPLATE_ROOTS,
    prose,
    script_strings,
    template_key,
    templates,
    visible_text,
    vocabulary_offences,
)

_TEMPLATES = templates()
_KEYS = [template_key(path) for path in _TEMPLATES]


@pytest.mark.parametrize("path", _TEMPLATES, ids=_KEYS)
def test_no_template_shows_a_banned_word_to_a_person(path: pathlib.Path) -> None:
    key = template_key(path)
    hits = vocabulary_offences(visible_text(path.read_text()), ALLOWED.get(key, set()))
    assert not hits, (
        f"{key} shows a relative a word the owner struck out. One word per concept:\n  "
        + "\n  ".join(hits)
    )


@pytest.mark.parametrize("path", _TEMPLATES, ids=_KEYS)
def test_no_word_a_script_writes_onto_the_page_is_a_banned_one(path: pathlib.Path) -> None:
    """The sweep above cannot see these: `<script>` is stripped before it reads a word.

    A script still writes words a person reads — a button's label, an error sentence, the
    name a screen reader announces — and `copy_scan.script_strings` is the narrow reader
    for them. Same vocabulary, same allowlist, so "the digest is sending" typed into a
    `textContent` fails exactly as it would in an `<h1>`.
    """
    key = template_key(path)
    allowed = ALLOWED.get(key, set())
    faults = [
        f"{where} {text!r}: " + "; ".join(hits)
        for where, text in script_strings(path.read_text())
        if (hits := vocabulary_offences(text, allowed))
    ]
    assert not faults, f"{key} has a script writing a struck-out word:\n  " + "\n  ".join(faults)


def test_the_script_reader_is_not_vacuous() -> None:
    """It finds the shapes it claims to, and still ignores everything else in a script."""
    assert script_strings('<script>el.textContent = "Turn On The Digest";</script>')
    assert script_strings("<script>el.innerText = 'Your Pods';</script>")
    assert script_strings('<script>b.setAttribute("aria-label", "Remove This Photo");</script>')
    assert script_strings(
        '<script type="application/json">{"confirmDelete": "Are You Sure?"}</script>'
    )
    assert vocabulary_offences(
        script_strings('<script>el.textContent = "The Digest";</script>')[0][1]
    )
    # A comment, a selector, a class name, a MIME type and a data value are not copy.
    assert not script_strings("<script>// the digest is sent by the worker\n</script>")
    assert not script_strings("<script>/* a pod is a household */ var x = 1;</script>")
    assert not script_strings("<script>document.querySelector('.pods');</script>")
    assert not script_strings("<script>el.className = 'yard';</script>")
    assert not script_strings("<script>canvas.toBlob(r, 'image/jpeg', 0.85);</script>")
    assert not script_strings("<script>if (el.getAttribute('data-when') === 'date') {}</script>")
    assert not script_strings("<script>el.textContent = file.name;</script>")
    assert not script_strings("<script>el.textContent = '';</script>")


def test_the_guard_is_not_vacuous() -> None:
    """Prove it can fail, and prove the stripping it depends on is real.

    Without this, a regex that matched nothing — or a `visible_text` that stripped the
    whole document — would report a clean product forever.
    """
    assert vocabulary_offences(visible_text("<p>Start a pod that is just your group</p>"))
    assert vocabulary_offences(visible_text("<h1>Your yards</h1>"))
    assert vocabulary_offences(visible_text("<p>Turn on the digest</p>"))
    assert vocabulary_offences(visible_text("<p>Do you want the Family email?</p>"))
    assert vocabulary_offences(visible_text("<p>This is the elder path.</p>"))
    assert vocabulary_offences(visible_text("<p>You look after a side of the family.</p>"))
    assert vocabulary_offences(visible_text("<p>Post when you feel like it.</p>"))
    assert vocabulary_offences(visible_text("<p>Members are taken straight to the feed.</p>"))
    assert vocabulary_offences(visible_text("<p>Tell us the name they will see.</p>"))
    assert not vocabulary_offences(visible_text("<h1>Your Backyard</h1>"))
    assert not vocabulary_offences(visible_text("<p>Your household will see this.</p>"))
    assert vocabulary_offences(visible_text('<input placeholder="e.g. Our house">'))
    assert vocabulary_offences(visible_text('<a aria-label="Your pods">Groups</a>'))
    # ...and cannot fail for the wrong reasons.
    assert not vocabulary_offences(visible_text('<a href="/pods/" class="pods">Groups</a>'))
    assert not vocabulary_offences(visible_text("{% url 'pod_list' %}{{ pod.name }}"))
    assert not vocabulary_offences(visible_text("{% comment %}the pod list{% endcomment %}"))
    assert not vocabulary_offences(visible_text("{# a yard is a side of the family #}"))
    assert not vocabulary_offences(visible_text("<!-- the digest token -->"))
    assert not vocabulary_offences(visible_text("<style>ul.pods { margin: 0 }</style>"))


def test_the_template_sweep_actually_sees_the_product() -> None:
    """Guard the guard. A broken glob scans nothing and passes."""
    names = {p.name for p in _TEMPLATES}
    assert len(names) > 30, f"only {len(names)} templates found; the globs are wrong"
    for expected in ("feed.html", "members.html", "digest.txt", "base_message.txt"):
        assert expected in names, f"{expected} was not scanned"


def test_every_allowlist_entry_still_points_at_a_real_file_and_a_real_word() -> None:
    """The allowlist is only ever SUBTRACTED, so a stale entry excuses nothing and says
    nothing — the failure mode `_UNLINKED_BY_DESIGN` already taught this repository once,
    where an entry named a route that did not exist and had been a no-op since it was
    written."""
    known = {template_key(path) for path in _TEMPLATES}
    for key, words in ALLOWED.items():
        assert key in known, f"the allowlist names {key}, which is not a template"
        assert words <= set(BANNED), f"the allowlist for {key} names a word nothing bans"
        path = next(p for p in _TEMPLATES if template_key(p) == key)
        assert vocabulary_offences(visible_text(path.read_text())), (
            f"the allowlist excuses {key}, and that file no longer uses any banned word. "
            "Delete the entry rather than leaving a standing exemption behind."
        )


def test_the_template_roots_are_both_real() -> None:
    """The keys, the allowlist and every `-k` filter are computed from these."""
    for root in TEMPLATE_ROOTS:
        assert root.is_dir(), f"{root} is not a directory; the scan is looking at nothing"


# --- the model choice labels ----------------------------------------------------------
#
# A template scan cannot see these. `{{ member.get_role_display }}` renders a string that
# lives in models.py, so the roster badge, the role select and "What the roles mean" all
# read whatever the model says while the template scan reports a clean product — the
# template says `{{ ... }}` and the stripper removes it, correctly, because the word is not
# IN the template. Found on the 2026-09-19 walk, on the one screen where a relative is
# handed the admin controls.
#
# The VALUES are not covered and must not be: `yard_admin` and `instance_admin` are what
# the database stores and what every permission predicate compares against, and renaming
# them would be a migration of live rows. Only the second element of each pair — the label
# a person reads — is scanned.


def _choice_labels() -> list[tuple[str, str]]:
    """Every (where, label) pair a person can be shown, from every model field that has
    choices. Computed by walking the app's models rather than naming the fields, so a
    field added later is covered without anybody remembering to add it here."""
    from django.apps import apps

    pairs: list[tuple[str, str]] = []
    for model in apps.get_app_config("core").get_models():
        for field in model._meta.get_fields():
            for _value, label in getattr(field, "choices", None) or ():
                pairs.append((f"{model.__name__}.{field.name}", str(label)))
    return pairs


def test_no_model_choice_label_shows_a_banned_word_to_a_person() -> None:
    offenders = [
        f"{where}: {label!r} — {', '.join(hits)}"
        for where, label in _choice_labels()
        if (hits := vocabulary_offences(label))
    ]
    assert not offenders, (
        "a choice LABEL carries a word the owner struck out. These render straight at a "
        "relative through get_FOO_display, so a clean template scan proves nothing about "
        "them. Rename the label, never the stored value:\n  " + "\n  ".join(offenders)
    )


def test_no_role_description_shows_a_banned_word_to_a_person() -> None:
    """The sentences under "What the roles mean" on the roster, which are prose in
    models.py and invisible to every template scan for the same reason as the labels.

    "You look after a side of the family" is the exact sentence the owner rewrote to "You
    are a Side Admin. You can add and remove members on your side.", so "look after" is on
    the banned list and this is the surface it was on."""
    from core.models import Member

    offenders = [
        f"{role}: {text!r} — {', '.join(hits)}"
        for role, text in Member.ROLE_DESCRIPTIONS.items()
        if (hits := vocabulary_offences(text))
    ]
    assert not offenders, "a role description carries a struck word:\n  " + "\n  ".join(offenders)


def test_the_choice_sweep_actually_sees_the_product() -> None:
    """Guard the guard. A wrong app label or a `choices` attribute that no longer exists
    would scan an empty list and pass forever."""
    pairs = _choice_labels()
    assert len(pairs) > 5, f"only {len(pairs)} choice labels found; the sweep is wrong"
    where = {w for w, _ in pairs}
    assert "Member.role" in where, "the roles were not scanned, and they are the reason"
    labels = {label for w, label in pairs if w == "Member.role"}
    assert {"Side Admin", "Family Admin"} <= labels, labels


# --- the e-mails --------------------------------------------------------------------
#
# A template scan cannot see a subject line assembled in Python, and the periodic e-mail's
# subject is one. These build the real messages and read them.


@pytest.mark.django_db
def test_the_email_updates_message_carries_no_banned_word_in_subject_or_body() -> None:
    """The whole message as it leaves: subject, plain text, and the HTML part mail clients
    actually render."""
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
    # Non-vacuity: the message really does carry the family's content, so a clean scan is a
    # scan of a real email rather than of an empty string.
    assert "A photo from the weekend" in built.text
    for part, name in ((built.subject, "subject"), (built.text, "text body")):
        hits = vocabulary_offences(prose(str(part)))
        assert not hits, f"the email update's {name}: {part[:200]!r}"
    assert not vocabulary_offences(prose(visible_text(built.html))), "the email update's HTML"


@pytest.mark.django_db
def test_the_address_confirmation_email_carries_no_banned_word() -> None:
    """The content-free confirmation (T-EMAIL-6), composed in Python from constants."""
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

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert "confirm" in message.body.lower()  # non-vacuity: it is the confirmation
    assert not vocabulary_offences(prose(str(message.subject))), message.subject
    assert not vocabulary_offences(prose(str(message.body))), message.body


@pytest.mark.django_db(transaction=True)
def test_the_account_email_allauth_sends_at_join_carries_no_banned_word() -> None:
    """The library's own e-mail, driven through the product rather than called directly.

    The address-confirmation mail went out as "[backyard.family] Please Confirm Your Email
    Address" / "Hello from backyard.family! You're receiving this email because user james
    has given your email address to register an account on backyard.family." — allauth's
    voice, not this product's, with the member's USERNAME in the body, and nobody had ever
    read it because nothing in the suite sent one.

    Sent by joining with an email address, which is the only way a relative ever triggers
    it. `transaction=True` because the send is deferred to `transaction.on_commit`.
    """
    from django.core import mail
    from django.test import Client
    from django.urls import reverse

    from core.invites import mint_invite
    from core.models import Pod, PodMembership, Yard

    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    _, raw = mint_invite(pod, None)
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
    assert PodMembership.objects.filter(pod=pod).exists()

    assert len(mail.outbox) == 1, [m.subject for m in mail.outbox]
    message = mail.outbox[0]
    assert "confirm" in message.body.lower()  # non-vacuity
    assert not message.subject.startswith("["), (
        f"the subject is still bracket-stamped with the site name: {message.subject!r}"
    )
    assert "cousinreed" not in message.body, "the e-mail prints the member's username"
    assert "register an account" not in message.body
    assert not vocabulary_offences(prose(str(message.subject))), message.subject
    assert not vocabulary_offences(prose(str(message.body))), message.body
