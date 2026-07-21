"""Root URL configuration for the Backyard hello-world scaffold."""

from __future__ import annotations

from django.urls import include, path

from core import (
    admin_views,
    digest_views,
    digesting_views,
    feed_views,
    media_views,
    pod_views,
    profile_views,
    views,
)
from core.breakglass import break_glass
from core.join import join

urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup, name="setup"),
    # The feed is the member's landing surface: their visible posts, newest first,
    # plus the composer. compose is POST-only and writes through core/posting.
    path("feed/", feed_views.feed, name="feed"),
    path("compose/", feed_views.compose, name="compose"),
    # Post lifecycle (S-302): edit within the window, delete anytime. Both are
    # author-only and resolve the post through the guard first.
    path("posts/<int:post_id>/edit/", feed_views.edit_post, name="edit_post"),
    path("posts/<int:post_id>/delete/", feed_views.delete_post, name="delete_post"),
    # A post and its replies. Comments inherit the post's audience through the guard;
    # add is any visible-post member, delete is author-only.
    path("posts/<int:post_id>/", feed_views.post_detail, name="post_detail"),
    path("posts/<int:post_id>/comment/", feed_views.add_comment, name="add_comment"),
    path("comments/<int:comment_id>/delete/", feed_views.delete_comment, name="delete_comment"),
    # Reactions (S-304): who reacted, never a count. Notification prefs (S-305): the
    # single reply opt-in, off by default.
    path("posts/<int:post_id>/react/", feed_views.react, name="react"),
    path("settings/notifications/", feed_views.notification_settings, name="notification_settings"),
    # Ad-hoc pods and quiet exits (S-204, S-205).
    path("pods/", pod_views.pod_list, name="pod_list"),
    path("pods/create/", pod_views.pod_create, name="pod_create"),
    path("pods/<int:pod_id>/add-member/", pod_views.pod_add_member, name="pod_add_member"),
    path("pods/<int:pod_id>/house-rule/", pod_views.pod_house_rule, name="pod_house_rule"),
    path("pods/<int:pod_id>/mute/", pod_views.pod_mute, name="pod_mute"),
    path("pods/<int:pod_id>/leave/", pod_views.pod_leave, name="pod_leave"),
    # Profiles and the family directory (S-901, S-902).
    path("directory/", profile_views.directory, name="directory"),
    path("directory/<int:member_id>/", profile_views.member_profile, name="member_profile"),
    path("settings/profile/", profile_views.profile_edit, name="profile_edit"),
    # Member data export (S-704): a zip of your own posts, comments, and photos.
    path("settings/export/", profile_views.export_data, name="export_data"),
    # Digest lifecycle (S-501): opt-in settings, the content-free address
    # confirmation (T-EMAIL-6), and the two-step unsubscribe. The token routes are
    # unauthenticated email-link surfaces; acting is always an explicit POST.
    path("settings/digest/", digesting_views.digest_settings, name="digest_settings"),
    path("digest/confirm/<str:token>/", digesting_views.confirm_digest, name="digest_confirm"),
    path(
        "digest/unsubscribe/<str:token>/",
        digesting_views.unsubscribe_digest,
        name="digest_unsubscribe",
    ),
    path("members/digests/", admin_views.digests, name="member_digests"),
    # The /d/ read surface (TM-5): what a digest deep link opens. The token only
    # authenticates; every render re-resolves through the one audience query.
    path("d/<str:token>/", digest_views.digest_view, name="digest_web"),
    path(
        "d/<str:token>/posts/<int:post_id>/",
        digest_views.digest_post_view,
        name="digest_web_post",
    ),
    # A private family instance is never indexed; token links double down with
    # per-response X-Robots-Tag (TM-5).
    path("robots.txt", views.robots, name="robots"),
    # The one access-checked path for every media byte (S-403, TM-9). The token is the
    # only URL handle; the view re-checks the owning post's audience.
    path("media/<str:token>/", media_views.serve_media, name="serve_media"),
    path("join/<str:token>/", join, name="join"),
    # Instance-admin member management (S-701 enforced, S-703 supervised, S-702 removal).
    path("members/", admin_views.members, name="members"),
    path("members/supervised/", admin_views.create_supervised, name="create_supervised"),
    path("members/<int:member_id>/remove/", admin_views.remove, name="member_remove"),
    # Break-glass admin reset (S-805). The token here is only ever minted by the
    # `break_glass` management command; no view creates one, so there is no web or
    # email admin-recovery path.
    path("break-glass/<str:uidb64>/<str:token>/", break_glass, name="break_glass"),
    path("healthz", views.healthz, name="healthz"),
    # Account and MFA (login, logout, password, passkeys). The invite-token signup
    # is a custom view (S-101) that lands with the invite surface; allauth's own
    # open signup is not mounted, so there is no self-serve account creation.
    path("accounts/", include("allauth.urls")),
]
