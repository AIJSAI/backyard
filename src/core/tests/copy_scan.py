"""Read a template the way a person reads it, so a copy guard can assert on the words.

Three guards share this module — the vocabulary (test_one_word_per_concept.py), the voice
(test_the_product_voice.py) and the capitalisation (test_title_case.py). They share it for
the reason `comment_stripping.py` exists: a source-text check is answerable by WRITING
ABOUT the thing it checks for, so the stripping has to live in one place that every check
calls, or the next one reintroduces the hole. Three copies of `_visible_text` would drift
within a week and two of them would go quiet.

WHAT IS VISIBLE. Comments in all three syntaxes, `<style>` and `<script>` bodies, template
tags and template variables come out before anything is searched, so `{% url 'pod_list' %}`,
`class="pods"`, `name="pod_id"` and `{{ pod.name }}` are invisible here and only the words a
person reads are left. Four attributes are lifted back IN before the tags go, because their
values are shown or read aloud: placeholder, aria-label, title and alt.

WHAT IS NOT COVERED, and must not be: model fields, URL names, CSS classes, Python
identifiers, test names and operator documentation. `Pod`, `Yard` and `DigestSubscription`
are what the code calls these things; renaming them is a migration of live rows, not a copy
pass.
"""

from __future__ import annotations

import html
import pathlib
import re
from collections.abc import Collection

from core.tests.comment_stripping import without_comments

_SRC = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE_ROOTS = (_SRC / "core" / "templates", _SRC / "templates")

# Attributes whose VALUE is copy a person reads or hears: the grey hint inside an empty
# box, the name a screen reader announces, a tooltip, a picture's description. Stripping
# tags wholesale takes these with the ids and the class names, which is how "e.g. Our
# house" once survived a vocabulary pass on the setup screen.
_VISIBLE_ATTRS = re.compile(r'\b(?:placeholder|aria-label|title|alt)="([^"]*)"', re.I)
_TEMPLATE_VAR = re.compile(r"\{\{.*?\}\}", re.S)
_TEMPLATE_TAG = re.compile(r"\{%.*?%\}", re.S)
_STYLE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)
_SCRIPT = re.compile(r"<script[^>]*>.*?</script>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")


def without_noise(source: str) -> str:
    """`source` with comments, `<style>` and `<script>` removed, and its MARKUP intact.

    What the capitalisation guard needs: it has to know which words sat inside an `<h2>`
    and which inside a `<p>`, so it cannot use `visible_text` below.
    """
    return _SCRIPT.sub(" ", _STYLE.sub(" ", without_comments(source)))


def without_template_syntax(text: str) -> str:
    """Template tags and variables out. What is left is literal text.

    Both, always: `{% if %}` is not visible and neither is `{{ member.display_name }}`,
    and a guard that stripped one would read the other as product copy and accuse a
    relative's own name of being badly capitalised.
    """
    return _TEMPLATE_TAG.sub(" ", _TEMPLATE_VAR.sub(" ", text))


def visible_text(source: str) -> str:
    """What a person actually reads on the page."""
    text = without_template_syntax(without_noise(source))
    spoken = " ".join(_VISIBLE_ATTRS.findall(text))
    return _TAG.sub(" ", text) + " " + spoken


def prose(text: str) -> str:
    """An e-mail body with its URLs removed.

    A link in a plain-text e-mail is visible, but the PATH inside it is a route name —
    `/digest/unsubscribe/<token>/` — and routes are code identifiers, which these guards
    deliberately do not police. Renaming them would be a redirect problem, not a copy one,
    and would break every link already sitting in somebody's inbox.
    """
    return _URL.sub(" ", text)


def templates() -> list[pathlib.Path]:
    """Every template in the product, both roots, both extensions."""
    paths: list[pathlib.Path] = []
    for root in TEMPLATE_ROOTS:
        for pattern in ("*.html", "*.txt"):
            paths.extend(root.rglob(pattern))
    return sorted(paths)


