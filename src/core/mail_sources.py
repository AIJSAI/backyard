"""The inbound mail seam (S-502): one pipeline, pluggable sources.

A MailSource yields raw RFC-5322 bytes and acknowledges what was consumed.
The fixture source drives the test corpus today; the IMAP adapter (W4-B2, one
thin class when the dedicated mailbox exists) plugs in here with zero change
to the pipeline, because everything security-relevant lives in core/inbound.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from . import inbound


class MailSource(Protocol):
    def fetch(self) -> Iterable[bytes]:
        """Raw messages awaiting processing."""
        ...

    def acknowledge(self, raw: bytes) -> None:
        """The message was processed (posted, bounced, quarantined, or a
        duplicate); the source may delete it (T-EMAIL-5: inbound mail is
        deleted after ingestion)."""
        ...


class FixtureMailSource:
    """An in-memory source for tests and the local repro."""

    def __init__(self, messages: list[bytes]) -> None:
        self._pending = list(messages)
        self.acknowledged: list[bytes] = []

    def fetch(self) -> Iterable[bytes]:
        return list(self._pending)

    def acknowledge(self, raw: bytes) -> None:
        self._pending.remove(raw)
        self.acknowledged.append(raw)


def poll(source: MailSource) -> list[inbound.InboundResult]:
    """Process everything a source holds. Every message is acknowledged no
    matter its outcome — quarantine and the ledger are the durable records;
    leaving a poison message unacknowledged would re-process it forever."""
    results: list[inbound.InboundResult] = []
    for raw in source.fetch():
        results.append(inbound.process_inbound(raw))
        source.acknowledge(raw)
    return results
