"""The off-box copy status file (T-OP-G3), the one health field an OPERATOR writes.

The copy step lives on the host on purpose — the destination credential must not sit beside
the ciphertext on the data volume — so the instance has never been able to say whether a
copy left the box. It now reads one small JSON file the host's job drops in `BACKUP_ROOT`,
which turns "nobody would ever know" into the existing alarm path.

Two properties are load-bearing here and both are about NOT crying wolf in the wrong
direction:

* **No file is not a failure.** Most self-hosters have no off-box job at all. An instance
  that went `degraded` the moment this shipped would teach its one operator that `degraded`
  means nothing, and the backup alarm rides the same word.
* **A file that is there and wrong IS a failure.** Somebody wired a job up and it is now
  writing rubbish, or something else is writing this path. Either way the instance can no
  longer answer the question it was asked, and that degrades.

Everything below the second property treats the file as hostile input: it is operator-owned
on a volume the app itself writes to, so a bad one must produce a FIELD, never a traceback
in the weekly email or a 500 on the endpoint an outside monitor polls.
"""

from __future__ import annotations

import datetime
import json
from collections import namedtuple
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import health, health_email
from core.models import BackupRun, CertificateStatus, Member

pytestmark = pytest.mark.django_db

_BACKEND = "django.contrib.auth.backends.ModelBackend"
_Usage = namedtuple("_Usage", "total used free")
LABEL = "Off-box copy"


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch: Any) -> None:
    """Pin disk headroom, as test_health_surface does: these tests assert on ANOTHER field
    and a CI runner that happens to be low on disk would fail them for a true reason that
    has nothing to do with the off-box copy."""
    monkeypatch.setattr("core.health.shutil.disk_usage", lambda path: _Usage(100, 20, 80))


def _healthy_instance() -> None:
    """A recent backup and a certificate with months left, so `degraded` in these tests can
    only have come from the off-box field."""
    BackupRun.objects.create(byte_count=1024, encrypted=True)
    CertificateStatus.objects.create(
        domain=health.instance_domain(),
        expires_at=timezone.now() + datetime.timedelta(days=60),
        checked_at=timezone.now(),
    )


def _write_status(payload: object) -> None:
    """Write the host job's status file, exactly where the runbook says to put it."""
    path = health.offbox_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_raw(blob: str) -> None:
    """Write something that is NOT the contract, byte for byte."""
    path = health.offbox_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(blob, encoding="utf-8")


def _stamp(hours_ago: float) -> str:
    return (timezone.now() - datetime.timedelta(hours=hours_ago)).isoformat()


def _field(now: datetime.datetime | None = None) -> health.Field:
    found = [f for f in health.measure(now) if f.label == LABEL]
    assert found, f"no {LABEL!r} field in {[f.label for f in health.measure(now)]}"
    return found[0]


def _signed_in(role: str) -> Client:
    user = User.objects.create_user(username=f"person-{role}")
    Member.objects.create(display_name="A Person", user=user, role=role)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


# ---------------------------------------------------------------- the four honest states


def test_no_status_file_is_not_set_up_and_never_degrades() -> None:
    """The state every existing instance is in. It must read exactly as it did before this
    field learned to measure anything: unmeasured, unalarming, and `ok` at /healthz."""
    _healthy_instance()

    field = _field()

    assert not field.measured, "a missing status file reported itself as a measurement"
    assert not field.alarming, "an instance with no off-box job cried wolf"
    assert "cannot see" in field.value and "T-OP-G3" in field.value
    assert Client().get(reverse("healthz")).json() == {"status": health.OK}


def test_a_fresh_success_is_reported_and_stays_ok() -> None:
    _healthy_instance()
    _write_status({"ok": True, "at": _stamp(2), "remote_objects": 412})

    field = _field()

    assert field.measured and not field.alarming
    assert "copied" in field.value
    assert "412" in field.value, "the object count the host reported was dropped"
    assert Client().get(reverse("healthz")).json() == {"status": health.OK}


def test_a_success_older_than_the_window_is_stale_and_degrades() -> None:
    """A copy job that stopped a month ago still reports its last success forever. The
    timestamp ageing past the window is the only thing that says so."""
    _healthy_instance()
    _write_status({"ok": True, "at": _stamp(49)})  # the literal hour, not the constant

    field = _field()

    assert field.alarming and field.measured
    assert "LAST COPIED" in field.value
    assert Client().get(reverse("healthz")).json() == {"status": health.DEGRADED}


def test_a_reported_failure_degrades_and_names_the_reason_to_the_admin() -> None:
    _healthy_instance()
    _write_status({"ok": False, "at": _stamp(1), "error": "rclone: quota exceeded"})

    field = _field()

    assert field.alarming and field.measured
    assert "FAILED" in field.value
    assert "rclone: quota exceeded" in field.value
    payload = _signed_in(Member.INSTANCE_ADMIN).get(reverse("healthz")).json()
    assert payload["status"] == health.DEGRADED
    detail = [f for f in payload["detail"] if f["label"] == LABEL]
    assert detail and "quota exceeded" in detail[0]["value"]


