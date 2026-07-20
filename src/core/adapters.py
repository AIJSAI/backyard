"""allauth adapters: account creation is invite-only (S-101).

allauth mounts an open signup view by default. Backyard never lets a stranger
create an account: the only path that mints a member is the invite redemption
(core/invites.py), which lands as a custom view. Closing allauth's signup here
means the open form renders a "closed" page and any signup POST creates nothing,
so there is no self-serve account surface for a scanner or curious teen to hit
(T-INVITE-1, T-YARD-G1).
"""

from __future__ import annotations

from typing import Any

from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]  # allauth is untyped
    def is_open_for_signup(self, request: Any) -> bool:  # noqa: ARG002
        return False
