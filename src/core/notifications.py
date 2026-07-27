"""Notification preferences (S-305): a negative guarantee.

The product promise is that Backyard pushes a member nothing unless they explicitly
opt in, and the only opt-in that exists is replies to their own posts. There is no
all-activity firehose. This module is intentionally tiny: it reads and flips the one
boolean. The absence of any other option is the feature, held by tests that assert
the preference model grows no firehose field and defaults to zero push.

Web push is still post-v1 per ADR-002, but the opt-in is no longer a dead switch: the
nudge goes out as EMAIL, over the same Anymail path everything else uses, gated on the
same one boolean. Before this, the settings page told the member "the only thing you can
turn on is a nudge when someone replies to your own post", the box was stored, and no
sending path anywhere read it — so ticking it produced silence indistinguishable from
nobody having replied.

Four conditions, all required, all of them the guarantee rather than decoration:

* the member opted in (default False — silence is the default and stays it),
* the reply is on a post they wrote, and is not their own reply to themselves,
* the address is one they CONFIRMED through the digest double opt-in (T-EMAIL-6), so a
  nudge can never be the thing that mails an unverified address, and
* the replier is still someone that member can see, re-resolved live at send time.

The mail carries no reply text and no photograph — only that someone replied, and a link
back. A notification that quotes content would become a second content path around the
audience query, and there is exactly one.
"""

from __future__ import annotations

import logging

from . import emailing, scoping
from .models import Comment, Member, NotificationPreference

logger = logging.getLogger(__name__)


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


def notify_reply(comment: Comment) -> bool:
    """Email the post's author that someone replied, if they asked to be told.

    Returns whether a nudge was sent, so callers and tests can assert on the silence as
    readily as on the send. Best-effort by construction: a transport failure must never
    fail the reply that triggered it — the reply is the member's writing, the nudge is a
    courtesy.
    """
    author = comment.post.author
    if comment.author_id == author.pk:
        return False  # replying to yourself is not news
    if not preference_for(author).notify_on_reply:
        return False  # the default, and the guarantee

    subscription = getattr(author, "digest_subscription", None)
    if subscription is None or subscription.confirmed_at is None:
        # No confirmed address means no send. The digest double opt-in (T-EMAIL-6) is the
        # only thing that verifies an address here, so a nudge never becomes the first
        # message to an unverified inbox.
        return False

    # Re-resolved live rather than trusted from the comment row: if the replier has since
    # left the author's yards, the author is not told their name.
    if not scoping.visible_members(author).filter(pk=comment.author_id).exists():
        return False

    who = comment.author.display_name
    url = emailing.absolute_url(f"/posts/{comment.post_id}/")
    try:
        emailing.send_family_email(
            to=subscription.address,
            subject=f"{who} replied to your post",
            text=(
                f"{who} replied to your post on Backyard.\n\n"
                f"Read it here: {url}\n\n"
                "You are getting this because you turned on reply notifications. "
                "You can turn them off any time in your settings."
            ),
        )
    except Exception:  # noqa: BLE001 - a courtesy must never fail the member's reply
        logger.warning("reply nudge failed for member %s", author.pk, exc_info=True)
        return False
    return True
