# Permission matrix (S-701)

The written, human-readable companion to `src/core/permissions.py` (the write and
grant authorization model) and `src/core/scoping.py` (the read guard). This is the
"who may do what to whom" reference S-701 requires in the docs. The code is the
source of truth; this table must match it, and the enforcement is exercised by
`src/core/tests/test_permissions.py` and `src/core/tests/test_admin_views.py`.

## The role ladder

Least to most privileged: **supervised < member = pod_owner < yard_admin <
instance_admin**.

That `=` is not a typo, and it used to be a `<`. `pod_owner` grants nothing a plain member
does not already have — see below.

- **supervised**: a managed account (typically a child) with no independent login;
  administered only by its managing parent (or the instance admin). See TM-10.
- **member**: a full participant. Reads and writes within their own audience; has
  no authority over other members.
- **pod_owner**: **grants nothing.** No predicate in `permissions.py` reads this role, so a
  member holding it can do exactly what a member can do. This entry used to claim authority
  "over their own pod's norms and its invites"; both halves were false —
  `pods.set_house_rule` raises `"A household pod has no house rule"`, and
  `can_issue_invite` returns `False` for it.

  The capability people mean by "pod owner" is real, and it is not this role: it is the
  `Pod.owner` **foreign key** on an **ad-hoc** pod, held by whoever created that pod, which
  any plain member may do. The role is a label left over from before that distinction
  existed. The roster no longer offers it (`_ASSIGNABLE_ROLES`); the constant remains for
  rows that already carry it.
- **yard_admin**: manages members, but **only within their own yards**.
- **instance_admin**: the operator of the instance; manages anyone.

## Read authorization

Every read goes through `scoping.py`. A request for something outside the viewer's
yards returns a byte-identical **404** (never a 403), so nothing leaks its
existence (S-202, the isolation suite). This matrix is about *writes and grants*;
reads are governed entirely by that one audience guard.

## Write / grant authorization

`can_manage_member(actor, target)`: may the actor remove, re-role, or otherwise
administer the target?

| actor \ target | self | a full member in the actor's yard(s) | a full member outside (bridging) | an admin (yard/instance) | someone's supervised child |
|---|---|---|---|---|---|
| **member / pod_owner** | no | no | no | no | no (unless they are the managing parent) |
| **yard_admin** | no | **yes** | no (needs instance admin, T-AUTH-G2) | no (no privilege inversion) | only if they are the managing parent, else no |
| **instance_admin** | no | yes | yes | yes | yes |
| **managing parent** (any role) | no | n/a | n/a | n/a | **yes**, for their own children (TM-10) |

Rules the table encodes (all enforced in `permissions.py`):

- **No self-administration.** No one removes or re-roles themselves; recovery and
  role changes come from above (`actor.pk == target.pk` is always denied).
- **Yard scoping (T-AUTH-G2).** A yard admin acts only on targets whose entire yard
  set is a subset of the admin's own yards. A *bridging* member (who also belongs to
  a yard the admin is not in) is out of reach and requires the instance admin, so a
  yard-A admin can never gain a lever over yard B through a shared member.
- **No privilege inversion.** Below the instance admin, no one manages an admin: a
  yard admin cannot remove or re-role an instance admin or a peer yard admin.
- **Supervised children (TM-10).** A supervised account is administered by its
  managing parent (regardless of the parent's own role) or by the instance admin,
  and by no one else.

`can_create_supervised(actor, parent)`: may the actor create a supervised account
that `parent` will manage? The parent themselves may (a parent for their own child);
the instance admin may on anyone's behalf; a yard admin may only if the parent is
within the admin's yard scope.

`can_assign_role(actor, target, new_role)`: role changes follow `can_manage_member`
scope, **and the two admin roles (`yard_admin`, `instance_admin`) are grantable only
by the instance admin**. No one re-roles themselves upward.

`can_edit_profile_of(actor, target)`: may the actor change the target's name, kinship
name and dates? Yourself always (editing your own name is the thing you
should never need a role for, so the self branch is first and is NOT
`can_manage_member`, which denies self-administration on purpose); a supervised child's
managing parent; and **any admin who may already administer the target**, which is
`can_manage_member` and therefore carries every rule in the table above. That last clause
read `is_instance_admin` until BY-11: a yard admin could remove a member of their own side
outright and could not correct their birthday, so a name typed wrong at invite time, or an
elder's details filled in for her — she has no login by design (TM-10) — routed back to
the founder.

**The contact fields are NOT in that widening**, and the second predicate is
`profile_views._may_edit_contact_fields`: yourself, a managing parent, the instance admin —
the set `can_edit_profile_of` had before BY-11. The edit form renders the raw `Member` row
rather than `profiles.viewable_profile`, so SHOWING a phone number or a home address there
is the same disclosure as changing it, and the visibility select beside it would let an
admin publish one to a whole side of the family with nothing telling its owner (the T-YARD-6
shape: a second surface bypassing per-field visibility). The view refuses to write them on
the same predicate the template hides them on, so a hand-written POST is not a way round.

`can_provision_token(actor, target)`: may the actor mint an elder link for the target?
Deliberately STRICTER than `can_manage_member`: the link is a working no-login credential
for the target's **whole** scope, which the issuer can open themselves, so a yard admin
may mint one only for a target whose pods are a subset of their own. Anything wider is the
instance admin's.

**The admin-issued recovery link (BY-01, `core/recovery.py`) is keyed on
`can_manage_member`, not on `can_provision_token`**, and the asymmetry is the point: a
recovery link grants ONE act — setting a password the issuer does not learn — and using it
ends every session the member had, so an issuer who redeemed one themselves would sign the
member out rather than read their family quietly. That signal is real but it is not proof:
an issuer can redeem, read, then mint a SECOND link and hand that one over, leaving the
member with a single unexplained sign-out. The authority is granted on the judgement that a
yard admin who can already remove that member and delete their photographs is not held
back by a password reset — not on the claim that impersonation is impossible. It is
refused for a member with no login (an elder), for a supervised child, who is their
parent's, and for a removed member, whose account is already deactivated. An admin's OWN
recovery is never in the product at all: that is break-glass, which needs server shell
(S-805, T-AUTH-G1), and it is keyed on the INSTANCE_ADMIN role rather than `is_superuser`
so the second admin the succession path creates can be recovered (S10). Recovery FROM
ABOVE is in the product: `can_manage_member` is True for the instance admin against a yard
admin or a peer instance admin, so the roster offers the link on those rows. It grants
nothing they do not already hold via remove and re-role, and it is written down here
rather than implied away.

## Provenance

Grants are the mandatory path for these actions, the same way `scoping.py` is
mandatory for reads. Removal runs the full revocation-and-teardown inventory
(`core/removal.py`, TM-1). See `docs/security/threat-model.md` (T-AUTH-G2, TM-1,
TM-10) and stories S-701 / S-702 / S-703.
