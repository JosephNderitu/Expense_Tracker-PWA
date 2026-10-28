# apps/core/management/commands/seed_demo.py
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Transaction
from apps.core.selectors import add_months
from apps.core.services import ensure_workspaces

# (category, entries per month, min, max)
PLAN = {
    "household": [
        ("Salary", 1, 3200, 3200), ("Rent", 1, 1200, 1200), ("Groceries", 8, 25, 110),
        ("Electricity", 1, 60, 120), ("Water", 1, 25, 45), ("Data and airtime", 1, 30, 30),
        ("Transport", 6, 8, 40), ("Shopping", 3, 20, 150), ("Family support", 2, 100, 300),
        ("Health", 1, 20, 120),
    ],
    "work": [
        ("Freight income", 12, 900, 2400), ("Fuel", 10, 250, 650), ("Maintenance", 1, 150, 1400),
        ("Tolls and parking", 5, 12, 60), ("Insurance", 1, 650, 650),
    ],
}


class Command(BaseCommand):
    help = "Create demo transactions for design review, or remove them with --clear"

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Owner email (default: first user)")
        parser.add_argument("--clear", action="store_true", help="Remove demo entries")

    def handle(self, *args, **opts):
        User = get_user_model()
        user = User.objects.filter(email=opts["email"]).first() if opts["email"] else User.objects.order_by("id").first()
        if not user:
            raise CommandError("No user found")
        ensure_workspaces(user)
        demo = Transaction.objects.filter(workspace__owner=user, note__startswith="[demo]")
        if opts["clear"]:
            self.stdout.write(f"Removed {demo.delete()[0]} demo entries")
            return
        demo.delete()
        rng = random.Random(42)
        today = timezone.localdate()
        count = 0
        for ws_type, plan in PLAN.items():
            ws = user.workspaces.get(type=ws_type)
            cats = {c.name: c for c in ws.categories.all()}
            for back in range(12):
                month = add_months(today.replace(day=1), -back)
                last_day = today.day if back == 0 else 28
                for name, entries, low, high in plan:
                    category = cats.get(name)
                    if not category:
                        continue
                    for _ in range(entries):
                        Transaction.objects.create(
                            workspace=ws, category=category,
                            date=month.replace(day=rng.randint(1, last_day)),
                            amount=Decimal(rng.randint(low * 100, high * 100)) / 100,
                            currency=ws.currency, note=f"[demo] {name.lower()}", source="system",
                        )
                        count += 1
        self.stdout.write(f"Created {count} demo entries for {user.email}")