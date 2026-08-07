"""S-806: the weekly admin health email (threat row T-MON-1).

T-MON-1 is rated **High** and its stated mitigation did not exist: *"Nothing is watching: a
dead backup cron or a filling disk goes unnoticed for months, giving every other threat
unlimited dwell time."*

The load-bearing property, and the one most easily lost in a refactor, is the **negative**
one: a field the app cannot compute is reported as NOT MEASURED, never dropped. An email
that silently omits a signal reads as "everything is fine", which is the failure T-MON-1
describes wearing the costume of a feature.
"""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.utils import timezone

from core import health, health_email
from core.models import BackupRun, DigestSubscription, DomainStatus, Member

pytestmark = pytest.mark.django_db


def _admin(*, address: str | None = "admin@example.com", confirmed: bool = True) -> Member:
    member = Member.objects.create(display_name="The Admin", role=Member.INSTANCE_ADMIN)
    if address:
        DigestSubscription.objects.create(
            member=member,
            address=address,
            enabled=True,
            confirmed_at=timezone.now() if confirmed else None,
            unsubscribe_token_digest="x" * 64,
        )
    return member


# ---------------------------------------------------------------- the negative property


def test_every_field_appears_even_when_it_cannot_be_measured() -> None:
    """The whole point. On a bare instance almost nothing is knowable, and the email must
    still list every line T-MON-1 asks for, marked NOT MEASURED."""
    _subject, text, _alarming = health_email.build()
    for label in (
        "Last backup",
        "Disk headroom",
        "Domain",
        "Failed sign-ins",
        "Off-box backup age",
    ):
        assert label in text, f"{label} is missing from the health email entirely"
    # The two that genuinely cannot be answered say so, rather than being absent.
    assert text.count(health.NOT_MEASURED) >= 2, text


def test_the_two_uninstrumented_fields_name_what_is_missing() -> None:
    """ "NOT MEASURED" alone would leave an operator unable to act. Each says why."""
    fields = {f.label: f.value for f in health.measure()}
    assert "audit log" in fields["Failed sign-ins"]
    assert "T-MON-1" in fields["Failed sign-ins"]
    assert "cannot see" in fields["Off-box backup age"]
    assert "T-OP-G3" in fields["Off-box backup age"]


def test_never_backed_up_is_distinct_from_not_measured() -> None:
    """Conflating "no backup has ever run" with "cannot tell" would hide the worse case
    behind the milder word."""
    field = next(f for f in health.measure() if f.label == "Last backup")
    assert "NEVER" in field.value
    assert field.value != health.NOT_MEASURED
    assert field.alarming


# ---------------------------------------------------------------- the measured fields


def test_a_recent_backup_reads_as_healthy_and_a_stale_one_alarms() -> None:
    now = timezone.now()
    run = BackupRun.objects.create(byte_count=1234, encrypted=True)
    field = next(f for f in health.measure(now) if f.label == "Last backup")
    assert "today" in field.value and "encrypted" in field.value
    assert not field.alarming

    BackupRun.objects.filter(pk=run.pk).update(
        finished_at=now - datetime.timedelta(days=health.STALE_BACKUP_DAYS + 1)
    )
    stale = next(f for f in health.measure(now) if f.label == "Last backup")
    assert stale.alarming, "a backup older than the staleness window did not alarm"


def test_a_plaintext_backup_is_named_as_plaintext() -> None:
    """An operator must be able to tell from the email that their archive is in the clear."""
    BackupRun.objects.create(byte_count=1, encrypted=False)
    field = next(f for f in health.measure() if f.label == "Last backup")
    assert "PLAINTEXT" in field.value


def test_disk_headroom_is_a_real_measurement() -> None:
    field = next(f for f in health.measure() if f.label == "Disk headroom")
    assert field.measured, field.value
    assert "% free" in field.value


def test_a_domain_expiring_soon_alarms_and_a_distant_one_does_not() -> None:
    now = timezone.now()
    domain = health.instance_domain()
    status = DomainStatus.objects.create(
        domain=domain,
        expires_at=now + datetime.timedelta(days=health.DOMAIN_WARN_DAYS - 1),
        checked_at=now,
    )
    soon = next(f for f in health.measure(now) if f.label == "Domain")
    assert soon.alarming and "expires in" in soon.value

    DomainStatus.objects.filter(pk=status.pk).update(expires_at=now + datetime.timedelta(days=400))
    later = next(f for f in health.measure(now) if f.label == "Domain")
    assert not later.alarming, later.value


