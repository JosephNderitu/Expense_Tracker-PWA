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
import json

from django.conf import settings
from django.http import JsonResponse

from apps.core.api import api_login_required

from .models import PushSubscription
from .push import push_ready, send_to_user



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
    return render(request, "notifications/prefs.html", {
        "form": form, "push_ready": push_ready(), "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        "crumbs": crumbs(("Settings", reverse("accounts:settings")), ("Notifications", None)),
    })


@api_login_required
@require_POST
def push_subscribe(request):
    try:
        data = json.loads(request.body)
        keys = data.get("keys", {})
        endpoint = data.get("endpoint", "")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)
    if not (endpoint.startswith("https://") and keys.get("p256dh") and keys.get("auth")):
        return JsonResponse({"error": "invalid subscription"}, status=400)
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={
        "owner": request.user, "p256dh": keys["p256dh"], "auth": keys["auth"],
        "user_agent": request.headers.get("User-Agent", "")[:200],
    })
    return JsonResponse({"ok": True})


@api_login_required
@require_POST
def push_unsubscribe(request):
    try:
        endpoint = json.loads(request.body).get("endpoint", "")
    except (ValueError, AttributeError):
        endpoint = ""
    PushSubscription.objects.filter(owner=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@api_login_required
@require_POST
def push_test(request):
    sent = send_to_user(request.user, "Test alert", "Phone alerts are working on this device.", reverse("notifications:inbox"), tag="test")
    return JsonResponse({"sent": sent})