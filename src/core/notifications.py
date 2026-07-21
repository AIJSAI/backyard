"""Notification preferences (S-305): a negative guarantee.

The product promise is that Backyard pushes a member nothing unless they explicitly
opt in, and the only opt-in that exists is replies to their own posts. There is no
all-activity firehose. This module is intentionally tiny: it reads and flips the one
boolean. The absence of any other option is the feature, held by tests that assert
the preference model grows no firehose field and defaults to zero push.

No push is actually sent anywhere yet (web push is post-v1 per ADR-002); this records
the single consent so the later reply-notification path has one place to check, and
the guarantee is structural until then.
"""

from __future__ import annotations

from .models import Member, NotificationPreference


def preference_for(member: Member) -> NotificationPreference:
    """The member's preference row, created with the zero-push defaults if absent."""
    pref, _created = NotificationPreference.objects.get_or_create(member=member)
    return pref


def set_reply_notification(member: Member, *, enabled: bool) -> NotificationPreference:
    """Flip the one and only opt-in: replies to my own posts."""
    pref = preference_for(member)
    pref.notify_on_reply = enabled
    pref.save(update_fields=["notify_on_reply"])
    return pref
