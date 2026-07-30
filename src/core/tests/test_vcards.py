"""vCard export of the family directory (S-904).

Two properties carry this story, and both are tested by trying to break them:

1. **A field the viewer may not see is not in the file.** Not blanked, not present-and-
   empty — absent. Every visibility test here is paired with a probe that flips the field
   to a scope the viewer *does* have, so a test that would pass against a serializer
   emitting nothing at all is not counted as evidence.
2. **A vCard is a line-oriented format, so unescaped member text is property injection.**
   A display name carrying a CRLF and a `TEL:` line would otherwise write a working phone
   number into every card of that member the family downloads.

Plus the boundary the download shares with the rest of the directory: cross-yard is the
same byte-identical 404, and an elder — who by TM-5 gets "no directory contact fields" —
cannot reach either route at all.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from core import elder_tokens, profiles, vcards
from core.models import Member, Pod, PodMembership, Yard

pytestmark = pytest.mark.django_db
User = get_user_model()
_BACKEND = "django.contrib.auth.backends.ModelBackend"
_TEST_PW = "a-Strong-passphrase-9"


def _member_with_user(pod: Pod, name: str) -> Member:
    user = User.objects.create_user(username=name.lower(), password=_TEST_PW)
    member = Member.objects.create(display_name=name, user=user)
    PodMembership.objects.create(member=member, pod=pod)
    return member


def _client_for(member: Member) -> Client:
    assert member.user is not None
    client = Client()
    client.force_login(member.user, backend=_BACKEND)
    return client


@dataclass
class World:
    maternal: Yard
    paternal: Yard
    author: Member
    pod_mate: Member  # same pod as author
    yard_mate: Member  # same yard, different pod
    other: Member  # the other side of the family


@pytest.fixture
def world() -> World:
    maternal = Yard.objects.create(name="Maternal", slug="maternal")
    paternal = Yard.objects.create(name="Paternal", slug="paternal")
    pod_a = Pod.objects.create(name="Cousins A")
    pod_a.yards.set([maternal])
    pod_b = Pod.objects.create(name="Cousins B")
    pod_b.yards.set([maternal])
    p_pod = Pod.objects.create(name="Paternal")
    p_pod.yards.set([paternal])
    return World(
        maternal=maternal,
        paternal=paternal,
        author=_member_with_user(pod_a, "Ann Author"),
        pod_mate=_member_with_user(pod_a, "Pat PodMate"),
        yard_mate=_member_with_user(pod_b, "Yves YardMate"),
        other=_member_with_user(p_pod, "Otto Other"),
    )


def _card_for(viewer: Member, target: Member) -> str:
    """Render exactly what the view renders, through the one visibility resolver."""
    return vcards.render([profiles.viewable_profile(viewer, target)])


def _properties(card: str) -> list[str]:
    """Property names present in a card body, unfolded first."""
    unfolded = card.replace("\r\n ", "")
    return [line.split(":", 1)[0].split(";", 1)[0] for line in unfolded.split("\r\n") if line]


def _components(value: str) -> list[str]:
    """Split a structured vCard value on its UNESCAPED semicolons — which is how a phone
    reads it. Counting raw `;` characters instead would count the escaped ones inside a
    member's own address and call a correct card broken."""
    out: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == ";":
            out.append("".join(current))
            current = []
        else:
            current.append(char)
    out.append("".join(current))
    return out


# --- 1. visibility: what the viewer may not see is absent, and the probe proves it ---


def test_hidden_field_is_absent_from_the_card(world: World) -> None:
    author = world.author
    author.phone = "555-0101"
    author.phone_visibility = Member.HIDDEN
    author.save()

    hidden = _card_for(world.yard_mate, author)
    assert "TEL" not in _properties(hidden)
    assert "555-0101" not in hidden

    # The probe: the same code path with the field scoped to the yard must emit it.
    # Without this, a serializer that dropped TEL unconditionally would pass above.
    author.phone_visibility = Member.YARD
    author.save()
    assert "TEL;TYPE=CELL,VOICE:555-0101" in _card_for(world.yard_mate, author)


