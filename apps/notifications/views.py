# apps/notifications/views.py
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.nav import crumbs

from .forms import PrefsForm
from .models import Notification
from .services import get_prefs, sync_alerts


@login_required
def inbox(request):
    items = list(Notification.objects.filter(owner=request.user)[:100])
    return render(request, "notifications/inbox.html", {
        "items": items, "has_unread": any(n.read_at is None for n in items), "crumbs": crumbs(("Notifications", None)),
    })


@login_required
def open_alert(request, pk):
    alert = get_object_or_404(Notification, pk=pk, owner=request.user)
    if alert.read_at is None:
        alert.read_at = timezone.now()
        alert.save(update_fields=["read_at", "updated_at"])
    return redirect(alert.url if alert.url.startswith("/") else "notifications:inbox")


@login_required
@require_POST
def mark_all(request):
    Notification.objects.filter(owner=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notifications:inbox")


@login_required
@require_POST
def refresh(request):
    sync_alerts(request.user)
    request.session["alerts_synced_at"] = time.time()
    messages.success(request, "Checked. Anything new is at the top.")
    return redirect("notifications:inbox")


@login_required
def prefs(request):
    form = PrefsForm(request.POST or None, instance=get_prefs(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Notification settings saved.")
        return redirect("accounts:settings")
    return render(request, "settings/form.html", {
        "form": form, "title": "Notifications", "cancel_url": reverse("accounts:settings"),
        "intro": "Choose which alerts appear in your inbox. Alerts to your phone arrive with the app install update.",
        "crumbs": crumbs(("Settings", reverse("accounts:settings")), ("Notifications", None)),
    })