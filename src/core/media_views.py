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


@login_required
def serve_media(request: HttpRequest, token: str) -> FileResponse:
    member = _acting_member(request)
    asset = scoping.visible_media(member).filter(Q(token=token) | Q(thumbnail_token=token)).first()
    if asset is None:
        raise Http404
    is_thumbnail = token == asset.thumbnail_token
    handle = asset.thumbnail if is_thumbnail else asset.image
    response = FileResponse(handle.open("rb"), content_type=asset.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = 'inline; filename="photo.jpg"'
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
