"""The two pages of "change somebody's household" (BY-14).

One route, three states, because they are one act being made deliberate:

* GET — the choices. Add them to a household that already exists, make a new household
  (name plus one or more sides) and put them in it, or take them out of one they are in.
* POST — CONFIRM. What was chosen, said back in plain words, naming the sides of the family
  whose posts, people and photographs this person will start or stop seeing. Nothing has
  happened yet. One act per submit, so the page never has to describe two.
* POST carrying the confirm page's nonce AND matching the fingerprint of what that page
  said — the act, then back to the members list. Both, because the nonce is keyed on the
  person and would otherwise be a permission to change this person's households rather
  than a confirmation of the one change the admin actually read.

Why a confirm step at all, when removal's only got one after a design walk: adding somebody
to a household in a side they were not in HANDS THEM THAT SIDE. It is the only control in
the product that widens what a person can read, it does it silently, and "The Smiths" in a
dropdown does not tell an admin which side of the family that is. The consequence is not
recoverable by undo either — they have seen what they have seen.

Authorization is `permissions.can_change_household_membership`, which is `is_admin` +
`can_manage_member` for the person and `can_issue_invite` for the household. The target is
resolved through `permissions.administrable_members` exactly as `remove`, `assign_role` and
`issue_recovery` do, so a target the actor may not administer is a byte-identical 404
(S-202) rather than a 403 that would confirm the person exists.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import handover, households, permissions, scoping
from .feed_views import _acting_member
from .models import ElderToken, Member, Pod, Yard

ADD = "add"
CREATE = "create"
REMOVE = "remove"
_ACTS = frozenset({ADD, CREATE, REMOVE})
# A family has two sides, or a few. This is not a business rule, it is a bound on how much
# work one POST can ask for: every id past it would be another query for the same answer.
_MAX_SIDES = 20


@dataclass(frozen=True)
class _Proposal:
    """One act, resolved and authorized, but not yet carried out.

    It carries what the confirm page has to SAY (the sides gained or lost) beside what the
    act will DO, both computed from the same membership rows, so the sentence on the page
    and the change to the database cannot describe different things.
    """

    act: str
    pod: Pod | None = None
    name: str = ""
    yards: list[Yard] = field(default_factory=list)
    gained: list[Yard] = field(default_factory=list)
    lost: list[Yard] = field(default_factory=list)

    @property
    def household_name(self) -> str:
        return self.pod.name if self.pod is not None else self.name


@login_required
def change_household(request: HttpRequest, member_id: int) -> HttpResponse:
    """Add somebody who already has an account to a household, or take them out of one."""
    actor = _acting_member(request)
    # is_admin first, so a plain member gets the same refusal whoever they name — including
    # for a member id that does not exist. The administrable set then 404s a target outside
    # the actor's reach, and can_change_household refuses one they can SEE but may not
    # administer: themselves, a peer admin, a bridging member, somebody else's child.
    if not permissions.is_admin(actor):
        raise PermissionDenied
    target = get_object_or_404(permissions.administrable_members(actor), pk=member_id)
    if not permissions.can_change_household(actor, target):
        raise PermissionDenied

    if request.method != "POST":
        return render(request, "core/change_household.html", _choices(actor, target))

    proposal = _proposal(request, actor, target)
    intent_key = f"household_intent:{target.id}"
    shown_key = f"household_shown:{target.id}"
    # The nonce proves a confirm page was rendered; the FINGERPRINT proves it was rendered
    # for THIS act. Keyed on the target alone, the nonce was a permission to change this
    # person's households rather than a confirmation of one change: the sentence the admin
    # read named a household and the sides it carries, and the submit that followed was
    # re-derived from its own POST body and never compared with it. Both have to match, and
    # the fingerprint is checked first so a mismatch does not spend the nonce.
    if request.session.get(shown_key) == _fingerprint(proposal) and handover.consume_intent(
        request, intent_key, request.POST.get("intent")
    ):
        request.session.pop(shown_key, None)
        try:
            _carry_out(actor, target, proposal)
        except households.HouseholdChangeRefused as refusal:
            # The world moved between the confirm page and this submit — another admin
            # added them, or took away the household that made this one not their last.
            # An honest sentence on the page they came from, not a 500.
            return render(request, "core/change_household.html", _choices(actor, target, [refusal]))
        return redirect("members")
    try:
        # Asked here as well as inside the act, so nobody is shown a confirm page for
        # something that is then refused. The act re-asks it in its own transaction.
        _check(target, proposal)
    except households.HouseholdChangeRefused as refusal:
        return render(request, "core/change_household.html", _choices(actor, target, [refusal]))
    response = render(
        request,
        "core/change_household_confirm.html",
        {
            "actor": actor,
            "target": target,
            "proposal": proposal,
            # The nonce for THIS confirmation, minted only now: a replayed submit (the back
            # button, a double tap on a slow phone) finds it spent and lands back here
            # instead of acting twice.
            "intent": _mint_confirmation(request, intent_key, shown_key, proposal),
            "elder": target.user_id is None and ElderToken.objects.filter(member=target).exists(),
        },
    )
    # The same hygiene the sibling admin hand-over pages carry: this page holds a
    # single-use nonce and a list of the family's household names, and a bfcache restore of
    # a walked-away-from admin screen should not bring either back.
    return handover.apply_token_body_headers(response)


def _proposal(request: HttpRequest, actor: Member, target: Member) -> _Proposal:
    """Read the submitted act, resolve every id through a scoped queryset, and work out
    what it would change. An unknown act, or an id outside the actor's reach, is the bare
    404 an unknown resource gets — never a 500 and never an existence oracle."""
    act = request.POST.get("act", "")
    if act not in _ACTS:
        raise Http404
    if act == CREATE:
        # The sides are resolved one by one through the actor's own reach: every side for
        # the instance admin (they own the instance and stand up new sides, S-708), and
        # require_visible_yard for a yard admin, which 404s a side they are not in. The
        # authorization on the finished pod is re-asked inside the service.
        # Capped: each id costs a query, and an instance has a handful of sides, not
        # thousands. An admin posting ten thousand of them is ten thousand queries.
        yard_ids = [
            handover.int_or_404(raw) for raw in request.POST.getlist("yard_ids")[:_MAX_SIDES]
        ]
        yards = [
            get_object_or_404(Yard, pk=yard_id)
            if permissions.is_instance_admin(actor)
            else scoping.require_visible_yard(actor, yard_id)
            for yard_id in yard_ids
        ]
        already = scoping.member_yard_ids(target)
        return _Proposal(
            act=CREATE,
            name=request.POST.get("household_name", "").strip()[:100],
            yards=yards,
            gained=[yard for yard in yards if yard.id not in already],
        )
    pod_id = handover.int_or_404(request.POST.get("pod_id", ""))
    pod = get_object_or_404(households.households_in_reach(actor), pk=pod_id)
    if act == ADD:
        return _Proposal(act=ADD, pod=pod, gained=households.sides_gained(target, pod))
    return _Proposal(act=REMOVE, pod=pod, lost=households.sides_lost(target, pod))


def _fingerprint(proposal: _Proposal) -> str:
    """What the confirm page SAID, in one stable string.

    The sides are in it as well as the household, so a pod whose sides changed between the
    two requests lands the admin back on a fresh confirm page naming the new ones, instead
    of handing somebody a side no page ever mentioned.
    """
    parts = (
        proposal.act,
        str(proposal.pod.id) if proposal.pod is not None else "",
        proposal.name,
        ",".join(str(yard.id) for yard in proposal.yards),
        ",".join(str(yard.id) for yard in proposal.gained),
        ",".join(str(yard.id) for yard in proposal.lost),
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _mint_confirmation(
    request: HttpRequest, intent_key: str, shown_key: str, proposal: _Proposal
) -> str:
    """Mint the nonce for THIS confirmation and record what it confirms. Set AFTER any
    consume, so it never clobbers the one just submitted."""
    request.session[shown_key] = _fingerprint(proposal)
    return handover.fresh_intent(request, intent_key)


def _check(target: Member, proposal: _Proposal) -> None:
    if proposal.act == CREATE:
        households.check_create(proposal.name, proposal.yards)
    elif proposal.pod is not None and proposal.act == ADD:
        households.check_add(target, proposal.pod)
    elif proposal.pod is not None:
        households.check_remove(target, proposal.pod)


def _carry_out(actor: Member, target: Member, proposal: _Proposal) -> None:
    if proposal.act == CREATE:
        households.create_household_and_add(
            actor=actor, member=target, name=proposal.name, yards=proposal.yards
        )
    elif proposal.pod is not None and proposal.act == ADD:
        households.add_to_household(actor=actor, member=target, pod=proposal.pod)
    elif proposal.pod is not None:
        households.remove_from_household(actor=actor, member=target, pod=proposal.pod)


def _choices(
    actor: Member,
    target: Member,
    errors: list[households.HouseholdChangeRefused] | None = None,
) -> dict[str, object]:
    """What the first page offers. The sides are named on every household, because "The
    Smiths" alone does not tell an admin which side of the family they are about to hand
    over — which is the whole thing this page is careful about."""
    joinable = households.households_they_could_join(actor, target).prefetch_related("yards")
    current = households.households_they_are_in(actor, target).prefetch_related("yards")
    return {
        "actor": actor,
        "target": target,
        "errors": [str(error) for error in errors or []],
        # Each household with its sides SPELLED OUT, and the sides walked here rather than
        # in the template. `pod.yards.all()` is the unscoped traversal scoping.py warns
        # about, and it is right here for the same reason `invite_household` lists every
        # side: `households_in_reach` has already bounded these pods to ones wholly inside
        # a yard admin's own sides, and the instance admin sits above yard isolation by
        # design (isolation is a member-level promise). Doing it in the view keeps that
        # judgement written down in one place instead of implied by a `{% for %}`.
        "joinable": [(pod, list(pod.yards.all())) for pod in joinable],
        # Each current household with the sides leaving it would cost, and whether it is
        # their LAST one — in which case the page says so instead of offering a control
        # that would be refused (a link that lies). A member in no household resolves
        # nobody through the guard, including themselves.
        "current": [
            (
                pod,
                list(pod.yards.all()),
                households.is_their_last_household(target, pod),
            )
            for pod in current
        ],
        "sides": list(
            Yard.objects.order_by("name")
            if permissions.is_instance_admin(actor)
            else scoping.visible_yards(actor).order_by("name")
        ),
    }
