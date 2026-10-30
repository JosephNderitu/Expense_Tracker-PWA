# apps/core/models.py
from decimal import Decimal
import uuid
from pathlib import Path

from .storage import get_private_storage
from .validators import CONTENT_TYPES

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Workspace(TimeStampedModel):
    class Type(models.TextChoices):
        HOUSEHOLD = "household", "Household"
        WORK = "work", "Work"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspaces")
    type = models.CharField(max_length=20, choices=Type.choices)
    name = models.CharField(max_length=80)
    currency = models.CharField(max_length=3, default="USD")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "type"], name="one_workspace_per_type")]

    def __str__(self):
        return f"{self.name} ({self.currency})"


class Category(TimeStampedModel):
    class Kind(models.TextChoices):
        EXPENSE = "expense", "Expense"
        INCOME = "income", "Income"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    icon = models.CharField(max_length=40, default="fa-tag", help_text="Font Awesome class, e.g. fa-bolt")
    color = models.CharField(max_length=7, default="#64748b")
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "kind", "name"], name="unique_category_per_workspace")
        ]

    def __str__(self):
        return self.name


KIND_TO_DIRECTION = {Category.Kind.EXPENSE: "out", Category.Kind.INCOME: "in"}

class ActiveTransactionManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

class Transaction(TimeStampedModel):
    class Direction(models.TextChoices):
        IN = "in", "Money in"
        OUT = "out", "Money out"

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        BANK = "bank", "Bank transfer"
        MOBILE = "mobile", "Mobile money"
        OTHER = "other", "Other"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        RECURRING = "recurring", "Recurring"
        SYSTEM = "system", "System"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="transactions")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions")
    date = models.DateField(default=timezone.localdate)
    direction = models.CharField(max_length=3, choices=Direction.choices, editable=False)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=3, default="USD")
    rate_to_base = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("1"))
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    note = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)
    
    objects = ActiveTransactionManager()
    all_objects = models.Manager()
    
    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["workspace", "date"]),
            models.Index(fields=["workspace", "category"]),
        ]

    def __str__(self):
        return f"{self.date} {self.category} {self.amount} {self.currency}"

    @property
    def base_amount(self):
        return (self.amount * self.rate_to_base).quantize(Decimal("0.01"))

    def clean(self):
        if self.category_id and self.workspace_id and self.category.workspace_id != self.workspace_id:
            raise ValidationError({"category": "This category belongs to a different workspace."})

    def save(self, *args, **kwargs):
        self.direction = KIND_TO_DIRECTION[self.category.kind]
        if self.currency == self.workspace.currency:
            self.rate_to_base = Decimal("1")
        super().save(*args, **kwargs)
        

def attachment_path(instance, filename):
    ext = Path(filename).suffix.lower()
    now = timezone.now()
    return f"{instance.transaction.workspace.owner_id}/{now:%Y/%m}/{uuid.uuid4().hex}{ext}"


class Attachment(TimeStampedModel):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        INVOICE = "invoice", "Invoice"
        DOCUMENT = "document", "Document"

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_path, storage=get_private_storage, max_length=255)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.RECEIPT)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.original_name

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            name = Path(self.file.name).name
            self.original_name = name[:255]
            self.size = self.file.size
            self.content_type = CONTENT_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")
        super().save(*args, **kwargs)

    @property
    def is_image(self):
        return self.content_type in {"image/jpeg", "image/png", "image/webp"}

    @property
    def is_pdf(self):
        return self.content_type == "application/pdf"

    @property
    def icon(self):
        if self.content_type.startswith("image/"):
            return "fa-file-image"
        return {
            "application/pdf": "fa-file-pdf",
            "text/csv": "fa-file-csv",
            "text/plain": "fa-file-lines",
        }.get(self.content_type) or (
            "fa-file-word" if "wordprocessingml" in self.content_type
            else "fa-file-excel" if "spreadsheetml" in self.content_type
            else "fa-file"
        )