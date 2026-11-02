# apps/notifications/models.py
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    class Kind(models.TextChoices):
        BILL = "bill", "Bills"
        INVOICE = "invoice", "Invoices"
        BUDGET = "budget", "Budgets"
        SUMMARY = "summary", "Weekly summary"

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