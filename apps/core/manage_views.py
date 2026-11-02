from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.planning.models import Bill

from .constants import ICON_CHOICES, SYSTEM_CATEGORIES
from .forms import CategoryForm
from .models import Category, Transaction, Workspace
from .nav import crumbs
from .services import ensure_workspaces

SETTINGS = lambda: ("Settings", reverse("accounts:settings"))
CATEGORIES = lambda: ("Categories", reverse("core:category_list"))


def _locked(category):
    return category.workspace.type == "work" and category.name in SYSTEM_CATEGORIES


@login_required
def category_list(request):
    ensure_workspaces(request.user)
    sections = []
    for ws in request.user.workspaces.order_by("type"):
        cats = list(ws.categories.annotate(uses=Count("transactions")).order_by("sort_order", "name"))
        sections.append({
            "workspace": ws,
            "groups": [("Money out", [c for c in cats if c.kind == "expense"]), ("Money in", [c for c in cats if c.kind == "income"])],
        })
    return render(request, "core/category_list.html", {"sections": sections, "crumbs": crumbs(SETTINGS(), ("Categories", None))})


def _category_form(request, pk=None):
    ensure_workspaces(request.user)
    if pk:
        category = get_object_or_404(Category.objects.select_related("workspace"), pk=pk, workspace__owner=request.user)
        workspace = category.workspace
    else:
        category = None
        kind = request.GET.get("workspace") if request.method == "GET" else request.POST.get("workspace")
        workspace = get_object_or_404(Workspace, owner=request.user, type=kind if kind in ("household", "work") else "household")
    form = CategoryForm(request.POST or None, instance=category, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"{saved.name} saved.")
        return redirect("core:category_list")
    return render(request, "core/category_form.html", {
        "form": form, "category": category, "workspace": workspace, "icons": ICON_CHOICES,
        "locked": bool(category and _locked(category)),
        "crumbs": crumbs(SETTINGS(), CATEGORIES(), (category.name if category else "New category", None)),
    })


@login_required
def category_create(request):
    return _category_form(request)


@login_required
def category_edit(request, pk):
    return _category_form(request, pk)


@login_required
@require_POST
def category_toggle(request, pk):
    category = get_object_or_404(Category, pk=pk, workspace__owner=request.user)
    category.is_active = not category.is_active
    category.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"{category.name} is now {'shown' if category.is_active else 'hidden'}.")
    return redirect("core:category_list")


@login_required
@require_POST
def category_delete(request, pk):
    category = get_object_or_404(Category.objects.select_related("workspace"), pk=pk, workspace__owner=request.user)
    used = Transaction.all_objects.filter(category=category).exists() or Bill.objects.filter(category=category).exists()
    if _locked(category) or used:
        messages.error(request, f"{category.name} is in use, so it cannot be deleted. Hide it instead and your history stays intact.")
        return redirect("core:category_edit", pk=category.pk)
    name = category.name
    category.delete()
    messages.success(request, f"{name} deleted.")
    return redirect("core:category_list")