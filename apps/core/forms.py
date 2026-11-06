# apps/core/forms.py
from decimal import Decimal
import re

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Q, Max

from .constants import SUPPORTED_CURRENCIES, ICON_CHOICES, SYSTEM_CATEGORIES
from .models import Attachment, Category, Transaction
from .validators import ACCEPT, MAX_PER_ENTRY, clean_uploads
from .rates import rate_to_base, usd_kes_from

INPUT = (
    "block w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink "
    "placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                widget.attrs.setdefault("class", "size-4")
            else:
                widget.attrs.setdefault("class", INPUT)


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
            shown = usd_kes_from(self.instance.currency, workspace.currency, self.instance.rate_to_base)
            if shown:
                self.initial["exchange_rate"] = shown
        else:
            self.initial["currency"] = workspace.currency
        self.fields["category"].queryset = categories
        self.fields["exchange_rate"].label = "Exchange rate: 1 USD equals how many KES"
        self.fields["exchange_rate"].help_text = "Starts from today's live rate. Change it if your bank or mobile money gave you a different one."

    def clean(self):
        cleaned = super().clean()
        currency = cleaned.get("currency")
        rate = cleaned.get("exchange_rate")
        if currency and currency != self.workspace.currency:
            if not rate:
                self.add_error("exchange_rate", "Enter the exchange rate (1 USD = how many KES).")
            else:
                self.instance.rate_to_base = rate_to_base(currency, self.workspace.currency, rate)
        else:
            self.instance.rate_to_base = Decimal("1")
        return cleaned


class CurrencyForm(StyledFormMixin, forms.Form):
    currency = forms.ChoiceField(choices=SUPPORTED_CURRENCIES, label="Account currency")
    show_equivalent = forms.ChoiceField(
        choices=[("", "Do not show")] + list(SUPPORTED_CURRENCIES), required=False,
        label="Also show approximate amounts in",
        help_text="Adds a small '≈' line under the dashboard cards, using the live rate.",
    )
    def __init__(self, *args, locked, **kwargs):
        super().__init__(*args, **kwargs)
        if locked:
            self.fields["currency"].disabled = True


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
    
class CategoryForm(StyledFormMixin, forms.ModelForm):
    icon = forms.ChoiceField(choices=[(i, i) for i in ICON_CHOICES])

    class Meta:
        model = Category
        fields = ["name", "kind", "icon", "color", "is_active"]
        widgets = {"kind": forms.RadioSelect, "color": forms.TextInput(attrs={"type": "color"})}
        labels = {"is_active": "Show in forms and lists"}

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.instance.workspace = workspace
        self.fields["color"].widget.attrs["class"] = "h-11 w-20 cursor-pointer rounded-lg border border-line bg-surface p-1"
        if self.instance.pk:
            self.fields["kind"].disabled = True        # changing it would flip the direction of existing entries

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        locked = self.instance.pk and self.workspace.type == "work" and self.instance.name in SYSTEM_CATEGORIES
        if locked and name != self.instance.name:
            raise ValidationError("The work screens rely on this name, so it cannot be renamed. You can change its icon and colour.")
        return name

    def clean_color(self):
        color = self.cleaned_data["color"]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValidationError("Choose a colour from the picker.")
        return color

    def clean(self):
        data = super().clean()
        name, kind = data.get("name"), data.get("kind") or self.instance.kind
        if name and Category.objects.filter(workspace=self.workspace, kind=kind, name__iexact=name).exclude(pk=self.instance.pk).exists():
            self.add_error("name", "You already have a category with this name.")
        return data

    def save(self, commit=True):
        if not self.instance.pk:
            top = Category.objects.filter(workspace=self.workspace).aggregate(m=Max("sort_order"))["m"] or 0
            self.instance.sort_order = top + 1
        return super().save(commit)