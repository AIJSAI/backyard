"""Root URL configuration for the Backyard hello-world scaffold."""

from __future__ import annotations

from django.urls import include, path

from core import views
from core.breakglass import break_glass
from core.join import join

urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup, name="setup"),
    path("join/<str:token>/", join, name="join"),
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