def template_key(path: pathlib.Path) -> str:
    """The path as a reader would name it: "core/email/health.txt", "account/login.html".

    Computed from the template ROOT rather than the repository, so it does not move when
    the checkout does, and it is what an allowlist entry and a `-k` filter both name.
    """
    for root in TEMPLATE_ROOTS:
        if root in path.parents:
            return str(path.relative_to(root))
    return path.name  # pragma: no cover - every template is under a root


# --- the vocabulary -------------------------------------------------------------------
#
# Each banned word carries the word the product uses instead, because a failure that says
# "pod is banned" is not actionable and "pod -> household" is.

BANNED: dict[str, str] = {
    # The nouns this product invented for itself.
    "pod": "household (or group, for one a member made)",
    "pods": "households (or groups)",
    "house": "household",
    "houses": "households",
    "yard": "side of the family",
    "yards": "sides of the family",
    "instance": "this Backyard",
    "instances": "Backyards",
    "token": "link",
    "tokens": "links",
    "elder path": "no-login link",
    "elder link": "no-login link",
    # Ruled out by the owner on 2026-09-19, by name.
    "digest": "Email Updates",
    "digests": "Email Updates",
    "family email": "Email Updates",
    "nag": "(delete the sentence)",
    "nags": "(delete the sentence)",
    "look after": "the role, plainly: adds and removes members",
    "looks after": "the role, plainly: adds and removes members",
    # The filler, the idioms and the reassurance, quoted from his critique.
    "feel like it": "(delete the sentence)",
    "and you are done": "(delete it; the screen already ended)",
    "straight to": "the literal thing that happens",
    "nothing that": "(delete the sentence)",
    "chase you": "(delete the sentence)",
    "tell us": "the instruction: 'Enter your name.'",
    "don't worry": "(delete the sentence)",
    "no pressure": "(delete the sentence)",
    "you can always": "'Change this anytime in Settings.'",
    "whenever you like": "(delete the phrase)",
    "if you ever": "'if you forget your password'",
    "simply": "(delete the word)",
    "of course": "(delete the phrase)",
}

# ALLOWLIST. Kept small, per (file, word), never a whole-file pass, and each entry says who
# reads that surface and why the word is the honest one there.
#
# One entry, and it is an operator surface: the weekly health e-mail goes to the family
# admin and to nobody else, and it is about the SERVER — the box, its disk, its backups.
# "This Backyard" would be the worse word there, because the thing being reported on is not
# the family's page, it is the machine underneath it.
ALLOWED: dict[str, set[str]] = {
    "core/email/health.txt": {"instance"},
}


def vocabulary_offences(text: str, allowed: Collection[str] = ()) -> list[str]:
    """Every banned word in `text`, each with its replacement. Word boundaries, so
    "Backyard" survives "yard" and "household" survives "house"."""
    found: list[str] = []
    for word, replacement in BANNED.items():
        if word in allowed:
            continue
        if re.search(rf"\b{re.escape(word)}\b", text, re.I):
            found.append(f"{word!r} (say: {replacement})")
    return found


# --- the voice ------------------------------------------------------------------------
#
# "The product is not a person." Never "we", "us", "our" — his question was "Who is us?
# That doesn't make sense." And nothing shouts, dashes or trails off: the punctuation rule
# is no exclamation marks, no em dashes, no ellipses.

_FIRST_PERSON = ("we", "we'll", "we've", "we're", "us", "our", "ours", "let's", "lets")
_PUNCTUATION: dict[str, str] = {
    "!": "a full stop",
    "—": "a full stop, or two sentences",  # em dash
    "&mdash;": "a full stop, or two sentences",
    "&#8212;": "a full stop, or two sentences",
    "…": "a full stop",  # ellipsis character
    "&hellip;": "a full stop",
    "...": "a full stop",
}


