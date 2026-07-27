"""Token redaction for request logs (threat model TS-EDGE-LOG).

Capability URLs put the credential in the path, and django.request logs paths:
every expired or mistyped digest link would otherwise write a working (or
nearly working) token into the log file, turning log access into content
access. This filter rewrites any capability-route path segment before a record
is emitted. It is attached to the handlers for django.request and
django.security in settings.LOGGING, and the redaction happens on the fully
formatted message so no arg-shape variant of the record slips through.
"""

from __future__ import annotations

import logging
import re

# Every route family whose path carries a bearer credential. Grown deliberately
# with each new capability surface; the test suite pins the set. Redaction is
# greedy past the route prefix (break-glass carries two sensitive segments, /d/
# links have sub-paths): losing a /posts/5/ suffix from a log line is a fair
# price for never having to reason about which segment was the secret.
_CAPABILITY_ROUTES = (
    "d",
    "t",
    "digest/confirm",
    "digest/unsubscribe",
    "join",
    "media",
    "break-glass",
)
_TOKEN_SEGMENT = re.compile(
    r"/(?P<route>" + "|".join(re.escape(route) for route in _CAPABILITY_ROUTES) + r")/[^\s?#]+"
)
# The path pattern deliberately stops at `?`, so a credential in a QUERY STRING would
# survive it. The digest surfaces pass their token that way when fetching media
# (/media/<t>/?d=<digest-token>): the page has no session, so each image request must
# re-present the capability. Without this second pattern every photo an emailed digest
# renders would write a live digest token into the request log.
_TOKEN_QUERY = re.compile(r"(?P<key>[?&]d=)[^\s&#]+")


class RedactCapabilityPaths(logging.Filter):
    """Rewrite capability-bearing path segments to [redacted] in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _TOKEN_SEGMENT.sub(r"/\g<route>/[redacted]", message)
        redacted = _TOKEN_QUERY.sub(r"\g<key>[redacted]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
