from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.core.forms import StyledFormMixin
from apps.core.models import Transaction

from .models import Bill
from .services import default_amount, pay_bill

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
MONEY_INPUT = forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal", "placeholder": "0.00"})


class BillForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Bill
        fields = ["name", "category", "amount", "amount_varies", "frequency", "next_due", "remind_days", "notes"]
        widgets = {"next_due": DATE_INPUT, "amount": MONEY_INPUT, "name": forms.TextInput(attrs={"placeholder": "Rent, Electricity, Truck insurance"})}
        labels = {"amount": "Amount (or your usual estimate)", "next_due": "Next due date",
                  "remind_days": "Remind me this many days before"}

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.instance.workspace = workspace
        categories = workspace.categories.filter(is_active=True)
        if self.instance.pk:
            categories = workspace.categories.filter(Q(is_active=True) | Q(pk=self.instance.category_id))
        field = self.fields["category"]
        field.queryset = categories.select_related()
        field.label_from_instance = lambda c: c.name if c.kind == "expense" else f"{c.name} (money coming in)"
        self.fields["amount_varies"].widget.attrs["class"] = "size-4"
        self.fields["remind_days"].widget.attrs.update({"min": 0, "max": 30})

    def save(self, commit=True):
        self.instance.anchor_day = self.cleaned_data["next_due"].day
        return super().save(commit)


class PayForm(StyledFormMixin, forms.Form):
    date = forms.DateField(initial=timezone.localdate, widget=DATE_INPUT, label="Date")
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), widget=MONEY_INPUT)
    payment_method = forms.ChoiceField(choices=Transaction.Method.choices, initial=Transaction.Method.BANK, label="Method")
    note = forms.CharField(required=False, max_length=255, label="Note (optional)")

    def __init__(self, *args, bill, **kwargs):
        super().__init__(*args, **kwargs)
        self.bill = bill
        self.initial["amount"] = default_amount(bill)

    def save(self):
        d = self.cleaned_data
        return pay_bill(self.bill, date=d["date"], amount=d["amount"], method=d["payment_method"], note=d["note"])