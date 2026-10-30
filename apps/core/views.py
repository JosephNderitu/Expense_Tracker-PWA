from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .constants import CURRENCY_SYMBOLS
from .forms import AttachmentUploadForm, TransactionForm
from .models import Attachment, Transaction
from .selectors import add_months, dashboard_data, parse_month, BASE, ZERO
from .services import SCOPES, ensure_workspaces, get_active_workspace, get_scope, scoped_workspaces
from .validators import MAX_PER_ENTRY

from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django_filters.views import FilterView
from .filters import TransactionFilter

INLINE_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


@login_required
def dashboard(request):
    ensure_workspaces(request.user)
    today = timezone.localdate()
    month_start = parse_month(request.GET.get("month"), today)
    context = dashboard_data(request.user, get_scope(request), month_start)
    context.update(
        month_start=month_start,
        prev_month=add_months(month_start, -1).strftime("%Y-%m"),
        next_month=add_months(month_start, 1).strftime("%Y-%m"),
        is_current_month=month_start == today.replace(day=1),
    )
    return render(request, "core/dashboard.html", context)


@login_required
@require_POST
def switch_workspace(request):
    choice = request.POST.get("scope")
    if choice in SCOPES:
        request.session["scope"] = choice
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "core:dashboard"
    return redirect(target)


