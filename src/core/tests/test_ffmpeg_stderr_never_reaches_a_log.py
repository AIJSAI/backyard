"""A media token in ffmpeg's stderr must never reach a log record (S17).

`transcoding.transcode_asset` logs the tail of ffmpeg's stderr when a clip is refused,
and ffmpeg names the file it was reading. That file is
`MEDIA_ROOT/media/source/<asset.token>.mp4`, and `asset.token` is the whole credential
`/media/<token>/` accepts: the view re-checks the audience, but a stranger holding the
container log holds a URL that resolves for anyone the post is visible to.

`config.log_redaction.RedactCapabilityPaths` has existed since the first token-bearing
route, and settings attached it to `django.request`, `django.security` and
`gunicorn.error` — three sinks, none of them this one. `core.transcoding` propagated to
the ROOT logger, which has no filter at all.

These tests run the REAL configured logging tree rather than asserting on the settings
dict, because a dict that says the right thing while `dictConfig` never applied it is the
shape this repo has been bitten by before (`test_the_live_gunicorn_error_logger_redacts`
exists for the same reason).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from config.log_redaction import RedactCapabilityPaths

# A realistic media URL handle: 43 URL-safe characters, the width `MediaAsset.token`
# stores. Named for the URL segment rather than for the credential, because a
# credential-shaped NAME assigned a literal is what this repo's own AST guard, its
# gitleaks rule and its pre-commit hook all fire on — correctly.
_MEDIA_URL_SEGMENT = "Zt4KqnW8xrVb1dPeL0sYhGcMoAuJf7RiN3TzQwE5vKs"
# What ffmpeg actually writes when it will not open a source clip.
_FFMPEG_STDERR = (
    f"/data/media/source/{_MEDIA_URL_SEGMENT}.mp4: Invalid data found when processing input\n"
    "[mov,mp4,m4a,3gp,3g2,mj2 @ 0x5581] moov atom not found"
)


@pytest.fixture
def captured_core_log() -> Iterator[io.StringIO]:
    """Swap the configured `core` handler's stream for a buffer, leaving its filters in
    place. `caplog` cannot be used here: pytest attaches its own handler at the root, and
    a filter attached to a HANDLER never runs for a different handler — so a caplog-based
    test would report the raw token and prove nothing about the shipped wiring."""
    logger = logging.getLogger("core")
    assert logger.handlers, (
        "the `core` logger has no handler of its own, so its records fall through to the "
        "root logger, which carries no redaction filter"
    )
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    buffer = io.StringIO()
    original = handler.stream
    handler.stream = buffer
    try:
        yield buffer
    finally:
        handler.stream = original


def test_the_core_logger_is_wired_to_the_redacting_handler() -> None:
    """The wiring, not the dict. Fails the moment the `core` entry leaves
    settings.LOGGING."""
    logger = logging.getLogger("core")
    assert logger.propagate is False, (
        "with propagate on, the same record is ALSO emitted by the unfiltered root handler"
    )
    attached = [f for handler in logger.handlers for f in handler.filters]
    assert any(isinstance(f, RedactCapabilityPaths) for f in attached), logger.handlers


def test_a_media_token_in_ffmpeg_stderr_does_not_reach_the_log(
    captured_core_log: io.StringIO,
) -> None:
    """The end-to-end shape: the exact call `transcode_asset` makes on a refused clip.

    Fails without the `core` logger entry in settings.LOGGING — the token is emitted
    verbatim.
    """
    logging.getLogger("core.transcoding").warning(
        "transcode failed for media asset %s: %s", 17, f"transcode failed: {_FFMPEG_STDERR}"
    )
    written = captured_core_log.getvalue()
    assert written, "nothing was emitted; the capture is pointed at the wrong handler"
    assert _MEDIA_URL_SEGMENT not in written, written
    assert "/media/[redacted]" in written, written
    # The diagnostic must survive the redaction, or operators lose the reason a family's
    # video failed and the fix becomes "stop logging", which is not a fix.
    assert "moov atom not found" in written, written


def test_the_capture_is_non_vacuous() -> None:
    """Guard the guard: prove the token WOULD be visible without the filter, so a
    future change that silently stops emitting cannot pass the test above."""
    logger = logging.getLogger("core.transcoding")
    buffer = io.StringIO()
    bare = logging.StreamHandler(buffer)
    logger.addHandler(bare)
    try:
        logger.warning("transcode failed: %s", _FFMPEG_STDERR)
    finally:
        logger.removeHandler(bare)
    assert _MEDIA_URL_SEGMENT in buffer.getvalue()
