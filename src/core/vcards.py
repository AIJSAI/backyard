"""vCard export for the family directory (S-904).

The point of the story is mundane and real: the family's numbers in everyone's phone are
five years stale, and nobody is going to retype twenty contacts. So the directory can be
downloaded — one person, or everyone you can see — as a `.vcf` a phone will import.

**This module never sees a Member.** It serializes `profiles.ViewableProfile`, which is
already reduced to exactly what one viewer may see. That is the whole visibility design:
a HIDDEN phone number cannot be omitted-by-mistake here, because it was never in the
object. There is one resolver (`profiles.viewable_profile`) feeding both the HTML
directory and this file, so per-field visibility cannot drift into a second
implementation (TM-2's shape, applied to a second output format; threat row T-YARD-10).

Two format decisions worth stating, because both were choices between imperfect options:

* **vCard 3.0**, not 4.0. 4.0 is the current standard (RFC 6350) but phone support for it
  is uneven, and a card that does not import is worth nothing. 3.0 is what iOS, Android
  and Google Contacts all read.
* **A birthday is written yearless** (`BDAY:--0305`). The product's rule is that a year and
  an age are never shown, and Apple's usual trick for a yearless birthday is a sentinel
  year (`1604`) that any client not in on the convention displays as a real birth year —
  inventing a false fact about a family member. The truncated form fails the other way: a
  client that cannot parse it drops the property. Omission over fabrication.

Escaping is not cosmetic here. A vCard is a line-oriented format whose values are
delimited by `;` and `,`, so an unescaped newline in someone's address does not corrupt
one field, it **injects a property line** — a display name of `Ann\\r\\nTEL:+15550000000`
would otherwise write a working phone number into the card of every viewer who can see
her. Every value goes through `_escape`.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from .profiles import MONTH_NUMBER, ViewableProfile

CONTENT_TYPE = "text/vcard; charset=utf-8"

_PRODID = "-//Backyard//vCard 3.0//EN"

# RFC 6350 §3.2: a content line SHOULD be folded to 75 octets, excluding the CRLF. A
# continuation line spends one of those octets on its leading space.
_FOLD_OCTETS = 75

_LINE_BREAK = "\r\n"

# The label every card carries, so twenty contacts that arrived together can be found —
# or removed — as a group later, instead of being untraceable once they are in a phone.
_CATEGORY = "Backyard family"


def _escape(value: str) -> str:
    """Escape a text value per RFC 6350 §3.4, backslash first so the escapes we add are
    not re-escaped. Newlines become the literal two-character `\\n`, which is what makes
    this the injection guard rather than a formatting nicety.

    C0 control characters are dropped — **except TAB**, which RFC 6350 §3.3 admits in a text
    value along with printable characters. The others are not valid there, and a stray one
    from a paste turns a card into an unparseable file rather than a wrong one. (The earlier
    wording said C0 was dropped without naming the tab exception; tab is 0x09, so the
    sentence described behaviour this function does not have.)
    """
    out = value.replace("\\", "\\\\")
    out = out.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    out = out.replace(";", "\\;").replace(",", "\\,")
    return "".join(ch for ch in out if ch == "\t" or ord(ch) >= 0x20)


def _fold(line: str) -> str:
    """Fold one content line to `_FOLD_OCTETS` octets, continuations prefixed with a
    space. Folding happens on character boundaries, never inside a UTF-8 sequence: the
    spec counts octets, but a parser handed half a codepoint is a mojibake bug waiting
    for the first non-ASCII family name.
    """
    parts: list[str] = []
    current: list[str] = []
    octets = 0
    limit = _FOLD_OCTETS
    for char in line:
        size = len(char.encode("utf-8"))
        if octets + size > limit:
            parts.append("".join(current))
            current, octets, limit = [], 0, _FOLD_OCTETS - 1
        current.append(char)
        octets += size
    parts.append("".join(current))
    return f"{_LINE_BREAK} ".join(parts)


def _structured_name(display_name: str) -> str:
    """The `N` value: family;given;additional;prefix;suffix.

    Backyard stores one name string, because that is how a family writes a name down.
    Phones sort and group on `N`, so putting the whole string in a single slot makes the
    directory sort under the wrong letter — the last whitespace-separated token becomes
    the family name, the rest the given name. That is the same guess Google Contacts
    makes on import, right for almost every name in this family and mildly wrong for a
    multi-token surname; `FN` still carries the name exactly as the family wrote it, and
    that is what a phone displays.
    """
    parts = display_name.split()
    if len(parts) < 2:
        return f"{_escape(display_name)};;;;"
    return f"{_escape(parts[-1])};{_escape(' '.join(parts[:-1]))};;;"


def _uid_host() -> str:
    """The host component of BASE_URL, so a UID is unique to this instance. Falls back to
    a fixed label rather than raising: a misconfigured BASE_URL must not be the reason a
    download fails."""
    return urlsplit(settings.BASE_URL).hostname or "backyard.invalid"


def _yearless(date_text: str) -> str:
    """`--MMDD` for a "March 5", or empty. The input is already the year-free rendering
    the viewer is allowed to see, so this only reformats — there is no year here to leak
    even if a caller wanted one.

    Deliberately not `strptime("%B %d")`: with no year in the format, Python supplies 1900,
    which is not a leap year, so **"February 29" raised and the birthday silently vanished
    from the card** — for the one member most likely to notice a missing birthday. Looking
    the month up needs no year at all.
    """
    month_name, _, day = date_text.partition(" ")
    month = MONTH_NUMBER.get(month_name)
    if month is None or not day.isdigit() or not 1 <= int(day) <= 31:
        return ""
    return f"--{month:02d}{int(day):02d}"


def _card_lines(profile: ViewableProfile, *, host: str, revised: str) -> list[str]:
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"PRODID:{_PRODID}",
        f"N:{_structured_name(profile.display_name)}",
        f"FN:{_escape(profile.display_name)}",
    ]
    if profile.kinship_name:
        # A kinship name is exactly what a phone means by a nickname, so searching a
        # phone for "Nana" finds her. It is also the one field that makes an imported
        # card recognisably family rather than a stranger with a surname in common.
        lines.append(f"NICKNAME:{_escape(profile.kinship_name)}")
    for contact in profile.contacts:
        if contact.kind == "phone":
            lines.append(f"TEL;TYPE=CELL,VOICE:{_escape(contact.value)}")
        elif contact.kind == "email":
            lines.append(f"EMAIL;TYPE=INTERNET:{_escape(contact.value)}")
        elif contact.kind == "address":
            # A single free-text address into a seven-component structured value: the
            # whole string goes in the street slot, and LABEL carries it as the
            # human-readable form 3.0 provides for exactly this case. Escaping matters
            # most here — real addresses contain the commas and newlines that would
            # otherwise split the components.
            lines.append(f"ADR;TYPE=HOME:;;{_escape(contact.value)};;;;")
            lines.append(f"LABEL;TYPE=HOME:{_escape(contact.value)}")
    birthday = _yearless(profile.birthday)
    if birthday:
        lines.append(f"BDAY:{birthday}")
    if profile.anniversary:
        # 3.0 has no anniversary property (`ANNIVERSARY` is 4.0, and the 3.0 workaround
        # is a vendor extension no other client reads), so it goes where every client
        # will show it rather than nowhere.
        lines.append(f"NOTE:Anniversary: {_escape(profile.anniversary)}")
    lines.append(f"CATEGORIES:{_escape(_CATEGORY)}")
    lines.append(f"UID:backyard-{profile.member_id}@{host}")
    lines.append(f"REV:{revised}")
    lines.append("END:VCARD")
    return lines


def render(viewable: Iterable[ViewableProfile], *, now: datetime.datetime | None = None) -> str:
    """One `.vcf` body for these profiles, CRLF-terminated as the format requires.

    Takes an iterable so the whole-directory download does not need every card in a list
    first, and takes `ViewableProfile` rather than members so there is no code path here
    that could reach an unscoped field.

    `now` must be timezone-aware. A naive value does NOT raise on `.astimezone()` — Python
    reads it as system local time and converts, which measured as a **five-hour shift in the
    REV stamp with no error at all** on a UTC-5 machine. Refusing it is better than guessing
    UTC on the caller's behalf, which is the same silent guess wearing a different coat.
    `timezone.now()` is aware, so nothing in the app is affected.
    """
    if now is not None and (now.tzinfo is None or now.tzinfo.utcoffset(now) is None):
        raise ValueError("vcards.render needs an aware `now`; a naive one silently shifts REV")
    stamp = (now or timezone.now()).astimezone(datetime.UTC)
    revised = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    host = _uid_host()
    lines: list[str] = []
    for profile in viewable:
        lines.extend(_fold(line) for line in _card_lines(profile, host=host, revised=revised))
    return "".join(f"{line}{_LINE_BREAK}" for line in lines)
