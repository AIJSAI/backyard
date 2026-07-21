"""Profile editing and the family directory (S-901, S-902).

The directory only lists members the viewer shares a yard with (scoping.visible_
members), so it never leaks across a yard boundary, and a single-member profile
resolves through require_visible_member (a cross-yard member is a byte-identical
404). Each contact field is shown only to a viewer the owner scoped it for; a member
edits their own profile and chooses, per field, exactly who sees it.
"""

from __future__ import annotations

import tempfile

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from . import export, profiles, scoping
from .feed_views import _acting_member
from .models import Member

_VISIBILITY = {Member.HIDDEN, Member.POD, Member.YARD}


def _visibility(value: str | None) -> str:
    """A submitted visibility, or HIDDEN if missing/unknown (fail closed to no one)."""
    return value if value in _VISIBILITY else Member.HIDDEN


def _int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def directory(request: HttpRequest) -> HttpResponse:
    """The family directory, searchable within the viewer's yards (S-902)."""
    member = _acting_member(request)
    query = request.GET.get("q", "").strip()
    members = scoping.visible_members(member).exclude(id=member.id)
    if query:
        members = members.filter(display_name__icontains=query)
    viewer_pod_ids = scoping.member_pod_ids(member)  # computed once, not per row (MEDIUM-2)
    rows = [
        profiles.viewable_profile(member, other, viewer_pod_ids=viewer_pod_ids)
        for other in members[:200]
    ]
    return render(request, "core/directory.html", {"member": member, "profiles": rows, "q": query})


@login_required
def member_profile(request: HttpRequest, member_id: int) -> HttpResponse:
    """One member's profile, as this viewer may see it. Cross-yard is a 404 (S-902)."""
    viewer = _acting_member(request)
    target = scoping.require_visible_member(viewer, member_id)
    return render(
        request,
        "core/member_profile.html",
        {"member": viewer, "profile": profiles.viewable_profile(viewer, target)},
    )


@login_required
def profile_edit(request: HttpRequest) -> HttpResponse:
    """Edit one's own profile (S-901): kinship name, birthday (month and day required
    together, year optional), and each contact field with its own visibility."""
    member = _acting_member(request)
    if request.method != "POST":
        return render(request, "core/profile_edit.html", _edit_context(member, []))

    errors: list[str] = []
    dates: dict[str, int | None] = {}
    for kind in ("birthday", "anniversary"):
        month = _int_or_none(request.POST.get(f"{kind}_month"))
        day = _int_or_none(request.POST.get(f"{kind}_day"))
        year = _int_or_none(request.POST.get(f"{kind}_year"))
        if bool(month) != bool(day):
            errors.append(f"A {kind} needs both a month and a day.")
        if month is not None and not 1 <= month <= 12:
            errors.append("That is not a real month.")
        if day is not None and not 1 <= day <= 31:
            errors.append("That is not a real day.")
        dates[f"{kind}_month"], dates[f"{kind}_day"], dates[f"{kind}_year"] = month, day, year
    if errors:
        return render(request, "core/profile_edit.html", _edit_context(member, errors))

    member.kinship_name = request.POST.get("kinship_name", "").strip()[:50]
    member.birthday_month = dates["birthday_month"]
    member.birthday_day = dates["birthday_day"]
    member.birthday_year = dates["birthday_year"]
    member.birthday_visibility = _visibility(request.POST.get("birthday_visibility"))
    member.anniversary_month = dates["anniversary_month"]
    member.anniversary_day = dates["anniversary_day"]
    member.anniversary_year = dates["anniversary_year"]
    member.anniversary_visibility = _visibility(request.POST.get("anniversary_visibility"))
    member.phone = request.POST.get("phone", "").strip()[:40]
    member.phone_visibility = _visibility(request.POST.get("phone_visibility"))
    member.contact_email = request.POST.get("contact_email", "").strip()[:254]
    member.contact_email_visibility = _visibility(request.POST.get("contact_email_visibility"))
    member.address = request.POST.get("address", "").strip()[:255]
    member.address_visibility = _visibility(request.POST.get("address_visibility"))
    member.save(
        update_fields=[
            "kinship_name",
            "birthday_month",
            "birthday_day",
            "birthday_year",
            "birthday_visibility",
            "anniversary_month",
            "anniversary_day",
            "anniversary_year",
            "anniversary_visibility",
            "phone",
            "phone_visibility",
            "contact_email",
            "contact_email_visibility",
            "address",
            "address_visibility",
        ]
    )
    return redirect("directory")


@login_required
def export_data(request: HttpRequest) -> FileResponse:
    """Download a zip of the member's own posts, comments, and photos (S-704). Never
    gated; strictly the acting member's own authored content. The archive is written to
    a temp file that spills to disk past a small threshold and is streamed back, so a
    heavy history cannot hold the whole zip in memory (security review of #32)."""
    member = _acting_member(request)
    archive = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    export.write_member_export(member, archive)
    archive.seek(0)
    response = FileResponse(archive, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="backyard-export.zip"'
    return response


def _edit_context(member: Member, errors: list[str]) -> dict[str, object]:
    return {
        "member": member,
        "errors": errors,
        "visibility_choices": Member.FIELD_VISIBILITY_CHOICES,
    }
