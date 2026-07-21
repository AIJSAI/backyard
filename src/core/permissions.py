"""The write/grant authorization model (S-701).

The scoping guard (core/scoping.py) answers "what may this member READ". This
module answers "what may this member DO to another member": remove them, create a
supervised account, change a role. It is the mandatory path for those grants, the
same way the guard is mandatory for reads (S-701 hardening), and the isolation
suite enumerates it.

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

from . import scoping
from .models import Member

_ADMIN_ROLES = frozenset({Member.YARD_ADMIN, Member.INSTANCE_ADMIN})
_GRANTABLE_ONLY_BY_INSTANCE_ADMIN = frozenset({Member.YARD_ADMIN, Member.INSTANCE_ADMIN})


def is_instance_admin(member: Member) -> bool:
    return member.role == Member.INSTANCE_ADMIN


def is_admin(member: Member) -> bool:
    return member.role in _ADMIN_ROLES


def _target_within_actor_scope(actor: Member, target: Member) -> bool:
    """True iff every yard the target belongs to is one the actor also belongs to.

    A yard admin acts only inside their own yards; a target whose yards spill
    outside (a bridging member) is out of a yard admin's reach and needs the
    instance admin (T-AUTH-G2)."""
    return scoping.member_yard_ids(target) <= scoping.member_yard_ids(actor)


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
    if actor.role == Member.YARD_ADMIN:
        return _target_within_actor_scope(actor, target)
    return False


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


def require_can_manage_member(actor: Member, target: Member) -> None:
    if not can_manage_member(actor, target):
        raise PermissionDenied
