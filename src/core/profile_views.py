"""Profile editing and the family directory (S-901, S-902).

The directory only lists members the viewer shares a yard with (scoping.visible_
members), so it never leaks across a yard boundary, and a single-member profile
resolves through require_visible_member (a cross-yard member is a byte-identical
404). Each contact field is shown only to a viewer the owner scoped it for; a member
edits their own profile and chooses, per field, exactly who sees it.
"""

from __future__ import annotations

import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from . import export, invites, permissions, profiles, scoping, vcards
from .feed_views import _acting_member
from .models import Member, Pod, Yard

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


def _may_edit_contact_fields(actor: Member, member: Member) -> bool:
    """Whose phone, email and address this form may SHOW and change.

    BY-11 widened `can_edit_profile_of` to any admin who may manage the target, so a yard
    admin can fix a name typed wrong at invite time and fill in a grandparent's birthday.
    It must not also hand every yard admin a plaintext read of the contact fields: this
    form renders the raw `Member` row, not `profiles.viewable_profile`, so a phone number
    its owner scoped to `No one` appears in a text input — and the visibility select beside
    it would let an admin publish an address to a whole side of the family with nothing
    telling its owner. Showing a field here is the same disclosure as changing it.

    So the contact half keeps the set `can_edit_profile_of` had before BY-11: yourself, a
    supervised child's managing parent, and the instance admin. Name, kinship name and the
    two dates -- the fields BY-11's evidence was actually about -- stay widened.
    """
    return (
        actor.pk == member.pk
        or (member.is_supervised and member.managing_parent_id == actor.pk)
        or permissions.is_instance_admin(actor)
    )


@login_required
def directory(request: HttpRequest) -> HttpResponse:
    """The family directory, searchable within the viewer's yards (S-902)."""
    member = _acting_member(request)
    query = request.GET.get("q", "").strip()
    members = scoping.visible_members(member).exclude(id=member.id)
    if query:
        members = members.filter(display_name__icontains=query)
    viewer_pod_ids = scoping.member_pod_ids(member)  # computed once, not per row (MEDIUM-2)
    # The household and side each row names, prefetched in two queries rather than the two
    # per row that calling scoping.visible_pods_of / visible_yards_of_pod directly would
    # cost. Both filters are the viewer's own yard set, so what comes back is exactly what
    # those two scoped helpers would have returned — never a bridge member's far side.
    viewer_yard_ids = scoping.member_yard_ids(member)
    members = members.prefetch_related(
        Prefetch(
            "pods",
            queryset=Pod.objects.filter(yards__id__in=viewer_yard_ids)
            .distinct()
            .prefetch_related(
                Prefetch(
                    "yards",
                    queryset=Yard.objects.filter(id__in=viewer_yard_ids),
                    to_attr="shared_yards",
                )
            ),
            to_attr="shared_pods",
        )
    )
    rows = [
        profiles.viewable_profile(
            member,
            other,
            viewer_pod_ids=viewer_pod_ids,
            placing=profiles.placing_text(member, other, shared_pods=other.shared_pods),
        )
        for other in members[:200]
    ]
    return render(
        request,
        "core/directory.html",
        {
            "member": member,
            "profiles": rows,
            "q": query,
            # BY-13: whose job inviting is. It used to be a loose paragraph on the FEED,
            # on every visit forever, which is neither where somebody wonders about it nor
            # a thing that changes. This is the page you open when you are thinking about
            # who is here, so the answer to "how do I add somebody" belongs on it. An
            # admin is the somebody else, so they are not told to go and ask one.
            "show_invite_help": not permissions.is_admin(member),
            "inviter": None if permissions.is_admin(member) else invites.inviter_of(member),
        },
    )


# What a profile page shows of somebody's writing: enough to prove there is a person
# behind the name, few enough that the page is still a profile and not a second feed.
_PROFILE_POSTS = 3


