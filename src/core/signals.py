"""Cross-cutting signal handlers.

Elder-key cleanup on login (#42 review, the reverse direction of the HIGH):
Django's login() only flushes the session when a DIFFERENT auth user already
owned it, so an elder session that precedes a real login on the same browser
keeps its elder_* keys in the now-authenticated session. Those keys grant
nothing to an authenticated request (the elder views 404 a request whose
member has a login-backed path only through _elder_member, which still works,
but the point is hygiene: a logged-in session should carry no elder capability
state). Drop them on every login so the two session identities never overlap.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpRequest

_ELDER_KEYS = ("elder_member_id", "elder_generation", "elder_big_text")


@receiver(user_logged_in)
def clear_elder_session_keys(
    sender: Any, request: HttpRequest | None = None, **kwargs: Any
) -> None:
    if request is None or not hasattr(request, "session"):
        return
    for key in _ELDER_KEYS:
        request.session.pop(key, None)
