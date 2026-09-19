"""Resend inbound webhook -> the inbound pipeline (S-502, wave 4 provider).

Resend's ``email.received`` webhook is metadata-only; django-anymail's Resend
inbound handler makes the second API fetch for the full message and fires the
``anymail.signals.inbound`` signal. This module is the ONE adapter between that
signal and core/inbound: it serializes the message to raw RFC-5322 bytes and
hands them to the same ``process_inbound`` the fixture (and a future IMAP) source
uses, so every security property — size caps, the three kill clocks, From
consistency, the separator strip, dedup, and the second visible_posts lock — is
shared with zero duplication.

It also owns the two things upstream does not do, both of which happen INSIDE the
webhook's own request cycle, on a gunicorn worker:

* **The fetch is bounded** (S1). `anymail.webhooks.resend` makes three
  ``requests.get`` calls with no ``timeout=`` and reads ``.content`` whole. A slow
  provider therefore pins a worker for as long as it likes, and a large response
  is buffered entirely before our 256 KB message cap is ever consulted — the cap
  applies to the parsed message, after the download. `BoundedResendInboundWebhookView`
  re-implements the two fetch helpers with a connect/read timeout, a streamed, size-capped
  read, AND one wall-clock budget across all three requests — the timeout alone does not
  bound a trickle, because it resets on every chunk, so neither a slow nor a fat response
  can hold or fill a worker.
* **The route only exists when the secret does** (S4). Anymail verifies the svix
  signature against ``RESEND_INBOUND_SECRET``; with no secret configured there is
  nothing to verify against, and an SMTP-configured self-hoster would answer every
  unauthenticated POST with an unhandled 500. ``config/urls`` does not mount the
  route in that case, and ``dispatch`` below refuses it anyway, so neither half
  alone is the whole control.

The capability is read from the address Resend RECORDED DELIVERING TO, taken from
the webhook payload (``event.esp_event["data"]["received_for"]``), not from the raw-MIME
To/Delivered-To header a sender fully controls (T-EMAIL-1). Anymail's Resend
handler is the one ESP that does not populate ``AnymailInboundMessage.
envelope_recipient`` (verified against the installed anymail source), so we read
Resend's own recipient record here rather than that always-None attribute.

Anymail verifies the webhook's signature against ``RESEND_INBOUND_SECRET`` (svix)
before this fires, so an unsigned or wrong-secret POST never reaches here; the
secret is required at boot (config/email_guard.py, TS-PP-8). Bounces are NOT
emailed: like the fixture pipeline, a failed reply produces no outbound mail (a
From address is forgeable, so auto-replying would be backscatter). The side
effects that matter — a posted comment, a quarantine row, the dedup ledger —
happen inside ``process_inbound``; its InboundResult is intentionally dropped.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urljoin

import requests
from anymail.inbound import AnymailInboundMessage
from anymail.signals import inbound
from anymail.webhooks.resend import ResendInboundWebhookView
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.dispatch import receiver
from django.http import Http404, HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from . import inbound as inbound_pipeline

logger = logging.getLogger(__name__)

# Connect and read timeouts for the two fetches the webhook makes, in seconds. The read
# timeout is per socket read, not for the whole body — which is why the size cap below is
# the other half of the bound: a trickle that sends one byte inside every read window
# would otherwise never time out.
_FETCH_TIMEOUT = (5, 20)
# The ceiling on any one fetched body. Deliberately ABOVE the pipeline's 256 KB message
# cap (`inbound._MAX_MESSAGE_BYTES`) so that an over-long but honest message is refused by
# the pipeline, which records a quarantine row the admin can see, rather than vanishing
# here. What this stops is the unbounded case: a body with no Content-Length and no end.
_MAX_FETCH_BYTES = 1024 * 1024
# Attachments are fetched one per download URL. The pipeline ignores attachments entirely
# (only the first text/plain part becomes a comment), so the only thing these bytes can do
# is cost memory; cap how many we are willing to pull at the same number of parts the
# pipeline tolerates.
_MAX_ATTACHMENTS = 20
# The WHOLE fetch, across all three requests, in seconds. The read timeout above bounds
# each socket read and RESETS on every chunk, so a sender that trickles one byte inside
# every window never times out and holds a gunicorn worker indefinitely — the docstring
# claimed the byte cap answered that, and it does not: a slow enough trickle never reaches
# the cap either. Mirrors `link_preview._TOTAL_BUDGET`, which exists for the same reason
# (that module's security review, HIGH-3).
_TOTAL_FETCH_BUDGET_SECONDS = 60.0


class InboundFetchRefused(Exception):
    """The inbound fetch was refused before it could hold or fill a worker."""


def _read_capped(response: requests.Response, *, what: str, deadline: float) -> bytes:
    """Stream a response body, refusing past `_MAX_FETCH_BYTES` or past `deadline`.

    `response.content` reads to the end, whatever the end turns out to be. This reads in
    chunks and gives up the moment the total passes the cap, so the worker never buffers
    an unbounded body — and closes the response, so the socket does not linger.

    The deadline is the other half, and the byte cap does not cover it: the socket read
    timeout resets on every chunk, so one byte inside every window is a legal, endless
    response that never reaches the cap. `deadline` is a `time.monotonic()` instant shared
    by every request in one webhook call, so the three of them together are bounded.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(65536):
            if time.monotonic() > deadline:
                raise InboundFetchRefused(
                    f"{what} outran the {_TOTAL_FETCH_BUDGET_SECONDS}s budget"
                )
            total += len(chunk)
            if total > _MAX_FETCH_BYTES:
                raise InboundFetchRefused(f"{what} exceeded {_MAX_FETCH_BYTES} bytes")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


