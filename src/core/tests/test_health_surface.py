"""/healthz and the two health fields it exists for (S-806, T-MON-1, TM-5).

The health email is a weekly worker periodic, so it cannot report the one failure that
matters most: a worker that has stopped sends nothing and reads exactly like a quiet week.
/healthz is the surface something OUTSIDE the box can read, so it has to answer two
questions at once, for readers with opposite rights:

* a stranger (and a container healthcheck, and the GitHub monitor) gets `ok` or `degraded`
  and nothing else. Free disk, backup age and certificate dates at a guessable URL on a
  private family instance are an operations map for whoever asks first;
* the instance admin gets the same fields the weekly email carries, because the person
  responsible should not have to wait for Monday 07:20 to see the reason.

The `degraded` rule is narrower than the email's `alarming` rule and the difference is the
load-bearing part: only something the instance MEASURED may degrade it. The monitor turns
this endpoint into an email every half hour, and "the registry did not answer" is not a
reason to page a family every thirty minutes forever.
"""

from __future__ import annotations

import datetime
from collections import namedtuple
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import health
from core.models import BackupFailure, BackupRun, CertificateStatus, Member

pytestmark = pytest.mark.django_db

_BACKEND = "django.contrib.auth.backends.ModelBackend"
_Usage = namedtuple("_Usage", "total used free")


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch: Any) -> None:
    """Pin disk headroom for every test here but the one about disk.

    These tests assert on the OTHER fields, and the disk field measures the real filesystem
    the runner happens to be on. A CI machine sitting below LOW_DISK_PERCENT would fail them
    for a true reason that has nothing to do with what they check, which is the kind of
    flake that gets a suite re-run instead of read.
    """
    monkeypatch.setattr("core.health.shutil.disk_usage", lambda path: _Usage(100, 20, 80))


def _healthy_instance() -> None:
    """Everything these fields read, in its good state: a recent backup, no failures, a
    certificate with months left. The domain field stays NOT MEASURED, which is unmeasured
    rather than known-bad and so cannot degrade the endpoint — that is the rule under test
    in `test_only_a_measured_failure_degrades_the_public_answer`."""
    BackupRun.objects.create(byte_count=1024, encrypted=True)
    CertificateStatus.objects.create(
        domain=health.instance_domain(),
        expires_at=timezone.now() + datetime.timedelta(days=60),
        checked_at=timezone.now(),
    )


def _signed_in(role: str) -> Client:
    user = User.objects.create_user(username=f"person-{role}")
    Member.objects.create(display_name="A Person", user=user, role=role)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


def _field(fields: list[health.Field], label: str) -> health.Field:
    found = [field for field in fields if field.label == label]
    assert found, f"no {label!r} field in {[f.label for f in fields]}"
    return found[0]


# ---------------------------------------------------------------- what a stranger sees


def test_a_stranger_is_told_ok_and_nothing_else() -> None:
    _healthy_instance()

    response = Client().get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_a_degraded_instance_still_answers_200() -> None:
    """Degraded is a statement about the INSTANCE, not about this process.

    A non-2xx would make Docker call the container unhealthy for a filling disk, and would
    fail CI's live probe on a fresh instance that has simply never taken a backup — so the
    status code answers "is the app up" and the body answers "is the instance well".
    """
    response = Client().get(reverse("healthz"))  # no BackupRun at all: never backed up

    assert response.status_code == 200
    assert response.json() == {"status": "degraded"}


def test_a_degraded_answer_carries_no_detail_for_a_stranger() -> None:
    BackupFailure.objects.create(error="pg_dump failed: connection refused at db.internal")

    response = Client().get(reverse("healthz"))

    assert set(response.json()) == {"status"}
    assert "pg_dump" not in response.content.decode()


def test_an_ordinary_member_is_a_stranger_here() -> None:
    """Being in the family is not being responsible for the box."""
    _healthy_instance()

    assert set(_signed_in(Member.MEMBER).get(reverse("healthz")).json()) == {"status"}


# ---------------------------------------------------------------- what the admin sees