@login_required
def member_profile(request: HttpRequest, member_id: int) -> HttpResponse:
    """One member's profile, as this viewer may see it. Cross-yard is a 404 (S-902)."""
    viewer = _acting_member(request)
    target = scoping.require_visible_member(viewer, member_id)
    # Their recent posts, through the SAME audience query the feed uses — so a post the
    # viewer could not see on the feed is not reachable through the directory either. A
    # profile that was three lines on a blank page is a dead end; a person's own words are
    # the one thing that makes it not one.
    recent_posts = list(
        scoping.visible_posts(viewer)
        .filter(author=target)
        .order_by("-created_at", "-id")[:_PROFILE_POSTS]
    )
    return render(
        request,
        "core/member_profile.html",
        {
            "member": viewer,
            "profile": profiles.viewable_profile(
                viewer, target, placing=profiles.placing_text(viewer, target)
            ),
            "recent_posts": recent_posts,
        },
    )


def _vcard_response(body: str, filename: str) -> HttpResponse:
    """A `.vcf` download. The filename is slugified, never the raw display name: a name
    is member-controlled text and this value lands in a response header."""
    response = HttpResponse(body, content_type=vcards.CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}.vcf"'
    return response


@login_required
def member_vcard(request: HttpRequest, member_id: int) -> HttpResponse:
    """One member's contact card (S-904). Resolved through the same guard as their
    profile page, so a cross-yard member is the same byte-identical 404 — the download
    is not a second route into the directory."""
    viewer = _acting_member(request)
    target = scoping.require_visible_member(viewer, member_id)
    profile = profiles.viewable_profile(viewer, target)
    return _vcard_response(
        vcards.render([profile]),
        slugify(profile.display_name) or f"member-{profile.member_id}",
    )


@login_required
def directory_vcards(request: HttpRequest) -> HttpResponse:
    """Everyone the viewer can see, as one `.vcf` (S-904).

    Deliberately the whole visible directory and not the current search result: a button
    that silently exports a filtered subset is how someone ends up believing they have
    the family's numbers when they have four of them. It is also uncapped, unlike the
    directory page's 200-row render — a truncated address book is the same lie.
    """
    viewer = _acting_member(request)
    members = scoping.visible_members(viewer).exclude(id=viewer.id).order_by("display_name", "id")
    viewer_pod_ids = scoping.member_pod_ids(viewer)  # once, not per row (MEDIUM-2)
    body = vcards.render(
        profiles.viewable_profile(viewer, other, viewer_pod_ids=viewer_pod_ids)
        for other in members.iterator()
    )
    return _vcard_response(body, "backyard-family")


