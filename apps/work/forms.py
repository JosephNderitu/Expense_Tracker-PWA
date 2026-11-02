# apps/work/forms.py
from decimal import Decimal

from django import forms
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.core.forms import MultipleFileField, MultipleFileInput, StyledFormMixin
from apps.core.models import Attachment, Category, Transaction
from apps.core.validators import ACCEPT, clean_uploads

from .constants import US_STATES
from .models import FuelDetail, Job, MaintenanceDetail, Party, Truck, FactoringDeal, Invoice
from .services import resolve_party

from django.core.exceptions import ValidationError

from .invoicing import perform_sale, record_chargeback, record_settlement, create_invoice_for_job
from .calc import sale_numbers

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
MONEY_INPUT = forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal", "placeholder": "0.00"})


def _setup_truck(form, workspace):
    trucks = workspace.trucks.filter(is_active=True)
    field = form.fields["truck"]
    field.queryset = trucks
    field.empty_label = None
    form.single_truck = trucks.count() <= 1
    if form.single_truck:
        field.widget = forms.HiddenInput()
    editing = getattr(form, "instance", None) is not None and form.instance.pk
    if not editing and not form.initial.get("truck") and trucks.first():
        form.initial["truck"] = trucks.first().pk


class JobForm(StyledFormMixin, forms.ModelForm):
    broker_name = forms.CharField(required=False, max_length=120, label="Broker or customer")
    field_order = ["date", "gross_pay", "broker_name", "reference", "origin", "destination", "miles", "truck", "notes"]

    class Meta:
        model = Job
        fields = ["truck", "date", "gross_pay", "reference", "origin", "destination", "miles", "notes"]
        widgets = {"date": DATE_INPUT, "gross_pay": MONEY_INPUT, "miles": forms.NumberInput(attrs={"inputmode": "numeric"})}
        labels = {"gross_pay": "Pay for this job", "reference": "Load or BOL number"}

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.instance.workspace = workspace
        _setup_truck(self, workspace)
        self.fields["broker_name"].widget.attrs.update({
            "autocomplete": "off", "role": "combobox", "aria-autocomplete": "list",
            "aria-expanded": "false", "aria-controls": "broker-list", "placeholder": "Type a name",
        })
        if self.instance.pk and self.instance.broker:
            self.initial["broker_name"] = self.instance.broker.name

    def save(self, commit=True):
        is_new = self.instance.pk is None
        old_pay = self.initial.get("gross_pay")
        self.instance.broker = resolve_party(self.workspace, Party.Kind.BROKER, self.cleaned_data.get("broker_name"))
        job = super().save(commit)
        if commit:
            if is_new:
                create_invoice_for_job(job)
            elif hasattr(job, "invoice"):
                invoice = job.invoice
                if invoice.status == "open" and not invoice.entries.exists() and invoice.amount == old_pay:
                    invoice.amount = job.gross_pay
                    invoice.save(update_fields=["amount", "updated_at"])
        return job