def test_the_instance_admin_sees_every_field() -> None:
    _healthy_instance()

    payload = _signed_in(Member.INSTANCE_ADMIN).get(reverse("healthz")).json()

    assert payload["status"] == "ok"
    labels = [field["label"] for field in payload["detail"]]
    for expected in ("Last backup", "Scheduled backup", "Disk headroom", "TLS certificate"):
        assert expected in labels, f"{expected} is missing from the admin's health detail"


def test_the_admin_detail_names_the_reason_a_backup_is_failing() -> None:
    BackupRun.objects.create(byte_count=1, encrypted=True)
    BackupFailure.objects.create(error="pg_dump failed: no space left on device")

    payload = _signed_in(Member.INSTANCE_ADMIN).get(reverse("healthz")).json()

    assert payload["status"] == "degraded"
    failing = _detail(payload, "Scheduled backup")
    assert failing["alarming"]
    assert "no space left on device" in failing["value"]


def _detail(payload: dict[str, Any], label: str) -> dict[str, Any]:
    found = [field for field in payload["detail"] if field["label"] == label]
    assert found, f"no {label!r} field in the admin detail"
    return dict(found[0])


# ---------------------------------------------------------------- the degraded rule


def test_only_a_measured_failure_degrades_the_public_answer() -> None:
    """An instance that cannot MEASURE something knows less; it is not known to be broken.

    The domain field on a fresh instance is `NOT MEASURED — no successful lookup yet` and
    alarming, which is right for a weekly email an operator reads and wrong for an endpoint
    a robot polls every thirty minutes: it would fail from the first minute of the first
    deploy and stay failing until an RDAP lookup succeeded.
    """
    unmeasured = [health.Field("Domain", f"{health.NOT_MEASURED} — no lookup yet", True)]
    measured = [health.Field("Disk headroom", "3% free (0.4 GB)", True)]

    assert health.public_status(unmeasured) == health.OK
    assert health.public_status(measured) == health.DEGRADED
    assert health.has_anything_alarming(unmeasured), (
        "the weekly email must still raise an unmeasured field; if this flips, the two "
        "rules have been collapsed into one and the email has gone quiet about gaps"
    )


def test_a_stopped_worker_degrades_the_endpoint_even_though_it_silences_the_email() -> None:
    """The failure this endpoint exists for, end to end.

    A dead worker stops the digest, the backup and the health email — including the email
    that would have reported it. What it cannot stop is the backup ageing, and that is a
    measured fact, so the one alarm outside the box does fire.
    """
    run = BackupRun.objects.create(byte_count=1024, encrypted=True)
    BackupRun.objects.filter(pk=run.pk).update(
        finished_at=timezone.now() - datetime.timedelta(days=health.STALE_BACKUP_DAYS + 1)
    )

    assert Client().get(reverse("healthz")).json() == {"status": "degraded"}


def test_a_filling_disk_degrades_the_endpoint(monkeypatch: Any) -> None:
    _healthy_instance()
    monkeypatch.setattr("core.health.shutil.disk_usage", lambda path: _Usage(100, 97, 3))

    assert Client().get(reverse("healthz")).json() == {"status": "degraded"}


# ---------------------------------------------------------------- the certificate field


def test_the_certificate_field_counts_down_and_calls_out_the_last_fortnight(
    settings: Any,
) -> None:
    settings.BASE_URL = "https://family.example"
    now = timezone.now()
    status = CertificateStatus.objects.create(
        domain="family.example",
        expires_at=now + datetime.timedelta(days=45),
        checked_at=now,
    )

    comfortable = _field(health.measure(now), "TLS certificate")
    assert "expires in 45 days" in comfortable.value
    assert not comfortable.alarming

    CertificateStatus.objects.filter(pk=status.pk).update(
        expires_at=now + datetime.timedelta(days=health.CERTIFICATE_WARN_DAYS)
    )
    tight = _field(health.measure(now), "TLS certificate")
    assert tight.alarming, "a certificate inside the warning window did not alarm"


