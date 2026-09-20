"""The write/grant authorization model (S-701).

The scoping guard (core/scoping.py) answers "what may this member READ". This
module answers "what may this member DO to another member": remove them, create a
supervised account, change a role, move them between households. It is the mandatory
path for those grants, the same way the guard is mandatory for reads (S-701 hardening),
and the isolation suite enumerates it.

The role ladder, least to most: supervised, member, pod_owner, yard_admin,
instance_admin. The load-bearing rules from S-701 and TM-10:

- Only admins manage members. A plain member or a pod owner cannot remove or
  re-role anyone (a pod owner's powers are their own pod's norms and invites,
  which are separate surfaces).
- A yard admin manages only within their own yards. Acting on a member whose
  yard set is NOT a subset of the acting admin's (a bridging member who also
  belongs to a yard the admin is not in) requires the instance admin. This is
  T-AUTH-G2: a yard-A admin must never gain a lever over yard B through a
  bridging member.
- The managing parent is the exclusive controller of their supervised accounts
  (TM-10): they can act on their own supervised children regardless of admin role,
  and no one below instance admin can act on someone else's supervised child.
- No one re-roles themselves upward, and only the instance admin grants the two
  admin roles (yard_admin, instance_admin).
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet

from . import scoping
from .models import Member, Pod

_ADMIN_ROLES = frozenset({Member.YARD_ADMIN, Member.INSTANCE_ADMIN})
_GRANTABLE_ONLY_BY_INSTANCE_ADMIN = frozenset({Member.YARD_ADMIN, Member.INSTANCE_ADMIN})


def is_instance_admin(member: Member) -> bool:
    return member.role == Member.INSTANCE_ADMIN


def is_admin(member: Member) -> bool:
    return member.role in _ADMIN_ROLES


def administrable_members(actor: Member) -> QuerySet[Member]:
    """The members `actor` may administer (S-707). The instance admin owns the whole
    instance and sits ABOVE yard isolation, so they administer every member — including
    those on a family side they are not a member of, which the seed-ally rollout requires
    (create the other side, invite its first household, then promote its delegate). A yard
    admin administers only the yard-scoped visible set, so resolving a member through here
    keeps the byte-identical 404 for a cross-yard target (S-202). can_manage_member still
    gates the actual action; this only bounds who can be looked up."""
    if is_instance_admin(actor):
        return Member.objects.all()
    return scoping.visible_members(actor)


def _target_within_actor_scope(actor: Member, target: Member) -> bool:
    """True iff every yard the target belongs to is one the actor also belongs to,
    AND the target belongs to at least one yard.

    A yard admin acts only inside their own yards; a target whose yards spill
    outside (a bridging member) is out of a yard admin's reach and needs the
    instance admin (T-AUTH-G2). A target with NO yards is not a vacuous pass: the
    empty set requires the instance admin too (analysis-loop judge finding)."""
    target_yards = scoping.member_yard_ids(target)
    return bool(target_yards) and target_yards <= scoping.member_yard_ids(actor)


def can_manage_member(actor: Member, target: Member) -> bool:
    """May `actor` remove, re-role, or otherwise administer `target`?"""
    if actor.pk == target.pk:
        return False  # no self-administration; recovery and role changes come from above
    if target.is_supervised:
        # A supervised child is managed by their parent, or by the instance admin.
        if target.managing_parent_id == actor.pk:
            return True
        return is_instance_admin(actor)
    if is_instance_admin(actor):
        return True
    # Below the instance admin, no one manages an admin: a yard admin cannot remove
    # or re-role an instance admin or a peer yard admin (no privilege inversion).
    if target.role in _ADMIN_ROLES:
        return False
    if actor.role == Member.YARD_ADMIN:
        return _target_within_actor_scope(actor, target)
    return False


def can_provision_token(actor: Member, target: Member) -> bool:
    """May `actor` mint a bearer credential that carries `target`'s visibility?

    Deliberately stricter than can_manage_member, because it is a different authority.
    Removing or re-roling a member grants the admin nothing; minting an elder link grants
    them a working no-login credential for **the target's whole scope**, which they can
    open themselves.

    can_manage_member's yard-admin branch compares YARD sets only, so a yard admin could
    mint a link for a member of an ad-hoc pod the admin is not in — then read that private
    pod and react in that member's name, defeating S-602's named-attribution backstop.
    T-MINOR-2 grants yard admins pod existence and rosters, never pod CONTENT.

    So a yard admin may provision only for a target whose pods are a subset of their own:
    the credential can then carry nothing the actor could not already see. Anything wider
    is the instance admin's call.
    """
    if not can_manage_member(actor, target):
        return False
    if is_instance_admin(actor):
        return True
    return scoping.member_pod_ids(target) <= scoping.member_pod_ids(actor)


def require_can_provision_token(actor: Member, target: Member) -> None:
    if not can_provision_token(actor, target):
        raise PermissionDenied


def can_edit_profile_of(actor: Member, target: Member) -> bool:
    """May `actor` edit `target`'s profile fields (S-901 acceptance 3)?

    Deliberately NOT `can_manage_member`, which is about removal and roles and forbids
    self-administration on purpose. Editing your own name and birthday is the opposite:
    it is the thing you should never need an admin for, and until now you did — the
    self-edit form covered every field EXCEPT display_name, so a member who married,
    changed their name, or was simply entered wrong had to ask someone with a role.

    Beyond yourself: a supervised child's managing parent, and any admin who may already
    administer the target (can_manage_member). An elder has no login of her own by design
    (TM-10), so the admin who provisions her link is the "designated helper" the story
    names — the model has no separate helper concept, and inventing one here would be a
    new authorization surface rather than a profile edit.

    That second clause used to read `is_instance_admin`, which made two of the three
    likeliest day-one requests route back to the founder: a name typed wrong at invite
    time, and a grandparent's birthday that needs filling in for her. A yard admin could
    REMOVE that member outright and could not correct their birthday. can_manage_member is
    strictly the narrower authority and already carries every isolation rule this needs —
    own yards only, never a peer admin, never a bridging member, never yourself (which is
    why the self branch stays first and separate: editing your own profile is the thing
    you should never need a role for).
    """
    if actor.pk == target.pk:
        return True
    if target.is_supervised and target.managing_parent_id == actor.pk:
        return True
    return is_admin(actor) and can_manage_member(actor, target)


def can_edit_profile_photo_of(actor: Member, target: Member) -> bool:
    """May `actor` set or remove `target`'s profile photo?

    NARROWER than can_edit_profile_of, on the principle profile_views already states for
    contact fields: a face is the most identifying field there is, and an adult with a
    sign-in chooses their own. So: yourself; the managing parent of a supervised child;
    the instance admin; and, for a member with NO sign-in of their own (a grandparent on
    a No-Login Link cannot reach Settings at all), an admin who may manage them. A side
    admin does not put a face on, or take one off, an adult who can do it themselves.
    """
    if actor.pk == target.pk:
        return True
    if target.is_supervised:
        return target.managing_parent_id == actor.pk or is_instance_admin(actor)
    if is_instance_admin(actor):
        return True
    return target.user_id is None and can_manage_member(actor, target)


def can_create_supervised(actor: Member, parent: Member) -> bool:
    """May `actor` create a supervised account managed by `parent`?

    A member may create a supervised account they will manage themselves (a parent
    for their own child); an admin may set one up on a parent's behalf within scope.
    """
    if actor.pk == parent.pk:
        return True
    if is_instance_admin(actor):
        return True
    if actor.role == Member.YARD_ADMIN:
        return _target_within_actor_scope(actor, parent)
    return False


def can_assign_role(actor: Member, target: Member, new_role: str) -> bool:
    """May `actor` set `target`'s role to `new_role`?

    The two admin roles are granted only by the instance admin; other role changes
    follow the same manage-member scope. No one re-roles themselves."""
    if not can_manage_member(actor, target):
        return False
    if new_role in _GRANTABLE_ONLY_BY_INSTANCE_ADMIN:
        return is_instance_admin(actor)
    return True


def can_mint_a_role_granting_invite(actor: Member) -> bool:
    """May `actor` mint an invite whose first redeemer becomes a side admin (R2-6)?

    The family admin, and nobody else. This is the same authority `can_assign_role`
    already fences — `_GRANTABLE_ONLY_BY_INSTANCE_ADMIN` holds the side-admin role — moved
    one step earlier, to the moment the link is made rather than the moment somebody
    redeems it. It has to be earlier: at redeem time there is no actor to ask about, only
    whoever is holding the link.

    Named here rather than written inline in the view for the reason every predicate in
    this module is: an authorization rule spelled in a template or a view is a rule the
    permission tests do not read, and this one hands out administrative reach.

    A side admin is refused even inside their own side. Their authority is over PEOPLE on
    that side (`can_manage_member`), never over who else gets to administer it — a delegate
    who can mint delegates is a delegate who can replace the family admin's roster.
    """
    return is_instance_admin(actor)


def can_change_household(actor: Member, target: Member) -> bool:
    """May `actor` move `target` between households at all — the PERSON half of the act?

    SELF IS THE FIRST BRANCH, and only for the instance admin. The lone owner of a
    self-hosted instance standing up the second side of the family and putting himself in
    it is the ORDINARY case, not the attack: he already holds every side through
    `can_issue_invite`, already administers every member through `administrable_members`,
    and could already mint a household there and redeem his own invite into it — so the
    refusal bought a shell session, not a boundary. Yard isolation is a MEMBER-level
    promise, and T-OP-G1 already discloses that the instance admin sits above it rather
    than pretending otherwise. The act stays deliberate and accountable either way: the
    confirm step names the sides he is about to start seeing, and the `HouseholdChange` row
    records that he did it to himself.

    A yard admin is a different person in this threat model and still may not act on
    themselves. Their authority is BOUNDED BY their own sides, so a self-seat is exactly
    the widening T-AUTH-G2 forbids — and the branch tests `is_instance_admin`, not
    `is_admin`, so that distinction cannot erode.

    The branch is local to this predicate on purpose. `can_manage_member` keeps denying
    self for everybody, because removal and re-roling are a different authority and must
    keep coming from above.

    Everything else is `can_manage_member` plus `is_admin`, and neither half is redundant:
    `can_manage_member` alone is True for a managing parent of ANY role (TM-10), which is
    right for editing their child's profile and wrong here, because placing somebody in a
    household grants a side of the family's whole feed, directory and photographs.

    The yard-subset rule is RE-ASKED here rather than inherited, because that same custody
    branch returns True for a managing parent before the subset test runs. A yard-A admin
    whose own supervised child also belongs to a household in yard B could otherwise take
    that child out of a yard-A household, and the shrink's revocation resolves its scope
    from the child's LIVE memberships — reaching into yard B. Below the instance admin,
    every target of this act is inside the actor's own yards.
    """
    if actor.pk == target.pk:
        return is_instance_admin(actor)
    if not (is_admin(actor) and can_manage_member(actor, target)):
        return False
    return is_instance_admin(actor) or _target_within_actor_scope(actor, target)


def can_change_household_membership(actor: Member, target: Member, pod: Pod) -> bool:
    """The whole act: may `actor` add `target` to `pod`, or take them out of it?

    The POD half is `can_issue_invite`, which is the same authority asked in the same
    direction — "may this admin put a person into this household" — and already carries the
    non-vacuous subset rule a yard admin needs (every one of the pod's sides must be inside
    their own, and a pod in no side is nobody's to fill). Reusing it rather than writing a
    third yard-subset comparison is the point: the two surfaces that place people into a
    household now answer to one predicate and cannot drift apart.

    Households only. An ad-hoc group is a member's own to make, join and leave (S-204,
    S-205); `permissions.py` reads no role for any ad-hoc capability, and giving admins one
    here would be a new power over a private group rather than a household fix.
    """
    return (
        pod.kind == Pod.HOUSEHOLD
        and can_change_household(actor, target)
        and can_issue_invite(actor, pod)
    )


def can_issue_invite(actor: Member, pod: Pod) -> bool:
    """May `actor` mint an invite into `pod`? (S-201/S-701). In v1 only admins
    issue invites: the instance admin for any pod, a yard admin only for a pod
    whose yards are ALL within the admin's own yards (T-AUTH-G2). A pod with no
    yard is never issuable by a yard admin, the same non-vacuous rule as
    _target_within_actor_scope. Pod owners do NOT issue invites in v1: an
    ownership-keyed branch would leak a cross-scope invite (analysis-loop judge
    HIGH finding), so invite authority stays with the two admin roles."""
    if is_instance_admin(actor):
        return True
    if actor.role == Member.YARD_ADMIN:
        pod_yards = scoping.pod_yard_ids(pod)
        return bool(pod_yards) and pod_yards <= scoping.member_yard_ids(actor)
    return False


def require_can_manage_member(actor: Member, target: Member) -> None:
    if not can_manage_member(actor, target):
        raise PermissionDenied