class BoundedResendInboundWebhookView(ResendInboundWebhookView):  # type: ignore[misc]
    """Anymail's Resend inbound view with a bounded, timed fetch (S1).

    The two overridden helpers mirror `anymail.webhooks.resend` 15.0 exactly, other than
    the timeout and the capped read. They are re-implemented rather than wrapped because
    the unbounded `requests.get` calls are inline in the upstream method bodies, with no
    seam to pass a timeout through — a comment pinning the mirrored version is the price
    of that, and a dependency bump should re-read it.
    """

    @method_decorator(csrf_exempt)
    @method_decorator(login_not_required)
    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Refuse the route outright when no inbound secret is configured (S4).

        `config/urls` already declines to mount it, so this is the second lock rather than
        the first: without a secret, Anymail's svix verification has nothing to verify
        against and falls through to a basic-auth check nobody configured, which answers an
        unauthenticated POST with an unhandled 500. A 404 is the honest answer — on an
        SMTP-configured instance this endpoint genuinely does not exist.

        BOTH DECORATORS ARE RE-APPLIED, and leaving them off is not a style question.
        `View.as_view()` copies `cls.dispatch.__dict__` onto the returned callable, which
        is how `csrf_exempt` and `login_not_required` reach the middleware at all — so an
        override that does not carry them silently drops Anymail's. Measured on the mounted
        route with `Client(enforce_csrf_checks=True)`: the undecorated subclass answered
        403 where upstream answered 400 for the identical request. In production that is
        CsrfViewMiddleware rejecting every Resend inbound POST before the svix signature is
        checked — no verification, no quarantine row, no bounce, and reply-by-email dies
        with nothing anywhere saying so. A webhook is a machine POST from another origin;
        it has no session and no CSRF token by construction.
        """
        if not settings.RESEND_INBOUND_SECRET:
            raise Http404
        response: HttpResponse = super().dispatch(request, *args, **kwargs)
        return response

    def _fetch_inbound_email(self, email_id: str) -> AnymailInboundMessage | None:
        """Fetch the full message from the Resend API, bounded in time and in size.

        Returns None when the fetch is refused, which `handle_inbound` treats exactly like
        Anymail's own message-less event: dropped, with a quarantine row, and never raised
        into a provider retry loop (a retry cannot make an over-large message smaller).
        """
        url = urljoin(self.api_url, f"emails/receiving/{email_id}")
        # ONE budget for the whole call, set here and read by every request below,
        # including `_fetch_attachment`, which the base class calls without arguments.
        deadline = time.monotonic() + _TOTAL_FETCH_BUDGET_SECONDS
        self._fetch_deadline = deadline
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=_FETCH_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()
            data = json.loads(
                _read_capped(response, what="the inbound message record", deadline=deadline)
            )

            raw_url = (data.get("raw") or {}).get("download_url")
            if raw_url:
                # Prefer raw MIME when available (more complete representation).
                raw_response = requests.get(raw_url, timeout=_FETCH_TIMEOUT, stream=True)
                raw_response.raise_for_status()
                raw = _read_capped(raw_response, what="the raw inbound message", deadline=deadline)
                return AnymailInboundMessage.parse_raw_mime_bytes(raw)
            return self._construct_from_fields(data)
        except InboundFetchRefused as exc:
            logger.warning("inbound fetch refused: %s", exc)
            inbound_pipeline.quarantine_transport_refusal()
            return None
        except (requests.Timeout, ValueError) as exc:
            # A timeout and unparseable JSON are both "we have nothing to process". Neither
            # is worth a 500: Resend would retry, and each retry re-runs the fetch.
            logger.warning("inbound fetch failed: %s", exc)
            inbound_pipeline.quarantine_transport_refusal()
            return None

    def _construct_from_fields(self, data: dict[str, Any]) -> AnymailInboundMessage:
        """Anymail 15.0's parsed-field fallback, used when Resend offers no raw MIME.

        Mirrors upstream `_fetch_inbound_email`'s second half; the only difference is that
        the attachments it pulls come through the bounded fetch below and are capped in
        number.
        """
        headers: list[tuple[str, str]] = []
        esp_headers = data.get("headers") or {}
        if isinstance(esp_headers, dict):
            for name, value in esp_headers.items():
                if isinstance(value, list):
                    headers.extend((name, item) for item in value)
                else:
                    headers.append((name, value))
        elif isinstance(esp_headers, list):
            headers = [(h["name"], h["value"]) for h in esp_headers]

        attachments = [
            self._fetch_attachment(att)
            for att in (data.get("attachments") or [])[:_MAX_ATTACHMENTS]
        ]
        message = AnymailInboundMessage.construct(
            from_email=data.get("from"),
            to=", ".join(data.get("to") or []) or None,
            cc=", ".join(data.get("cc") or []) or None,
            bcc=", ".join(data.get("bcc") or []) or None,
            subject=data.get("subject"),
            headers=headers,
            text=data.get("text"),
            html=data.get("html"),
            attachments=attachments,
        )
        if data.get("reply_to") and "Reply-To" not in message:
            message["Reply-To"] = ", ".join(data["reply_to"])
        if data.get("message_id") and "Message-ID" not in message:
            message["Message-ID"] = data["message_id"]
        return message

    def _fetch_attachment(self, attachment: dict[str, Any]) -> AnymailInboundMessage:
        """One attachment, timed and size-capped like every other fetch here."""
        response = requests.get(attachment["download_url"], timeout=_FETCH_TIMEOUT, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type") or attachment.get(
            "content_type", "application/octet-stream"
        )
        content = _read_capped(
            response,
            what="an inbound attachment",
            # Set by `_fetch_inbound_email`, which is this method's only caller. The
            # fallback keeps an attachment bounded even if that ever stops being true.
            deadline=getattr(
                self, "_fetch_deadline", time.monotonic() + _TOTAL_FETCH_BUDGET_SECONDS
            ),
        )
        constructed: AnymailInboundMessage = AnymailInboundMessage.construct_attachment(
            content_type=content_type,
            content=content,
            filename=attachment.get("filename"),
            content_id=attachment.get("content_id"),
        )
        return constructed


class UntrustedRecipient(Exception):
    """The webhook payload carried no address we are willing to treat as the capability."""


def _trusted_recipient(esp_event: Any) -> str:
    """The address Resend RECORDED DELIVERING TO: its envelope-delivered-for record.

    ``received_for`` and nothing else, and a refusal rather than a guess (S5). The two
    behaviours that were here before both converted TM-4's "the address IS the credential"
    into "a header is the credential":

    * it fell back to ``data["to"]``, which is the parsed To recipients of the received
      message. A sender writes that field. Delivering a message to their OWN valid inbound
      address while addressing it ``To: reply+<somebody-else's-capability>@…`` would have
      posted a comment as that somebody else, which is the precise forgery T-EMAIL-1
      exists to prevent;
    * when neither field was present it returned ``""``, and ``process_inbound`` reads
      ``""`` as "this transport has no envelope recipient, use the message header" — the
      fixture/IMAP contract, where the header really is MTA-prepended. Through the webhook
      it is the sender's own header.

    A multi-recipient list is REFUSED rather than resolved to its first element: an
    envelope delivered for two addresses has two capabilities, and picking one is picking
    one arbitrarily. Reply addresses are minted per member and per post, so a genuine
    reply is always delivered for exactly one.
    """
    data = (esp_event or {}).get("data") or {}
    value = data.get("received_for")
    if isinstance(value, list):
        if len(value) != 1:
            raise UntrustedRecipient(
                f"the webhook payload names {len(value)} delivered-for addresses"
            )
        value = value[0]
    if not isinstance(value, str) or not value.strip():
        raise UntrustedRecipient("the webhook payload carries no delivered-for address")
    return value


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
        # email_id (nothing to fetch or process), and the bounded view above returns
        # None for a fetch it refused. Drop it rather than raising: a
        # malformed-but-signed event must not become a poison HTTP-500 retry
        # loop at Resend (security review LOW-1).
        return
    try:
        recipient = _trusted_recipient(getattr(event, "esp_event", None))
    except UntrustedRecipient as exc:
        # Fail CLOSED, visibly. Nothing is posted and nothing falls back to a header, but
        # a quarantine row puts it on the admin's panel — so if Resend's payload shape is
        # ever not what this expects, whoever registers the webhook finds out from the
        # product rather than from replies quietly never arriving.
        # The KEY NAMES of the payload's data object, never its values: whoever reads this
        # needs to know which field Resend actually sent, and the values are somebody's
        # mail. Sorted so the line is stable enough to compare across messages.
        logger.warning(
            "inbound refused, no trustworthy delivered-for address: %s (payload data keys: %s)",
            exc,
            sorted((getattr(event, "esp_event", None) or {}).get("data", {}) or {}),
        )
        inbound_pipeline.quarantine_transport_refusal()
        return
    raw = bytes(message.as_bytes())
    inbound_pipeline.process_inbound(raw, envelope_recipient=recipient)
