# apps/core/forms.py
from decimal import Decimal

from django import forms

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