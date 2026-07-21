"""Member data export (S-704): take your whole history with you.

A member can download a zip of everything they authored: their posts, their comments,
and the photos on their posts, in a documented JSON format. The export is strictly the
member's own authored content, never anyone else's: it reads their reverse relations
(member.posts, member.comments) directly, not the audience query, so it can only ever
contain what they wrote. It is available from the first release and never gated.
"""

from __future__ import annotations

import io
import json
import zipfile

from django.utils import timezone

from .models import Member

EXPORT_FORMAT = "backyard-member-export/1"


def build_member_export(member: Member) -> bytes:
    """Return a zip of the member's own posts, comments, and media as bytes.

    Layout: manifest.json, posts.json, comments.json, media.json, and media/<token>.jpg
    for each photo. Only the member's authored, non-deleted content is included.
    """
    posts = list(
        member.posts.filter(deleted_at__isnull=True)
        .select_related("pod")
        .prefetch_related("audience_yards", "media")
    )
    comments = list(member.comments.filter(deleted_at__isnull=True))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
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
            for asset in post.media.all():
                if asset.deleted_at is not None:
                    continue
                arcname = f"media/{asset.token}.jpg"
                archive.writestr(arcname, asset.image.read())
                media_index.append(
                    {"post_id": post.id, "file": arcname, "alt_text": asset.alt_text}
                )
        archive.writestr("media.json", json.dumps(media_index, indent=2))
    return buffer.getvalue()
