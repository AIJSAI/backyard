"""The one-time setup secret is handed over in a file, not printed (G10).

`ensure_setup` runs from the container entrypoint on every boot until an admin exists,
and it used to print the plaintext secret to stdout under a banner. `docker-compose.yml`
sets the json-file logging driver with `max-size: 10m, max-file: 3`, so that line was
written to a file on disk, replayed by `docker compose logs` to anyone who can run it,
and kept through rotation. Whoever holds it becomes the instance admin of a family's
whole archive.

The window was bounded — the token dies when an admin is created — but bounded is not
absent, and the container log is the one place operators are trained to paste from. So
the secret goes to a 0600 file on the data volume, only the path is printed, and the file
is deleted the moment setup completes.
"""

from __future__ import annotations

import stat
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from core.management.commands import ensure_setup
from core.models import SetupToken

pytestmark = pytest.mark.django_db
User = get_user_model()
_STRONG_PASSWORD = "a-Strong-passphrase-9"


def _run() -> str:
    out = StringIO()
    call_command("ensure_setup", stdout=out)
    return out.getvalue()


def _handover_text() -> str:
    return ensure_setup.handover_path().read_text().strip()


def test_the_secret_is_written_to_a_file_and_never_printed() -> None:
    """Fails without the file hand-over: the secret is in the command's stdout, which on
    a real instance is the Docker json log."""
    printed = _run()
    secret = _handover_text()

    assert secret, "nothing was handed over"
    assert secret not in printed, "the live secret is in the boot output, i.e. in the log"
    assert str(ensure_setup.handover_path()) in printed, (
        "an operator has to be told where to read it, or the product is unusable"
    )


def test_the_handed_over_secret_is_the_one_that_works() -> None:
    """Guard the guard: a file holding the wrong value would pass every assertion above
    and leave a self-hoster unable to finish setting up."""
    _run()
    response = Client().post(
        reverse("setup"),
        {
            "setup_secret": _handover_text(),
            "username": "founder",
            "password": _STRONG_PASSWORD,
            "display_name": "The Founder",
            "yard_name": "One side",
            "pod_name": "A household",
        },
    )
    assert response.status_code == 302, response.content[:400]
    assert User.objects.filter(is_superuser=True).exists()


def test_only_the_container_user_can_read_the_file() -> None:
    """0600. A file on a volume that a backup, a bind mount or a stray `docker cp`
    might carry elsewhere is not a place for a group- or world-readable credential."""
    _run()
    mode = ensure_setup.handover_path().stat().st_mode
    assert not mode & stat.S_IRGRP, oct(mode)
    assert not mode & stat.S_IROTH, oct(mode)
    assert not mode & stat.S_IWOTH, oct(mode)


def test_a_pre_existing_loose_file_does_not_keep_its_permissions() -> None:
    """`O_CREAT` ignores its mode argument for a file that already exists, so writing over
    yesterday's file would have kept yesterday's permissions — and on a volume restored
    from a backup or copied with a loose umask those can be world-readable.

    Fails without the `unlink` before the create in `write_handover`.
    """
    path = ensure_setup.handover_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("an older secret\n")
    path.chmod(0o644)

    _run()

    assert not path.stat().st_mode & stat.S_IROTH, oct(path.stat().st_mode)


def test_the_file_is_gone_the_moment_the_first_admin_exists(
    django_capture_on_commit_callbacks: object,
) -> None:
    """The window closes with the act, not with the next boot.

    Fails without the `clear_handover` on the setup view's success path: a live-looking
    file sits on the volume until something reboots the container.

    Driven through `django_capture_on_commit_callbacks` because the delete is deliberately
    an `on_commit` callback: if the wizard's transaction rolls back the secret is still
    live, and deleting the only copy of a live credential would leave a self-hoster with
    an instance they cannot finish setting up. A test that ran it inline would be testing
    a different, worse implementation.
    """
    _run()
    secret = _handover_text()
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        Client().post(
            reverse("setup"),
            {
                "setup_secret": secret,
                "username": "founder",
                "password": _STRONG_PASSWORD,
                "display_name": "The Founder",
                "yard_name": "One side",
                "pod_name": "A household",
            },
        )
    assert not ensure_setup.handover_path().exists()


def test_a_later_boot_clears_a_stale_file_too() -> None:
    """The entrypoint runs this command on every boot; once an admin exists it must take
    the file with the token, not only the token."""
    path = ensure_setup.handover_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("a secret from before the admin existed\n")
    SetupToken.objects.create(token_hash=make_password("anything-at-all"))
    User.objects.create_superuser(username="already-here", password=_STRONG_PASSWORD)

    printed = _run()

    assert not path.exists()
    assert not SetupToken.objects.exists()
    assert "setup wizard is closed" in printed


def test_the_path_is_configurable_and_defaults_to_the_data_volume(settings: object) -> None:
    """The self-hoster who mounts things elsewhere gets a knob, and the default is the
    same volume the Django secret key already lives on."""
    assert ensure_setup.handover_path() == Path(settings.SETUP_HANDOVER_FILE)  # type: ignore[attr-defined]
    settings.SETUP_HANDOVER_FILE = str(Path(settings.SETUP_HANDOVER_FILE).parent / "elsewhere")  # type: ignore[attr-defined]
    _run()
    assert ensure_setup.handover_path().name == "elsewhere"
    assert ensure_setup.handover_path().exists()
