# apps/pwa/urls.py
from django.urls import path
from . import views

app_name = "pwa"

urlpatterns = [
    path("sw.js", views.service_worker, name="sw"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("offline/", views.offline, name="offline"),
    path("pwa/lookups.json", views.lookups, name="lookups"),
    path("pwa/sync/", views.sync, name="sync"),
]