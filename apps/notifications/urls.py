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
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("push/unsubscribe/", views.push_unsubscribe, name="push_unsubscribe"),
    path("push/test/", views.push_test, name="push_test"),
]