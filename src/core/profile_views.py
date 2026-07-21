"""Profile editing and the family directory (S-901, S-902).

The directory only lists members the viewer shares a yard with (scoping.visible_
members), so it never leaks across a yard boundary, and a single-member profile
resolves through require_visible_member (a cross-yard member is a byte-identical
404). Each contact field is shown only to a viewer the owner scoped it for; a member
edits their own profile and chooses, per field, exactly who sees it.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
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

    month = _int_or_none(request.POST.get("birthday_month"))
    day = _int_or_none(request.POST.get("birthday_day"))
    year = _int_or_none(request.POST.get("birthday_year"))
    errors: list[str] = []
    if bool(month) != bool(day):
        errors.append("A birthday needs both a month and a day.")
    if month is not None and not 1 <= month <= 12:
        errors.append("That is not a real month.")
    if day is not None and not 1 <= day <= 31:
        errors.append("That is not a real day.")
    if errors:
        return render(request, "core/profile_edit.html", _edit_context(member, errors))

    member.kinship_name = request.POST.get("kinship_name", "").strip()[:50]
    member.birthday_month = month
    member.birthday_day = day
    member.birthday_year = year
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
def export_data(request: HttpRequest) -> HttpResponse:
    """Download a zip of the member's own posts, comments, and photos (S-704). Never
    gated; strictly the acting member's own authored content."""
    member = _acting_member(request)
    archive = export.build_member_export(member)
    response = HttpResponse(archive, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="backyard-export.zip"'
    return response


def _edit_context(member: Member, errors: list[str]) -> dict[str, object]:
    return {
        "member": member,
        "errors": errors,
        "visibility_choices": Member.FIELD_VISIBILITY_CHOICES,
    }
