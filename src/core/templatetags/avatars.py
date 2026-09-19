"""The initials avatar: a calm tinted disc wherever a person's name leads something.

The design walk's biggest finding was that a product whose whole purpose is family
warmth had no human presence in its chrome at all — the directory was a list of green
underlined links, a profile was three lines on a blank page. This is the smallest thing
that fixes it: two initials on one of six tinted discs, no photo upload, no new column.

Two properties are load-bearing.

**Deterministic, by member id.** The same relative is the same colour on the feed, in a
thread, in the directory and on their profile. Keyed on the id rather than the name so
that correcting a typo in somebody's name does not change what they look like — the
directory is the one place a member is recognised at a glance.

**The tone is an INDEX, never a colour.** The tag emits `data-tone="3"`; base.html maps
that to a `--tone-3-bg` / `--tone-3-ink` token pair, and test_design_system_wcag proves
every pair clears AA in both themes. A computed hue could not be proven at all.
"""

from __future__ import annotations

from django import template

register = template.Library()

# Six is enough variety for a family and few enough to stay calm on a directory page.
# Kept in step with the --tone-N-* token pairs in core/templates/core/base.html and with
# _TONES in core/tests/test_avatars.py.
TONE_COUNT = 6


def initials(name: str) -> str:
    """One or two letters from a display name, for the disc.

    First and last word, because that is how a family reads a name ("Rose Whitfield" ->
    RW). A single word gives one letter rather than two from the same word: "RO" reads as
    a truncation, "R" reads as a monogram. A name with no letters at all (a member called
    entirely in an alphabet with no case, or in emoji) falls back to the bullet rather
    than rendering an empty circle.
    """
    words = [word for word in name.split() if word]
    if not words:
        return "•"
    picked = words[0][0] if len(words) == 1 else words[0][0] + words[-1][0]
    return picked.upper()


def tone_for(seed: object) -> int:
    """The 1-based tone index for a member id (or anything else stable).

    Not `hash()`: Python salts str hashing per process, so two gunicorn workers would
    serve the same person in two different colours within one page load. A sum of
    codepoints over the string form is stable everywhere, forever, and the distribution
    over small integer ids is simply round-robin, which is the best spread available.
    """
    return sum(ord(ch) for ch in str(seed)) % TONE_COUNT + 1


@register.inclusion_tag("core/_avatar.html")
def avatar(name: str, seed: object, size: str = "") -> dict[str, object]:
    """Render one person's disc. `size` is "" (default), "sm" (a reply) or "lg" (a profile).

    `aria-hidden` lives in the partial: the name this disc stands for is always rendered
    as text immediately beside it, so announcing "RW" first would make every byline in
    the product read twice.
    """
    return {
        "text": initials(name or ""),
        "tone": tone_for(seed),
        "size_class": f" avatar-{size}" if size in {"sm", "lg"} else "",
    }
