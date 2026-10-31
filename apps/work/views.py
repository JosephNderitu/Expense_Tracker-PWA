# apps/work/views.py
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

from .forms import FuelForm, JobForm, MaintenanceForm
from .models import FuelDetail, Job, Party
from .services import get_work_workspace


def _month_url(job):
    return f"{reverse('work:job_list')}?month={job.date:%Y-%m}"


def _broker_names(workspace):
    return list(Party.objects.filter(workspace=workspace, kind=Party.Kind.BROKER)
                .order_by("-last_used_at").values_list("name", flat=True))


@login_required
def add(request):
    get_work_workspace(request)
    return render(request, "work/add.html")


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
        ).select_related("broker")
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
        )
        return ctx


def _job_form(request, pk=None):
    workspace = get_work_workspace(request)
    job = get_object_or_404(Job.objects.select_related("broker"), pk=pk, workspace=workspace) if pk else None
    form = JobForm(request.POST or None, instance=job, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, "Job updated." if job else "Job saved.")
        return redirect("work:job_create" if "another" in request.POST else _month_url(saved))
    return render(request, "work/job_form.html", {
        "form": form, "job": job, "workspace": workspace, "broker_names": _broker_names(workspace),
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
    return redirect(_month_url(job))


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