from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.nav import crumbs

from .forms import PartyForm, TruckForm
from .models import Job, Party, Truck
from .services import get_work_workspace

SETTINGS = lambda: ("Settings", reverse("accounts:settings"))


@login_required
def truck_list(request):
    ws = get_work_workspace(request)
    trucks = ws.trucks.annotate(job_count=Count("jobs", distinct=True), fuel_count=Count("fuel_entries", distinct=True)).order_by("-is_active", "name")
    return render(request, "work/truck_list.html", {"trucks": trucks, "crumbs": crumbs(SETTINGS(), ("Trucks", None))})


def _truck_form(request, pk=None):
    ws = get_work_workspace(request)
    truck = get_object_or_404(Truck, pk=pk, workspace=ws) if pk else None
    form = TruckForm(request.POST or None, instance=truck, workspace=ws)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"{saved.name} saved.")
        return redirect("work:truck_list")
    return render(request, "settings/form.html", {
        "form": form, "title": "Edit truck" if truck else "Add a truck", "cancel_url": reverse("work:truck_list"),
        "intro": "With more than one truck in service, job and fuel forms ask which truck." if not truck else "",
        "crumbs": crumbs(SETTINGS(), ("Trucks", reverse("work:truck_list")), (truck.name if truck else "Add truck", None)),
    })


@login_required
def truck_create(request):
    return _truck_form(request)


@login_required
def truck_edit(request, pk):
    return _truck_form(request, pk)


@login_required
def party_list(request):
    ws = get_work_workspace(request)
    parties = Party.objects.filter(workspace=ws).annotate(job_count=Count("jobs", distinct=True), deal_count=Count("deals", distinct=True)).order_by("name")
    return render(request, "work/party_list.html", {
        "brokers": [p for p in parties if p.kind == "broker"], "factors": [p for p in parties if p.kind == "factor"],
        "crumbs": crumbs(SETTINGS(), ("Brokers and factoring companies", None)),
    })


@login_required
def party_edit(request, pk):
    ws = get_work_workspace(request)
    party = get_object_or_404(Party, pk=pk, workspace=ws)
    form = PartyForm(request.POST or None, instance=party)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("work:party_list")
    return render(request, "settings/form.html", {
        "form": form, "title": party.name, "cancel_url": reverse("work:party_list"),
        "intro": party.get_kind_display(), "extra_template": "work/_party_delete.html", "party": party,
        "crumbs": crumbs(SETTINGS(), ("Brokers and factoring companies", reverse("work:party_list")), (party.name, None)),
    })


@login_required
@require_POST
def party_delete(request, pk):
    ws = get_work_workspace(request)
    party = get_object_or_404(Party, pk=pk, workspace=ws)
    if Job.all_objects.filter(broker=party).exists() or party.deals.exists():
        messages.error(request, f"{party.name} is used by jobs or sales, so it cannot be deleted. You can rename it instead.")
        return redirect("work:party_edit", pk=party.pk)
    name = party.name
    party.delete()
    messages.success(request, f"{name} deleted.")
    return redirect("work:party_list")