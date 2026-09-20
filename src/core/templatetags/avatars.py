"""The avatar: a member's photo where they have one, their initials disc where they do not.

The design walk's biggest finding was that a product whose whole purpose is family
warmth had no human presence in its chrome at all — the directory was a list of green
underlined links, a profile was three lines on a blank page. The first fix was the
smallest one: two initials on one of six tinted discs. The photograph is the second, and
the disc is now the FALLBACK rather than the only state — same circle, same sizes, same
places, so nothing moves when a member adds or removes one.

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
from django.urls import reverse

from ..media import AVATAR_FULL_PX, AVATAR_SMALL_PX

register = template.Library()

# Six is enough variety for a family and few enough to stay calm on a directory page.
# Kept in step with the --tone-N-* token pairs in core/templates/core/base.html and with
# _TONES in core/tests/test_avatars.py.
TONE_COUNT = 6


def initials(name: str) -> str:
    """One or two letters from a display name, for the disc.

    First and last word, because that is how a family reads a name ("Rose Whitfield" ->
    RW). A single word gives one letter rather than two from the same word: "RO" reads as
    a truncation, "R" reads as a monogram.

    The fallback is narrow on purpose: ONLY a name that is empty or entirely whitespace
    gives the bullet, because that is the only input with no character to show. Anything
    else keeps its own first character — a script with no case (`.upper()` is a no-op
    there) or an emoji renders as itself, which is still that person's mark and is better
    than a bullet standing in for a name the product does have.
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
def avatar(
    name: str, seed: object, size: str = "", photo: tuple[str, str] | None = None
) -> dict[str, object]:
    """Render one person's avatar. `size` is "" (default), "sm" (a reply) or "lg" (a profile).

    `photo` is the member's `avatar_tokens` — (large, small) — or None. The caller passes
    the tokens rather than a row so that nothing with a path back to a raw Member reaches
    a template (the rule `profiles.ViewableProfile` already keeps), and so a surface that
    draws a hundred bylines can load them in its own select_related rather than here.

    The SIZE picks the rendition: only the profile page's `lg` disc needs the 128px
    square, everything else takes the 96px one, which is the whole reason two are stored.

    `aria-hidden` lives in the partial, for the photo exactly as for the disc: the name it
    stands for is always rendered as text immediately beside it, so announcing the
    monogram — or "photo of" — would make every byline in the product read twice.
    """
    is_large = size == "lg"
    return {
        "text": initials(name or ""),
        "tone": tone_for(seed),
        "size_class": f" avatar-{size}" if size in {"sm", "lg"} else "",
        "photo_url": (
            reverse("serve_profile_photo", args=[photo[0] if is_large else photo[1]])
            if photo
            else ""
        ),
        # The rendition's own pixels, on the img element, so the circle has its intrinsic
        # size and aspect ratio before any stylesheet loads and nothing on the page moves
        # when the bytes arrive. CSS still decides how big it draws.
        "photo_px": AVATAR_FULL_PX if is_large else AVATAR_SMALL_PX,
    }
