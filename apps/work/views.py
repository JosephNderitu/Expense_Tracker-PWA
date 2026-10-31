# apps/work/views.py
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.core.constants import CURRENCY_SYMBOLS
from apps.core.models import Transaction
from apps.core.selectors import add_months, parse_month
from apps.core.forms import AttachmentUploadForm
from apps.core.nav import crumbs
from apps.core.validators import MAX_PER_ENTRY

from .forms import FuelForm, InvoiceForm, JobForm, MaintenanceForm, SellForm, SettleForm, ChargebackForm
from .invoicing import create_invoice_for_job, undo_last_step
from .models import FuelDetail, Invoice, Job, Party
from .services import get_work_workspace

ZERO = Decimal("0")

def _month_url(job):
    return f"{reverse('work:job_list')}?month={job.date:%Y-%m}"


def _broker_names(workspace):
    return list(Party.objects.filter(workspace=workspace, kind=Party.Kind.BROKER)
                .order_by("-last_used_at").values_list("name", flat=True))


@login_required
def add(request):
    get_work_workspace(request)
    return render(request, "work/add.html", {"crumbs": crumbs(("Add entry", None))})


# ---- jobs ----

class JobListView(LoginRequiredMixin, ListView):
    template_name = "work/job_list.html"
    context_object_name = "jobs"
    paginate_by = 20

    def get_queryset(self):
        self.workspace = get_work_workspace(self.request)
        self.month = parse_month(self.request.GET.get("month"), timezone.localdate())
        qs = Job.objects.filter(
            workspace=self.workspace, date__gte=self.month, date__lt=add_months(self.month, 1)
        ).select_related("broker", "invoice")
        self.q = self.request.GET.get("q", "").strip()
        if self.q:
            qs = qs.filter(Q(reference__icontains=self.q) | Q(origin__icontains=self.q) | Q(destination__icontains=self.q)
                           | Q(broker__name__icontains=self.q) | Q(notes__icontains=self.q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        agg = self.object_list.aggregate(
            n=Count("pk"), total_earned=Sum("gross_pay"), total_miles=Sum("miles"),
            pay_with_miles=Sum("gross_pay", filter=Q(miles__isnull=False)),
        )
        miles = agg["total_miles"] or 0
        undo_pk = self.request.session.pop("undo_job", None)
        params = self.request.GET.copy()
        params.pop("page", None)
        today = timezone.localdate().replace(day=1)
        ctx.update(
            month=self.month, q=self.q, count=agg["n"], earned=agg["total_earned"] or 0, miles=miles,
            per_mile=(agg["pay_with_miles"] / miles) if miles else None,
            symbol=CURRENCY_SYMBOLS.get(self.workspace.currency, f"{self.workspace.currency} "),
            prev_month=add_months(self.month, -1).strftime("%Y-%m"),
            next_month=add_months(self.month, 1).strftime("%Y-%m"),
            is_current_month=self.month == today, querystring=params.urlencode(),
            undo_job=Job.all_objects.filter(pk=undo_pk, workspace=self.workspace, deleted_at__isnull=False).first() if undo_pk else None,
            crumbs=crumbs(("Jobs", None)),
        )
        return ctx


def _job_form(request, pk=None):
    workspace = get_work_workspace(request)
    job = get_object_or_404(Job.objects.select_related("broker"), pk=pk, workspace=workspace) if pk else None
    form = JobForm(request.POST or None, instance=job, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, "Job updated." if job else "Job saved. Next: attach the documents or sell the invoice.")
        return redirect("work:job_create" if "another" in request.POST else "work:job_detail", **({} if "another" in request.POST else {"pk": saved.pk}))
    jobs_url = reverse("work:job_list")
    trail = crumbs(("Jobs", jobs_url), ("Edit job", None)) if job else crumbs(("Jobs", jobs_url), ("Add job", None))
    return render(request, "work/job_form.html", {
        "form": form, "job": job, "workspace": workspace, "broker_names": _broker_names(workspace), "crumbs": trail,
    })


@login_required
def job_create(request):
    return _job_form(request)


@login_required
def job_edit(request, pk):
    return _job_form(request, pk)


@login_required
@require_POST
def job_delete(request, pk):
    job = get_object_or_404(Job, pk=pk, workspace__owner=request.user)
    invoice = getattr(job, "invoice", None)
    if invoice and invoice.entries.exists():
        messages.error(request, "This job has recorded payments. Undo them from the job page first.")
        return redirect("work:job_detail", pk=job.pk)
    job.deleted_at = timezone.now()
    job.save(update_fields=["deleted_at", "updated_at"])
    request.session["undo_job"] = job.pk
    return redirect(_month_url(job))


@login_required
@require_POST
def job_restore(request, pk):
    job = get_object_or_404(Job.all_objects, pk=pk, workspace__owner=request.user, deleted_at__isnull=False)
    job.deleted_at = None
    job.save(update_fields=["deleted_at", "updated_at"])
    messages.success(request, "Job restored.")
    return redirect("work:job_detail", pk=job.pk)

# ---- fuel and maintenance ----

def _expense_view(request, form_class, label, kind, pk=None):
    workspace = get_work_workspace(request)
    entry, initial = None, {}
    if pk:
        entry = get_object_or_404(Transaction.objects.select_related("category"), pk=pk, workspace=workspace)
        if not hasattr(entry, form_class.detail_attr):
            raise Http404
    elif form_class is FuelForm:   # remember the last state used
        initial["state"] = FuelDetail.objects.filter(
            transaction__workspace=workspace, transaction__deleted_at__isnull=True
        ).order_by("-transaction__date", "-pk").values_list("state", flat=True).first() or ""
    form = form_class(request.POST or None, request.FILES or None, workspace=workspace, entry=entry, initial=initial)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"{label} {'updated' if entry else 'saved'}.")
        if entry:
            return redirect("core:transaction_detail", pk=saved.pk)
        return redirect(request.path if "another" in request.POST else "core:transaction_list")
    return render(request, "work/expense_form.html", {
        "form": form, "workspace": workspace, "entry": entry, "kind": kind, "label": label,
        "crumbs": (crumbs(("Entries", reverse("core:transaction_list")),
                          (entry.category.name, reverse("core:transaction_detail", args=[entry.pk])), ("Edit", None))
                   if entry else crumbs(("Add entry", reverse("work:add")), (label, None))),
    })


@login_required
def fuel_create(request):
    return _expense_view(request, FuelForm, "Fuel entry", "fuel")


@login_required
def fuel_edit(request, pk):
    return _expense_view(request, FuelForm, "Fuel entry", "fuel", pk)


@login_required
def maintenance_create(request):
    return _expense_view(request, MaintenanceForm, "Maintenance entry", "maintenance")


@login_required
def maintenance_edit(request, pk):
    return _expense_view(request, MaintenanceForm, "Maintenance entry", "maintenance", pk)

def _invoice(request, pk):
    return get_object_or_404(
        Invoice.objects.with_balance().select_related("job", "job__broker", "workspace", "deal", "deal__factor"),
        pk=pk, workspace__owner=request.user, job__deleted_at__isnull=True,
    )


def _symbol(workspace):
    return CURRENCY_SYMBOLS.get(workspace.currency, f"{workspace.currency} ")


@login_required
def job_detail(request, pk):
    workspace = get_work_workspace(request)
    job = get_object_or_404(Job.objects.select_related("broker", "truck"), pk=pk, workspace=workspace)
    if not hasattr(job, "invoice"):
        create_invoice_for_job(job)
    invoice = Invoice.objects.with_balance().select_related("deal", "deal__factor").get(job=job)
    attachments = list(job.attachments.all())
    form = AttachmentUploadForm(request.POST or None, request.FILES or None, parent=job)
    if request.method == "POST" and form.is_valid():
        added = form.save()
        messages.success(request, f"{added} file{'s' if added != 1 else ''} added.")
        return redirect("work:job_detail", pk=job.pk)
    entries = list(invoice.entries.filter(transaction__deleted_at__isnull=True).select_related("transaction").order_by("id"))
    fees = sum((e.transaction.amount for e in entries if e.kind == "fee"), ZERO)
    received = invoice.inflow - invoice.back
    label = job.reference or f"{job.date:%b %d}"
    return render(request, "work/job_detail.html", {
        "job": job, "invoice": invoice, "entries": entries, "attachments": attachments, "form": form,
        "can_add": len(attachments) < MAX_PER_ENTRY, "symbol": _symbol(workspace),
        "received": received, "fees": fees, "net_cash": received - fees,
        "charged_back": any(e.kind == "chargeback" for e in entries),
        "empty_hint": "No documents yet. Attach the rate confirmation, bill of lading and proof of delivery. Brokers and factoring companies usually ask for them.",
        "crumbs": crumbs(("Jobs", reverse("work:job_list")), (label, None)),
    })


class InvoiceListView(LoginRequiredMixin, ListView):
    template_name = "work/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 20

    def get_queryset(self):
        self.workspace = get_work_workspace(self.request)
        self.today = timezone.localdate()
        self.tab = self.request.GET.get("status", "open")
        qs = (Invoice.objects.filter(workspace=self.workspace, job__deleted_at__isnull=True)
              .with_balance().select_related("job", "job__broker"))
        if self.tab == "overdue":
            qs = qs.filter(status="open", due_date__lt=self.today)
        elif self.tab in ("open", "sold", "paid"):
            qs = qs.filter(status=self.tab)
        else:
            self.tab = "all"
        return qs.order_by("-due_date" if self.tab in ("paid", "all") else "due_date", "id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base = Invoice.objects.filter(workspace=self.workspace, job__deleted_at__isnull=True)
        counts = base.aggregate(
            n_open=Count("pk", filter=Q(status="open")), n_sold=Count("pk", filter=Q(status="sold")),
            n_paid=Count("pk", filter=Q(status="paid")),
            n_overdue=Count("pk", filter=Q(status="open", due_date__lt=self.today)), n_all=Count("pk"),
        )
        waiting = list(base.exclude(status="paid").with_balance())
        aging = []
        for label, lo, hi in (("0–30 days", 0, 30), ("31–60 days", 31, 60), ("61–90 days", 61, 90), ("Over 90 days", 91, 10**6)):
            total = sum((i.bal for i in waiting if lo <= (self.today - i.issue_date).days <= hi), ZERO)
            aging.append({"label": label, "total": total})
        top = max((a["total"] for a in aging), default=ZERO)
        for a in aging:
            a["pct"] = int(a["total"] / top * 100) if top else 0
        overdue = [i for i in waiting if i.status == "open" and i.due_date < self.today]
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx.update(
            tab=self.tab, counts=counts, aging=aging, symbol=_symbol(self.workspace),
            outstanding=sum((i.bal for i in waiting), ZERO), overdue_total=sum((i.bal for i in overdue), ZERO),
            querystring=params.urlencode(), crumbs=crumbs(("Invoices", None)),
        )
        return ctx


ACTIONS = {
    "sell": {"title": "Sell this invoice", "button": "Record the sale",
             "intro": "Enter what the factoring company agreed to pay you. The preview shows exactly what lands in your account and when.",
             "success": "Sale recorded. The advance is now in your entries.",
             "allowed": lambda i: i.status == "open" and not hasattr(i, "deal")},
    "release": {"title": "Record the reserve", "button": "Record the reserve",
                "intro": "The factoring company released the rest of your money. Check the amounts match what hit your account.",
                "success": "Reserve recorded.",
                "allowed": lambda i: i.status == "sold" and hasattr(i, "deal")},
    "pay": {"title": "Record a payment", "button": "Record the payment",
            "intro": "Your customer (or a quick-pay program) paid this invoice directly.",
            "success": "Payment recorded.",
            "allowed": lambda i: i.status == "open"},
    "chargeback": {"title": "Record a chargeback", "button": "Record the chargeback",
                   "intro": "Use this when your customer never paid and the factoring company took the advance back. The invoice goes back to open.",
                   "success": "Chargeback recorded. The invoice is open again.",
                   "allowed": lambda i: i.status == "sold" and hasattr(i, "deal") and i.deal.recourse},
    "edit": {"title": "Edit invoice details", "button": "Save details",
             "intro": "Change the invoice number, dates or amount.",
             "success": "Invoice updated.", "allowed": lambda i: True},
}


def _invoice_action(request, pk, mode):
    invoice = _invoice(request, pk)
    config = ACTIONS[mode]
    if not config["allowed"](invoice):
        messages.info(request, "That step is not available for this invoice right now.")
        return redirect("work:job_detail", pk=invoice.job_id)
    data = request.POST or None
    if mode == "sell":
        form = SellForm(data, invoice=invoice, workspace=invoice.workspace)
    elif mode in ("release", "pay"):
        form = SettleForm(data, invoice=invoice, mode="release" if mode == "release" else "payment")
    elif mode == "chargeback":
        form = ChargebackForm(data, invoice=invoice)
    else:
        form = InvoiceForm(data, instance=Invoice.objects.get(pk=invoice.pk))
    if request.method == "POST" and form.is_valid():
        form.save()
        if mode == "edit":
            invoice.refresh_status()
        messages.success(request, config["success"])
        return redirect("work:job_detail", pk=invoice.job_id)
    job = invoice.job
    label = job.reference or f"{job.date:%b %d}"
    return render(request, "work/invoice_action.html", {
        "invoice": invoice, "job": job, "form": form, "mode": mode, "symbol": _symbol(invoice.workspace),
        "title": config["title"], "intro": config["intro"], "button": config["button"],
        "factor_names": list(Party.objects.filter(workspace=invoice.workspace, kind=Party.Kind.FACTOR)
                             .order_by("-last_used_at").values_list("name", flat=True)) if mode == "sell" else [],
        "crumbs": crumbs(("Jobs", reverse("work:job_list")), (label, reverse("work:job_detail", args=[job.pk])), (config["title"], None)),
    })


@login_required
def invoice_sell(request, pk):
    return _invoice_action(request, pk, "sell")


@login_required
def invoice_release(request, pk):
    return _invoice_action(request, pk, "release")


@login_required
def invoice_pay(request, pk):
    return _invoice_action(request, pk, "pay")


@login_required
def invoice_chargeback(request, pk):
    return _invoice_action(request, pk, "chargeback")


@login_required
def invoice_edit(request, pk):
    return _invoice_action(request, pk, "edit")


@login_required
@require_POST
def invoice_undo(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, workspace__owner=request.user)
    messages.success(request, "Last step undone." if undo_last_step(invoice) else "Nothing to undo.")
    return redirect("work:job_detail", pk=invoice.job_id)