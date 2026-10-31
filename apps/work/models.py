# apps/work/models.py
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Lower, Coalesce
from django.utils import timezone

from apps.core.models import TimeStampedModel, Transaction, Workspace

from .constants import US_STATES

from .calc import sale_numbers


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Party(TimeStampedModel):
    """A name the owner types once and picks from later: brokers/customers now, factoring companies in Sprint 6."""

    class Kind(models.TextChoices):
        BROKER = "broker", "Broker or customer"
        FACTOR = "factor", "Factoring company"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="parties")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=120)
    terms_days = models.PositiveSmallIntegerField(default=90)
    last_used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "parties"
        constraints = [models.UniqueConstraint(Lower("name"), "workspace", "kind", name="unique_party_name")]

    def __str__(self):
        return self.name


class Truck(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="trucks")
    name = models.CharField(max_length=60, default="My truck")
    plate = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Job(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="jobs")
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT, related_name="jobs")
    broker = models.ForeignKey(Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs")
    date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=60, blank=True)
    origin = models.CharField(max_length=80, blank=True)
    destination = models.CharField(max_length=80, blank=True)
    miles = models.PositiveIntegerField(null=True, blank=True)
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    notes = models.CharField(max_length=255, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["workspace", "date"])]

    def __str__(self):
        return f"{self.date} {self.reference or 'job'} {self.gross_pay}"

    @property
    def route(self):
        return " → ".join(p for p in (self.origin, self.destination) if p)


class FuelDetail(models.Model):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="fuel")
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT, related_name="fuel_entries")
    gallons = models.DecimalField(max_digits=8, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    price_per_gallon = models.DecimalField(max_digits=7, decimal_places=3)
    state = models.CharField(max_length=2, choices=US_STATES)
    odometer = models.PositiveIntegerField(null=True, blank=True)
    station = models.CharField(max_length=80, blank=True)


class MaintenanceDetail(models.Model):
    class Service(models.TextChoices):
        OIL = "oil", "Oil and filters"
        TIRES = "tires", "Tires"
        BRAKES = "brakes", "Brakes"
        REPAIR = "repair", "Repair"
        INSPECTION = "inspection", "Inspection"
        PARTS = "parts", "Parts"
        OTHER = "other", "Other"

    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="maintenance")
    truck = models.ForeignKey(Truck, on_delete=models.PROTECT, related_name="maintenance_entries")
    service_type = models.CharField(max_length=12, choices=Service.choices, default=Service.OTHER)
    vendor = models.CharField(max_length=80, blank=True)
    odometer = models.PositiveIntegerField(null=True, blank=True)
    
RECEIVED_KINDS = ("advance", "reserve_release", "payment")


class InvoiceQuerySet(models.QuerySet):
    def with_balance(self):
        """Adds inflow (cash received), back (charged back) and bal (still to come) to every invoice."""
        live = Q(entries__transaction__deleted_at__isnull=True)
        zero = Value(Decimal("0"), output_field=DecimalField(max_digits=12, decimal_places=2))
        return self.annotate(
            inflow=Coalesce(Sum("entries__transaction__amount", filter=live & Q(entries__kind__in=RECEIVED_KINDS)), zero),
            back=Coalesce(Sum("entries__transaction__amount", filter=live & Q(entries__kind="chargeback")), zero),
        ).annotate(
            bal=ExpressionWrapper(F("amount") - F("inflow") + F("back"), output_field=DecimalField(max_digits=14, decimal_places=2))
        )


class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SOLD = "sold", "Sold"
        PAID = "paid", "Paid"

    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="invoice")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invoices")
    number = models.CharField(max_length=40, blank=True)
    issue_date = models.DateField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN, db_index=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "id"]
        indexes = [models.Index(fields=["workspace", "status"])]

    def __str__(self):
        return f"Invoice {self.number or self.pk} · {self.amount}"

    @property
    def days_to_due(self):
        return (self.due_date - timezone.localdate()).days

    @property
    def days_overdue(self):
        return -self.days_to_due

    def refresh_status(self):
        """Status always follows the recorded money, never the other way round."""
        row = Invoice.objects.with_balance().get(pk=self.pk)
        charged_back = self.entries.filter(kind=InvoiceEntry.Kind.CHARGEBACK, transaction__deleted_at__isnull=True).exists()
        sold = FactoringDeal.objects.filter(invoice=self).exists()
        if row.bal <= 0:
            new = self.Status.PAID
        elif sold and not charged_back:
            new = self.Status.SOLD
        else:
            new = self.Status.OPEN
        if new != self.status:
            self.status = new
            self.save(update_fields=["status", "updated_at"])


class FactoringDeal(TimeStampedModel):
    class FeeTiming(models.TextChoices):
        RESERVE = "reserve", "Taken from the reserve"
        UPFRONT = "upfront", "Taken from the advance"

    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="deal")
    factor = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="deals")
    sold_on = models.DateField(default=timezone.localdate)
    advance_pct = models.DecimalField(max_digits=5, decimal_places=2)
    fee_rate_pct = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    fee_flat = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    fee_timing = models.CharField(max_length=8, choices=FeeTiming.choices, default=FeeTiming.RESERVE)
    recourse = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    @property
    def numbers(self):
        return sale_numbers(self.invoice.amount, self.advance_pct, self.fee_rate_pct, self.fee_flat, self.fee_timing)

    @property
    def cost_pct(self):
        return self.numbers["fee"] / self.invoice.amount * 100


class InvoiceEntry(models.Model):
    """Links a ledger entry to the invoice step that created it."""

    class Kind(models.TextChoices):
        ADVANCE = "advance", "Advance received"
        RESERVE = "reserve_release", "Reserve released"
        PAYMENT = "payment", "Payment received"
        FEE = "fee", "Fee"
        CHARGEBACK = "chargeback", "Advance charged back"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="entries")
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="invoice_link")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    step = models.UUIDField(default=uuid.uuid4)   # everything one action creates shares this, so it can be undone together