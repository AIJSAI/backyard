"""One word per concept, held by a guard rather than by care.

The product used three words for a household (pod / household / house), two for a side of
the family (yard / side of the family), three for the Family email (digest / weekly email /
Digest delivery), and printed "elder path", "token" and "instance" at relatives. The worst
of it was one tap wide: the composer said "Our house", the feed said "your household", and
the confirmation screen one tap later said "not only your pod".

A first-time relative cannot build a mental model when the same object is renamed on every
screen — and the control that decides who sees their phone number was labelled "People in
my yards", with no screen in the product defining a yard.

The vocabulary, ruled 2026-09-19:

    household          never pod, never house
    side of the family never yard
    the Family email   never digest
    no-login link      never elder path, never token
    this Backyard      never instance

Model fields, URL names, class names and Python identifiers are NOT covered and are not
supposed to be: `Pod`, `Yard` and `DigestSubscription` are what the code calls these
things, and renaming them would be a migration, not a copy pass. What is covered is
everything a person reads — a template's visible text, and the body and subject of every
e-mail this product can send.

HOW IT READS A TEMPLATE. Comments (both syntaxes), <style>, <script>, template tags and
template variables are removed before the search, so `{% url 'pod_list' %}`,
`class="pods"`, `name="pod_id"` and `{{ pod.name }}` are invisible to it and the words a
person reads are all that is left. "Backyard" contains "yard" and survives, because the
search is on word boundaries.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2]
_TEMPLATE_ROOTS = (_SRC / "core" / "templates", _SRC / "templates")

# The banned words, each with the word the product uses instead. The message a failure
# prints is the replacement, because "pod is banned" is not actionable and
# "pod -> household" is.
BANNED: dict[str, str] = {
    "pod": "household (or group, for an ad-hoc one)",
    "pods": "households (or groups)",
    # "house" was DOCUMENTED as banned above and missing from this dict, so the guard
    # could not see the placeholders that still said "e.g. Our house" — which is exactly
    # the kind of gap an allowlist-shaped check rots into. Review caught it.
    "house": "household",
    "houses": "households",
    "yard": "side of the family",
    "yards": "sides of the family",
    "digest": "the Family email",
    "digests": "Family emails",
    "instance": "this Backyard",
    "instances": "Backyards",
    "token": "link",
    "tokens": "links",
    "elder path": "no-login link",
    "elder link": "no-login link",
}

# ALLOWLIST. Kept small and each entry says who reads that surface and why the word is
# the honest one there. It is a per-(file, word) exemption, never a whole-file pass.
#
# Only one entry, and it is an operator surface: the weekly health e-mail goes to the
# instance admin and to nobody else, and it is about the SERVER — the box, its disk, its
# backups. "This Backyard" would be a worse word there, because the thing being reported
# on is not the family's page, it is the machine underneath it.
ALLOWED: dict[str, set[str]] = {
    "core/email/health.txt": {"instance"},
}


# Attributes whose VALUE is copy a person reads or hears: the grey hint inside an empty
# box, the name a screen reader announces, a tooltip, a picture's description. Stripping
# tags wholesale took these with the ids and the class names, which is how "e.g. Our
# house" survived the vocabulary pass on the setup screen.
_VISIBLE_ATTRS = re.compile(r'\b(?:placeholder|aria-label|title|alt)="([^"]*)"', re.I)


def _visible_text(source: str) -> str:
    """What a person actually reads on the page.

    Everything a browser does not render as words comes out first: both comment
    syntaxes, <style> and <script> bodies, template tags and variables, and finally HTML
    tags — which takes every attribute with them, so an id, a class, a form field name
    and a `{% url %}` route name cannot trip this guard. The four attributes above are
    lifted back out before that happens, because their values are read aloud or shown.
    """
    text = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", " ", source, flags=re.S)
    text = re.sub(r"\{#.*?#\}", " ", text, flags=re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.S)
    text = re.sub(r"\{%.*?%\}", " ", text, flags=re.S)
    spoken = " ".join(_VISIBLE_ATTRS.findall(text))
    return re.sub(r"<[^>]+>", " ", text) + " " + spoken


def _prose(text: str) -> str:
    """An e-mail body with its URLs removed.

    A link in a plain-text e-mail is visible, but the PATH inside it is a route name —
    `/digest/unsubscribe/<token>/` — and routes are code identifiers, which this guard
    deliberately does not police. Renaming them would be a redirect problem, not a copy
    one, and would break every link already sitting in somebody's inbox. What is left
    after this is the sentences.
    """
    return re.sub(r"https?://\S+", " ", text)


def _offences(text: str, allowed: set[str]) -> list[str]:
    found: list[str] = []
    for word, replacement in BANNED.items():
        if word in allowed:
            continue
        if re.search(rf"\b{re.escape(word)}\b", text, re.I):
            found.append(f"{word!r} (say: {replacement})")
    return found


def _templates() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for root in _TEMPLATE_ROOTS:
        for pattern in ("*.html", "*.txt"):
            paths.extend(root.rglob(pattern))
    return sorted(paths)


def test_no_template_shows_a_banned_word_to_a_person() -> None:
    offenders: list[str] = []
    for path in _templates():
        key = str(path.relative_to(path.parents[1] if path.parent.name else path.parent))
        # The key is the path as a reader would name it: "core/email/health.txt",
        # "account/email/base_message.txt". Computed from the template ROOT, so it does
        # not move when the repository does.
        for root in _TEMPLATE_ROOTS:
            if root in path.parents:
                key = str(path.relative_to(root))
                break
        hits = _offences(_visible_text(path.read_text()), ALLOWED.get(key, set()))
        if hits:
            offenders.append(f"{key}: {', '.join(hits)}")
    assert not offenders, (
        "the product's internal nouns are back in text a relative reads. One word per "
        "concept:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_is_not_vacuous() -> None:
    """Prove it can fail, and prove the stripping it depends on is real.

    Without this, a regex that matched nothing — or a `_visible_text` that stripped the
    whole document — would report a clean product forever.
    """
    assert _offences(_visible_text("<p>Start a pod that is just your group</p>"), set())
    assert _offences(_visible_text("<h1>Your yards</h1>"), set())
    assert _offences(_visible_text("<p>Turn on the digest</p>"), set())
    assert _offences(_visible_text("<p>This is the elder path.</p>"), set())
    assert not _offences(_visible_text("<h1>Your backyard</h1>"), set())
    assert _offences(_visible_text('<input placeholder="e.g. Our house">'), set())
    assert _offences(_visible_text('<a aria-label="Your pods">Groups</a>'), set())
    # ...and cannot fail for the wrong reasons.
    assert not _offences(_visible_text('<a href="/pods/" class="pods">Groups</a>'), set())
    assert not _offences(_visible_text("{% url 'pod_list' %}{{ pod.name }}"), set())
    assert not _offences(_visible_text("{% comment %}the pod list{% endcomment %}"), set())
    assert not _offences(_visible_text("{# a yard is a side of the family #}"), set())
    assert not _offences(_visible_text("<style>ul.pods { margin: 0 }</style>"), set())


def test_the_template_sweep_actually_sees_the_product() -> None:
    """Guard the guard. A broken glob scans nothing and passes."""
    names = {p.name for p in _templates()}
    assert len(names) > 30, f"only {len(names)} templates found; the globs are wrong"
    for expected in ("feed.html", "members.html", "digest.txt", "base_message.txt"):
        assert expected in names, f"{expected} was not scanned"


def test_every_allowlist_entry_still_points_at_a_real_file_and_a_real_word() -> None:
    """The allowlist is only ever SUBTRACTED, so a stale entry excuses nothing and says
    nothing — the failure mode `_UNLINKED_BY_DESIGN` already taught this repository once,
    where an entry named a route that did not exist and had been a no-op since it was
    written."""
    known = set()
    for root in _TEMPLATE_ROOTS:
        for pattern in ("*.html", "*.txt"):
            known |= {str(p.relative_to(root)) for p in root.rglob(pattern)}
    for key, words in ALLOWED.items():
        assert key in known, f"the allowlist names {key}, which is not a template"
        assert words <= set(BANNED), f"the allowlist for {key} names a word nothing bans"
        text = _visible_text((_SRC / "core" / "templates" / key).read_text())
        assert _offences(text, set()), (
            f"the allowlist excuses {key}, and that file no longer uses any banned word. "
            "Delete the entry rather than leaving a standing exemption behind."
        )


# --- the e-mails --------------------------------------------------------------------
#
# A template scan cannot see a subject line assembled in Python, and the digest's subject
# was one: "<side>: your family digest". These build the real messages and read them.


@pytest.mark.django_db
def test_the_family_email_carries_no_banned_word_in_subject_or_body() -> None:
    """The whole message as it leaves: subject, plain text, and the HTML part mail
    clients actually render."""
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
    # Non-vacuity: the message really does carry the family's content, so a clean scan
    # is a scan of a real email rather than of an empty string.
    assert "A photo from the weekend" in built.text
    for part, name in ((built.subject, "subject"), (built.text, "text body")):
        assert not _offences(_prose(str(part)), set()), f"the Family email's {name}: {part[:200]!r}"
    assert not _offences(_prose(_visible_text(built.html)), set()), "the Family email's HTML"


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
    assert not _offences(_prose(str(message.subject)), set()), message.subject
    assert not _offences(_prose(str(message.body)), set()), message.body


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
    assert not _offences(_prose(str(message.subject)), set()), message.subject
    assert not _offences(_prose(str(message.body)), set()), message.body


def test_no_exclamation_marks_in_the_product_copy() -> None:
    """Tone, ruled the same day: calm, warm, short. Nothing shouts.

    Scoped to visible text for the same reason as the words above, and to the templates
    this product wrote — the two `{% element %}` layers allauth ships are not ours.
    """
    offenders: list[str] = []
    for path in _templates():
        for root in _TEMPLATE_ROOTS:
            if root in path.parents:
                key = str(path.relative_to(root))
                break
        else:  # pragma: no cover - the loop above always matches
            key = path.name
        # `[!]` is the weekly health e-mail's marker beside a line that wants the
        # instance admin's attention — a flag in a fixed-width report, not a raised
        # voice. Removed before the check rather than allowlisting the whole file, so a
        # real exclamation mark in that e-mail would still be caught.
        text = _visible_text(path.read_text()).replace("[!]", "")
        if "!" in text:
            context = text[max(0, text.index("!") - 60) : text.index("!") + 10]
            offenders.append(f"{key}: ...{' '.join(context.split())}")
    assert not offenders, "product copy does not shout:\n  " + "\n  ".join(offenders)
