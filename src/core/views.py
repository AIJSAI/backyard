"""Views for the Backyard hello-world scaffold.

This is the walking skeleton of S-801's first-run wizard and the TM-8 gate: the
setup flow exists only while no admin exists, and it is protected by a one-time
secret printed to the server console.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model, login
from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify

from .models import Member, Pod, PodMembership, SetupToken, Yard

if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserModel

User = get_user_model()
_username_validator = UnicodeUsernameValidator()


class _SetupClosed(Exception):
    """Raised when the wizard's gate closed between the request starting and committing."""


def _admin_exists() -> bool:
    return User.objects.filter(is_superuser=True).exists()


def _validate_username(username: str) -> str | None:
    if not username:
        return "Pick a username for the first admin."
    if len(username) > 150:
        return "That username is too long (max 150 characters)."
    try:
        _username_validator(username)
    except ValidationError:
        return "That username has characters that are not allowed. Use letters, numbers, and @ . + - _ only."  # noqa: E501
    return None


def _unique_yard_slug(name: str) -> str:
    """A URL-safe, unique slug for the first yard. Falls back to a generic base if
    the name slugifies to nothing (all punctuation), and disambiguates collisions."""
    base = slugify(name) or "yard"
    slug = base
    n = 2
    while Yard.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _try_create_admin(
    username: str,
    password: str,
    secret: str,
    *,
    display_name: str,
    yard_name: str,
    pod_name: str,
) -> UserModel | None:
    """Create the first admin, first yard, and first pod atomically (S-801), or
    return None if the secret is wrong.

    The whole thing runs in one transaction with the token row locked, and the
    "no admin yet" gate is re-checked under that lock. Two concurrent POSTs that
    both passed the early check cannot both create an admin: the second one blocks
    on the lock, then sees the admin already exists and raises _SetupClosed. This
    makes TM-8's "disabled the moment an admin exists" atomic, not best-effort, and
    it means the yard, pod, and admin-membership either all land or none do.
    """
    with transaction.atomic():
        locked = SetupToken.objects.select_for_update().order_by("id").first()
        if _admin_exists():
            raise _SetupClosed
        if locked is None or not check_password(secret, locked.token_hash):
            return None
        admin = User.objects.create_superuser(username=username, password=password)
        yard = Yard.objects.create(name=yard_name, slug=_unique_yard_slug(yard_name))
        pod = Pod.objects.create(name=pod_name)
        pod.yards.set([yard])
        member = Member.objects.create(
            display_name=display_name, user=admin, role=Member.INSTANCE_ADMIN
        )
        PodMembership.objects.create(member=member, pod=pod)
        SetupToken.objects.all().delete()
        return admin


def home(request: HttpRequest) -> HttpResponse:
    """The instance's front door. Until an admin exists, it routes to setup. A
    signed-in member goes straight to their feed (their landing surface, S-101), so
    the root is never a dead-end hello-world for someone with an account; only a
    logged-out visitor to a set-up instance sees the public landing."""
    if not _admin_exists():
        return redirect("setup")
    if request.user.is_authenticated and Member.objects.filter(user_id=request.user.pk).exists():
        return redirect("feed")
    return render(request, "core/home.html")


def setup(request: HttpRequest) -> HttpResponse:
    """First-run wizard. Hard-disabled the moment an admin exists (TM-8).

    The gate is "zero admins", not a config flag, so a restore or upgrade that
    briefly reopens the process can never reopen setup while an admin is present.
    """
    if _admin_exists():
        raise Http404("Setup is complete.")

    errors: list[str] = []
    if request.method == "POST":
        secret = request.POST.get("setup_secret", "")
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        display_name = request.POST.get("display_name", "").strip()
        yard_name = request.POST.get("yard_name", "").strip()
        pod_name = request.POST.get("pod_name", "").strip()

        username_error = _validate_username(username)
        if username_error:
            errors.append(username_error)
        if not display_name:
            errors.append("Tell us the name your family will see for you.")
        if not yard_name:
            errors.append("Name this side of the family (its yard).")
        if not pod_name:
            errors.append("Name your household (its pod).")
        # Pass the prospective user so password-equals-username is rejected for the
        # most privileged account on the instance.
        try:
            validate_password(password, User(username=username))
        except ValidationError as exc:
            errors.extend(exc.messages)

        if not errors:
            try:
                admin = _try_create_admin(
                    username,
                    password,
                    secret,
                    display_name=display_name,
                    yard_name=yard_name,
                    pod_name=pod_name,
                )
            except _SetupClosed as exc:
                raise Http404("Setup is complete.") from exc
            if admin is None:
                errors.append(
                    "That setup secret is not correct. It was printed to the server "
                    "console at startup."
                )
            else:
                # Two auth backends exist now (ModelBackend + allauth's), so login
                # must name which one authenticated this user.
                login(request, admin, backend="django.contrib.auth.backends.ModelBackend")
                return redirect("home")
    return render(request, "core/setup.html", {"errors": errors})


def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness probe: confirms the process is up and the database answers."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok"})


def robots(request: HttpRequest) -> HttpResponse:
    """A private family instance is never crawled: disallow everything (TM-5).
    Token routes additionally send X-Robots-Tag per response, so this file is a
    politeness layer, not the control."""
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
