"""Boot-time validation of the instance's time zone.

Every timestamp this product shows was rendered in UTC, because `TIME_ZONE` was the
Django default and nothing offered to change it. A post written at 4:28 in the morning
Central read "9:28 a.m." on the family's own feed — a wrong fact, stated calmly, on the
one screen a relative is most likely to trust.

The zone is an operator setting (`BACKYARD_TIME_ZONE`), not a member one: it is the
instance's own clock, the one e-mail is written in, because an e-mail is composed on the
server and read hours later with no browser to correct it. What a signed-in relative sees
on a *page* is then localised in their own browser on top of this, so a cousin two zones
over reads their own wall clock.

It is validated here rather than in settings.py for the same reason `email_guard` and
`base_url_guard` are: the rule stays a plain function the suite can exercise directly,
and a typo fails the boot with a sentence an operator can act on instead of Django's
"ValueError: Incorrect timezone setting" from somewhere inside the first template render.
"""

from __future__ import annotations

import zoneinfo

# The variable an operator sets. Named here so the error message and the documentation
# cannot drift apart from the settings module that reads it.
ENV_VAR = "BACKYARD_TIME_ZONE"
DEFAULT = "UTC"


def validate_time_zone(name: str) -> str:
    """Return `name` if it is an IANA zone this machine knows, or refuse to boot.

    Empty means the operator left it unset, which is the documented default rather than
    a mistake, so it resolves to UTC instead of failing.
    """
    candidate = name.strip() or DEFAULT
    try:
        zoneinfo.ZoneInfo(candidate)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            f"{ENV_VAR}={candidate!r} is not a time zone this machine knows. "
            "Use an IANA name such as America/Chicago, Europe/London or UTC "
            '(the full list is `python -c "import zoneinfo; '
            'print(sorted(zoneinfo.available_timezones()))"`). '
            "Every date and time the family reads, and every e-mail this instance "
            "sends, is written in this zone. See docs/runbooks/self-host.md."
        ) from exc
    return candidate
