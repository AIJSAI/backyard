"""Capitalise Every Word, in the places the owner named, without exception.

His example was the first thing a keyboard user reaches on every page: "Skip To Content",
not "Skip to content". The rule covers page titles, headings, buttons, nav items, links
that act as commands, form labels, fieldset legends, table headers and e-mail subjects —
every word, including "To", "A", "The", "Of".

It does NOT cover body text, hints, errors, flash messages, e-mail bodies or empty states.
Those are sentence case with a full stop. A string that is used both as a heading and
inside a sentence is two strings.

THE CAPITALS LIVE IN THE SOURCE. Never CSS `text-transform`: it mangles names and e-mail
addresses, a screen reader reads the source, and so does this guard.

WHAT IS LEFT ALONE. A word a person typed — a household's name, a side's name, a post — is
never re-cased, and neither is an e-mail address, a domain or a file name: any token
carrying an `@` or a dot-domain is skipped. Only the first letter of a word is examined, so
"AGPL", "iPhone" and "McKay" pass untouched. Text inside `{% ... %}` and `{{ ... }}` is
removed before the check, so a relative's own name in a heading is not this guard's
business.

RUN IT ON ONE FILE. Parametrised by template: `pytest -k "members.html"`. A failure prints
the file, the text as it stands and the same text with the rule applied, so the fix can be
pasted.
"""

from __future__ import annotations

import pathlib

import pytest

from core.tests.copy_scan import (
    script_button_labels,
    template_key,
    templates,
    title_case_offences,
    title_case_targets,
    title_cased,
    without_template_syntax,
)

_TEMPLATES = templates()
_KEYS = [template_key(path) for path in _TEMPLATES]
# An e-mail subject is a whole template: one line, no markup, and the capitalisation rule
# covers it exactly as it covers a heading.
_SUBJECT_SUFFIX = "_subject.txt"


def _subject_of(path: pathlib.Path) -> list[tuple[str, str]]:
    if not path.name.endswith(_SUBJECT_SUFFIX):
        return []
    subject = " ".join(without_template_syntax(path.read_text()).split())
    return [("e-mail subject", subject)] if subject else []


@pytest.mark.parametrize("path", _TEMPLATES, ids=_KEYS)
def test_every_heading_button_and_label_is_title_case(path: pathlib.Path) -> None:
    key = template_key(path)
    faults: list[str] = []
    for where, text in title_case_targets(path.read_text()) + _subject_of(path):
        offenders = title_case_offences(text)
        if offenders:
            faults.append(
                f"{where} {text!r}\n      small: {', '.join(offenders)}"
                f"\n      fix:   {title_cased(text)!r}"
            )
    assert not faults, f"{key} — Capitalise Every Word:\n    " + "\n    ".join(faults)


@pytest.mark.parametrize("path", _TEMPLATES, ids=_KEYS)
def test_a_button_a_script_builds_is_title_case_too(path: pathlib.Path) -> None:
    """A button the markup declares is covered above; a button JavaScript creates was not.

    The password toggle on the join page is one: nothing in the template says "Show
    Password", the script does, and the sweep above cannot see it because `<script>` is
    stripped. Only a button is claimed here, and only where the source says so in one
    place — `document.createElement("button")` assigned to a name, and that name given a
    literal `textContent`. A bare string in a script carries no element around it, so
    nothing else in there can be told apart from a sentence (`copy_scan.script_strings`
    reads those for the vocabulary and the voice, which need no such distinction).
    """
    key = template_key(path)
    faults = [
        f"{where} {text!r}\n      small: {', '.join(offenders)}\n      fix:   {title_cased(text)!r}"
        for where, text in script_button_labels(path.read_text())
        if (offenders := title_case_offences(text))
    ]
    assert not faults, f"{key} — Capitalise Every Word:\n    " + "\n    ".join(faults)


def test_the_script_button_reader_is_not_vacuous() -> None:
    """It reads the shape the product actually writes, and claims nothing else."""
    toggle = (
        '<script>var toggle = document.createElement("button");'
        'toggle.textContent = "Show password";</script>'
    )
    found = script_button_labels(toggle)
    assert found and title_case_offences(found[0][1]) == ["password"]
    assert not script_button_labels(
        '<script>var p = document.createElement("p"); p.textContent = "all caught up";</script>'
    ), "a paragraph is not a button; body text is sentence case"
    assert not script_button_labels('<script>el.textContent = "a sentence in a div";</script>')