def test_the_window_is_the_documented_forty_eight_hours() -> None:
    """Both sides of the boundary, in LITERAL hours.

    Written against the constant instead, these two tests would move with it and pass at
    any width — including one hour, which would alarm on every host whose cron runs a
    little later than the instance's clock. 48 is also a published number: the runbook
    tells an operator what the instance expects of their job.
    """
    assert health.OFFBOX_STALE_HOURS == 48, "the runbook publishes this number as a contract"

    _write_status({"ok": True, "at": _stamp(47)})
    assert not _field().alarming, "a copy inside the window was called stale"

    _write_status({"ok": True, "at": _stamp(49)})
    assert _field().alarming, "a copy a day and a half past the window read as healthy"


# ---------------------------------------------------------------- what a stranger is told


def test_the_public_answer_never_carries_the_error_text() -> None:
    """The reason a copy failed is a sentence about the destination — a bucket name, a
    host, a path — published at a guessable URL if it leaked here (TM-5)."""
    _healthy_instance()
    _write_status(
        {"ok": False, "at": _stamp(1), "error": "rclone: 403 on backups-bucket at the vault"}
    )

    response = Client().get(reverse("healthz"))

    assert response.json() == {"status": health.DEGRADED}
    body = response.content.decode()
    assert "rclone" not in body and "backups-bucket" not in body


def test_an_ordinary_member_is_a_stranger_here_too() -> None:
    _write_status({"ok": False, "at": _stamp(1), "error": "rclone: quota exceeded"})

    response = _signed_in(Member.MEMBER).get(reverse("healthz"))

    assert set(response.json()) == {"status"}
    assert "quota" not in response.content.decode()


# ---------------------------------------------------------------- hostile input

# Each of these is a file the app itself must survive: it is operator-written, on the volume
# the app also writes to, and it is read by a weekly email job and by an endpoint an outside
# monitor polls every half hour. A traceback in either place is the alarm going quiet.
_A_TIME = "2026-09-18T00:00:00Z"
HOSTILE = [
    pytest.param("{not json at all", "invalid JSON", id="invalid-json"),
    pytest.param('"a string"', "a bare JSON string", id="not-an-object"),
    pytest.param("[]", "a JSON array", id="array"),
    pytest.param(json.dumps({"at": _A_TIME}), "no ok key", id="missing-ok"),
    pytest.param(json.dumps({"ok": "true", "at": _A_TIME}), "ok as a string", id="ok-a-string"),
    pytest.param(json.dumps({"ok": 1, "at": _A_TIME}), "ok as a number", id="ok-a-number"),
    pytest.param(json.dumps({"ok": True}), "no at key", id="missing-at"),
    pytest.param(json.dumps({"ok": True, "at": "whenever"}), "unparseable at", id="bad-at"),
    pytest.param(json.dumps({"ok": True, "at": 1758153600}), "at as a number", id="at-a-number"),
]


@pytest.mark.parametrize(("blob", "why"), HOSTILE)
def test_a_malformed_status_file_is_unreadable_and_degrades(blob: str, why: str) -> None:
    _healthy_instance()
    _write_raw(blob)

    field = _field()

    assert field.alarming, f"{why} did not raise the field"
    assert field.measured, f"{why} was filed as unmeasured, so it never reached /healthz"
    assert "UNREADABLE" in field.value
    assert Client().get(reverse("healthz")).json() == {"status": health.DEGRADED}


def test_a_future_dated_copy_is_unreadable_rather_than_fresh() -> None:
    """A clock wrong by a year would otherwise report "copied 0 hours ago" forever, which
    is the one answer that can never age into an alarm."""
    _write_raw(json.dumps({"ok": True, "at": _stamp(-72)}))

    field = _field()

    assert field.alarming and "UNREADABLE" in field.value


def test_a_copy_stamped_a_minute_ahead_is_still_a_copy() -> None:
    """The other side of it: two machines, two clocks. A host a minute ahead of the instance
    has taken a backup copy, not written a hostile file."""
    _write_raw(json.dumps({"ok": True, "at": _stamp(-1 / 60)}))

    assert not _field().alarming, "a few seconds of clock skew was treated as an attack"


def test_an_enormous_file_is_capped_rather_than_read() -> None:
    """The app must not pull an arbitrarily large operator file into the worker's memory on
    a box whose whole problem may be that it is out of resources."""
    _write_raw(json.dumps({"ok": True, "at": _stamp(1), "error": "A" * health.OFFBOX_MAX_BYTES}))

    field = _field()

    assert field.alarming and "UNREADABLE" in field.value
    assert "AAAA" not in field.value


