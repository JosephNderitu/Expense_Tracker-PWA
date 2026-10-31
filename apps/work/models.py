# apps/work/models.py
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import TimeStampedModel, Transaction, Workspace

from .constants import US_STATES


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