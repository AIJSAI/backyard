"""Member data export (S-704): take your whole history with you.

A member can download a zip of everything they authored: their posts, their comments,
and the photos and videos on their posts, in a documented JSON format. The export is strictly the
member's own authored content, never anyone else's: it reads their reverse relations
(member.posts, member.comments) directly, not the audience query, so it can only ever
contain what they wrote. It is available from the first release and never gated.

The archive is written into a caller-provided file so the view can spill it to disk
and stream it, keeping peak memory to about one media file at a time (a photo, or a
video's <=100MB source) plus the zip buffers, rather than the whole archive at once
(security review of #32).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import IO

from django.utils import timezone

from .models import MediaAsset, Member

EXPORT_FORMAT = "backyard-member-export/1"


def write_member_export(member: Member, destination: IO[bytes]) -> None:
    """Write the member's own posts, comments, and media as a zip into `destination`.

    Layout: manifest.json, posts.json, comments.json, media.json, and media/<token>.jpg
    for each photo. Only the member's authored, non-deleted content is included. A media
    file that is missing from storage is skipped rather than failing the whole export.
    """
    posts = list(
        member.posts.filter(deleted_at__isnull=True)
        .select_related("pod")
        .prefetch_related("audience_yards", "media")
    )
    comments = list(member.comments.filter(deleted_at__isnull=True))

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": EXPORT_FORMAT,
                    "member": {
                        "id": member.id,
                        "display_name": member.display_name,
                        "kinship_name": member.kinship_name,
                    },
                    "exported_at": timezone.now().isoformat(),
                    "counts": {"posts": len(posts), "comments": len(comments)},
                },
                indent=2,
            ),
        )
        archive.writestr(
            "posts.json",
            json.dumps(
                [
                    {
                        "id": post.id,
                        "body": post.body,
                        "created_at": post.created_at.isoformat(),
                        "edited_at": post.edited_at.isoformat() if post.edited_at else None,
                        "pod": post.pod.name,
                        "audience_yards": sorted(yard.name for yard in post.audience_yards.all()),
                    }
                    for post in posts
                ],
                indent=2,
            ),
        )
        archive.writestr(
            "comments.json",
            json.dumps(
                [
                    {
                        "id": comment.id,
                        "body": comment.body,
                        "created_at": comment.created_at.isoformat(),
                        "post_id": comment.post_id,
                    }
                    for comment in comments
                ],
                indent=2,
            ),
        )
        media_index = []
        for post in posts:
            # The member's OWN photos only: a LINK_PREVIEW asset is a re-hosted copy of a
            # third party's og:image, not the member's content, so it never rides their
            # personal data export (S-301 / S-704).
            for asset in post.media.exclude(media_kind=MediaAsset.LINK_PREVIEW):
                if asset.deleted_at is not None:
                    continue
                # A photo exports its full re-encoded image; a video exports the
                # metadata-stripped SOURCE original (retained precisely for member export,
                # T-MEDIA-6), never the served H.264 rendition. A video's `image` is empty
                # by design, so branching on kind is what keeps the export from 500-ing for
                # any member who ever posted a clip (S-704 — leaving takes your data).
                if asset.media_kind == MediaAsset.VIDEO:
                    stored = asset.source
                    ext = PurePosixPath(asset.source.name or "").suffix or ".mp4"
                else:
                    stored = asset.image
                    ext = ".jpg"
                arcname = f"media/{asset.token}{ext}"
                try:
                    with stored.open("rb") as handle:
                        archive.writestr(arcname, handle.read())
                except (FileNotFoundError, ValueError):
                    continue  # a missing or unpopulated file is skipped, never a 500
                media_index.append(
                    {"post_id": post.id, "file": arcname, "alt_text": asset.alt_text}
                )
        archive.writestr("media.json", json.dumps(media_index, indent=2))


def build_member_export(member: Member) -> bytes:
    """The export as bytes. Convenience for callers that want the whole archive in
    memory (tests); the view streams from a temp file instead."""
    buffer = io.BytesIO()
    write_member_export(member, buffer)
    return buffer.getvalue()