def test_an_expired_certificate_says_what_the_family_is_seeing(settings: Any) -> None:
    """ "expires in -3 days" is the wrong sentence at the one moment this line matters."""
    settings.BASE_URL = "https://family.example"
    now = timezone.now()
    CertificateStatus.objects.create(
        domain="family.example",
        expires_at=now - datetime.timedelta(days=3),
        checked_at=now,
    )

    expired = _field(health.measure(now), "TLS certificate")

    assert expired.alarming
    assert "EXPIRED 3 days ago" in expired.value
    assert "security warning" in expired.value


def test_a_plain_http_instance_is_not_nagged_about_a_certificate_it_cannot_have(
    settings: Any,
) -> None:
    """The local clean-machine repro is plain HTTP by design. An alarm that fires on every
    developer's instance is how a real alarm gets learned as noise."""
    settings.BASE_URL = "http://localhost:8000"
    _healthy_instance()

    field = _field(health.measure(), "TLS certificate")

    assert not field.alarming
    assert not field.measured
    assert Client().get(reverse("healthz")).json() == {"status": "ok"}


def test_a_never_checked_certificate_on_an_https_instance_is_alarming(settings: Any) -> None:
    settings.BASE_URL = "https://family.example"

    field = _field(health.measure(), "TLS certificate")

    assert field.alarming, "an https instance that has never read its own certificate"
    assert not field.measured  # unknown, so this one does not degrade the public endpoint


def test_a_stale_check_says_so_rather_than_passing_an_old_number_off_as_current(
    settings: Any,
) -> None:
    settings.BASE_URL = "https://family.example"
    now = timezone.now()
    CertificateStatus.objects.create(
        domain="family.example",
        expires_at=now + datetime.timedelta(days=40),
        checked_at=now - datetime.timedelta(days=9),
    )

    field = _field(health.measure(now), "TLS certificate")

    assert "last checked 9 days ago" in field.value


# ---------------------------------------------------------------- reading the certificate


def test_openssls_own_expiry_string_parses() -> None:
    """The real string, from the live instance's real certificate (measured 2026-09-18).

    A drifted format string breaks nothing loudly: the field just reads NOT MEASURED
    forever, which is indistinguishable from a lookup that keeps failing.
    """
    from core import cert_expiry

    assert cert_expiry.parse_not_after("Oct 20 20:36:34 2026 GMT") == datetime.datetime(
        2026, 10, 20, 20, 36, 34, tzinfo=datetime.UTC
    )
    with pytest.raises(cert_expiry.CertificateLookupFailed):
        cert_expiry.parse_not_after("whenever")


def test_a_failed_check_keeps_the_last_good_expiry(monkeypatch: Any, settings: Any) -> None:
    """Same rule as the domain lookup: "expires in 40 days, last checked 9 days ago" is a
    more useful thing to tell an operator than throwing away a true answer because today's
    handshake timed out."""
    from core import cert_expiry

    settings.BASE_URL = "https://family.example"
    good = timezone.now() + datetime.timedelta(days=40)
    CertificateStatus.objects.create(
        domain="family.example", expires_at=good, checked_at=timezone.now()
    )

    def boom(domain: str, **kwargs: Any) -> datetime.datetime:
        raise cert_expiry.CertificateLookupFailed("connection refused")

    monkeypatch.setattr(cert_expiry, "fetch_not_after", boom)
    status = cert_expiry.refresh()

    assert status.expires_at == good
    assert "connection refused" in status.error


def test_a_recovered_check_clears_the_error(monkeypatch: Any, settings: Any) -> None:
    from core import cert_expiry

    settings.BASE_URL = "https://family.example"
    CertificateStatus.objects.create(domain="family.example", error="connection refused")
    fresh = timezone.now() + datetime.timedelta(days=89)
    monkeypatch.setattr(cert_expiry, "fetch_not_after", lambda domain, **kwargs: fresh)

    status = cert_expiry.refresh()

    assert status.error == "", "a recovered check left a stale error on the row"
    assert status.expires_at == fresh and status.checked_at is not None
