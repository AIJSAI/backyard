"""Profiles and the family directory (S-901, S-902), and family dates (S-903).

A profile carries the family-terms identity: the kinship name shown beside the legal
name, a birthday and an anniversary as month and day (year optional, age never
shown), and optional contact fields. Every one of these fields has its own
visibility (S-902, S-903): no one, people in my pods, or people in my yards — dates
included, so a birthday is never auto-broadcast. This module resolves what a given
viewer may see of a given member's profile; the directory only ever lists members
the viewer shares a yard with (scoping.visible_members), and a field the viewer is
not scoped for is simply absent, never blanked-but-present.

upcoming_dates is the one date resolver: the feed's quiet on-the-day banner and the
digest's upcoming-dates section both consume it, so date visibility has exactly one
enforcement point, the same shape as scoping's one audience query (TM-2).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from . import scoping
from .models import Member, Yard

_MONTHS = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass
class ContactField:
    label: str
    value: str


@dataclass
class ViewableProfile:
    """A profile reduced to exactly what the viewer may see. It carries safe
    primitives, never the raw Member (security review LOW-1), so a HIDDEN field or
    the birthday year cannot leak through a future template accessing profile.member.
    """

    member_id: int
    display_name: str
    kinship_name: str
    birthday: str  # "March 5" or ""; never a year, never an age
    anniversary: str  # same contract as birthday
    contacts: list[ContactField]


def _date_text(month: int | None, day: int | None) -> str:
    """A month-and-day rendering, or empty. Never a year, never an age (S-901)."""
    if not month or not day:
        return ""
    if not 1 <= month <= 12:
        return ""
    return f"{_MONTHS[month]} {day}"


def birthday_text(member: Member) -> str:
    """The birthday as month and day, or empty. Never a year, never an age (S-901)."""
    return _date_text(member.birthday_month, member.birthday_day)


def anniversary_text(member: Member) -> str:
    """The anniversary, same month-and-day-only contract as the birthday (S-903)."""
    return _date_text(member.anniversary_month, member.anniversary_day)


def _can_see_field(
    viewer: Member, member: Member, visibility: str, viewer_pod_ids: set[int]
) -> bool:
    """Whether the viewer may see a field with this visibility. A member always sees
    their own fields; YARD is the directory scope (a shared yard is already implied);
    POD needs a shared pod; HIDDEN is never."""
    if viewer.id == member.id:
        return True
    if visibility == Member.YARD:
        return True
    if visibility == Member.POD:
        return bool(viewer_pod_ids & scoping.member_pod_ids(member))
    return False


def viewable_profile(
    viewer: Member, member: Member, *, viewer_pod_ids: set[int] | None = None
) -> ViewableProfile:
    """The member's profile as this viewer may see it: only the contact fields the
    viewer is scoped for, each present only if it has a value. The caller may pass the
    viewer's pod-id set (computed once) to avoid recomputing it per row in a directory
    render (security review MEDIUM-2)."""
    if viewer_pod_ids is None:
        viewer_pod_ids = scoping.member_pod_ids(viewer)
    fields = [
        (member.phone, member.phone_visibility, "Phone"),
        (member.contact_email, member.contact_email_visibility, "Email"),
        (member.address, member.address_visibility, "Address"),
    ]
    contacts = [
        ContactField(label=label, value=value)
        for value, visibility, label in fields
        if value and _can_see_field(viewer, member, visibility, viewer_pod_ids)
    ]
    # Dates are gated exactly like contact fields (S-903): a date the viewer is not
    # scoped for is absent, never blanked-but-present. Before this gate the birthday
    # rendered to every directory viewer unconditionally.
    birthday = (
        birthday_text(member)
        if _can_see_field(viewer, member, member.birthday_visibility, viewer_pod_ids)
        else ""
    )
    anniversary = (
        anniversary_text(member)
        if _can_see_field(viewer, member, member.anniversary_visibility, viewer_pod_ids)
        else ""
    )
    return ViewableProfile(
        member_id=member.id,
        display_name=member.display_name,
        kinship_name=member.kinship_name,
        birthday=birthday,
        anniversary=anniversary,
        contacts=contacts,
    )


@dataclass
class UpcomingDate:
    """One family date as one viewer may see it: who, which kind, and when — as
    month and day text only, never a year, never an age."""

    member_id: int
    display_name: str
    kinship_name: str
    kind: str  # "birthday" or "anniversary"
    on: datetime.date  # the concrete occurrence within the asked window
    date_text: str  # "March 5"


def upcoming_dates(
    viewer: Member, *, start: datetime.date, days: int, within_yard: Yard | None = None
) -> list[UpcomingDate]:
    """Birthdays and anniversaries falling in [start, start + days), among members
    the viewer shares a yard with, honoring each date's own visibility (S-903).

    This is the single date resolver: the feed banner asks for one day, the digest
    section for seven. Occurrences come from the real calendar, so a February 29
    date appears only in leap years and a window crossing New Year still works.

    `within_yard` narrows the candidates to members of one yard: a per-yard digest
    must never carry the other side's dates for a bridge recipient (S-501's
    no-fusion rule). It only ever narrows — the base set is still visible_members,
    so this stays the one enforcement point rather than a second path.

    The window is capped at a year (security review of #33 LOW-2): past 366 days
    every (month, day) recurs, so a larger ask is a caller bug, and the one
    enforcement point should own its own DoS bound.
    """
    if not 0 <= days <= 366:
        raise ValueError("upcoming_dates windows are at most a year")
    window: dict[tuple[int, int], datetime.date] = {}
    for offset in range(days):
        day = start + datetime.timedelta(days=offset)
        window[(day.month, day.day)] = day

    viewer_pod_ids = scoping.member_pod_ids(viewer)
    candidates = scoping.visible_members(viewer).exclude(
        birthday_month__isnull=True, anniversary_month__isnull=True
    )
    if within_yard is not None:
        candidates = candidates.filter(pods__yards=within_yard).distinct()
    found: list[UpcomingDate] = []
    for member in candidates:
        dated = [
            (
                "birthday",
                member.birthday_month,
                member.birthday_day,
                member.birthday_visibility,
            ),
            (
                "anniversary",
                member.anniversary_month,
                member.anniversary_day,
                member.anniversary_visibility,
            ),
        ]
        for kind, month, day_of_month, visibility in dated:
            if not month or not day_of_month:
                continue
            occurrence = window.get((month, day_of_month))
            if occurrence is None:
                continue
            if not _can_see_field(viewer, member, visibility, viewer_pod_ids):
                continue
            found.append(
                UpcomingDate(
                    member_id=member.id,
                    display_name=member.display_name,
                    kinship_name=member.kinship_name,
                    kind=kind,
                    on=occurrence,
                    date_text=_date_text(month, day_of_month),
                )
            )
    found.sort(key=lambda d: (d.on, d.display_name, d.kind))
    return found
