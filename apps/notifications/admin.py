# apps/notifications/admin.py
from django.contrib import admin
from .models import Notification, NotificationPrefs, PushSubscription

admin.site.register([Notification, NotificationPrefs, PushSubscription])