"""A member-facing page that is routed but linked from nowhere does not exist.

The defect: `/settings/digest/` was routed (`urls.py`), rendered fine, and had a working
form -- and the ONLY `{% url 'digest_settings' %}` in the whole codebase was that page's own
form action. Nothing linked to it. The header's "Settings" went to `profile_edit`, whose only
outbound link was "Back to the directory".

So the product's single notification channel could not be switched on by any member,
including the admin. And it did not fail loudly: `health_email.admin_recipients()` filters on
`confirmed_at__isnull=False`, so an instance whose digest page is unreachable also reports its
backup age and disk headroom to NOBODY, every week, silently.

Nothing in the suite could catch that, because every existing test reached such pages by
`reverse()` -- which is exactly the step a real member cannot perform. These tests navigate by
LINK instead.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import Resolver404, get_resolver, resolve, reverse
from django.utils import timezone

from core.models import Comment, Invite, Member, Pod, PodMembership, Post, Yard

_BACKEND = "django.contrib.auth.backends.ModelBackend"
# Enough for every page this product has, several times over. Reaching it means a cursor
# loop, and the crawl says so rather than reporting a truncated result as a finding.
_CRAWL_CAP = 200

User = get_user_model()


def _logged_in_member() -> Client:
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    # No password argument on purpose: force_login() below bypasses authentication, so a
    # literal here would be a credential-shaped string with no reason to exist. The ECC
    # pre-commit guard flagged the first version of this line, and it was right to.
    user = User.objects.create_user(username="m")
    member = Member.objects.create(display_name="M", user=user)
    PodMembership.objects.create(member=member, pod=pod)
    client = Client()
    client.force_login(user, backend=_BACKEND)
    return client


def _hrefs(html: str) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', html))


@pytest.mark.django_db
def test_a_member_can_reach_the_digest_settings_by_following_links() -> None:
    """Navigate the way a person does: feed -> Settings -> the digest page.

    Asserted as a REACHABILITY chain rather than `reverse()`, because the bug was that the
    page was perfectly reachable by URL and unreachable by human.
    """
    client = _logged_in_member()

    feed = client.get(reverse("feed"))
    settings_url = reverse("profile_edit")
    assert settings_url in _hrefs(feed.content.decode()), (
        "the header nav must offer a route into settings"
    )

    settings_page = client.get(settings_url)
    digest_url = reverse("digest_settings")
    assert digest_url in _hrefs(settings_page.content.decode()), (
        "the digest page is routed but nothing links to it, so no member can enable the "
        "only notification channel the product has -- and the weekly health email, which "
        "needs a CONFIRMED subscription, silently reaches nobody"
    )

    assert client.get(digest_url).status_code == 200


@pytest.mark.django_db
def test_the_digest_link_is_not_shown_when_an_admin_edits_someone_else() -> None:
    """A digest address is the member's own; an admin editing another profile must not be
    offered a control that would point THAT person's family email somewhere else.

    Rendered through the real managed-edit route (S-901's third path), not asserted against
    template source. The first version of this test passed a query string the view ignores
    and then fell back to grepping for `{% if not editing_other %}` -- which is precisely
    the source-text-assertion weakness the rest of this file exists to avoid, and it could
    have passed with the link shown to everyone. Review caught it.
    """
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])

    admin_user = User.objects.create_user(username="admin")
    admin = Member.objects.create(display_name="Admin", user=admin_user, role=Member.INSTANCE_ADMIN)
    PodMembership.objects.create(member=admin, pod=pod)

    other_user = User.objects.create_user(username="other")
    other = Member.objects.create(display_name="Other", user=other_user)
    PodMembership.objects.create(member=other, pod=pod)

    client = Client()
    client.force_login(admin_user, backend=_BACKEND)
    digest_url = reverse("digest_settings")

    # Denominator: the admin DOES see it on their own profile, so an absence below means
    # the branch fired rather than the link having vanished everywhere.
    own = client.get(reverse("profile_edit"))
    assert digest_url in _hrefs(own.content.decode())

    managed = client.get(reverse("managed_profile_edit", args=[other.pk]))
    assert managed.status_code == 200, managed.status_code
    assert digest_url not in _hrefs(managed.content.decode()), (
        "an admin editing someone else's profile was offered a link that sets where THAT "
        "person's family email is delivered"
    )


# Routes a person is not supposed to arrive at by clicking, each with the reason. Anything
# NOT listed here must be reachable by following links from the feed, so adding a route
# forces a decision instead of silently widening the gap.
#
# This replaces a hand-maintained list of three names that had to be reachable. That list
# was the defect: it was opt-in, so every route added after it was written was invisible to
# the check, and the check was 1-hop and non-transitive, so a link from ANY other template
# satisfied it — including a link from inside the same orphaned cluster. `members` was
# linked from eight templates and every one of them was in the cluster.
_UNLINKED_BY_DESIGN = {
    # Entrances, reached from outside the product.
    "home": "the signed-out entrance; an authenticated member is redirected to the feed",
    "setup": "the first-run wizard; 404s once an instance admin exists (TM-8)",
    "join": "reached from an invite link somebody was handed, not from inside the product",
    "break_glass": "an emailed recovery link; deliberately has no in-product entrance",
    "elder_enter": "the elder's handed-over token URL, exchanged for a session",
    "elder_feed": "the elder surface; S-601 gives it no links off itself and none into it",
    "elder_react": "an elder-surface form action",
    "elder_text_size": "an elder-surface form action",
    # Email-only, by design: these are what a link in a message resolves to.
    "digest_confirm": "the confirm link inside the digest opt-in email",
    "digest_unsubscribe": "the unsubscribe link every digest carries",
    "digest_web": "the browser copy of a sent digest, linked from that digest",
    "digest_web_post": "a deep link from a digest into one post",
    # Machine surfaces.
    "healthz": "a container healthcheck",
    "robots": "robots.txt",
    "manifest": "the PWA manifest, referenced from <head>",
    "service_worker": "the PWA service worker",
    "icon_192": "a PWA icon, referenced from <head>",
    "icon_512": "a PWA icon, referenced from the manifest",
    "icon_maskable_512": "a PWA icon, referenced from the manifest",
    "serve_media": "an <img src>, not a page",
    "anymail_resend_inbound": "the inbound mail webhook",
    # These were one entry, `"vcard"`, which is not a route — the real names are
    # `directory_vcards` and `member_vcard`. The set is only ever SUBTRACTED, so a stale or
    # misspelled key excuses nothing and says nothing; the list can rot with no signal.
    # `test_every_excluded_route_still_exists` below is the signal.
    "directory_vcards": "a download of the whole directory, offered as an attachment",
    "member_vcard": "one member's contact card, offered as an attachment",
    # Reached only partway through a flow this crawl cannot drive with GETs.
    "compose_cancel": "the Cancel button on the widen-audience confirm step, which only "
    "exists after a POST that proposes widening",
}


def _crawl(client: Client) -> tuple[set[str], set[str], set[tuple[str, int]]]:
    """`(routes that answered, control labels, routes that were OFFERED and refused)`."""
    labels: set[str] = set()
    refused: set[tuple[str, int]] = set()
    routes = _reachable_route_names(client, labels, refused)
    return routes, labels, refused


def _reachable_route_names(
    client: Client, labels: set[str] | None = None, refused: set[tuple[str, int]] | None = None
) -> set[str]:
    """Every route a person can arrive at by starting on the feed and following the product.

    A real crawl, not a source-text scan. Two reasons it has to be:

    * Source text is answerable by writing about it. This repo has been bitten four times by
      a `{% url %}` inside a comment satisfying a check, which is why `comment_stripping.py`
      exists at all.
    * "Some other template links to it" is not reachability. The whole admin cluster
      satisfied that and was still unreachable, because the templates linking to `members`
      were `members_invites.html`, `invite_household.html`, `new_elder.html` and five more —
      all of them inside the cluster, none of them reachable themselves.

    Form actions count as reachable even though they are not followed: a person submits the
    form, so the route is reachable by clicking. Only `href`s are traversed.
    """
    found: set[str] = set()
    refused = refused if refused is not None else set()
    seen_urls: set[str] = set()
    queue = [reverse("feed")]

    # A cursor loop must not run forever. Hitting the cap is reported to the caller rather
    # than swallowed: truncation shrinks `found`, which makes routes look unreachable, and
    # the resulting failure would blame the product for a limit in the crawler.
    while queue and len(seen_urls) < _CRAWL_CAP:
        url = queue.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        response = client.get(url)
        if response.status_code in (301, 302):
            target = response.headers.get("Location", "")
            if target.startswith("/"):
                queue.append(target)
            continue
        if response.status_code != 200 or "text/html" not in response.headers.get(
            "Content-Type", ""
        ):
            continue

        body = response.content.decode()
        # This page answered 200, so everything it offers was reached FROM somewhere a
        # person can stand. Record it as visited-and-open.
        if labels is not None:
            # The words on the controls, so a runbook that says "Members → Add a
            # grandparent" can be checked against what the product actually says.
            for element in re.finditer(
                r"<(?:a|button|summary|legend|h1)\b[^>]*>(.*?)</(?:a|button|summary|legend|h1)>",
                body,
                re.S,
            ):
                text = " ".join(re.sub(r"<[^>]+>", " ", element.group(1)).split())
                if text:
                    labels.add(text)
        for match in re.finditer(r'(?:href|action)="(/[^"#?]*)', body):
            target = match.group(1)
            try:
                name = resolve(target).url_name or ""
            except Resolver404:
                continue
            if match.group(0).startswith("href"):
                # An href is an OFFER, not an arrival. Follow it and see what it answers —
                # a link that 403s is a link that lies, and counting it as reachable is how
                # `Elder link` (rendered on `can_manage_member`, gated on the stricter
                # `can_provision_token`) read as reachable while 403-ing for a yard admin.
                if target not in seen_urls:
                    queue.append(target)
                answer = client.get(target)
                if answer.status_code in (403, 404):
                    refused.add((name, answer.status_code))
                    continue
            found.add(name)

    for url in seen_urls:
        try:
            found.add(resolve(url).url_name or "")
        except Resolver404:
            continue
    assert not queue, (
        f"the crawl hit its {_CRAWL_CAP}-URL cap with {len(queue)} links still queued, so "
        "everything below is measured against a TRUNCATED walk. Truncation shrinks the "
        "reachable set, so the next assertion would blame the product for a limit in this "
        "crawler. Find the cursor loop, or raise the cap deliberately."
    )
    return found


@pytest.mark.django_db
def test_every_route_is_reachable_by_clicking_or_is_listed_as_deliberately_not() -> None:
    """The general form of the bug, walked rather than grepped.

    `/settings/digest/` was routed, rendered, had a working form, and no member could get
    to it. So did `/settings/notifications/`, one route over, for a month after the digest
    was fixed — while the feed told every new member "Nothing is ever sent to you unless
    you turn it on in Settings". So did `/members/` and the ten routes behind it, which is
    the entire surface a delegate needs to onboard anyone.
    """
    admin_user = User.objects.create_user(username="crawl-admin")
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    admin = Member.objects.create(
        display_name="Crawl Admin", user=admin_user, role=Member.INSTANCE_ADMIN
    )
    PodMembership.objects.create(member=admin, pod=pod)
    # The instance needs CONTENT, or the crawl reports "unreachable" for every route whose
    # link only exists beside a post, a reply, an invite or a pod it can act on. That would
    # be an artefact of an empty fixture rather than a defect in the product, and it would
    # push toward listing real defects in _UNLINKED_BY_DESIGN to get to green.
    other = Member.objects.create(display_name="Someone Else")
    PodMembership.objects.create(member=other, pod=pod)
    post = Post.objects.create(author=admin, pod=pod, body="something to act on")
    Comment.objects.create(post=post, author=other, body="a reply to act on")
    Comment.objects.create(post=post, author=admin, body="my own reply, to delete")
    Invite.objects.create(
        pod=pod,
        token_digest="crawl-digest",
        created_by=admin,
        expires_at=timezone.now() + timedelta(days=7),
    )
    adhoc = Pod.objects.create(name="An ad-hoc group", kind=Pod.ADHOC, owner=admin)
    adhoc.yards.set([yard])
    PodMembership.objects.create(member=admin, pod=adhoc)

    client = Client()
    client.force_login(admin_user, backend=_BACKEND)
    reachable = _reachable_route_names(client)

    # Denominator, measured rather than assumed: if the crawl stalls on the first page the
    # assertion below passes trivially by finding everything "unreachable"... no — it would
    # FAIL loudly, which is the safe direction. This guards the opposite: a crawl that
    # somehow reports everything reachable proves nothing either.
    assert reverse("members") and len(reachable) > 8, (
        f"the crawl only reached {sorted(reachable)}; it is not walking the product, so "
        "this check cannot fail for the right reason"
    )

    # Only top-level `path(..., name=...)` entries: an included URLconf (allauth's, the
    # webhook's) owns its own reachability and is not this project's to police.
    all_named: set[str] = {
        name
        for pattern in get_resolver().url_patterns
        if isinstance(name := getattr(pattern, "name", None), str)
    }
    unreachable = sorted(all_named - reachable - set(_UNLINKED_BY_DESIGN))
    assert not unreachable, (
        f"routed, but a signed-in instance admin cannot reach them by clicking: "
        f"{unreachable}.\n\nA member cannot type a URL they have never seen. Either link "
        "it from somewhere they already are, or add it to _UNLINKED_BY_DESIGN with the "
        "reason it has no entrance."
    )


def test_every_excluded_route_still_exists() -> None:
    """`_UNLINKED_BY_DESIGN` is only ever SUBTRACTED, so a stale key excuses nothing and
    reports nothing. It contained `"vcard"`, which is not a route at all — the real names
    are `directory_vcards` and `member_vcard` — so the entry had been a no-op since it was
    written, and would have gone on misleading whoever edited the list next."""
    all_named = {
        name
        for pattern in get_resolver().url_patterns
        if isinstance(name := getattr(pattern, "name", None), str)
    }
    stale = sorted(set(_UNLINKED_BY_DESIGN) - all_named)
    assert not stale, (
        f"_UNLINKED_BY_DESIGN names routes that do not exist: {stale}. Each entry excuses a "
        "route from the reachability check, so one that matches nothing is silently dead."
    )


@pytest.mark.django_db
def test_a_plain_member_is_not_offered_the_admin_cluster() -> None:
    """The other half: the Members link is role-gated, and the gate is the real predicate.

    Without this, the fix for the defect above would be "show everyone the admin link",
    which trades an unreachable surface for a misleading one.
    """
    user = User.objects.create_user(username="plain")
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    member = Member.objects.create(display_name="Plain", user=user)
    PodMembership.objects.create(member=member, pod=pod)

    client = Client()
    client.force_login(user, backend=_BACKEND)
    feed = client.get(reverse("feed")).content.decode()
    assert reverse("members") not in _hrefs(feed), (
        "a plain member was offered the admin roster in the site header"
    )

    # Denominator: the same header DOES offer it to an admin, so the absence above is the
    # role branch firing rather than the link having been removed altogether.
    member.role = Member.YARD_ADMIN
    member.save(update_fields=["role"])
    feed = client.get(reverse("feed")).content.decode()
    assert reverse("members") in _hrefs(feed), (
        "a yard admin was NOT offered the roster — which is the role that needs it most, "
        "since a yard admin is exactly the delegate who onboards their own side"
    )


# `Members` → `Invite a household` — the shape every navigation instruction in the delegate
# runbook takes. Both halves must be things the product actually says out loud.
_NAV_INSTRUCTION = re.compile(r"`([A-Z][^`\n]{0,30})`\s*→\s*`([^`\n]{0,40})`")
_DELEGATE_RUNBOOK = (
    Path(__file__).resolve().parents[3] / "docs" / "runbooks" / "setting-up-your-side.md"
)


@pytest.mark.django_db
def test_the_delegate_runbook_names_controls_that_exist() -> None:
    """The runbook a non-technical relative follows must describe the product they see.

    Every navigation instruction in `setting-up-your-side.md` was wrong. It said
    "Members → Invite a household" as though `Members` were a menu item; there was no such
    item, no URL anywhere in the document, and no sign-in step — so its own opening promise,
    "if a step is not here, you do not have to do it", was false for every step. The person
    it was written for had nothing to click.

    Checked against the RENDERED product rather than against templates, because the question
    is what a reader sees, and a label inside a template a delegate cannot reach is not an
    answer.
    """
    # A YARD admin, not an instance admin. `setting-up-your-side.md` opens by telling the
    # reader they must have been made "a **yard admin** (or an instance admin)" — so
    # validating its instructions as an instance admin certifies sentences that are false for
    # the reader it is written for. An instance admin sees a strictly larger roster.
    admin_user = User.objects.create_user(username="runbook-admin")
    yard = Yard.objects.create(name="Y", slug="y")
    pod = Pod.objects.create(name="P")
    pod.yards.set([yard])
    admin = Member.objects.create(
        display_name="Runbook Admin", user=admin_user, role=Member.YARD_ADMIN
    )
    PodMembership.objects.create(member=admin, pod=pod)
    PodMembership.objects.create(member=Member.objects.create(display_name="Someone"), pod=pod)

    client = Client()
    client.force_login(admin_user, backend=_BACKEND)
    _, labels, _refused = _crawl(client)

    instructions = _NAV_INSTRUCTION.findall(_DELEGATE_RUNBOOK.read_text(encoding="utf-8"))
    assert len(instructions) >= 4, (
        f"only {len(instructions)} navigation instructions parsed from "
        f"{_DELEGATE_RUNBOOK.name}; the extractor is broken, so this check proves nothing"
    )

    # EXACT match against a control's own text, not a substring of one.
    #
    # The first version of this asked `any(label in seen for seen in labels)`, and it was
    # vacuous: rewriting the runbook to say "Admin → Invite a household" still passed,
    # because "Admin" is a substring of the fixture member's display name rendered in a
    # heading. A substring standing in for a structural property is the exact defect the
    # rest of this file exists to remove, and it took one measurement to find it here —
    # break the runbook, watch the guard not care.
    missing = sorted(
        {
            label
            for instruction in instructions
            for label in instruction
            if label.casefold() not in {seen.casefold() for seen in labels}
        }
    )
    assert not missing, (
        f"{_DELEGATE_RUNBOOK.name} tells a delegate to click {missing}, and no control an "
        "admin can reach says that. The runbook is describing a product that does not "
        "exist — which is exactly how it read before `Members` was added to the nav."
    )


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Member.YARD_ADMIN, Member.INSTANCE_ADMIN])
def test_no_link_the_product_offers_is_refused_when_you_click_it(role: str) -> None:
    """A link that 403s is a link that lies.

    The crawl used to count an `href` the moment it saw one, without ever asking what the
    destination answered. That is how `Elder link` read as reachable while refusing: the
    roster rendered it on `can_manage_member`, but `provision_elder` gates on the
    deliberately stricter `can_provision_token` — minting an elder link hands over a working
    no-login credential for the target's WHOLE SCOPE, so a yard admin may only do it for
    someone whose pods are a subset of their own.

    Measured before the fix: a yard admin saw `Elder link` on a member of another household
    in their yard, and clicking it returned 403 — while `setting-up-your-side.md` tells them
    to click exactly that when a grandparent's link goes to the wrong person.

    Parameterised over BOTH admin roles, because the instance admin sees a strictly larger
    roster and the yard admin is the one the delegate runbook is written for.
    """
    yard = Yard.objects.create(name="Maternal", slug="maternal")
    own = Pod.objects.create(name="Their own household")
    own.yards.set([yard])
    other = Pod.objects.create(name="A different household")
    other.yards.set([yard])

    user = User.objects.create_user(username="admin-clicks")
    admin = Member.objects.create(display_name="Admin", user=user, role=role)
    PodMembership.objects.create(member=admin, pod=own)
    # Someone in the same yard but a household the actor is not in — the exact shape that
    # separates can_manage_member from can_provision_token.
    elsewhere = Member.objects.create(display_name="Someone Elsewhere")
    PodMembership.objects.create(member=elsewhere, pod=other)

    client = Client()
    client.force_login(user, backend=_BACKEND)
    _, _labels, refused = _crawl(client)

    assert not refused, (
        f"as {role}, the product offered links that refuse on click: {sorted(refused)}. "
        "Rendering a control the viewer may not use is worse than hiding it — they are told "
        "the thing is theirs to do, and the refusal reads as a fault."
    )
