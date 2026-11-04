import zoneinfo
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Transaction
from apps.notifications.models import Notification
from apps.notifications.push import push_ready, send_to_user
from apps.notifications.services import K, T, _add, get_prefs, sync_alerts
from apps.work.models import Job


def in_quiet(now, start, end):
    if start == end:
        return False
    return start <= now < end if start < end else (now >= start or now < end)


class Command(BaseCommand):
    help = "Create alerts, send phone notifications and the daily entry reminder. Run it every 15 minutes."

    def handle(self, *args, **opts):
        now_utc, sent = timezone.now(), 0
        for user in get_user_model().objects.filter(is_active=True):
            try:
                tz = zoneinfo.ZoneInfo(user.timezone)
            except zoneinfo.ZoneInfoNotFoundError:
                tz = zoneinfo.ZoneInfo("America/New_York")
            local = now_utc.astimezone(tz)
            with timezone.override(tz):
                sync_alerts(user)
                prefs = get_prefs(user)
                self.remind(user, prefs, local)
            sent += self.deliver(user, prefs, local, now_utc)
        self.stdout.write(f"Done. {sent} phone notification(s) sent.")

    def remind(self, user, prefs, local):
        if not prefs.entry_reminder or local.time() < prefs.reminder_time:
            return
        today = local.date()
        key = f"noentry:{today}"
        if Notification.objects.filter(owner=user, dedupe_key=key).exists():
            return
        if Transaction.objects.filter(workspace__owner=user, date=today).exists() or Job.objects.filter(workspace__owner=user, date=today).exists():
            return
        _add(user, K.REMINDER, key, T.INFO, "Nothing logged today",
             "Add today's jobs, fuel or expenses so your numbers stay right.", reverse("core:transaction_create"))

    def deliver(self, user, prefs, local, now_utc):
        if not push_ready() or in_quiet(local.time(), prefs.quiet_start, prefs.quiet_end):
            return 0
        pending = list(Notification.objects.filter(
            owner=user, pushed_at__isnull=True, read_at__isnull=True, created_at__gte=now_utc - timedelta(hours=24),
        ).order_by("created_at"))
        if not pending or not user.push_subscriptions.exists():
            return 0
        if len(pending) > 3:
            sent = send_to_user(user, f"{len(pending)} new alerts", "Open Expense Tracker to see them.", reverse("notifications:inbox"), tag="batch")
        else:
            sent = sum(send_to_user(user, n.title, n.body, reverse("notifications:open", args=[n.pk]), tag=n.dedupe_key) for n in pending)
        if sent:
            Notification.objects.filter(pk__in=[n.pk for n in pending]).update(pushed_at=now_utc)
        return sent