class WorkExpenseForm(StyledFormMixin, forms.Form):
    """Shared base: one Transaction in the ledger plus a detail row (fuel or maintenance)."""
    category_name, category_icon, category_color, detail_attr = "", "fa-tag", "#64748b", ""

    date = forms.DateField(initial=timezone.localdate, widget=DATE_INPUT)
    total = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), label="Total cost", widget=MONEY_INPUT)
    payment_method = forms.ChoiceField(choices=Transaction.Method.choices, initial=Transaction.Method.CARD)
    odometer = forms.IntegerField(required=False, min_value=0, label="Odometer (miles)")
    truck = forms.ModelChoiceField(queryset=Truck.objects.none())
    note = forms.CharField(required=False, max_length=255)
    attachments = MultipleFileField(required=False, widget=MultipleFileInput(attrs={"accept": ACCEPT, "class": "peer sr-only"}))
    attachment_kind = forms.ChoiceField(choices=Attachment.Kind.choices, initial=Attachment.Kind.RECEIPT, required=False, label="Document type")

    def __init__(self, *args, workspace, entry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace, self.entry = workspace, entry
        _setup_truck(self, workspace)
        if entry:
            self.initial.update(self.initial_for(entry))
            del self.fields["attachments"], self.fields["attachment_kind"]

    def clean_attachments(self):
        return clean_uploads(self.cleaned_data.get("attachments"))

    def save(self):
        data = self.cleaned_data
        with db_transaction.atomic():
            category, _ = Category.objects.get_or_create(
                workspace=self.workspace, kind=Category.Kind.EXPENSE, name=self.category_name,
                defaults={"icon": self.category_icon, "color": self.category_color, "is_default": True},
            )
            entry = self.entry or Transaction(workspace=self.workspace)
            entry.category, entry.date, entry.amount = category, data["date"], data["total"]
            entry.currency = self.workspace.currency
            entry.payment_method, entry.note = data["payment_method"], data["note"]
            entry.save()
            self.save_detail(entry)
            if not self.entry:
                kind = data.get("attachment_kind") or Attachment.Kind.RECEIPT
                for upload in data.get("attachments") or []:
                    Attachment.objects.create(transaction=entry, file=upload, kind=kind)
        return entry


class FuelForm(WorkExpenseForm):
    category_name, category_icon, category_color, detail_attr = "Fuel", "fa-gas-pump", "#f97316", "fuel"
    gallons = forms.DecimalField(max_digits=8, decimal_places=3, min_value=Decimal("0.001"))
    price_per_gallon = forms.DecimalField(required=False, max_digits=7, decimal_places=3, min_value=Decimal("0.001"), label="Price per gallon (optional)")
    state = forms.ChoiceField(choices=[("", "Choose state")] + US_STATES, label="State")
    station = forms.CharField(required=False, max_length=80, label="Station (optional)")
    field_order = ["date", "gallons", "price_per_gallon", "total", "state", "station", "payment_method", "odometer", "truck", "note"]

    @staticmethod
    def initial_for(entry):
        d = entry.fuel
        return {"date": entry.date, "total": entry.amount, "payment_method": entry.payment_method, "note": entry.note,
                "truck": d.truck_id, "odometer": d.odometer, "gallons": d.gallons,
                "price_per_gallon": d.price_per_gallon, "state": d.state, "station": d.station}

    def save_detail(self, entry):
        data = self.cleaned_data
        price = data["price_per_gallon"] or (data["total"] / data["gallons"]).quantize(Decimal("0.001"))
        FuelDetail.objects.update_or_create(transaction=entry, defaults={
            "truck": data["truck"], "gallons": data["gallons"], "price_per_gallon": price,
            "state": data["state"], "odometer": data["odometer"], "station": data["station"],
        })


class MaintenanceForm(WorkExpenseForm):
    category_name, category_icon, category_color, detail_attr = "Maintenance", "fa-wrench", "#0ea5e9", "maintenance"
    service_type = forms.ChoiceField(choices=MaintenanceDetail.Service.choices, label="Service")
    vendor = forms.CharField(required=False, max_length=80, label="Shop or vendor (optional)")
    field_order = ["date", "service_type", "total", "vendor", "payment_method", "odometer", "truck", "note"]

    @staticmethod
    def initial_for(entry):
        d = entry.maintenance
        return {"date": entry.date, "total": entry.amount, "payment_method": entry.payment_method, "note": entry.note,
                "truck": d.truck_id, "odometer": d.odometer, "service_type": d.service_type, "vendor": d.vendor}

    def save_detail(self, entry):
        data = self.cleaned_data
        MaintenanceDetail.objects.update_or_create(transaction=entry, defaults={
            "truck": data["truck"], "service_type": data["service_type"],
            "vendor": data["vendor"], "odometer": data["odometer"],
        })
        
        
class SellForm(StyledFormMixin, forms.Form):
    factor_name = forms.CharField(max_length=120, label="Factoring company")
    sold_on = forms.DateField(initial=timezone.localdate, widget=DATE_INPUT, label="Date sold")
    advance_pct = forms.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("1"), max_value=Decimal("100"),
                                     initial=Decimal("90"), label="Advance (% of invoice)")
    fee_rate_pct = forms.DecimalField(max_digits=6, decimal_places=3, min_value=Decimal("0"), max_value=Decimal("100"),
                                      initial=Decimal("3"), label="Fee (% of invoice)")
    fee_flat = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False,
                                  initial=Decimal("0"), label="Flat fees (optional)", widget=MONEY_INPUT)
    fee_timing = forms.ChoiceField(choices=FactoringDeal.FeeTiming.choices, widget=forms.RadioSelect,
                                   initial=FactoringDeal.FeeTiming.RESERVE, label="When is the fee taken?")
    recourse = forms.BooleanField(required=False, initial=True,
                                  label="Recourse: I repay the advance if my customer never pays")
    notes = forms.CharField(required=False, max_length=255)

    def __init__(self, *args, workspace, invoice, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace, self.invoice = workspace, invoice
        self.fields["factor_name"].widget.attrs.update({
            "autocomplete": "off", "role": "combobox", "aria-autocomplete": "list",
            "aria-expanded": "false", "aria-controls": "factor-list", "placeholder": "Type a name",
        })
        self.fields["fee_timing"].widget.attrs["class"] = "size-4"
        self.fields["recourse"].widget.attrs["class"] = "size-4 mt-0.5"
        last = FactoringDeal.objects.filter(invoice__workspace=workspace).order_by("-id").first()
        if last:   # remember the terms from your last sale
            self.initial.update(advance_pct=last.advance_pct, fee_rate_pct=last.fee_rate_pct, fee_flat=last.fee_flat,
                                fee_timing=last.fee_timing, recourse=last.recourse)

    def clean(self):
        data = super().clean()
        if all(k in data for k in ("advance_pct", "fee_rate_pct", "fee_timing")):
            n = sale_numbers(self.invoice.amount, data["advance_pct"], data["fee_rate_pct"],
                             data.get("fee_flat"), data["fee_timing"])
            if data["fee_timing"] == "reserve" and n["fee"] > n["reserve"]:
                raise ValidationError("The fee is larger than the reserve, so it cannot be taken from the reserve. "
                                      "Choose 'Taken from the advance' or lower the fee.")
            if n["cash_now"] <= 0:
                raise ValidationError("The advance would not cover the fee.")
        return data

    def save(self):
        d = self.cleaned_data
        factor = resolve_party(self.workspace, Party.Kind.FACTOR, d["factor_name"])
        return perform_sale(self.invoice, factor, sold_on=d["sold_on"], advance_pct=d["advance_pct"],
                            fee_rate_pct=d["fee_rate_pct"], fee_flat=d.get("fee_flat"),
                            fee_timing=d["fee_timing"], recourse=d["recourse"], notes=d["notes"])


class SettleForm(StyledFormMixin, forms.Form):
    """Reserve released by the factor, or the customer paying (including quick-pay)."""
    date = forms.DateField(initial=timezone.localdate, widget=DATE_INPUT)
    received = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), widget=MONEY_INPUT)
    fee_withheld = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False,
                                      initial=Decimal("0"), widget=MONEY_INPUT)

    def __init__(self, *args, invoice, mode, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice, self.mode = invoice, mode
        if mode == "release":
            n = invoice.deal.numbers
            self.initial["received"] = min(n["release"], invoice.bal)
            self.initial["fee_withheld"] = n["fee"] if invoice.deal.fee_timing == "reserve" else Decimal("0")
            self.fields["received"].label = "Cash received from the reserve"
            self.fields["fee_withheld"].label = "Fee withheld from the reserve"
        else:
            self.initial["received"] = invoice.bal
            self.fields["received"].label = "Cash received"
            self.fields["fee_withheld"].label = "Fee withheld by the payer (quick-pay fee)"

    def clean(self):
        data = super().clean()
        if "received" in data:
            total = data["received"] + (data.get("fee_withheld") or Decimal("0"))
            if total <= 0:
                raise ValidationError("Enter the cash you received.")
            if total > self.invoice.bal:
                raise ValidationError(f"That is more than the remaining balance of {self.invoice.bal}.")
        return data

    def save(self):
        d = self.cleaned_data
        record_settlement(self.invoice, self.mode, d["date"], d["received"], d.get("fee_withheld"))


class ChargebackForm(StyledFormMixin, forms.Form):
    date = forms.DateField(initial=timezone.localdate, widget=DATE_INPUT)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
                                label="Advance repaid to the factor", widget=MONEY_INPUT)

    def __init__(self, *args, invoice, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        self.net_received = invoice.inflow - invoice.back
        self.initial["amount"] = self.net_received

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount > self.net_received:
            raise ValidationError(f"You have only received {self.net_received} on this invoice.")
        return amount

    def save(self):
        record_chargeback(self.invoice, self.cleaned_data["date"], self.cleaned_data["amount"])


class InvoiceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["number", "issue_date", "due_date", "amount"]
        widgets = {"issue_date": DATE_INPUT, "due_date": DATE_INPUT, "amount": MONEY_INPUT}
        labels = {"number": "Your invoice number (optional)", "amount": "Invoice amount"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.entries.exists():
            self.fields["amount"].disabled = True
            self.fields["amount"].help_text = "Locked because money has been recorded. Undo those steps to change it."

    def clean(self):
        data = super().clean()
        if data.get("issue_date") and data.get("due_date") and data["due_date"] < data["issue_date"]:
            self.add_error("due_date", "The due date cannot be before the issue date.")
        return data
    
class TruckForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Truck
        fields = ["name", "plate", "is_active"]
        labels = {"name": "Truck name", "plate": "Plate (optional)", "is_active": "In service"}

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.instance.workspace = workspace
        if not self.instance.pk:
            del self.fields["is_active"]

    def clean_is_active(self):
        active = self.cleaned_data["is_active"]
        if not active and not Truck.objects.filter(workspace=self.workspace, is_active=True).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Keep at least one truck in service.")
        return active


class PartyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Party
        fields = ["name", "terms_days"]
        labels = {"terms_days": "Usual payment terms (days)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.kind == Party.Kind.FACTOR:
            del self.fields["terms_days"]
        else:
            self.fields["terms_days"].help_text = "New invoices for this broker are due this many days after the job."

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Party.objects.filter(workspace=self.instance.workspace, kind=self.instance.kind, name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("A saved name like this already exists.")
        return name