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

from . import health, permissions
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
    """Liveness probe, and the one health surface something outside the box can read.

    Three readers, and the answer is sized for the narrowest of them (S-806, TM-5):

    * a container healthcheck and the external monitor, which are anonymous and get two
      words — `ok` or `degraded`. Disk headroom, backup age and certificate dates at a
      guessable URL on a private family instance are an operations map for a stranger;
    * a signed-in INSTANCE ADMIN, who gets the same fields the weekly email carries, so the
      person responsible does not have to wait until Monday 07:20 to see why;
    * everyone else signed in, who is not responsible for the instance and gets the two
      words, like a stranger.

    Always HTTP 200 when the process and the database answer, `degraded` included. Degraded
    is a statement about the instance, not about this process: a full disk is not a reason
    for Docker to cycle the container, and a fresh instance that has not taken its first
    backup yet would otherwise never report healthy at all.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    fields = health.measure()
    payload: dict[str, object] = {"status": health.public_status(fields)}
    if _is_instance_admin(request):
        payload["detail"] = [
            {"label": f.label, "value": f.value, "alarming": f.alarming} for f in fields
        ]
    return JsonResponse(payload)


def _is_instance_admin(request: HttpRequest) -> bool:
    """Whether this request is a signed-in instance admin. Never raises: healthz must
    answer a probe even when the member lookup finds nothing to answer about."""
    if not request.user.is_authenticated or request.user.pk is None:
        return False
    member = Member.objects.filter(user_id=request.user.pk).first()
    return member is not None and permissions.is_instance_admin(member)


def how_it_works(request: HttpRequest) -> HttpResponse:
    """One plain page that answers the questions a relative actually asks (owner
    direction 7-8), and the family's plain-language privacy note (S-705, GAP-7).

    Deliberately public: it is linked from the sign-in page, so somebody who cannot
    get in can still read what this is and how to get help. It names no member and
    lists no household — the only thing it reads from the database is the first name
    of whoever runs this Backyard, through the same context processor the footer uses.
    """
    return render(request, "core/how_it_works.html")


def about(request: HttpRequest) -> HttpResponse:
    """The quiet page that carries the licence and the source offer (AGPL section 13).

    It used to be the second-loudest line in the footer of every screen, including a
    grandparent's. The obligation is to OFFER the source to a network user, which a page
    one tap from Settings and from the sign-in page does; the family does not need a
    licence notice under every photograph.
    """
    return render(request, "core/about.html")


def robots(request: HttpRequest) -> HttpResponse:
    """A private family instance is never crawled: disallow everything (TM-5).
    Token routes additionally send X-Robots-Tag per response, so this file is a
    politeness layer, not the control."""
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