@login_required
def transaction_create(request):
    workspace = get_active_workspace(request)
    form = TransactionForm(request.POST or None, request.FILES or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry saved.")
        return redirect("core:transaction_create" if "another" in request.POST else "core:transaction_list")
    return render(request, "core/transaction_form.html", {"form": form, "workspace": workspace})

@login_required
def transaction_detail(request, pk):
    entry = get_object_or_404(
        Transaction.objects.select_related("category", "workspace"), pk=pk, workspace__owner=request.user
    )
    attachments = list(entry.attachments.all())
    form = AttachmentUploadForm(request.POST or None, request.FILES or None, transaction=entry)
    if request.method == "POST" and form.is_valid():
        added = form.save()
        messages.success(request, f"{added} file{'s' if added != 1 else ''} added.")
        return redirect("core:transaction_detail", pk=entry.pk)
    base = entry.workspace.currency
    display_rate = None
    if entry.currency != base and entry.rate_to_base:
        display_rate = (Decimal(1) / entry.rate_to_base).quantize(Decimal("0.0001"))
    return render(request, "core/transaction_detail.html", {
        "entry": entry,
        "attachments": attachments,
        "form": form,
        "can_add": len(attachments) < MAX_PER_ENTRY,
        "entry_symbol": CURRENCY_SYMBOLS.get(entry.currency, f"{entry.currency} "),
        "base_symbol": CURRENCY_SYMBOLS.get(base, f"{base} "),
        "display_rate": display_rate,
    })


@login_required
def attachment_file(request, pk):
    attachment = get_object_or_404(Attachment, pk=pk, transaction__deleted_at__isnull=True, transaction__workspace__owner=request.user)
    as_download = request.GET.get("download") == "1" or attachment.content_type not in INLINE_TYPES
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError:
        raise Http404("The file is missing from storage.")
    response = FileResponse(handle, content_type=attachment.content_type)
    response["Content-Disposition"] = content_disposition_header(as_download, attachment.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300"
    return response


@login_required
@require_POST
def attachment_delete(request, pk):
    attachment = get_object_or_404(Attachment, pk=pk, transaction__workspace__owner=request.user, transaction__deleted_at__isnull=True)
    entry_pk = attachment.transaction_id
    attachment.delete()
    messages.success(request, "File removed.")
    return redirect("core:transaction_detail", pk=entry_pk)

def _display(field, value):
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    choices = getattr(field, "choices", None)
    if choices and not hasattr(value, "pk"):
        return dict((str(k), v) for k, v in choices).get(str(value), str(value))
    return str(value)


class TransactionListView(LoginRequiredMixin, FilterView):
    filterset_class = TransactionFilter
    template_name = "core/transaction_list.html"
    context_object_name = "transactions"
    PER_PAGE = (10, 20, 50)

    def get_queryset(self):
        ensure_workspaces(self.request.user)
        self.workspaces = list(scoped_workspaces(self.request))
        return (
            Transaction.objects.filter(workspace__in=self.workspaces)
            .select_related("category", "workspace")
            .annotate(
                base_total=BASE,
                has_files=Exists(Attachment.objects.filter(transaction=OuterRef("pk"))),
            )
        )

    def get_paginate_by(self, queryset):
        try:
            per_page = int(self.request.GET.get("per_page", 20))
        except ValueError:
            per_page = 20
        return per_page if per_page in self.PER_PAGE else 20

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        params = self.request.GET.copy()
        params.pop("page", None)

        totals = self.object_list.order_by().aggregate(
            inc=Sum("base_total", filter=Q(direction="in")),
            out=Sum("base_total", filter=Q(direction="out")),
            n=Count("pk"),
        )
        income, spent = totals["inc"] or ZERO, totals["out"] or ZERO
        currencies = {w.currency for w in self.workspaces}
        currency = self.workspaces[0].currency

        first = today.replace(day=1)
        last_month_end = first - timedelta(days=1)
        ranges = [
            ("Today", today, today),
            ("Last 7 days", today - timedelta(days=6), today),
            ("This month", first, today),
            ("Last month", last_month_end.replace(day=1), last_month_end),
            ("This year", today.replace(month=1, day=1), today),
        ]
        current = (self.request.GET.get("date_from"), self.request.GET.get("date_to"))
        quick = []
        for label, start, end in ranges:
            link = params.copy()
            link["date_from"], link["date_to"] = start.isoformat(), end.isoformat()
            quick.append({"label": label, "url": "?" + link.urlencode(),
                          "active": current == (start.isoformat(), end.isoformat())})

        chips = []
        form = self.filterset.form
        if self.filterset.is_bound and form.is_valid():
            for name, value in form.cleaned_data.items():
                if name == "sort" or value in (None, "", []):
                    continue
                rest = params.copy()
                rest.pop(name, None)
                chips.append({"label": form.fields[name].label or name,
                              "value": _display(form.fields[name], value),
                              "remove": "?" + rest.urlencode()})

        page = ctx.get("page_obj")
        undo_pk = self.request.session.pop("undo_pk", None)
        ctx.update(
            income=income, spent=spent, net=income - spent, count=totals["n"],
            mixed_currency=len(currencies) > 1,
            symbol=CURRENCY_SYMBOLS.get(currency, f"{currency} "),
            querystring=params.urlencode(),
            per_page=self.get_paginate_by(None), per_page_options=self.PER_PAGE,
            quick_ranges=quick, active_filters=chips,
            page_range=list(ctx["paginator"].get_elided_page_range(page.number, on_each_side=1, on_ends=1)) if page else [],
            undo_entry=(
                Transaction.all_objects.select_related("category")
                .filter(pk=undo_pk, workspace__owner=self.request.user, deleted_at__isnull=False).first()
                if undo_pk else None
            ),
        )
        return ctx


@login_required
def transaction_edit(request, pk):
    entry = get_object_or_404(
        Transaction.objects.select_related("workspace", "category"), pk=pk, workspace__owner=request.user
    )
    form = TransactionForm(request.POST or None, instance=entry, workspace=entry.workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry updated.")
        return redirect("core:transaction_detail", pk=entry.pk)
    return render(request, "core/transaction_form.html",
                  {"form": form, "workspace": entry.workspace, "entry": entry, "editing": True})


@login_required
@require_POST
def transaction_delete(request, pk):
    entry = get_object_or_404(Transaction, pk=pk, workspace__owner=request.user)
    entry.deleted_at = timezone.now()
    entry.save(update_fields=["deleted_at", "updated_at"])
    request.session["undo_pk"] = entry.pk
    return redirect("core:transaction_list")


@login_required
@require_POST
def transaction_restore(request, pk):
    entry = get_object_or_404(
        Transaction.all_objects, pk=pk, workspace__owner=request.user, deleted_at__isnull=False
    )
    entry.deleted_at = None
    entry.save(update_fields=["deleted_at", "updated_at"])
    messages.success(request, "Entry restored.")
    return redirect("core:transaction_detail", pk=entry.pk)


@login_required
def transaction_trash(request):
    entries = (
        Transaction.all_objects.filter(workspace__owner=request.user, deleted_at__isnull=False)
        .select_related("category", "workspace").order_by("-deleted_at")[:100]
    )
    return render(request, "core/transaction_trash.html", {"entries": entries})