def test_a_stale_domain_check_says_so_rather_than_passing_an_old_number_off(
    settings: pytest.FixtureRequest,
) -> None:
    """A number from a month ago presented as current is worse than no number."""
    now = timezone.now()
    DomainStatus.objects.create(
        domain=health.instance_domain(),
        expires_at=now + datetime.timedelta(days=300),
        checked_at=now - datetime.timedelta(days=30),
    )
    field = next(f for f in health.measure(now) if f.label == "Domain")
    assert "last checked 30 days ago" in field.value


# ---------------------------------------------------------------- sending


def test_it_sends_to_an_instance_admin_with_a_confirmed_address() -> None:
    _admin()
    mail.outbox.clear()
    result = health_email.send_health_emails()
    assert result.sent == 1
    assert len(mail.outbox) == 1
    assert health.instance_domain() in mail.outbox[0].subject


def test_an_admin_with_no_confirmed_address_is_reported_not_silently_skipped() -> None:
    """The one failure mode that silences the thing whose job is to break silence. It must
    be countable by the caller, not swallowed."""
    _admin(confirmed=False)
    mail.outbox.clear()
    result = health_email.send_health_emails()
    assert result.sent == 0
    assert result.skipped_no_confirmed_address == 1
    assert mail.outbox == []


def test_it_never_mails_a_non_admin_member() -> None:
    member = Member.objects.create(display_name="Just a cousin", role=Member.MEMBER)
    DigestSubscription.objects.create(
        member=member,
        address="cousin@example.com",
        enabled=True,
        confirmed_at=timezone.now(),
        unsubscribe_token_digest="y" * 64,
    )
    mail.outbox.clear()
    assert health_email.send_health_emails().sent == 0
    assert mail.outbox == []


def test_the_subject_changes_when_something_needs_attention() -> None:
    _admin()
    # A bare instance has never been backed up, which is alarming by construction.
    subject, _text, alarming = health_email.build()
    assert alarming and "needs attention" in subject

    BackupRun.objects.create(byte_count=1, encrypted=True)
    DomainStatus.objects.create(
        domain=health.instance_domain(),
        expires_at=timezone.now() + datetime.timedelta(days=400),
        checked_at=timezone.now(),
    )
    subject2, _t2, alarming2 = health_email.build()
    assert not alarming2, "a healthy instance still reported as alarming"
    assert "weekly health check" in subject2


def test_it_carries_no_per_person_activity() -> None:
    """P1 and the calm-surfaces rule: this is instance health, not surveillance. A member's
    name appearing here would make it an activity report."""
    member = Member.objects.create(display_name="Nosy Target", role=Member.MEMBER)
    _admin()
    _subject, text, _alarming = health_email.build()
    assert member.display_name not in text
    # Asserted on member NAMES and on activity COUNTS, not on the bare words "posted" or
    # "signed in": the email's own footer promises it never reports who posted or signed
    # in, so a substring check for those words fails against correct output. Same class of
    # mistake as asserting "photo" was absent from a digest that legitimately mentions
    # photographs.
    for name in Member.objects.values_list("display_name", flat=True):
        assert name not in text, f"a member name reached the health email: {name}"
    assert "never reports who" in text  # it says so on the page, too


def test_it_rides_the_shared_send_path_so_the_anti_phishing_footer_is_present() -> None:
    from core import emailing

    _admin()
    mail.outbox.clear()
    health_email.send_health_emails()
    assert emailing.STANDING_FOOTER in mail.outbox[0].body


# ---------------------------------------------------------------- the domain lookup