def test_a_symlink_is_not_followed() -> None:
    """The status file sits in a directory the app writes to. If a link there were followed,
    this reader would become a way to ask the app to open a path of someone else's choosing
    and report what it found (a secret keyfile, `/proc/self/environ`) into an email."""
    elsewhere = health.offbox_status_path().parent / "somewhere-else.json"
    elsewhere.parent.mkdir(parents=True, exist_ok=True)
    elsewhere.write_text(json.dumps({"ok": True, "at": _stamp(1)}), encoding="utf-8")
    health.offbox_status_path().symlink_to(elsewhere)

    field = _field()

    assert field.alarming, "a symlink was followed and reported as a healthy copy"
    assert "UNREADABLE" in field.value


def test_a_file_that_is_not_utf8_is_unreadable() -> None:
    """A truncated write, or a job that wrote a log in some other encoding."""
    path = health.offbox_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"ok": true, "at": "\xff\xfe"}')

    field = _field()

    assert field.alarming and "UNREADABLE" in field.value


def test_a_failure_with_no_reason_still_says_it_failed() -> None:
    """`error` is the only field of the contract a job can honestly omit — it may not have
    one. The state must survive without it, rather than reading as malformed."""
    _write_status({"ok": False, "at": _stamp(1)})

    field = _field()

    assert field.alarming and "FAILED" in field.value
    assert "no reason" in field.value


def test_a_directory_in_its_place_is_unreadable() -> None:
    health.offbox_status_path().mkdir(parents=True)

    field = _field()

    assert field.alarming and "UNREADABLE" in field.value


# ---------------------------------------------------------------- how it renders


def test_the_error_text_cannot_forge_a_line_in_the_weekly_email() -> None:
    """The email is one line per field and an alarming line starts with `[!]`. An error
    carrying newlines would otherwise write lines of its own into an operator's health
    report, which is the whole trick behind every log-injection."""
    _write_status(
        {
            "ok": False,
            "at": _stamp(1),
            "error": "no route to host\n[!] Last backup: today (encrypted)\nDisk headroom: fine",
        }
    )

    _subject, text, _alarming = health_email.build()

    forged = [
        line for line in text.splitlines() if line.strip() == "[!] Last backup: today (encrypted)"
    ]
    assert not forged, f"the error text wrote a line of its own into the email: {forged}"
    carrying = [line for line in text.splitlines() if LABEL in line]
    assert len(carrying) == 1, "the off-box field spilled across more than one line"
    assert "no route to host" in carrying[0], "the reason was dropped instead of flattened"
    assert "Last backup: today (encrypted)" in carrying[0], (
        "the injected text must stay ON the off-box line, quoted, rather than disappearing "
        "silently — an operator should see exactly what their job wrote"
    )


def test_a_long_error_is_truncated() -> None:
    _write_status({"ok": False, "at": _stamp(1), "error": "x" * 4000})

    value = _field().value

    assert len(value) < 500, "an operator-written error was reported at full length"
    assert "xxx" in value, "the error was dropped instead of truncated"


def test_the_error_text_is_escaped_where_it_renders() -> None:
    """Django autoescapes every template, `.txt` included, and /healthz is JSON-encoded. The
    assertion is that the field value passes through those renderers rather than around
    them: nothing here builds its own HTML or its own JSON."""
    _write_status({"ok": False, "at": _stamp(1), "error": "<script>alert(1)</script> & so on"})

    _subject, text, _alarming = health_email.build()

    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_the_email_carries_one_plain_sentence_per_state() -> None:
    """Four states, four readable lines, all through the same loop the other fields use."""
    _write_status({"ok": True, "at": _stamp(2), "remote_objects": 7})
    assert f"    {LABEL}: copied" in health_email.build()[1]

    _write_status({"ok": True, "at": _stamp(53)})
    assert f"[!] {LABEL}: LAST COPIED" in health_email.build()[1]

    _write_status({"ok": False, "at": _stamp(1), "error": "quota exceeded"})
    assert f"[!] {LABEL}: FAILED" in health_email.build()[1]

    _write_raw("{")
    assert f"[!] {LABEL}: UNREADABLE" in health_email.build()[1]


def test_an_object_count_that_is_not_a_number_does_not_hide_the_copy() -> None:
    """`remote_objects` is decoration; `ok` and `at` are the contract. A host job that
    reports its count as a string has a cosmetic bug, and turning the family's instance red
    over a number nobody acts on is how a real alarm gets learned as noise."""
    _write_raw(json.dumps({"ok": True, "at": _stamp(2), "remote_objects": "many"}))

    field = _field()

    assert not field.alarming
    assert "copied" in field.value and "many" not in field.value
