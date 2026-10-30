import django_filters as df
from django import forms
from django.db.models import Exists, OuterRef, Q

from .forms import INPUT
from .models import Attachment, Category, Transaction
from .services import scoped_workspaces


class TransactionFilter(df.FilterSet):
    q = df.CharFilter(method="search", label="Search",
                      widget=forms.TextInput(attrs={"placeholder": "Note or category"}))
    date_from = df.DateFilter(field_name="date", lookup_expr="gte", label="From",
                              widget=forms.DateInput(attrs={"type": "date"}))
    date_to = df.DateFilter(field_name="date", lookup_expr="lte", label="To",
                            widget=forms.DateInput(attrs={"type": "date"}))
    category = df.ModelChoiceFilter(queryset=Category.objects.none(), empty_label="All categories")
    direction = df.ChoiceFilter(label="Type", choices=Transaction.Direction.choices, empty_label="Money in and out")
    payment_method = df.ChoiceFilter(label="Payment method", choices=Transaction.Method.choices, empty_label="Any method")
    min_amount = df.NumberFilter(field_name="base_total", lookup_expr="gte", label="Min amount")
    max_amount = df.NumberFilter(field_name="base_total", lookup_expr="lte", label="Max amount")
    files = df.ChoiceFilter(label="Documents", method="by_files", empty_label="Any",
                            choices=[("with", "With documents"), ("without", "Without documents")])
    sort = df.ChoiceFilter(label="Sort by", method="sort_by", empty_label=None, choices=[
        ("newest", "Newest first"), ("oldest", "Oldest first"),
        ("highest", "Highest amount"), ("lowest", "Lowest amount"),
    ])

    class Meta:
        model = Transaction
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workspaces = list(scoped_workspaces(self.request))
        self.filters["category"].queryset = (
            Category.objects.filter(workspace__in=workspaces, is_active=True).select_related("workspace")
        )
        fields = self.form.fields
        if len(workspaces) > 1:
            fields["category"].label_from_instance = lambda c: f"{c.name} ({c.workspace.name})"
        for field in fields.values():
            field.widget.attrs.setdefault("class", INPUT)

    def search(self, qs, name, value):
        return qs.filter(Q(note__icontains=value) | Q(category__name__icontains=value))

    def by_files(self, qs, name, value):
        has = Exists(Attachment.objects.filter(transaction=OuterRef("pk")))
        return qs.filter(has) if value == "with" else qs.filter(~has)

    def sort_by(self, qs, name, value):
        order = {
            "newest": ("-date", "-id"), "oldest": ("date", "id"),
            "highest": ("-base_total", "-id"), "lowest": ("base_total", "-id"),
        }
        return qs.order_by(*order[value])