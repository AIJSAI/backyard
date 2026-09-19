"""A time this product prints is the family's own time, not the server's.

Found on the production walk, 2026-09-19: a post written at 4:28 in the morning Central
read "9:28 a.m." on the family's own feed. `TIME_ZONE` was Django's "UTC" default and
nothing offered to change it, so every timestamp in the product — feed, thread, invite
expiry, the Family email — was stated calmly, with no hedge, in a zone nobody in the
family lives in.

Two halves, and both are tested here because either alone is wrong:

  * the SERVER renders in the instance's own zone, which is the only zone available to an
    e-mail (composed here, read hours later, no browser to correct it); and
  * the markup carries the instant, so the BROWSER can re-render it into the READER's
    zone — the cousin who moved away reads her own wall clock.

The browser half is JavaScript and is asserted here at the seam a test can hold: the
`<time datetime="...">` element with a real offset, and the server's own text inside it
so the page is correct with no script at all.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import zoneinfo
from typing import Any

import pytest
from django.template import Context, Template
from django.test import Client
from django.urls import reverse

from config.time_zone_guard import DEFAULT, ENV_VAR, validate_time_zone
from core.models import Member, Pod, PodMembership, Post, Yard

_CHICAGO = zoneinfo.ZoneInfo("America/Chicago")


# --- the boot guard ------------------------------------------------------------------


def test_a_real_zone_is_accepted_and_an_unset_one_means_utc() -> None:
    assert validate_time_zone("America/Chicago") == "America/Chicago"
    assert validate_time_zone("UTC") == "UTC"
    # Unset is the documented default, not an operator mistake.
    assert validate_time_zone("") == DEFAULT
    assert validate_time_zone("   ") == DEFAULT


def test_the_variable_the_guard_names_is_the_one_settings_reads() -> None:
    """`ENV_VAR` is what the ERROR MESSAGE prints; settings.py spells the same name out as
    a literal, because test_self_host_docs reads that file as text to prove every
    documented variable is one the app consumes — and an indirection is invisible to it.
    Two spellings of one name is exactly the drift that guard exists to catch, so they are
    compared here rather than trusted."""
    settings_src = (
        pathlib.Path(__file__).resolve().parents[2] / "config" / "settings.py"
    ).read_text()
    assert f'os.environ.get("{ENV_VAR}"' in settings_src, ENV_VAR

    # ...and it has to survive the trip into the container, which is a separate fact: a
    # variable compose does not name never reaches the app however well it is documented.
    compose = (pathlib.Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text()
    assert compose.count(f"{ENV_VAR}: ") == 2, (
        f"{ENV_VAR} must be passed to BOTH web and worker — the worker sends the Family "
        "email, which is written in the instance's zone"
    )


def test_a_typo_refuses_to_boot_and_says_what_to_type_instead() -> None:
    """A wrong zone is a wrong fact on every screen, so it fails loudly rather than
    quietly picking UTC. The message has to be actionable: an operator reading it should
    not have to find this file."""
    with pytest.raises(RuntimeError) as caught:
        validate_time_zone("America/Omaha")  # a real city, not an IANA zone
    message = str(caught.value)
    assert ENV_VAR in message
    assert "America/Chicago" in message, "the error names no example an operator can copy"
    assert "self-host" in message, "the error points at no documentation"


def test_the_guard_is_not_vacuous() -> None:
    """Prove it can reject. A `try: ... except: pass` here would pass everything."""
    for nonsense in ("Mars/Olympus", "GMT+25", "not a zone at all"):
        with pytest.raises(RuntimeError):
            validate_time_zone(nonsense)


# --- the markup ----------------------------------------------------------------------


def _render(template: str, **context: object) -> str:
    return Template("{% load times %}" + template).render(Context(context))


@pytest.mark.parametrize("tag", ["when", "when_date"])
def test_a_timestamp_is_a_time_element_carrying_the_instant(tag: str) -> None:
    """The `datetime` attribute is what makes the browser half possible at all, and it
    carries an explicit offset: a bare naive string is read differently by different
    engines, which would move the time rather than localise it."""
    moment = datetime.datetime(2026, 9, 18, 9, 28, tzinfo=datetime.UTC)
    html = _render("{% " + tag + " moment %}", moment=moment)
    match = re.search(r'<time datetime="([^"]+)" data-when="(\w+)">([^<]+)</time>', html)
    assert match, f"{tag} did not render a <time> element: {html!r}"
    stamp, kind, text = match.groups()
    assert kind == ("datetime" if tag == "when" else "date")
    assert re.search(r"[+-]\d{2}:\d{2}$|\+00:00$", stamp), f"no UTC offset in {stamp!r}"
    assert datetime.datetime.fromisoformat(stamp) == moment, "the instant was altered"
    assert text.strip(), "the element is empty, so a reader with no JavaScript sees nothing"


def test_the_text_inside_is_the_server_s_own_answer_in_the_instance_zone(settings: Any) -> None:
    """With no JavaScript — a text browser, a locked-down phone, a feed reader — the
    server's text is the whole answer, so it must already be right."""
    settings.TIME_ZONE = "America/Chicago"
    moment = datetime.datetime(2026, 9, 18, 9, 28, tzinfo=datetime.UTC)  # 4:28 a.m. Central
    assert ">Sep 18, 4:28 a.m.<" in _render("{% when moment %}", moment=moment)
    assert ">Sep 18, 2026<" in _render("{% when_date moment %}", moment=moment)


