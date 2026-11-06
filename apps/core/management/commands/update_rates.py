from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import ExchangeRate
from apps.core.rates import latest, refresh


class Command(BaseCommand):
    help = "Fetch today's USD to KES rate and keep a year of history. Run it once a day."

    def handle(self, *args, **opts):
        before = latest()
        row = refresh(force=True)
        if row is None:
            self.stdout.write("No rate available: the services did not answer. Nothing is stored yet.")
        elif before and row.pk == before.pk:
            self.stdout.write(f"No new rate (tried a moment ago, or the services failed). Current: 1 USD = {row.rate} KES")
        else:
            self.stdout.write(f"1 USD = {row.rate} KES (from {row.source})")
        ExchangeRate.objects.filter(fetched_at__lt=timezone.now() - timedelta(days=400)).delete()