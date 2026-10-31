# apps/work/forms.py
from decimal import Decimal

from django import forms
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.core.forms import MultipleFileField, MultipleFileInput, StyledFormMixin
from apps.core.models import Attachment, Category, Transaction
from apps.core.validators import ACCEPT, clean_uploads

from .constants import US_STATES
from .models import FuelDetail, Job, MaintenanceDetail, Party, Truck
from .services import resolve_party

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
        self.instance.broker = resolve_party(self.workspace, Party.Kind.BROKER, self.cleaned_data.get("broker_name"))
        return super().save(commit)


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