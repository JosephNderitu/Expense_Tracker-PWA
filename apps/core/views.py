# apps/core/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.contrib import messages
from .forms import TransactionForm
from .services import get_active_workspace

WORKSPACES = ("household", "work")


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html")


@login_required
@require_POST
def switch_workspace(request):
    choice = request.POST.get("workspace")
    if choice in WORKSPACES:
        request.session["active_workspace"] = choice
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "core:dashboard"
    return redirect(target)

# apps/core/views.py  (add imports and the new view)
@login_required
def transaction_create(request):
    workspace = get_active_workspace(request)
    if not workspace.categories.exists():
        messages.info(request, "This workspace has no categories yet.")
        return redirect("core:dashboard")
    form = TransactionForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry saved.")
        return redirect("core:transaction_create" if "another" in request.POST else "core:dashboard")
    return render(request, "core/transaction_form.html", {"form": form, "workspace": workspace})