def test_pod_scoped_field_reaches_a_pod_mate_and_not_a_yard_mate(world: World) -> None:
    author = world.author
    author.address = "1 Maple St"
    author.address_visibility = Member.POD
    author.contact_email = "ann@example.com"
    author.contact_email_visibility = Member.YARD
    author.save()

    pod_card = _card_for(world.pod_mate, author)
    yard_card = _card_for(world.yard_mate, author)

    assert "1 Maple St" in pod_card and "ADR" in _properties(pod_card)
    assert "1 Maple St" not in yard_card and "ADR" not in _properties(yard_card)
    # Both viewers still get the yard-scoped field, so the yard card is not simply empty.
    assert "ann@example.com" in pod_card and "ann@example.com" in yard_card


def test_a_birthday_never_carries_a_year(world: World) -> None:
    author = world.author
    author.birthday_month, author.birthday_day, author.birthday_year = 3, 5, 1980
    author.birthday_visibility = Member.YARD
    author.save()

    card = _card_for(world.yard_mate, author)
    assert "BDAY:--0305" in card
    # The whole point: the stored year exists and must not appear anywhere in the file,
    # including inside a sentinel-year BDAY that a client would render as a real one.
    assert "1980" not in card
    assert "1604" not in card

    author.birthday_visibility = Member.HIDDEN
    author.save()
    assert "BDAY" not in _properties(_card_for(world.yard_mate, author))


def test_a_leap_day_birthday_survives_the_export(world: World) -> None:
    # A regression pinned deliberately: rendering --MMDD via strptime("%B %d") supplies
    # year 1900, which is not a leap year, so "February 29" raised and the birthday was
    # dropped from the card with no error anywhere.
    author = world.author
    author.birthday_month, author.birthday_day = 2, 29
    author.birthday_visibility = Member.YARD
    author.save()
    assert "BDAY:--0229" in _card_for(world.yard_mate, author)


def test_every_month_name_round_trips_to_a_number(world: World) -> None:
    for month in range(1, 13):
        world.author.birthday_month, world.author.birthday_day = month, 15
        world.author.birthday_visibility = Member.YARD
        world.author.save()
        assert f"BDAY:--{month:02d}15" in _card_for(world.yard_mate, world.author)


def test_an_anniversary_the_viewer_may_not_see_is_absent(world: World) -> None:
    author = world.author
    author.anniversary_month, author.anniversary_day = 6, 14
    author.anniversary_visibility = Member.POD
    author.save()

    assert "Anniversary: June 14" in _card_for(world.pod_mate, author)
    assert "June 14" not in _card_for(world.yard_mate, author)


# --- 2. escaping: member text cannot inject a property line ---


def test_a_crlf_in_a_name_cannot_inject_a_property(world: World) -> None:
    author = world.author
    author.display_name = "Ann\r\nTEL:+15550000000"
    author.save()

    card = _card_for(world.yard_mate, author)
    assert "TEL" not in _properties(card)  # the injected line is not a property
    assert "\\nTEL:+15550000000" in card  # it survives as escaped text in FN
    assert card.count("BEGIN:VCARD") == 1 and card.count("END:VCARD") == 1


def test_delimiters_in_an_address_are_escaped(world: World) -> None:
    author = world.author
    author.address = "1 Maple St, Apt 2; back door\nOmaha, NE"
    author.address_visibility = Member.YARD
    author.save()

    card = _card_for(world.yard_mate, author)
    unfolded = card.replace("\r\n ", "")
    adr = next(line for line in unfolded.split("\r\n") if line.startswith("ADR"))
    # ADR is a seven-component structured value: pobox;ext;street;locality;region;post;
    # country. The whole address belongs in the street slot and nowhere else — an
    # unescaped semicolon in "Apt 2; back door" would otherwise push "back door" into
    # the locality and shift the rest of the address down one field each.
    parts = _components(adr.split(":", 1)[1])
    assert len(parts) == 7
    assert parts[2] == vcards._escape(author.address)
    assert [p for i, p in enumerate(parts) if i != 2] == ["", "", "", "", "", ""]
    assert "\\," in adr and "\\;" in adr and "\\n" in adr


