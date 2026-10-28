# apps/core/forms.py
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction

from .models import Attachment, Transaction
from .validators import ACCEPT, MAX_PER_ENTRY, clean_uploads
from .constants import SUPPORTED_CURRENCIES
from .models import Transaction

INPUT = (
    "block w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-sm "
    "placeholder-slate-400 focus:border-household focus:outline-none focus:ring-2 focus:ring-household/30"
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

class TransactionForm(StyledFormMixin, forms.ModelForm):
    currency = forms.ChoiceField(choices=SUPPORTED_CURRENCIES)
    exchange_rate = forms.DecimalField(
        required=False, min_value=Decimal("0.0001"), max_digits=14, decimal_places=4
    )

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
        self.fields["category"].queryset = workspace.categories.filter(is_active=True)
        self.fields["exchange_rate"].label = f"Exchange rate: how many of this currency equal 1 {workspace.currency}"
        if not self.instance.pk:
            self.initial["currency"] = workspace.currency

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
    attachment_kind = forms.ChoiceField(choices=Attachment.Kind.choices, initial=Attachment.Kind.RECEIPT, label="Document type")

    def __init__(self, *args, transaction, **kwargs):
        super().__init__(*args, **kwargs)
        self.transaction = transaction

    def clean_attachments(self):
        files = clean_uploads(self.cleaned_data.get("attachments"))
        if not files:
            raise ValidationError("Choose at least one file.")
        if self.transaction.attachments.count() + len(files) > MAX_PER_ENTRY:
            raise ValidationError(f"An entry can hold up to {MAX_PER_ENTRY} files.")
        return files

    def save(self):
        files = self.cleaned_data["attachments"]
        with db_transaction.atomic():
            for upload in files:
                Attachment.objects.create(
                    transaction=self.transaction, file=upload, kind=self.cleaned_data["attachment_kind"]
                )
        return len(files)