def test_the_instance_zone_is_what_moved_the_clock(settings: Any) -> None:
    """The bug itself, as a test: the same instant, two instance zones, two readings."""
    moment = datetime.datetime(2026, 9, 18, 9, 28, tzinfo=datetime.UTC)
    settings.TIME_ZONE = "UTC"
    assert ">Sep 18, 9:28 a.m.<" in _render("{% when moment %}", moment=moment)
    settings.TIME_ZONE = "America/Chicago"
    assert ">Sep 18, 4:28 a.m.<" in _render("{% when moment %}", moment=moment)


def test_a_plain_date_is_never_shifted() -> None:
    """A `date` has no instant to move. Handing one to a browser's zone is how a birthday
    lands on the wrong day, so it renders with no `data-when` and nothing touches it."""
    html = _render("{% when_date day %}", day=datetime.date(2026, 3, 5))
    assert "data-when" not in html, "a plain date was marked for the browser to move"
    assert ">Mar 5, 2026<" in html


def test_a_missing_value_renders_nothing_rather_than_none() -> None:
    assert _render("{% when nothing %}", nothing=None) == ""
    assert _render("{% when_date nothing %}", nothing=None) == ""


# --- the walk ------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_feed_shows_the_family_s_own_time_not_the_server_s(client: Any, settings: Any) -> None:
    """The screen the walk was on. Written 4:28 a.m. Central; it read 9:28."""
    from django.contrib.auth import get_user_model

    settings.TIME_ZONE = "America/Chicago"
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username="cousinreed")
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=member, pod=pod, body="Up with the baby again.")
    post.audience_yards.set([yard])
    Post.objects.filter(pk=post.pk).update(
        created_at=datetime.datetime(2026, 9, 18, 4, 28, tzinfo=_CHICAGO)
    )

    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    body = client.get(reverse("feed")).content.decode()

    assert "Up with the baby again." in body  # non-vacuity: the post really is on the page
    assert ">Sep 18, 4:28 a.m.<" in body, "the feed is still printing the server's zone"
    assert "9:28 a.m." not in body


@pytest.mark.django_db
def test_the_page_carries_the_script_that_moves_it_into_the_reader_s_zone(client: Any) -> None:
    """The second half. It is inline with the response's CSP nonce, like every other
    script in this product — nothing here loosens the policy, and `test_csp.py` is what
    holds that in general."""
    from django.contrib.auth import get_user_model

    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    user = get_user_model().objects.create_user(username="cousinreed")
    member = Member.objects.create(display_name="Cousin Reed", user=user)
    PodMembership.objects.create(member=member, pod=pod)

    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    response = client.get(reverse("feed"))
    body = response.content.decode()

    assert "time[data-when]" in body, "nothing on the page localises the timestamps"
    nonce = re.search(r"'nonce-([A-Za-z0-9_-]+)'", response["Content-Security-Policy"])
    assert nonce, response["Content-Security-Policy"]
    assert f'<script nonce="{nonce.group(1)}">' in body


