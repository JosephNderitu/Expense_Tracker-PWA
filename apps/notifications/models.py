# apps/notifications/models.py
from django.conf import settings
from django.db import models
from datetime import time

from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    class Kind(models.TextChoices):
        BILL = "bill", "Bills"
        INVOICE = "invoice", "Invoices"
        BUDGET = "budget", "Budgets"
        SUMMARY = "summary", "Weekly summary"
        REMINDER = "reminder", "Reminder"

    class Tone(models.TextChoices):
        INFO = "info", "Info"
        WARN = "warn", "Heads up"
        BAD = "bad", "Needs action"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    tone = models.CharField(max_length=5, choices=Tone.choices, default=Tone.INFO)
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=255, blank=True)
    url = models.CharField(max_length=200, blank=True)
    dedupe_key = models.CharField(max_length=120)       # makes sure each alert is created only once
    read_at = models.DateTimeField(null=True, blank=True)
    pushed_at = models.DateTimeField(null=True, blank=True)     # when it was sent to the phone

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["owner", "dedupe_key"], name="unique_alert_per_owner")]
        indexes = [models.Index(fields=["owner", "read_at"])]


class NotificationPrefs(TimeStampedModel):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_prefs")
    bills = models.BooleanField(default=True, verbose_name="Bills coming due or overdue")
    invoices = models.BooleanField(default=True, verbose_name="Invoices overdue, or waiting on a reserve")
    budgets = models.BooleanField(default=True, verbose_name="Budgets reaching 80% and 100%")
    weekly = models.BooleanField(default=True, verbose_name="A summary of last week, each Monday")
    entry_reminder = models.BooleanField(default=True, verbose_name="Remind me if I have not logged anything today")
    reminder_time = models.TimeField(default=time(20, 0), verbose_name="Reminder time")
    quiet_start = models.TimeField(default=time(22, 0), verbose_name="Quiet hours start")
    quiet_end = models.TimeField(default=time(7, 0), verbose_name="Quiet hours end")
    
class PushSubscription(TimeStampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.CharField(max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=200, blank=True)