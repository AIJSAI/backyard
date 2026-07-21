"""Inbound reply-by-email (S-502): bounded parse, resolve, strip, post.

One pipeline for every inbound message regardless of adapter (the fixture
source today, IMAP when the mailbox exists): cap sizes before parsing, find the
reply capability in the recipient address, run the three kill clocks, check
From: for consistency (quarantine on mismatch — NEVER attribute from it,
T-EMAIL-1), dedupe on Message-ID + capability (an IMAP re-poll never posts
twice), strip everything below the digest's deterministic separator (a missing
separator quarantines rather than republishing a quoted digest, T-EMAIL-G2),
and write through commenting.create_comment — whose independent visible_posts
re-check is the second lock, so a valid capability for a post outside the
sender's CURRENT audience bounces exactly like an unknown address.

Documented postures, on the record: a TOP-quoting client (quoted digest above
the user's words) quarantines rather than posts — fail-closed for T-EMAIL-G2,
at the cost of losing that client's replies to the admin panel; recovering the
below-quote text is a founder product decision. A Message-ID-less client that
sends two byte-identical short replies dedupes the second (narrow, fail-safe).
Invalid-capability bounces are unmetered (cheap, never sent, private mailbox)
and the ledger is unpruned — both fine at family scale, revisit with volume.

Bounces are built by one branch-free constructor: "no such thread" and "not
your thread" are the same bytes (the email analog of the guard's 404 parity).
Quarantine rows hold mail content, so they surface only on the instance-admin
panel and are deleted once handled (T-OP-G2).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from email.utils import parseaddr

from django.core.cache import cache
from django.db import IntegrityError, transaction

from . import commenting, digest, reply_addresses
from .models import DigestSubscription, InboundLedger, InboundQuarantine

# MTA-edge shapes (T-EMAIL-4, TS-PP-7): applied before real parsing.
_MAX_MESSAGE_BYTES = 256 * 1024
_MAX_PARTS = 20
_MAX_BODY_CHARS = 2000  # a reply is a comment; the composer's cap applies
_EXCERPT_CHARS = 500  # what a quarantine row retains for the admin
# Per-capability inbound ceiling, on the shared DatabaseCache (TS-DJ-13).
_RATE_LIMIT_PER_HOUR = 20

# A quoting client's attribution line, e.g. "On Mon, Jul 20 ... wrote:" or
# Outlook's "-----Original Message-----".
_ATTRIBUTION_LINE = re.compile(r"^(On .{0,200}wrote:|-{3,}\s*Original Message\s*-{3,})$")

# One constant, one construction path: byte-identical for every refusal shape
# that must not leak thread existence (S-502 hardening verbatim).
BOUNCE_TEXT = (
    "This reply could not be delivered to your family's Backyard.\n\n"
    "The reply address in this email is not active. Digest reply addresses "
    "only work for a few weeks; please reply to a newer digest email, or "
    "visit your backyard directly.\n"
)


@dataclass(frozen=True)
class InboundResult:
    outcome: str  # "posted" | "bounced" | "quarantined" | "duplicate"
    bounce_text: str | None = None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bounce() -> InboundResult:
    """THE bounce. No arguments on purpose: there is nothing to vary, so no
    caller can accidentally make 'no such thread' differ from 'not your
    thread' by a byte."""
    return InboundResult(outcome="bounced", bounce_text=BOUNCE_TEXT)


def _quarantine(
    reason: str, *, from_header: str = "", body: str = "", member_id: int | None = None
) -> InboundResult:
    InboundQuarantine.objects.create(
        reason=reason,
        from_header=from_header[:254],
        body_excerpt=body[:_EXCERPT_CHARS],
        member_id=member_id,
    )
    return InboundResult(outcome="quarantined")


def _walk_capped(message: Message) -> list[Message]:
    """The message's parts, refusing bombs: too many parts or too deep raises
    ValueError before any content is touched (TS-PP-7)."""
    parts: list[Message] = []

    def walk(node: Message, depth: int) -> None:
        if depth > 5:
            raise ValueError("nesting too deep")
        if node.is_multipart():
            for child in node.get_payload():
                if not isinstance(child, Message):
                    raise ValueError("malformed multipart payload")
                walk(child, depth + 1)
        else:
            parts.append(node)
        if len(parts) > _MAX_PARTS:
            raise ValueError("too many parts")

    walk(message, 0)
    return parts


def _plain_text_of(message: Message) -> str:
    """The first text/plain part, decoded and size-capped. HTML is stripped by
    ignoring it; attachments are ignored (S-502 spec)."""
    for part in _walk_capped(message):
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")[: _MAX_BODY_CHARS * 4]
    return ""