def test_the_guard_is_not_vacuous() -> None:
    """Prove it finds each shape it claims to cover, and that it leaves alone what it
    must. Without this, a regex that matched no elements would report a clean product."""
    assert title_case_offences("Skip to content")
    assert title_case_offences("Create a link")
    assert not title_case_offences("Skip To Content")
    assert not title_case_offences("Create A Link")
    assert title_cased("Skip to content") == "Skip To Content"
    # BOTH HALVES OF A HYPHENATED WORD (copy walk decision 3, 2026-09-19). "Sign-in Link"
    # and "No-login Link" are offences the way "sign In" is, and the fix a failure prints
    # has to be pastable, so `title_cased` moves each half and keeps the edge punctuation.
    assert title_case_offences("Sign-in Link")
    assert title_case_offences("No-login Link")
    assert title_case_offences("Your sign-in Email")
    assert not title_case_offences("Sign-In Link")
    assert not title_case_offences("No-Login Link")
    assert title_cased("Sign-in Link") == "Sign-In Link"
    assert title_cased("No-login link") == "No-Login Link"
    assert title_cased('"Sign-in?"') == '"Sign-In?"'
    # An address still keeps its own case, hyphen or no hyphen.
    assert not title_case_offences("Open my-backyard.example.test In Your Browser")
    # Every covered element is actually found.
    for markup, expected in (
        ("<title>Join your family</title>", "<title>"),
        ("<h1>Say hello</h1>", "<h1>"),
        ("<h2>Your sign-in email</h2>", "<h2>"),
        ("<h3>Add an email address</h3>", "<h3>"),
        ("<h4>Recent sends</h4>", "<h4>"),
        ("<button type='submit'>Save changes</button>", "<button>"),
        ("<legend>Who can see this</legend>", "<legend>"),
        ("<label for='name'>Your name</label>", "<label>"),
        ("<th>How often</th>", "<th>"),
        ("<summary>What the roles mean</summary>", "<summary>"),
        ("<nav><a href='/'>Back to the feed</a></nav>", "nav link"),
        ("<a class='btn primary' href='/'>Go to sign in</a>", "link styled as a button"),
        ("{% element h1 %}say hello{% endelement %}", "{% element h1 %}"),
        (
            '{% element button type="submit" style="width:100%" %}save changes{% endelement %}',
            "{% element button %}",
        ),
        ('<span class="role">side admin</span>', "badge"),
        ('<option value="x">no change</option>', "<option>"),
        # The shared e-mail layout draws the heading and the one button; each message
        # fills them from a child template, where the words have no element around them.
        (
            "{% block heading %}confirm your email address{% endblock %}",
            "{% block heading %} (an e-mail heading)",
        ),
        (
            "{% block action_label %}set a new password{% endblock %}",
            "{% block action_label %} (an e-mail button)",
        ),
    ):
        found = title_case_targets(markup)
        assert found, f"{expected} was not found in {markup!r}"
        assert any(where == expected and title_case_offences(text) for where, text in found), found
    # The layout's own empty definitions of those two blocks are markup, not copy.
    assert not title_case_targets("{% block heading %}{% endblock %}")
    assert not title_case_targets("{% block action_label %}{% endblock %}")
    # A link that is NOT navigation and NOT a button is body text, and body text is
    # sentence case. The guard must not reach it.
    assert not title_case_targets("<p>Read <a href='/about/'>about this page</a>.</p>")
    # Neither may it reach a comment, a stylesheet or a script.
    assert not title_case_targets("{% comment %}<h1>a heading in prose</h1>{% endcomment %}")
    assert not title_case_targets("<style>h1 { font-size: 2rem }</style>")
    assert not title_case_targets("<script>const h = '<h1>hi</h1>';</script>")
    assert not title_case_targets("<script>'{% element h1 %}hi{% endelement %}'</script>")
    # A slot inside an element is markup, not copy, and the body is still read.
    assert any(
        where == "{% element button %}" and text == "save it"
        for where, text in title_case_targets(
            "{% element button %}{% slot label %}save it{% endslot %}{% endelement %}"
        )
    )


def test_it_never_re_cases_what_a_person_typed_or_a_machine_owns() -> None:
    """The half that would do damage if it were wrong. A household's name, an address and
    a domain keep exactly the case they were given."""
    # A name comes through a variable, which is stripped before the words are read.
    assert not title_case_offences(
        title_case_targets("<h1>{{ pod.name }}</h1><h2>Your {{ side.name }} Side</h2>")[0][1]
    )
    assert not title_case_offences("Email Sent To you@example.com")
    assert not title_case_offences("Open backyard.family In Your Browser")
    assert title_cased("Email Sent To you@example.com") == "Email Sent To you@example.com"
    # An acronym and an internal capital survive.
    assert not title_case_offences("The AGPL Source Offer")
    assert not title_case_offences("Ask McKay For A Link")
    # A PRODUCT NAME THAT OPENS ON A SMALL LETTER keeps its own case, which the module
    # docstring has always promised ("so AGPL, iPhone and McKay pass untouched") and the
    # implementation did not do until the install page needed the heading. The evidence is
    # the capital further along; a word with none is an offence exactly as before.
    assert not title_case_offences("iPhone And iPad")
    assert title_cased("iPhone And iPad") == "iPhone And iPad"
    assert title_case_offences("iphone And ipad") == ["iphone", "ipad"]
    # Punctuation is not a word.
    assert not title_case_offences("Delete This Post?")
    assert not title_case_offences("“Hi Everyone” (Optional)")


def test_the_sweep_actually_sees_the_product() -> None:
    """Guard the guard: a broken glob, or a target list that finds nothing, passes."""
    names = {p.name for p in _TEMPLATES}
    assert len(names) > 30, f"only {len(names)} templates found; the globs are wrong"
    covered = sum(len(title_case_targets(p.read_text())) + len(_subject_of(p)) for p in _TEMPLATES)
    assert covered > 100, (
        f"only {covered} headings, buttons and labels found; the patterns are wrong"
    )
    subjects = [p for p in _TEMPLATES if p.name.endswith(_SUBJECT_SUFFIX)]
    assert len(subjects) >= 3, f"only {len(subjects)} e-mail subject templates found"


@pytest.mark.django_db
def test_the_email_updates_subject_is_title_case() -> None:
    """The one subject assembled in Python, so no template scan can reach it.

    The SIDE'S OWN NAME is taken out before the check and not before: it is a word a
    relative typed, and the glossary says a side is said by its own name. What is left is
    the product's own words in the subject line, which are the ones this rule governs.
    """
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
    subject = digest.build_digest(
        issue,
        digest_token=digest_links.mint(issue),
        unsubscribe_token="unsub-raw-value",
    ).subject
    assert subject  # non-vacuity: there is a subject to read
    ours = subject.replace(yard.name, " ")
    assert not title_case_offences(ours), (
        f"the subject a relative reads in their inbox is {subject!r}; "
        f"the product's own words in it should read {title_cased(ours)!r}"
    )
