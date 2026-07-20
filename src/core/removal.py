"""Member removal (S-702): the lifecycle flow that revokes, then tears down.

Removal is the T-REMOVE-1 path: a removed member (a removed ex, a departed
relative) loses every credential AND their membership, in one atomic act. The
order is load-bearing and enforced here structurally, which is the fix the
revocation review's H-1 finding asked for:

  1. revoke_member_credentials FIRST, while the member's PodMembership rows still
     exist, because invite voiding resolves the yard scope from live memberships
     (revoking after teardown would silently miss reachable invites, reopening
     T-AUTH-G3).
  2. THEN tear down the memberships.
  3. THEN deactivate the User, so password login dies (the credential class the
     revocation registry names but the generic handler does not touch, because
     voluntary leave and regeneration must not deactivate an account).

The Member row is kept (deactivated), not deleted, so their authored content
stays attributable. The keep-attributed / anonymize / delete choice S-702 also
requires operates on content, which arrives in the feed and media waves; this is
the credential-and-membership half the revocation-completeness test covers.
"""

from __future__ import annotations

from django.db import transaction

from .models import Member, PodMembership
from .revocation import revoke_member_credentials


def remove_member(member: Member) -> None:
    """Remove a member: revoke everything, then detach and deactivate. Atomic."""
    with transaction.atomic():
        # 1. Revoke while memberships are still live (H-1 ordering contract).
        revoke_member_credentials(member)
        # 2. Detach from every pod.
        PodMembership.objects.filter(member=member).delete()
        # 3. Kill password login. Removal-only: leave and regeneration keep the account.
        user = member.user
        if user is not None:
            user.is_active = False
            user.save(update_fields=["is_active"])
