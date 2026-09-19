"""The one way this product prints a date or a time to a person.

Found on the production walk, 2026-09-19: a post written at 4:28 in the morning read
"9:28 a.m." on the family's own feed. `TIME_ZONE` was Django's "UTC" default, so every
timestamp in the product was stated, calmly and without a hedge, in a zone nobody in the
family lives in.

Two halves fix that, and both are needed:

  * The SERVER renders in the instance's own zone (`BACKYARD_TIME_ZONE`). That is the
    zone the household lives in, and it is the only one available to an e-mail, which is
    composed here and read hours later with no browser to correct it.
  * The BROWSER then re-renders the same instant into the reader's own zone. A family
    spread across three zones is the normal case for the thing this product is for, and
    the cousin who moved away should read her own wall clock, not her mother's.

The markup is what carries the second half: `<time datetime="<ISO with offset>">` with
the server's own text inside it. With no JavaScript — a text browser, a locked-down
phone, a feed reader, the e-mail client that will never run a script — the server's text
is what shows, which is why it is rendered fully formed rather than left as an empty
element for a script to fill. That is also why the ISO string carries an explicit UTC
offset: a bare naive string would be read differently by different engines.

The formats are pinned here rather than in each template so the browser half can match
them exactly. `M j, g:i a` and `M j, Y` are Django's; `_localise` in base.html reproduces
them by hand for the same reason.
"""

from __future__ import annotations

import datetime

from django import template
from django.template.defaultfilters import date as date_filter
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.timezone import is_aware, localtime

register = template.Library()

# Django format strings. "M j, g:i a" -> "Sep 18, 4:38 a.m."; "M j, Y" -> "Sep 18, 2026".
DATETIME_FORMAT = "M j, g:i a"
DATE_FORMAT = "M j, Y"


def _element(value: datetime.datetime | datetime.date | None, *, kind: str) -> SafeString:
    """`<time datetime="...">text</time>`, or the empty string for a missing value.

    A `date` (no time of day) is passed through untouched: a birthday has no instant to
    move, and shifting one into a browser's zone is how a birthday lands on the wrong
    day. Only a real `datetime` is localised.
    """
    if value is None:
        return SafeString("")
    fmt = DATETIME_FORMAT if kind == "datetime" else DATE_FORMAT
    if isinstance(value, datetime.datetime):
        local = localtime(value) if is_aware(value) else value
        return format_html(
            '<time datetime="{}" data-when="{}">{}</time>',
            local.isoformat(),
            kind,
            date_filter(local, fmt),
        )
    return format_html('<time datetime="{}">{}</time>', value.isoformat(), date_filter(value, fmt))


@register.simple_tag
def when(value: datetime.datetime | datetime.date | None) -> SafeString:
    """A moment: date and time of day. What a post or a reply is stamped with."""
    return _element(value, kind="datetime")


@register.simple_tag
def when_date(value: datetime.datetime | datetime.date | None) -> SafeString:
    """A day, with no time of day.

    Used where the time would be noise rather than information: an invite's last day, and
    the grandparent's page, which shows dates only on purpose and keeps doing so.
    """
    return _element(value, kind="date")