def test_the_rdap_parser_reads_the_expiration_event() -> None:
    """Registries agree on `events[].eventAction == "expiration"`; the various top-level
    `*Date` keys are registrar-specific and deliberately not trusted."""
    from core import domain_expiry

    parsed = domain_expiry._parse_expiry(
        {
            "events": [
                {"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"},
                {"eventAction": "expiration", "eventDate": "2027-03-04T05:06:07Z"},
            ]
        }
    )
    assert (parsed.year, parsed.month, parsed.day) == (2027, 3, 4)
    assert parsed.tzinfo is not None, "a naive datetime would break the days-remaining maths"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"events": "not a list"},
        {"events": [{"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"}]},
        {"events": [{"eventAction": "expiration", "eventDate": "not a date"}]},
        {"events": [{"eventAction": "expiration"}]},
    ],
)
def test_a_malformed_rdap_response_fails_loudly_not_silently(payload: dict[str, object]) -> None:
    """Every shape a registry might hand back raises rather than yielding a wrong date. A
    silently-wrong expiry is worse than none: it would reassure an operator right up to the
    day a squatter takes the domain (T-OP-G4)."""
    from core import domain_expiry

    with pytest.raises(domain_expiry.DomainLookupFailed):
        domain_expiry._parse_expiry(payload)


