"""The boot guard for web push, and the command that makes a key pair (S-107).

The property under test is that a HALF-CONFIGURED instance refuses to start. A public key
with no private key renders a working-looking Turn On Notifications button whose
notifications can never arrive — silent failure on the one feature whose job is to break
silence — and a private key with no public key renders a button with nothing to hand
`PushManager.subscribe`. Required configuration is validated where the process starts,
which is the rule `config/email_guard.py` already follows.

Every key in this file is GENERATED. `.gitleaks.toml` walks every commit on every branch,
so one credential-shaped literal fails the secrets job on every open pull request at once
(docs/RESUME-HERE.md). Generating them also means the guard is tested against the exact
bytes `generate_vapid_keys` prints, rather than against a shape somebody remembered.
"""

from __future__ import annotations

import base64
import io
import secrets

import pytest
from django.core.management import call_command

from config.push_guard import PushConfigError, validate_vapid
from core.management.commands.generate_vapid_keys import generate_pair

_SUBJECT = "mailto:admin@example.test"


@pytest.fixture
def pair() -> tuple[str, str]:
    return generate_pair()


# --- the guard ---------------------------------------------------------------------------


def test_no_keys_at_all_means_the_feature_is_simply_off(pair: tuple[str, str]) -> None:
    """The ordinary self-hoster, who must lose nothing by never generating a key."""
    assert validate_vapid(public_key="", private_key="", subject="") is False
    # ...and a stray subject with no keys is still just off, not a boot failure: an
    # operator who pasted one line of three and then thought better of it still boots.
    assert validate_vapid(public_key="", private_key="", subject=_SUBJECT) is False


def test_a_full_valid_set_turns_it_on(pair: tuple[str, str]) -> None:
    public, private = pair
    assert validate_vapid(public_key=public, private_key=private, subject=_SUBJECT) is True


def test_a_public_key_with_no_private_key_refuses_to_boot(pair: tuple[str, str]) -> None:
    public, _private = pair
    with pytest.raises(PushConfigError) as refusal:
        validate_vapid(public_key=public, private_key="", subject=_SUBJECT)
    assert "BACKYARD_VAPID_PRIVATE_KEY" in str(refusal.value)
    assert "generate_vapid_keys" in str(refusal.value)


def test_a_private_key_with_no_public_key_refuses_to_boot(pair: tuple[str, str]) -> None:
    _public, private = pair
    with pytest.raises(PushConfigError) as refusal:
        validate_vapid(public_key="", private_key=private, subject=_SUBJECT)
    assert "BACKYARD_VAPID_PUBLIC_KEY" in str(refusal.value)


def test_a_refusal_never_echoes_the_key(pair: tuple[str, str]) -> None:
    """The message names the VARIABLE. A boot failure is printed to the container log, so
    a message that quoted the value would put a private key there."""
    _public, private = pair
    with pytest.raises(PushConfigError) as refusal:
        validate_vapid(public_key="", private_key=private, subject=_SUBJECT)
    assert private not in str(refusal.value)


def test_keys_without_a_subject_refuse_to_boot(pair: tuple[str, str]) -> None:
    """Not pedantry: RFC 8292 makes `sub` mandatory and Apple's push service refuses a
    token without a usable one, so an instance with keys and no subject works on Android
    and fails silently on every iPhone in the family."""
    public, private = pair
    with pytest.raises(PushConfigError) as refusal:
        validate_vapid(public_key=public, private_key=private, subject="")
    assert "BACKYARD_VAPID_SUBJECT" in str(refusal.value)


@pytest.mark.parametrize("subject", ["https://example.test", "admin@example.test", "mailto:"])
def test_a_subject_that_is_not_a_mailto_address_refuses_to_boot(
    pair: tuple[str, str], subject: str
) -> None:
    public, private = pair
    with pytest.raises(PushConfigError):
        validate_vapid(public_key=public, private_key=private, subject=subject)


@pytest.mark.parametrize("bad", ["not base64!", "YWJjZA", "a" * 200])
def test_a_malformed_public_key_refuses_to_boot(pair: tuple[str, str], bad: str) -> None:
    _public, private = pair
    with pytest.raises(PushConfigError):
        validate_vapid(public_key=bad, private_key=private, subject=_SUBJECT)