@login_required
def profile_edit(request: HttpRequest, member_id: int | None = None) -> HttpResponse:
    """Edit a profile (S-901): name, kinship name, birthday (month and day required
    together, year optional), and each contact field with its own visibility.

    Without `member_id` this is your own profile. With one it is somebody you may edit on
    behalf of — a supervised child's managing parent, or an instance admin standing in for
    an elder, who has no login of her own by design (TM-10). That second path is S-901's
    third acceptance criterion, and it did not exist.
    """
    actor = _acting_member(request)
    if member_id is None:
        member = actor
    else:
        # Resolved through the ADMINISTRABLE set, which is what `can_edit_profile_of` is
        # ultimately asking about, so the roster's `Edit profile` link and this route
        # answer the same question. It used to resolve through the READ guard
        # (scoping.require_visible_member), and BY-11's widening made the two disagree: the
        # instance admin owns the whole instance and sits above yard isolation — the threat
        # model says so in as many words, isolation is a member-level promise and not an
        # admin-level one, and the role's own description is "Manages anyone, on either
        # side" — so the roster offered them the link for a member on a side they are not
        # in, and the click 404d. Crossing sides is a deliberate act for that one role,
        # which is why removal, re-roling and the recovery link already resolve here.
        #
        # For everybody else the set IS the yard-scoped visible set, so a plain member and
        # a yard admin still get the byte-identical 404 across a boundary (S-202/S-902),
        # rather than a permission error that would confirm the person exists.
        member = get_object_or_404(permissions.administrable_members(actor), pk=member_id)
        if not permissions.can_edit_profile_of(actor, member):
            raise PermissionDenied("You cannot edit this person's profile.")
    if request.method != "POST":
        return render(request, "core/profile_edit.html", _edit_context(member, [], actor))

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
        # Range-check the year too (security review of #33 LOW-1): an out-of-range
        # value would blow past the smallint column as a 500 instead of a message.
        if year is not None and not 1 <= year <= 9999:
            errors.append("That is not a real year.")
        dates[f"{kind}_month"], dates[f"{kind}_day"], dates[f"{kind}_year"] = month, day, year
    # A name is how a family recognises someone; an empty one is never what was meant.
    display_name = request.POST.get("display_name", "").strip()[:100]
    if not display_name:
        errors.append("A name cannot be empty.")

    if errors:
        return render(request, "core/profile_edit.html", _edit_context(member, errors, actor))

    member.display_name = display_name
    member.kinship_name = request.POST.get("kinship_name", "").strip()[:50]
    member.birthday_month = dates["birthday_month"]
    member.birthday_day = dates["birthday_day"]
    member.birthday_year = dates["birthday_year"]
    member.birthday_visibility = _visibility(request.POST.get("birthday_visibility"))
    member.anniversary_month = dates["anniversary_month"]
    member.anniversary_day = dates["anniversary_day"]
    member.anniversary_year = dates["anniversary_year"]
    member.anniversary_visibility = _visibility(request.POST.get("anniversary_visibility"))
    updated = [
        "display_name",
        "kinship_name",
        "birthday_month",
        "birthday_day",
        "birthday_year",
        "birthday_visibility",
        "anniversary_month",
        "anniversary_day",
        "anniversary_year",
        "anniversary_visibility",
    ]
    # The contact half only for somebody entitled to READ it. Not an `if` in the template
    # alone: a hand-written POST must not set a field the page would not show.
    if _may_edit_contact_fields(actor, member):
        member.phone = request.POST.get("phone", "").strip()[:40]
        member.phone_visibility = _visibility(request.POST.get("phone_visibility"))
        member.contact_email = request.POST.get("contact_email", "").strip()[:254]
        member.contact_email_visibility = _visibility(request.POST.get("contact_email_visibility"))
        member.address = request.POST.get("address", "").strip()[:255]
        member.address_visibility = _visibility(request.POST.get("address_visibility"))
        updated += [
            "phone",
            "phone_visibility",
            "contact_email",
            "contact_email_visibility",
            "address",
            "address_visibility",
        ]
    member.save(update_fields=updated)
    # Saving landed on the directory with nothing said (walk item 27). The member's own
    # card is somewhere down a list of everyone, so on a phone the screen simply changed
    # and the only honest reading was "did that save?". Same calm flash the composer uses.
    # Named, because an admin can be here editing SOMEBODY ELSE's profile and "Saved."
    # alone would not say whose.
    messages.success(
        request,
        "Saved." if member.pk == actor.pk else f"Saved {member.display_name}'s profile.",
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


def _edit_context(member: Member, errors: list[str], actor: Member) -> dict[str, object]:
    return {
        "member": member,
        # The signed-in member, kept separate from the profile being edited so the page
        # can say whose profile this is when they are not the same person.
        "actor": actor,
        "editing_other": member.pk != actor.pk,
        # Whether to render the contact half at all. A yard admin who may fix a name is
        # not entitled to READ a phone number its owner scoped to no one (BY-11).
        "show_contact_fields": _may_edit_contact_fields(actor, member),
        "errors": errors,
        "visibility_choices": Member.FIELD_VISIBILITY_CHOICES,
        # A parent creating their OWN child's account.
        #
        # `can_create_supervised` has always permitted this — `actor.pk == parent.pk` is its
        # first branch — but the only control in the product sat on `/members/`, which is
        # `is_admin` only. Measured: the permission returns True, the roster returns 403, and
        # a hand-written POST succeeds. The capability was built, authorized and unreachable
        # by the person it was written for, so every child account had to go through an
        # admin.
        #
        # Offered here only for your own profile, and only for households you are actually
        # in — the same pair of conditions the service now enforces.
        "can_add_own_child": (
            not member.is_supervised
            and member.pk == actor.pk
            and permissions.can_create_supervised(actor, actor)
        ),
        # HOUSEHOLDS, because that is what the control says. `member.pods` includes ad-hoc
        # groups, so the copy would have promised a narrower list than the select offered —
        # the same mislabel already fixed once on the roster.
        "own_pods": (
            member.pods.filter(kind=Pod.HOUSEHOLD).order_by("name") if member.pk == actor.pk else []
        ),
    }
