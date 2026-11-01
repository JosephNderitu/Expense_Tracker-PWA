import calendar
from datetime import timedelta
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.dates import add_months
from apps.core.models import Category, TimeStampedModel, Transaction, Workspace


class Bill(TimeStampedModel):
    class Frequency(models.TextChoices):
        WEEKLY = "weekly", "Every week"
        MONTHLY = "monthly", "Every month"
        YEARLY = "yearly", "Every year"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="bills")
    name = models.CharField(max_length=80)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="bills")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    amount_varies = models.BooleanField(default=False, verbose_name="The amount changes each time (like electricity)")
    frequency = models.CharField(max_length=8, choices=Frequency.choices, default=Frequency.MONTHLY)
    next_due = models.DateField()
    anchor_day = models.PositiveSmallIntegerField(default=1, editable=False)   # keeps "the 31st" from drifting after short months
    remind_days = models.PositiveSmallIntegerField(default=3, validators=[MaxValueValidator(30)])
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["next_due", "name"]

    def __str__(self):
        return self.name

    @property
    def days_to_due(self):
        return (self.next_due - timezone.localdate()).days

    @property
    def days_overdue(self):
        return -self.days_to_due

    @property
    def is_income(self):
        return self.category.kind == Category.Kind.INCOME

    @property
    def monthly_equivalent(self):
        if self.frequency == self.Frequency.WEEKLY:
            return (self.amount * 52 / 12).quantize(Decimal("0.01"))
        if self.frequency == self.Frequency.YEARLY:
            return (self.amount / 12).quantize(Decimal("0.01"))
        return self.amount

    def following(self, current):
        """The due date after `current`."""
        if self.frequency == self.Frequency.WEEKLY:
            return current + timedelta(days=7)
        step = 1 if self.frequency == self.Frequency.MONTHLY else 12
        first = add_months(current.replace(day=1), step)
        return first.replace(day=min(self.anchor_day, calendar.monthrange(first.year, first.month)[1]))


class BillPayment(TimeStampedModel):
    """One cycle of a bill: paid (linked to a ledger entry) or skipped."""
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="payments")
    due_date = models.DateField()                       # the cycle this covered
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, null=True, blank=True, related_name="bill_payment")
    skipped = models.BooleanField(default=False)


class Budget(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="budgets")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="budgets")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "category"], name="one_budget_per_category")]