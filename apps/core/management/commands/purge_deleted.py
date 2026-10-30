from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import Transaction


class Command(BaseCommand):
    help = "Permanently remove entries (and their files) deleted more than N days ago"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        old = Transaction.all_objects.filter(deleted_at__lt=cutoff)
        count = old.count()
        old.delete()
        self.stdout.write(f"Purged {count} entries deleted before {cutoff:%Y-%m-%d}")