def _capability_of(message: Message) -> str:
    """The reply capability from the recipient address's local part. The
    address IS the credential; every other header is untrusted decoration."""
    for header in ("Delivered-To", "To"):
        _display, address = parseaddr(str(message.get(header, "")))
        if "@" in address:
            return address.rsplit("@", 1)[0]
    return ""


def _strip_below_separator(body: str) -> str | None:
    """Everything above the digest's deterministic separator, or None if the
    separator is nowhere in the reply (T-EMAIL-G2: never guess, never post the
    quoted tail). Quote prefixes ('> ') in front of the separator line are
    tolerated: clients quote the digest, separator included."""
    for lineno, line in enumerate(body.splitlines()):
        if digest.REPLY_SEPARATOR in line:
            kept = body.splitlines()[:lineno]
            # Drop a trailing client attribution line ("On ... wrote:",
            # "-----Original Message-----") so the sending address never posts
            # into the thread (#39 review LOW-2). Cosmetic; the separator rule
            # above is the security boundary.
            while kept and (_ATTRIBUTION_LINE.match(kept[-1].strip()) or not kept[-1].strip()):
                kept.pop()
            return "\n".join(kept).strip()
    return None


def _strip_control(text: str) -> str:
    """Comment bodies keep newlines and tabs; every other control char dies."""
    return "".join(ch for ch in text if ch in ("\n", "\t") or ch.isprintable())


def process_inbound(raw: bytes) -> InboundResult:
    """One inbound message through the whole pipeline. Never raises for
    message-shaped problems: every failure is a bounce or a quarantine row."""
    if len(raw) > _MAX_MESSAGE_BYTES:
        return _quarantine(InboundQuarantine.MALFORMED)
    try:
        message = message_from_bytes(raw)
        body = _plain_text_of(message)
    except (ValueError, UnicodeError, LookupError):
        return _quarantine(InboundQuarantine.MALFORMED)

    local_part = _capability_of(message)
    try:
        address = reply_addresses.resolve(local_part)
    except reply_addresses.ReplyAddressInvalid:
        return _bounce()

    # Rate ceiling per capability, before any further work (shared cache).
    rate_key = f"inbound-rate:{_sha(local_part)}"
    if cache.get_or_set(rate_key, 0, timeout=3600) >= _RATE_LIMIT_PER_HOUR:  # type: ignore[operator]
        return _quarantine(InboundQuarantine.RATE_LIMITED, member_id=address.member_id)
    try:
        cache.incr(rate_key)
    except ValueError:
        # The key was culled between get_or_set and incr (#39 review MED-1):
        # the pipeline never raises for cache weather; restart the counter.
        cache.set(rate_key, 1, timeout=3600)

    # From: is a consistency check ONLY (T-EMAIL-1): mismatch quarantines and
    # never attributes; match proves nothing (it is spoofable) and grants
    # nothing — attribution stays with the capability.
    _display, from_address = parseaddr(str(message.get("From", "")))
    subscription = DigestSubscription.objects.filter(member=address.member).first()
    expected = subscription.address if subscription else ""
    if not from_address or from_address.lower() != expected.lower():
        return _quarantine(
            InboundQuarantine.FROM_MISMATCH,
            from_header=from_address,
            body=body,
            member_id=address.member_id,
        )

    # Idempotency: the same message on the same capability posts once, ever.
    message_id = str(message.get("Message-ID", "")).strip()
    ledger_key = _sha(message_id) if message_id else _sha(body[:1000])
    try:
        with transaction.atomic():
            InboundLedger.objects.create(
                message_id_digest=ledger_key, local_part_digest=_sha(local_part)
            )
    except IntegrityError:
        return InboundResult(outcome="duplicate")

    above = _strip_below_separator(body)
    if above is None:
        return _quarantine(
            InboundQuarantine.NO_SEPARATOR,
            from_header=from_address,
            body=body,
            member_id=address.member_id,
        )
    comment_body = _strip_control(above)[:_MAX_BODY_CHARS].strip()
    if not comment_body:
        return _quarantine(
            InboundQuarantine.NO_SEPARATOR,
            from_header=from_address,
            body=body,
            member_id=address.member_id,
        )

    # The second lock (TM-2): the write goes through the same service as the
    # web form, whose independent visible_posts re-check bounces a post outside
    # the sender's CURRENT audience — byte-identically with an unknown address.
    try:
        commenting.create_comment(
            author=address.member, post=address.post, body=comment_body, via_email=True
        )
    except commenting.CommentNotAllowed:
        return _bounce()
    return InboundResult(outcome="posted")