def test_a_failed_refresh_keeps_the_last_good_expiry_and_records_why(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A registry outage must not throw away a true answer. The health email would rather
    say "expires in 200 days, last checked 20 days ago" than nothing at all."""
    from core import domain_expiry

    now = timezone.now()
    good = now + datetime.timedelta(days=200)
    DomainStatus.objects.create(
        domain=health.instance_domain(),
        expires_at=good,
        checked_at=now - datetime.timedelta(days=20),
    )

    def boom(domain: str) -> datetime.datetime:
        raise domain_expiry.DomainLookupFailed("registry unreachable: timed out")

    monkeypatch.setattr(domain_expiry, "fetch_expiry", boom)
    status = domain_expiry.refresh()

    assert status.expires_at == good, "a failed lookup discarded a true expiry"
    assert "unreachable" in status.error
    # And the email still reports the number, flagged as stale rather than as current.
    field = next(f for f in health.measure(now) if f.label == "Domain")
    assert "expires in 200 days" in field.value and "last checked 20 days ago" in field.value


def test_a_successful_refresh_clears_a_previous_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from core import domain_expiry

    DomainStatus.objects.create(
        domain=health.instance_domain(), error="registry unreachable: timed out"
    )
    fresh = timezone.now() + datetime.timedelta(days=365)
    monkeypatch.setattr(domain_expiry, "fetch_expiry", lambda domain: fresh)

    status = domain_expiry.refresh()
    assert status.error == "", "a recovered lookup left a stale error on the row"
    assert status.expires_at == fresh and status.checked_at is not None


def test_the_domain_lookup_is_registered_on_the_worker_not_the_edge() -> None:
    """S-725 / TS-CO-4: the edge process makes no outbound connections. The lookup being a
    periodic worker task is the structural half of that; asserted so a future refactor
    cannot move it into a view."""
    from core import tasks

    assert hasattr(tasks, "refresh_domain_status_task")
    assert hasattr(tasks, "send_health_email_task")
    import inspect
    import pathlib

    from core import domain_expiry

    # Enumerated from disk, not hardcoded. The list was
    # ("feed_views", "admin_views", "digest_views", "elder_views", "views") — five of the
    # eleven view modules in `core`, so `digesting_views`, `media_views`, `pod_views`,
    # `profile_views`, `provisioning_views` and `pwa_views` could each have grown an outbound
    # RDAP lookup on the edge-facing web process with nothing to notice. A hardcoded
    # enumeration presented as a rule only ever covers what somebody remembered to add.
    #
    # Measured before widening: all eleven pass today, so this closes a gap rather than
    # papering over one.
    root = pathlib.Path(__file__).resolve().parents[1]
    web_modules = sorted(path.stem for path in root.glob("*views*.py"))
    assert len(web_modules) >= 8, (
        f"only {len(web_modules)} view modules found in {root}; the glob is wrong and this "
        "check is inspecting almost nothing"
    )
    for name in web_modules:
        module = __import__(f"core.{name}", fromlist=["x"])
        source = inspect.getsource(module)
        assert "domain_expiry" not in source, (
            f"the outbound lookup reached core.{name}. The RDAP fetch is SSRF-sensitive and "
            "belongs on the worker (S-725, TS-CO-4), never on the edge-facing web process."
        )
    assert domain_expiry.fetch_expiry.__module__ == "core.domain_expiry"


def test_a_redirect_to_a_non_https_scheme_is_refused() -> None:
    """bandit B310, answered by construction rather than by nosec.

    rdap.org is a third-party REDIRECTOR — the second URL in the exchange is chosen by
    someone else — and Python's default handler permits `ftp:` even though it blocks
    `file:`. A control that is only claimed in a comment is the vacuity pattern this
    project keeps finding, so the restriction is exercised here.
    """
    import urllib.error
    import urllib.request

    from core import domain_expiry

    handler = domain_expiry._HttpsOnlyRedirects()
    request = urllib.request.Request("https://rdap.org/domain/example.family")

    for hostile in ("ftp://evil.example/x", "file:///etc/passwd", "http://evil.example/x"):
        with pytest.raises(urllib.error.URLError, match="non-HTTPS"):
            handler.redirect_request(request, None, 302, "Found", {}, hostile)


def test_a_redirect_to_https_is_still_followed() -> None:
    """The other half: refusing everything would break the real lookup, which genuinely
    depends on rdap.org redirecting to the registry that serves the TLD."""
    import urllib.request

    from core import domain_expiry

    handler = domain_expiry._HttpsOnlyRedirects()
    request = urllib.request.Request("https://rdap.org/domain/example.family")
    followed = handler.redirect_request(
        request, None, 302, "Found", {}, "https://rdap.identitydigital.services/rdap/domain/x"
    )
    assert followed is not None, "a legitimate https redirect was refused"
    assert followed.full_url.startswith("https://rdap.identitydigital.services")


def test_the_opener_installs_no_extra_transports() -> None:
    """No proxy handler, no unknown-scheme handler: the only transport it can speak is the
    one installed on purpose."""
    from core import domain_expiry

    # `handlers` exists at runtime but not in the typeshed stub for OpenerDirector.
    installed = {type(h).__name__ for h in domain_expiry._OPENER.handlers}  # type: ignore[attr-defined]
    assert "HTTPSHandler" in installed
    assert "_HttpsOnlyRedirects" in installed
    # These are what `build_opener` silently added, and why the opener is now built from a
    # bare OpenerDirector. Each is a transport this lookup has no business speaking.
    for forbidden in ("FileHandler", "FTPHandler", "DataHandler", "HTTPHandler", "ProxyHandler"):
        assert forbidden not in installed, f"the opener can still speak {forbidden}"


# ---------------------------------------------------------------- reviewer catches, #102


def test_measured_is_false_for_a_field_that_carries_its_reason() -> None:
    """Reviewer catch: `measured` compared the value to the bare marker, but every
    unmeasured value carries its REASON — so it reported all of them as measured. Nothing
    depended on it yet, which is exactly how it would have survived to the first caller
    that did."""
    fields = {f.label: f for f in health.measure()}
    assert not fields["Failed sign-ins"].measured
    assert not fields["Off-box backup age"].measured
    assert fields["Disk headroom"].measured, "a real measurement reported itself unmeasured"


def test_an_already_expired_domain_says_so_instead_of_counting_backwards() -> None:
    """ "expires in -3 days" at the single moment this line matters most. A lapsed domain
    hands every printed QR and elder link to a squatter (T-OP-G4)."""
    now = timezone.now()
    DomainStatus.objects.create(
        domain=health.instance_domain(),
        expires_at=now - datetime.timedelta(days=3),
        checked_at=now,
    )
    field = next(f for f in health.measure(now) if f.label == "Domain")
    assert "EXPIRED 3 days ago" in field.value
    assert "-3" not in field.value, "it still counts backwards"
    assert "renew it NOW" in field.value
    assert field.alarming


def test_an_admin_who_confirmed_then_disabled_the_digest_is_also_excluded() -> None:
    """The send path filters on enabled AND confirmed. An admin who confirmed an address
    and then turned the digest off receives nothing — so a warning that says only "no
    confirmed address" would send on-call chasing the wrong thing."""
    member = Member.objects.create(display_name="Opted Out", role=Member.INSTANCE_ADMIN)
    DigestSubscription.objects.create(
        member=member,
        address="optedout@example.com",
        enabled=False,  # confirmed, but switched off
        confirmed_at=timezone.now(),
        unsubscribe_token_digest="z" * 64,
    )
    mail.outbox.clear()
    result = health_email.send_health_emails()
    assert result.sent == 0
    assert result.skipped_no_confirmed_address == 1
    assert mail.outbox == []