def voice_offences(text: str) -> list[str]:
    """First-person product voice and the three banned marks.

    Word boundaries throughout, so "week" is not "we" and "because" is not "us". The
    apostrophe forms are named explicitly rather than left to `\\b`, so the message a
    failure prints quotes the thing that is actually in the file.
    """
    found: list[str] = []
    for word in _FIRST_PERSON:
        if re.search(rf"\b{re.escape(word)}\b", text, re.I):
            found.append(f"{word!r} — the product is not a person; address the reader as 'you'")
    for mark, instead in _PUNCTUATION.items():
        if mark in text:
            found.append(f"{mark!r} — use {instead}")
    return found


# --- the capitalisation ----------------------------------------------------------------
#
# "Capitalise Every Word" (his example: "Skip To Content", not "Skip to content") in page
# titles, headings, buttons, nav items, links that act as commands, form labels, fieldset
# legends, table headers and e-mail subjects. Every word, including "To", "A", "The", "Of".
# The capitals are written in the SOURCE text: CSS text-transform would mangle a name and
# an e-mail address, and neither the tests nor a screen reader would see it.

_TITLE_CASE_ELEMENTS = (
    "title",
    "h1",
    "h2",
    "h3",
    "h4",
    "button",
    "legend",
    "label",
    "th",
    "summary",
)
_NAV_BLOCK = re.compile(r"<nav\b[^>]*>(.*?)</nav>", re.S | re.I)
_ANCHOR = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
# Both quote styles: the product writes double quotes, but a guard that only sees one of
# them is a guard that goes quiet the first time somebody writes the other.
_BUTTON_ANCHOR = re.compile(
    r"""<a\b[^>]*class=["'][^"']*\bbtn\b[^"']*["'][^>]*>(.*?)</a>""", re.S | re.I
)
# A word is a whitespace-delimited token with its bordering punctuation taken off. The
# leading/trailing set is deliberately wide: a heading can be wrapped in quotes, end in a
# question mark, or sit inside brackets, and none of that is a word.
_EDGE = "\"'“”‘’()[]{}.,:;?!/|&·—–…-"
# A machine-shaped token keeps whatever case it was given: an e-mail address, a domain, a
# file name. Re-casing one would be wrong, not pedantic.
_MACHINE = re.compile(r"@|\.[A-Za-z]{2,}")


def _element_text(inner: str) -> str:
    """The words inside one element: nested markup and template syntax out, entities in."""
    return " ".join(html.unescape(_TAG.sub(" ", without_template_syntax(inner))).split())


def title_case_targets(source: str) -> list[tuple[str, str]]:
    """(where, text) for every string the capitalisation rule covers in one template."""
    text = without_noise(source)
    targets: list[tuple[str, str]] = []
    for element in _TITLE_CASE_ELEMENTS:
        pattern = re.compile(rf"<{element}\b[^>]*>(.*?)</{element}>", re.S | re.I)
        for inner in pattern.findall(text):
            targets.append((f"<{element}>", _element_text(inner)))
    for nav in _NAV_BLOCK.findall(text):
        for inner in _ANCHOR.findall(nav):
            targets.append(("nav link", _element_text(inner)))
    for inner in _BUTTON_ANCHOR.findall(text):
        targets.append(("link styled as a button", _element_text(inner)))
    return [(where, words) for where, words in targets if words]


def title_case_offences(text: str) -> list[str]:
    """The words in `text` that a person reads starting with a small letter."""
    return [word for word in text.split() if _is_lowercased(word)]


def _is_lowercased(word: str) -> bool:
    stripped = word.strip(_EDGE)
    if not stripped or _MACHINE.search(stripped):
        return False
    first = next((ch for ch in stripped if ch.isalpha()), "")
    return bool(first) and first.islower()


def title_cased(text: str) -> str:
    """`text` with the rule applied: the fix a failure prints, ready to paste.

    Only the first letter of each word moves. A name a person typed, an acronym and an
    address are left exactly as they are, which is why this is not `str.title()`.
    """
    fixed: list[str] = []
    for word in text.split():
        if not _is_lowercased(word):
            fixed.append(word)
            continue
        index = next(i for i, ch in enumerate(word) if ch.isalpha())
        fixed.append(word[:index] + word[index].upper() + word[index + 1 :])
    return " ".join(fixed)
