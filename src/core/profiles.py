"""Profiles and the family directory (S-901, S-902).

A profile carries the family-terms identity: the kinship name shown beside the legal
name, a birthday as month and day (year optional, age never shown), and optional
contact fields. Each contact field has its own visibility (S-902): no one, people in
my pods, or people in my yards. This module resolves what a given viewer may see of a
given member's profile; the directory only ever lists members the viewer shares a
yard with (scoping.visible_members), and a field the viewer is not scoped for is
simply absent, never blanked-but-present.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import scoping
from .models import Member

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
    contacts: list[ContactField]


def birthday_text(member: Member) -> str:
    """The birthday as month and day, or empty. Never a year, never an age (S-901)."""
    if not member.birthday_month or not member.birthday_day:
        return ""
    if not 1 <= member.birthday_month <= 12:
        return ""
    return f"{_MONTHS[member.birthday_month]} {member.birthday_day}"


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
    return ViewableProfile(
        member_id=member.id,
        display_name=member.display_name,
        kinship_name=member.kinship_name,
        birthday=birthday_text(member),
        contacts=contacts,
    )
