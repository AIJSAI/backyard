"""Strip every comment syntax a file uses, before asserting on its source text.

Written because the same defect appeared FOUR times in one session, each time in a check
that read source text and each time reintroduced by hand:

1. A template guard passed with the link deleted, because the comment explaining the bug
   quoted `{% url 'digest_settings' %}` as prose.
2. The fix for (1) stripped `{% comment %}` and `<!-- -->` but not `{# ... #}` — the same
   hole one syntax down.
3. A version guard failed because a comment explaining why a link was removed quoted the
   URL it was explaining.
4. A brand-new test repeated (2) exactly, written by someone who had just fixed it twice.

The lesson is not "remember to strip comments". It is that a source-text assertion is
answerable by WRITING ABOUT the thing it checks for, so the stripping has to live in one
place that every such check calls — otherwise the next one reintroduces it, which is
precisely what happened.
"""

from __future__ import annotations

import re

_DJANGO_BLOCK = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S)
_DJANGO_INLINE = re.compile(r"\{#.*?#\}", re.S)
_HTML = re.compile(r"<!--.*?-->", re.S)


def without_comments(source: str) -> str:
    """`source` with Django block, Django inline, and HTML comments removed.

    All three, always. Stripping a subset is how this came back: prose in whichever syntax
    was missed still satisfies the assertion, and the check reports green while the thing
    it guards is absent.
    """
    source = _DJANGO_BLOCK.sub("", source)
    source = _DJANGO_INLINE.sub("", source)
    return _HTML.sub("", source)
