"""Resend inbound webhook -> the inbound pipeline (S-502, wave 4 provider).

Resend's ``email.received`` webhook is metadata-only; django-anymail's Resend
inbound handler makes the second API fetch for the full message and fires the
``anymail.signals.inbound`` signal with a normalized ``AnymailInboundMessage``.
This receiver is the ONE adapter between that signal and core/inbound: it
serializes the message to raw RFC-5322 bytes and hands them to the same
``process_inbound`` the fixture (and a future IMAP) source uses, so every
security property — size caps, the three kill clocks, From consistency, the
separator strip, dedup, and the second visible_posts lock — is shared with zero
duplication.

The capability is read from the message's ENVELOPE recipient (the address Resend
actually delivered to), never a To/Delivered-To header a sender can forge
(T-EMAIL-1). Anymail verifies the webhook's signature against
``RESEND_INBOUND_SECRET`` before this fires, so an unsigned or wrong-secret POST
never reaches here.

Bounces are NOT emailed: exactly like the fixture pipeline, a failed reply
produces no outbound mail (a From address is forgeable, so auto-replying would be
backscatter). The side effects that matter — a posted comment, a quarantine row,
the dedup ledger — happen inside ``process_inbound``; its InboundResult is
intentionally dropped here.
"""

from __future__ import annotations

from typing import Any

from anymail.signals import inbound
from django.dispatch import receiver

from . import inbound as inbound_pipeline


@receiver(inbound, dispatch_uid="core.inbound_webhook.handle_resend_inbound")
def handle_inbound(sender: object, event: Any, esp_name: str = "", **kwargs: Any) -> None:
    """Process one Anymail-delivered inbound email through the shared pipeline.

    ``process_inbound`` never raises for message-shaped problems (it bounces or
    quarantines), so a genuinely unexpected error here propagates to Anymail,
    which returns HTTP 500 and Resend retries — a transient failure never
    silently drops a family member's reply.
    """
    message = event.message
    raw = bytes(message.as_bytes())
    envelope = message.envelope_recipient or ""
    inbound_pipeline.process_inbound(raw, envelope_recipient=envelope)
