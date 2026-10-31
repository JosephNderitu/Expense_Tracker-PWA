# apps/core/forms.py
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Q

from .constants import SUPPORTED_CURRENCIES
from .models import Attachment, Transaction
from .validators import ACCEPT, MAX_PER_ENTRY, clean_uploads

INPUT = (
    "block w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink "
    "placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(d, initial) for d in data]
        return [single_clean(data, initial)]


def _file_widget():
    return MultipleFileInput(attrs={"accept": ACCEPT, "class": "peer sr-only"})


def kind_choices(*values):
    return [(v, l) for v, l in Attachment.Kind.choices if v in values]


class TransactionForm(StyledFormMixin, forms.ModelForm):
    currency = forms.ChoiceField(choices=SUPPORTED_CURRENCIES)
    exchange_rate = forms.DecimalField(
        required=False, min_value=Decimal("0.0001"), max_digits=14, decimal_places=4
    )
    attachment_kind = forms.ChoiceField(choices=kind_choices("receipt", "invoice", "document"))

    field_order = ["category", "amount", "currency", "exchange_rate", "date", "payment_method", "note"]

    class Meta:
        model = Transaction
        fields = ["category", "date", "amount", "currency", "payment_method", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal", "placeholder": "0.00"}),
            "note": forms.TextInput(attrs={"placeholder": "Optional note"}),
        }

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.instance.workspace = workspace
        categories = workspace.categories.filter(is_active=True)
        if self.instance.pk:   # editing: no file fields, and keep a now-hidden category selectable
            categories = workspace.categories.filter(Q(is_active=True) | Q(pk=self.instance.category_id))
            self.fields.pop("attachments", None)
            self.fields.pop("attachment_kind", None)
            if self.instance.currency != workspace.currency and self.instance.rate_to_base:
                self.initial["exchange_rate"] = (Decimal(1) / self.instance.rate_to_base).quantize(Decimal("0.0001"))
        else:
            self.initial["currency"] = workspace.currency
        self.fields["category"].queryset = categories
        self.fields["exchange_rate"].label = f"Exchange rate: how many of this currency equal 1 {workspace.currency}"

    def clean(self):
        cleaned = super().clean()
        currency = cleaned.get("currency")
        rate = cleaned.get("exchange_rate")
        if currency and currency != self.workspace.currency:
            if not rate:
                self.add_error("exchange_rate", f"Enter how many {currency} equal 1 {self.workspace.currency}.")
            else:
                self.instance.rate_to_base = (Decimal(1) / rate).quantize(Decimal("0.00000001"))
        else:
            self.instance.rate_to_base = Decimal("1")
        return cleaned


class AttachmentUploadForm(StyledFormMixin, forms.Form):
    attachments = MultipleFileField(required=False, widget=_file_widget())
    attachment_kind = forms.ChoiceField(choices=Attachment.Kind.choices, label="Document type")

    def __init__(self, *args, parent, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent
        self.is_job = parent._meta.model_name == "job"
        field = self.fields["attachment_kind"]
        if self.is_job:
            field.choices = kind_choices("bol", "pod", "rate", "invoice", "document")
            field.initial = Attachment.Kind.BOL
        else:
            field.choices = kind_choices("receipt", "invoice", "document")
            field.initial = Attachment.Kind.RECEIPT

    def clean_attachments(self):
        files = clean_uploads(self.cleaned_data.get("attachments"))
        if not files:
            raise ValidationError("Choose at least one file.")
        if self.parent.attachments.count() + len(files) > MAX_PER_ENTRY:
            raise ValidationError(f"Up to {MAX_PER_ENTRY} files can be attached here.")
        return files

    def save(self):
        files = self.cleaned_data["attachments"]
        owner = {"job": self.parent} if self.is_job else {"transaction": self.parent}
        with db_transaction.atomic():
            for upload in files:
                Attachment.objects.create(file=upload, kind=self.cleaned_data["attachment_kind"], **owner)
        return len(files)