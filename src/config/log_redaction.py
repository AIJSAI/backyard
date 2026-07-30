"""Token redaction for request logs (threat model TS-EDGE-LOG).

Capability URLs put the credential in the URL, and the log stream sees URLs:
every expired or mistyped digest link would otherwise write a working (or
nearly working) token into the log file, turning log access into content
access. This filter rewrites any capability-bearing URL before a record is
emitted, and the redaction happens on the fully formatted message so no
arg-shape variant of the record slips through.

Two sinks, not one. django.request and django.security log the PATH of a 4xx.
gunicorn.error logs the RAW REQUEST LINE — query string included — whenever a
request raises, and it sets propagate=False with its own handler, so it saw
none of this until settings.LOGGING named it explicitly. Both are attached to
the redacting handler there; the settings wiring has its own guard.
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
    # django-allauth's own credential-bearing paths, which arrive via include("allauth.urls")
    # and were absent until a resolver walk found them. A wrapped or truncated reset link
    # 404s, and `django.request` then logs the whole path at WARNING -- putting an
    # ACCOUNT-TAKEOVER credential in plaintext in the container log the runbooks train
    # operators to read. Found by enumeration, not by inspection: the two redaction tests
    # only ever asserted routes already in this list, which is a self-confirming shape.
    "accounts/password/reset/key",
    "accounts/confirm-email",
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
