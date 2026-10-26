# apps/core/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

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