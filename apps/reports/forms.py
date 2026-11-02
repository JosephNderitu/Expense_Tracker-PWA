# apps/reports/forms.py
import io
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile, UploadedFile
from PIL import Image

from apps.core.forms import StyledFormMixin
from apps.core.validators import IMAGE_FORMATS, validate_and_clean_upload

from .models import BrandProfile, ReportRun

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ReportForm(StyledFormMixin, forms.Form):
    kind = forms.ChoiceField(choices=ReportRun.Kind.choices)
    scope = forms.ChoiceField(choices=[("all", "Household and work"), ("household", "Household only"), ("work", "Work only")], label="Include")
    date_from = forms.DateField(widget=DATE_INPUT, label="From")
    date_to = forms.DateField(widget=DATE_INPUT, label="To")
    detail = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end:
            if start > end:
                self.add_error("date_to", "The end date must be on or after the start date.")
            elif (end - start).days > 1830:
                self.add_error("date_to", "Choose a period of five years or less.")
        return data


def _logo_png(upload):
    image = Image.open(upload)
    image.load()
    image.thumbnail((600, 600))
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    size = buffer.tell()
    buffer.seek(0)
    return InMemoryUploadedFile(buffer, None, "logo.png", "image/png", size, None)


class BrandForm(StyledFormMixin, forms.ModelForm):
    remove_logo = forms.BooleanField(required=False, label="Remove the current logo")

    class Meta:
        model = BrandProfile
        fields = ["business_name", "address", "phone", "email", "footer_text", "accent_color", "logo"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3, "placeholder": "Street, city, state, ZIP"}),
            "accent_color": forms.TextInput(attrs={"type": "color", "class": "h-11 w-20 cursor-pointer rounded-lg border border-line bg-surface p-1"}),
            "logo": forms.FileInput(attrs={"accept": ".png,.jpg,.jpeg,.webp"}),
            "footer_text": forms.TextInput(attrs={"placeholder": "Shown at the bottom of every page"}),
        }
        labels = {"accent_color": "Accent colour", "footer_text": "Footer text"}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if isinstance(logo, UploadedFile):
            if Path(logo.name).suffix.lower() not in IMAGE_FORMATS:
                raise ValidationError("Use a PNG, JPG or WEBP image.")
            return _logo_png(validate_and_clean_upload(logo))
        return logo

    def save(self, commit=True):
        brand = self.instance
        old = BrandProfile.objects.get(pk=brand.pk).logo if brand.pk else None
        if self.cleaned_data.get("remove_logo") and not isinstance(self.cleaned_data.get("logo"), UploadedFile):
            brand.logo = ""
        saved = super().save(commit)
        if old and old.name and old.name != saved.logo.name:
            old.delete(save=False)
        return saved