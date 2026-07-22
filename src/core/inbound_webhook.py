"""Resend inbound webhook -> the inbound pipeline (S-502, wave 4 provider).

Resend's ``email.received`` webhook is metadata-only; django-anymail's Resend
inbound handler makes the second API fetch for the full message and fires the
``anymail.signals.inbound`` signal. This receiver is the ONE adapter between that
signal and core/inbound: it serializes the message to raw RFC-5322 bytes and
hands them to the same ``process_inbound`` the fixture (and a future IMAP) source
uses, so every security property — size caps, the three kill clocks, From
consistency, the separator strip, dedup, and the second visible_posts lock — is
shared with zero duplication.

The capability is read from the address Resend RECORDED DELIVERING TO, taken from
the webhook payload (``event.esp_event["data"]``), not from the raw-MIME
To/Delivered-To header a sender fully controls (T-EMAIL-1). Anymail's Resend
handler is the one ESP that does not populate ``AnymailInboundMessage.
envelope_recipient`` (verified against the installed anymail source), so we read
Resend's own recipient record here rather than that always-None attribute. NOTE:
whether ``received_for`` (the envelope-delivered-for address) or ``to`` carries
the reply address is confirmed by the wave-4 live round-trip receipt.

Anymail verifies the webhook's signature against ``RESEND_INBOUND_SECRET`` (svix)
before this fires, so an unsigned or wrong-secret POST never reaches here; the
secret is required at boot (config/email_guard.py, TS-PP-8). Bounces are NOT
emailed: like the fixture pipeline, a failed reply produces no outbound mail (a
From address is forgeable, so auto-replying would be backscatter). The side
effects that matter — a posted comment, a quarantine row, the dedup ledger —
happen inside ``process_inbound``; its InboundResult is intentionally dropped.
"""

from __future__ import annotations

from typing import Any

from anymail.signals import inbound
from django.dispatch import receiver

from . import inbound as inbound_pipeline


def _trusted_recipient(esp_event: Any) -> str:
    """The address Resend recorded delivering to, from the webhook payload: its
    envelope-delivered-for record (``received_for``) if present, else the parsed
    recipient (``to``). This is Resend's server-side record, not a raw-MIME
    header a sender controls, so it is the trustworthy capability source
    (T-EMAIL-1). Empty string when neither is present -> process_inbound falls
    back to the message header (the fixture/IMAP contract)."""
    data = (esp_event or {}).get("data") or {}
    for field in ("received_for", "to"):
        value = data.get(field)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str) and value:
            return value
    return ""


@receiver(inbound, dispatch_uid="core.inbound_webhook.handle_resend_inbound")
def handle_inbound(sender: object, event: Any, esp_name: str = "", **kwargs: Any) -> None:
    """Process one Anymail-delivered inbound email through the shared pipeline.

    ``process_inbound`` never raises for message-shaped problems (it bounces or
    quarantines), so a genuinely unexpected error here propagates to Anymail,
    which returns HTTP 500 and Resend retries — a transient failure never
    silently drops a family member's reply.
    """
    message = event.message
    if message is None:
        # Anymail sets message=None for an email.received event that carries no
        # email_id (nothing to fetch or process). Drop it rather than raising:
        # a malformed-but-signed event must not become a poison HTTP-500 retry
        # loop at Resend (security review LOW-1).
        return
    raw = bytes(message.as_bytes())
    recipient = _trusted_recipient(getattr(event, "esp_event", None))
    inbound_pipeline.process_inbound(raw, envelope_recipient=recipient)