def test_a_public_key_of_the_right_length_but_the_wrong_form_refuses_to_boot(
    pair: tuple[str, str],
) -> None:
    _public, private = pair
    wrong = base64.urlsafe_b64encode(b"\x03" + b"\x01" * 64).rstrip(b"=").decode()
    with pytest.raises(PushConfigError):
        validate_vapid(public_key=wrong, private_key=private, subject=_SUBJECT)


@pytest.mark.parametrize("length", [16, 31, 33, 64])
def test_a_private_key_of_the_wrong_length_refuses_to_boot(
    pair: tuple[str, str], length: int
) -> None:
    public, _private = pair
    wrong = base64.urlsafe_b64encode(secrets.token_bytes(length)).rstrip(b"=").decode()
    with pytest.raises(PushConfigError):
        validate_vapid(public_key=public, private_key=wrong, subject=_SUBJECT)


def test_the_settings_module_reads_the_three_documented_names() -> None:
    """The `test_compose_env_reaches_the_container` lesson from the other side: a rename
    here would leave `.env.example`, the runbook and docker-compose naming variables
    nothing consumes."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "src" / "config" / "settings.py").read_text()
    for name in (
        "BACKYARD_VAPID_PUBLIC_KEY",
        "BACKYARD_VAPID_PRIVATE_KEY",
        "BACKYARD_VAPID_SUBJECT",
        "BACKYARD_PUSH_SERVICE_HOSTS",
    ):
        assert f'os.environ.get("{name}"' in source, f"{name} is no longer read by settings"


# --- the command -------------------------------------------------------------------------


def test_the_command_prints_a_pair_the_guard_accepts() -> None:
    """The loop that matters: what the documented command produces is what the app boots
    on. A test that checked the format against its own idea of the format would pass while
    an operator's instance refused to start."""
    out = io.StringIO()
    call_command("generate_vapid_keys", stdout=out, stderr=io.StringIO())
    printed = dict(line.split("=", 1) for line in out.getvalue().splitlines() if "=" in line)
    assert set(printed) == {
        "BACKYARD_VAPID_PUBLIC_KEY",
        "BACKYARD_VAPID_PRIVATE_KEY",
        "BACKYARD_VAPID_SUBJECT",
    }
    assert (
        validate_vapid(
            public_key=printed["BACKYARD_VAPID_PUBLIC_KEY"],
            private_key=printed["BACKYARD_VAPID_PRIVATE_KEY"],
            subject=_SUBJECT,
        )
        is True
    )


def test_the_command_makes_a_different_pair_every_time() -> None:
    assert generate_pair() != generate_pair()


def test_the_command_writes_nothing_and_logs_nothing(
    tmp_path: object, caplog: pytest.LogCaptureFixture
) -> None:
    """It PRINTS. It does not edit .env (a wrong path silently truncates an operator's
    secrets file) and it does not log (compose's json-file driver writes stdout to disk,
    where `docker compose logs` replays it — the exact defect the first-run setup secret
    already had once, see settings.SETUP_HANDOVER_FILE)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    before = sorted(p.name for p in root.iterdir())
    out, err = io.StringIO(), io.StringIO()
    with caplog.at_level(0):
        call_command("generate_vapid_keys", stdout=out, stderr=err)
    assert sorted(p.name for p in root.iterdir()) == before
    assert caplog.records == []
    # The private key is on stdout, which the operator's terminal shows, and NOWHERE else.
    private = next(
        line.split("=", 1)[1]
        for line in out.getvalue().splitlines()
        if line.startswith("BACKYARD_VAPID_PRIVATE_KEY=")
    )
    assert private not in err.getvalue()


def test_the_command_warns_that_rotating_signs_every_device_out() -> None:
    """The one fact an operator about to replace a pair has to be told, and the one they
    will only read if it is beside the command."""
    err = io.StringIO()
    call_command("generate_vapid_keys", stdout=io.StringIO(), stderr=err)
    assert "device" in err.getvalue()
    assert "Settings" in err.getvalue()
