"""Root URL configuration for the Backyard hello-world scaffold."""

from __future__ import annotations

from django.urls import path

from core import views

urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup, name="setup"),
    path("healthz", views.healthz, name="healthz"),
]