def test_a_backslash_is_escaped_before_the_escapes_we_add(world: World) -> None:
    # Order matters: escaping the delimiters first and the backslash second would turn
    # our own "\," into "\\," and change the value the phone imports.
    assert vcards._escape("a\\b,c") == "a\\\\b\\,c"


def test_control_characters_are_dropped(world: World) -> None:
    assert vcards._escape("Ann\x00\x0bSmith\t") == "AnnSmith\t"


# --- format: a phone has to be able to read it ---


def test_lines_are_crlf_terminated_and_the_card_is_well_formed(world: World) -> None:
    card = _card_for(world.yard_mate, world.author)
    assert card.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
    assert card.endswith("END:VCARD\r\n")
    assert "\n" not in card.replace("\r\n", "")  # no bare LF anywhere
    assert _properties(card)[:2] == ["BEGIN", "VERSION"]


def test_a_long_value_folds_and_unfolds_to_the_original(world: World) -> None:
    author = world.author
    author.address = "Flat 4, " + "The Long Meadow Farmhouse Road " * 4 + "Omaha"
    author.address_visibility = Member.YARD
    author.save()

    card = _card_for(world.yard_mate, author)
    raw_lines = card.split("\r\n")
    assert any(line.startswith(" ") for line in raw_lines), "nothing folded"
    assert all(len(line.encode()) <= 75 for line in raw_lines), "a line exceeded 75 octets"
    # Unfolding must reproduce the value exactly, or the imported address is corrupt.
    unfolded = card.replace("\r\n ", "")
    label = next(line for line in unfolded.split("\r\n") if line.startswith("LABEL"))
    assert label.split(":", 1)[1] == vcards._escape(author.address)


def test_folding_round_trips_at_every_alignment(world: World) -> None:
    """Fold then unfold must be the identity, whatever the fold boundary lands on.

    Written this way after the first version of this test was proven vacuous: it decoded
    each folded line and asserted no error, but folding operates on `str`, which cannot
    hold half a codepoint — so the assertion could not fail for any implementation.
    Round-trip equality can fail, and sweeping the offset means no single lucky alignment
    (where the 75th octet happens to sit on an ASCII byte) hides a bug.
    """
    for offset in range(0, 90):
        value = ("x" * offset) + ("Ståle Grønnedal Vägen " * 6)
        folded = vcards._fold(value)
        assert folded.replace("\r\n ", "") == value, offset
        assert all(len(line.encode()) <= 75 for line in folded.split("\r\n")), offset


def test_a_non_ascii_address_survives_the_card(world: World) -> None:
    author = world.author
    author.address = "Ståle Grønnedal Vägen 12, Malmö"
    author.address_visibility = Member.YARD
    author.save()
    card = _card_for(world.yard_mate, author)
    assert vcards._escape(author.address) in card.replace("\r\n ", "")


def test_the_structured_name_splits_on_the_last_token(world: World) -> None:
    assert vcards._structured_name("Ann Author") == "Author;Ann;;;"
    assert vcards._structured_name("Mary Anne Van Der Berg") == "Berg;Mary Anne Van Der;;;"
    assert vcards._structured_name("Nana") == "Nana;;;;"  # a mononym still sorts
    assert vcards._structured_name("") == ";;;;"


def test_a_kinship_name_becomes_the_nickname(world: World) -> None:
    author = world.author
    author.kinship_name = "Nana"
    author.save()
    assert "NICKNAME:Nana" in _card_for(world.yard_mate, author)


