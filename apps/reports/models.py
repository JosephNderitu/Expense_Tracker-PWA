import secrets
import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.storage import get_private_storage


def logo_path(instance, filename):
    return f"brand/{instance.owner_id}/{uuid.uuid4().hex}.png"


def report_path(instance, filename):
    return f"reports/{instance.owner_id}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.pdf"


def new_token():
    return secrets.token_urlsafe(32)


class BrandProfile(TimeStampedModel):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="brand")
    business_name = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True, max_length=300)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    footer_text = models.CharField(max_length=160, blank=True)
    accent_color = models.CharField(max_length=7, default="#166534",
                                    validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Use a colour like #166534.")])
    logo = models.FileField(upload_to=logo_path, storage=get_private_storage, blank=True, max_length=255)


class ReportRun(TimeStampedModel):
    class Kind(models.TextChoices):
        STATEMENT = "statement", "Income and expense statement"
        INVOICES = "invoices", "Invoices and receivables"
        FUEL = "fuel", "Fuel by state"
        JOBS = "jobs", "Jobs and earnings"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=160)
    scope = models.CharField(max_length=10, default="all")
    date_from = models.DateField()
    date_to = models.DateField()
    detail = models.BooleanField(default=False)
    file = models.FileField(upload_to=report_path, storage=get_private_storage, max_length=255)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title


class ShareLink(TimeStampedModel):
    report = models.ForeignKey(ReportRun, on_delete=models.CASCADE, related_name="links")
    token = models.CharField(max_length=64, unique=True, default=new_token)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    views = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self):
        return not self.revoked and self.expires_at > timezone.now()


@receiver(post_delete, sender=ReportRun)
def delete_report_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)