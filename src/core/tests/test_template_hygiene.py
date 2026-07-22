"""Template hygiene guards.

Django's `{# #}` comment is SINGLE-LINE ONLY: a comment that spans more than one
line is not recognised by the tokenizer and passes straight through as literal
text into the rendered page. This was caught live on the persistent instance —
the multi-line PWA and "Homestead mark" comments in base.html rendered as visible
text at the top of the authenticated feed. Multi-line comments must use
`{% comment %} … {% endcomment %}`, which the engine strips. This guard fails the
build on any multi-line `{# #}` in a template, and separately proves base.html
renders clean with the auth block active.
"""

from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

from django.template import Context, Template
from django.template.loader import get_template

_TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"


def test_no_multiline_hash_comments_in_templates() -> None:
    offenders: list[str] = []
    for path in _TEMPLATES.rglob("*.html"):
        for match in re.finditer(r"\{#(.*?)#\}", path.read_text(), re.S):
            if "\n" in match.group(1):
                rel = path.relative_to(_TEMPLATES)
                offenders.append(f"{rel}: {match.group(0)[:60]!r}")
    assert not offenders, (
        "multi-line {# #} comments leak as literal text (Django {# #} is single-line "
        "only); use {% comment %}…{% endcomment %} instead:\n" + "\n".join(offenders)
    )


def test_the_guard_is_non_vacuous() -> None:
    # Prove the leak the guard defends against is real: a multi-line {# #} renders
    # its own text, while {% comment %} strips it.
    assert Template("A{# x\ny #}B").render(Context({})) == "A{# x\ny #}B"  # leaks
    assert Template("A{% comment %}x\ny{% endcomment %}B").render(Context({})) == "AB"


def test_base_html_renders_clean_with_auth_block() -> None:
    # The full base.html with the authenticated PWA/service-worker block active must
    # carry no leaked comment markers or developer-comment text.
    ctx = {
        "user": SimpleNamespace(is_authenticated=True),
        "request": SimpleNamespace(csp_nonce="test-nonce"),
    }
    html = get_template("core/base.html").render(ctx)
    for leak in ("{#", "#}", "PWA install surface", "Homestead mark", "{% comment"):
        assert leak not in html, f"base.html leaked {leak!r} into the rendered page"