def test_a_card_carries_a_stable_instance_scoped_uid(world: World) -> None:
    with override_settings(BASE_URL="https://backyard.family"):
        first = _card_for(world.yard_mate, world.author)
        second = _card_for(world.yard_mate, world.author)
    uid = f"UID:backyard-{world.author.id}@backyard.family"
    assert uid in first and uid in second


def test_a_naive_now_is_refused_rather_than_silently_shifted(world: World) -> None:
    # Measured: a naive datetime does not raise on .astimezone() — Python reads it as
    # system local time, which stamped a REV five hours off with no error on a UTC-5
    # machine. Refusing beats guessing UTC for the caller.
    profile = profiles.viewable_profile(world.yard_mate, world.author)
    with pytest.raises(ValueError, match="aware"):
        vcards.render([profile], now=datetime.datetime(2026, 7, 29, 15, 4, 5))

    # And the aware path still works, so the guard is not just refusing everything.
    aware = datetime.datetime(2026, 7, 29, 15, 4, 5, tzinfo=datetime.UTC)
    assert "REV:2026-07-29T15:04:05Z" in vcards.render([profile], now=aware)


def test_a_non_utc_aware_now_is_converted_not_stamped_verbatim(world: World) -> None:
    profile = profiles.viewable_profile(world.yard_mate, world.author)
    offset = datetime.timezone(datetime.timedelta(hours=-5))
    stamped = vcards.render([profile], now=datetime.datetime(2026, 7, 29, 10, 4, 5, tzinfo=offset))
    assert "REV:2026-07-29T15:04:05Z" in stamped  # 10:04 at -05:00 is 15:04 UTC


def test_a_tab_survives_escaping_and_the_other_c0_characters_do_not(world: World) -> None:
    # RFC 6350 §3.3 admits TAB in a text value; the rest of C0 is not valid there. Pinned
    # because the docstring claimed all of C0 was dropped while the code kept the tab.
    assert vcards._escape("a\tb") == "a\tb"
    assert vcards._escape("a\x00\x01\x1fb") == "ab"


def test_rev_is_utc_and_the_render_is_otherwise_deterministic(world: World) -> None:
    stamp = datetime.datetime(2026, 7, 29, 15, 4, 5, tzinfo=datetime.UTC)
    card = vcards.render([profiles.viewable_profile(world.yard_mate, world.author)], now=stamp)
    assert "REV:2026-07-29T15:04:05Z" in card


# --- the routes: the same audience boundary as the directory itself ---


def test_member_vcard_downloads_as_a_vcf(world: World) -> None:
    author = world.author
    author.phone = "555-0101"
    author.phone_visibility = Member.YARD
    author.save()

    response = _client_for(world.yard_mate).get(reverse("member_vcard", args=[author.id]))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/vcard; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="ann-author.vcf"'
    assert "555-0101" in response.content.decode()


def test_a_cross_yard_member_vcard_is_a_404(world: World) -> None:
    client = _client_for(world.author)
    cross_yard = client.get(reverse("member_vcard", args=[world.other.id]))
    unknown = client.get(reverse("member_vcard", args=[world.other.id + 10_000]))
    assert cross_yard.status_code == unknown.status_code == 404
    # S-202: the page must carry no signal that one id exists and the other does not.
    # The rendered 404 differs by exactly one thing between any two requests — the
    # per-response CSP nonce — so that is normalised out rather than the assertion
    # softened to a status-code check.
    nonce = re.compile(rb'nonce="[^"]+"')
    assert nonce.sub(b"nonce", cross_yard.content) == nonce.sub(b"nonce", unknown.content)


def test_a_name_that_would_break_a_header_is_slugified(world: World) -> None:
    author = world.author
    author.display_name = '../../etc/passwd"\r\nX-Injected: 1'
    author.save()
    response = _client_for(world.yard_mate).get(reverse("member_vcard", args=[author.id]))
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="etcpasswd-x-injected-1.vcf"'
    assert "X-Injected" not in dict(response.items())


