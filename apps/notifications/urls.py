# apps/notifications/urls.py
from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("settings/", views.prefs, name="prefs"),
    path("read-all/", views.mark_all, name="mark_all"),
    path("check/", views.refresh, name="refresh"),
    path("<int:pk>/open/", views.open_alert, name="open"),
]