@pytest.mark.django_db
def test_a_page_with_no_timestamps_ships_no_localiser(client: Any) -> None:
    """The lesson from putting the include in base.html, kept as a test.

    The script carries the response's CSP nonce, which is fresh every request. On every
    page, that put a per-request random string into the 404 body — and a byte-identical
    404 is what makes a denial and a does-not-exist indistinguishable here, which is the
    whole of the cross-side isolation story (S-202). `test_every_dead_link_answers_
    identically` caught it. Each page that renders a stamp opts in instead.
    """
    page = client.get("/no-such-page-at-all/")
    assert page.status_code == 404
    body = page.content.decode()
    assert "time[data-when]" not in body, (
        "the timestamp localiser is on a page with no timestamps, and it carries a "
        "per-request nonce — so this 404 is no longer byte-identical to any other"
    )
    assert "<script" not in body


@pytest.mark.django_db
def test_the_grandparent_s_page_still_shows_dates_only(settings: Any) -> None:
    """Ruled, and kept: no time of day on the no-login page. It is a `<time>` element
    like everywhere else, so a forwarded link opened two zones away still reads right."""
    from core import elder_tokens

    settings.TIME_ZONE = "America/Chicago"
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Nana")
    PodMembership.objects.create(member=member, pod=pod)
    author = Member.objects.create(display_name="Cousin Reed")
    PodMembership.objects.create(member=author, pod=pod)
    post = Post.objects.create(author=author, pod=pod, body="A photo from the weekend")
    post.audience_yards.set([yard])
    Post.objects.filter(pk=post.pk).update(
        created_at=datetime.datetime(2026, 9, 18, 4, 28, tzinfo=_CHICAGO)
    )

    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(member)]))
    body = client.get(reverse("elder_feed")).content.decode()

    assert "A photo from the weekend" in body  # non-vacuity
    assert ">Sep 18, 2026<" in body
    # The VISIBLE text, not the raw HTML: the `datetime` attribute carries the whole
    # instant by design (that is what the browser half reads), so a naive substring
    # search over the source would fail on markup that is exactly right.
    visible = re.sub(r"<[^>]+>", " ", body)
    assert "4:28" not in visible, "the grandparent's page grew a time of day"
    assert "a.m." not in visible and "p.m." not in visible


@pytest.mark.django_db
def test_the_family_email_is_written_in_the_instance_s_own_zone(settings: Any) -> None:
    """An e-mail has no browser to correct it, so the instance zone is the whole answer
    there. This is why the zone is a setting and not only a browser trick."""
    from django.utils import timezone

    from core import digest, digest_links
    from core.models import DigestIssue

    settings.TIME_ZONE = "America/Chicago"
    yard = Yard.objects.create(name="Mom's side", slug="moms-side")
    pod = Pod.objects.create(name="The Reeds")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Cousin Reed")
    PodMembership.objects.create(member=member, pod=pod)
    post = Post.objects.create(author=member, pod=pod, body="A photo from the weekend")
    post.audience_yards.set([yard])
    # 00:30 UTC on the 19th is still the evening of the 18th in Chicago. In UTC this
    # e-mail would have said the 19th — the wrong DAY, not merely the wrong hour.
    Post.objects.filter(pk=post.pk).update(
        created_at=datetime.datetime(2026, 9, 19, 0, 30, tzinfo=datetime.UTC)
    )
    issue = DigestIssue.objects.create(
        member=member,
        yard=yard,
        window_start=timezone.now() - datetime.timedelta(days=7),
        window_end=timezone.now() + datetime.timedelta(minutes=1),
    )

    built = digest.build_digest(
        issue,
        digest_token=digest_links.mint(issue),
        unsubscribe_token="unsub-raw-value",
    )
    assert "A photo from the weekend" in built.text  # non-vacuity
    # The POST's own date line, not the window header — the window is anchored on "now",
    # so asserting over the whole body would pass or fail depending on the day it runs.
    assert "Cousin Reed on September 18:" in built.text, built.text
    assert "on September 19" not in built.text