def test_a_name_with_no_sluggable_characters_falls_back_to_the_id(world: World) -> None:
    author = world.author
    author.display_name = "☃☃☃"
    author.save()
    response = _client_for(world.yard_mate).get(reverse("member_vcard", args=[author.id]))
    assert response["Content-Disposition"] == f'attachment; filename="member-{author.id}.vcf"'


def test_directory_vcards_carries_every_visible_member_and_no_one_else(world: World) -> None:
    response = _client_for(world.author).get(reverse("directory_vcards"))
    body = response.content.decode()
    assert response.status_code == 200
    assert body.count("BEGIN:VCARD") == 2  # pod_mate and yard_mate
    assert "Pat PodMate" in body and "Yves YardMate" in body
    assert "Otto Other" not in body  # the other side of the family
    assert "Ann Author" not in body  # you are already in your own phone


def test_the_directory_download_is_not_silently_capped(world: World) -> None:
    # The directory *page* renders at most 200 rows. An address book that stops at a cap
    # is the same lie as one that stops at four, so the download has no cap; 220 proves
    # the page's bound was not copied into it.
    pod = Pod.objects.create(name="Big branch")
    pod.yards.set([world.maternal])
    for index in range(220):
        cousin = Member.objects.create(display_name=f"Cousin {index:03d}")
        PodMembership.objects.create(member=cousin, pod=pod)

    body = _client_for(world.author).get(reverse("directory_vcards")).content.decode()
    assert body.count("BEGIN:VCARD") == 222  # 220 cousins + pod_mate + yard_mate
    assert "Cousin 219" in body


def test_the_download_is_scoped_per_viewer_not_per_instance(world: World) -> None:
    # The other side of the family downloads the same route and gets their own yard.
    body = _client_for(world.other).get(reverse("directory_vcards")).content.decode()
    assert body.count("BEGIN:VCARD") == 0  # Otto shares a yard with nobody else
    assert "Ann Author" not in body and "Pat PodMate" not in body


def test_an_elder_session_cannot_reach_either_download(world: World) -> None:
    # TM-5: the elder token grants read and one-tap react, and explicitly "no directory
    # contact fields". Both routes must be closed to a live elder session, not merely
    # absent from her page.
    nana = Member.objects.create(display_name="Nana", user=None)
    author_membership = world.author.pod_memberships.first()
    assert author_membership is not None
    PodMembership.objects.create(member=nana, pod=author_membership.pod)
    client = Client()
    client.get(reverse("elder_enter", args=[elder_tokens.mint(nana)]))
    assert client.get(reverse("elder_feed")).status_code == 200  # the session is live

    for url in (reverse("directory_vcards"), reverse("member_vcard", args=[world.author.id])):
        response = client.get(url)
        # An elder has user_id NULL by design (TM-10), so she never satisfies the member
        # app's login_required and is sent to sign in — a door she has no key for, which
        # is the point. Asserting the exact shape, not "not a 200": a future change that
        # made this a 500 would still be "not a 200".
        assert response.status_code == 302, url
        assert "login" in response["Location"], url
        assert b"BEGIN:VCARD" not in response.content, url


def test_anonymous_is_sent_to_sign_in(world: World) -> None:
    for url in (reverse("directory_vcards"), reverse("member_vcard", args=[world.author.id])):
        response = Client().get(url)
        assert response.status_code == 302 and "login" in response["Location"], url


def test_the_directory_page_offers_the_download(world: World) -> None:
    body = _client_for(world.author).get(reverse("directory")).content.decode()
    assert reverse("directory_vcards") in body
    profile = _client_for(world.author).get(reverse("member_profile", args=[world.pod_mate.id]))
    assert reverse("member_vcard", args=[world.pod_mate.id]) in profile.content.decode()
