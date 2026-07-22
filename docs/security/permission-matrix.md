# Permission matrix (S-701)

The written, human-readable companion to `src/core/permissions.py` (the write and
grant authorization model) and `src/core/scoping.py` (the read guard). This is the
"who may do what to whom" reference S-701 requires in the docs. The code is the
source of truth; this table must match it, and the enforcement is exercised by
`src/core/tests/test_permissions.py` and `src/core/tests/test_admin_views.py`.

## The role ladder

Least to most privileged: **supervised < member < pod_owner < yard_admin <
instance_admin**.

- **supervised**: a managed account (typically a child) with no independent login;
  administered only by its managing parent (or the instance admin). See TM-10.
- **member**: a full participant. Reads and writes within their own audience; has
  no authority over other members.
- **pod_owner**: a member's authority is over their own pod's norms and its invites
  (a separate surface from member administration). A pod owner does not remove or
  re-role anyone.
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

## Provenance

Grants are the mandatory path for these actions, the same way `scoping.py` is
mandatory for reads. Removal runs the full revocation-and-teardown inventory
(`core/removal.py`, TM-1). See `docs/security/threat-model.md` (T-AUTH-G2, TM-1,
TM-10) and stories S-701 / S-702 / S-703.
