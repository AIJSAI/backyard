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


class RedactCapabilityPaths(logging.Filter):
    """Rewrite capability-bearing path segments to [redacted] in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _TOKEN_SEGMENT.sub(r"/\g<route>/[redacted]", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
