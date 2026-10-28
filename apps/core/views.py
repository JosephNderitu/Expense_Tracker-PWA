from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import TransactionForm
from .selectors import add_months, dashboard_data, parse_month
from .services import SCOPES, ensure_workspaces, get_active_workspace, get_scope


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
    form = TransactionForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry saved.")
        return redirect("core:transaction_create" if "another" in request.POST else "core:dashboard")
    return render(request, "core/transaction_form.html", {"form": form, "workspace": workspace})