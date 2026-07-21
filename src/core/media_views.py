"""The one access-checked path every media byte is served through (S-403, TM-9).

There is no static route to MEDIA_ROOT; a photo or its thumbnail is reachable only by
its unguessable token, and even with the token the view re-checks that the requesting
member can see the owning post (scoping.visible_media over visible_posts). A cross-yard
member, or anyone whose access was revoked or whose post was deleted, gets the same
404 as an unknown token. The response pins the stored content type with nosniff and a
Content-Disposition, and is marked no-store so a shared-device cache does not retain a
deleted photo (T-MEDIA-6).
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest

from . import scoping
from .feed_views import _acting_member
from .models import MediaAsset


@login_required
def serve_media(request: HttpRequest, token: str) -> FileResponse:
    member = _acting_member(request)
    asset = scoping.visible_media(member).filter(Q(token=token) | Q(thumbnail_token=token)).first()
    if asset is None:
        raise Http404
    # By kind: thumbnail_token serves the JPEG thumbnail (photo) or poster (video), always
    # image/jpeg; token serves the full image (photo) or the transcoded rendition (video),
    # whose content_type is pinned. A video whose transcode has not finished (or failed)
    # has no rendition/poster file yet, so it falls through to the same 404 below.
    is_thumbnail = token == asset.thumbnail_token
    if is_thumbnail:
        handle, content_type, filename = asset.thumbnail, "image/jpeg", "poster.jpg"
    elif asset.media_kind == MediaAsset.VIDEO:
        handle, content_type, filename = asset.video, asset.content_type, "clip.mp4"
    else:
        handle, content_type, filename = asset.image, asset.content_type, "photo.jpg"
    try:
        stream = handle.open("rb")
    except (FileNotFoundError, ValueError) as exc:
        # Fail closed to the same 404 as an unknown token, never a 500 and never another
        # asset's bytes: FileNotFoundError if a purge removed the file mid-request (review
        # of #31); ValueError if the FileField is empty (a video still transcoding, S-402).
        raise Http404 from exc
    response = FileResponse(stream, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
