"""Root URL configuration for the Backyard hello-world scaffold."""

from __future__ import annotations

from django.urls import include, path

from core import admin_views, feed_views, views
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
