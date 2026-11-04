# apps/pwa/views.py
import hashlib
import json
import os

from django.contrib.staticfiles import finders
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.api import api_login_required
from apps.core.forms import TransactionForm
from apps.core.models import Transaction, Workspace
from apps.core.services import ensure_workspaces
from apps.work.constants import US_STATES
from apps.work.forms import FuelForm, JobForm
from apps.work.models import FuelDetail, Party
from apps.work.services import default_truck

from .models import OfflineItem

# Files kept on the device so the app opens instantly and the offline screen can work
PRECACHE = [
    "css/tailwind.css", "vendor/fontawesome/css/all.min.css", "vendor/fontawesome/webfonts/fa-solid-900.woff2",
    "vendor/fontawesome/webfonts/fa-regular-400.woff2", "vendor/fontawesome/webfonts/fa-brands-400.woff2",
    "vendor/fonts/inter-latin-wght-normal.woff2", "js/offline-db.js", "js/pwa.js", "js/offline-entry.js",
    "icons/icon-192.png",
]


def _version():
    digest = hashlib.md5()
    for path in PRECACHE:
        digest.update(static(path).encode())
        found = finders.find(path)
        if found:
            digest.update(str(os.path.getmtime(found)).encode())
    return digest.hexdigest()[:10]


@require_GET
def service_worker(request):
    response = render(request, "pwa/sw.js", {
        "version": _version(), "precache": json.dumps([static(p) for p in PRECACHE]),
        "offline_url": reverse("pwa:offline"),
    }, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def manifest(request):
    icon = lambda size, name, purpose="any": {"src": static(f"icons/{name}"), "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}
    return JsonResponse({
        "id": "/", "name": "Expense Tracker", "short_name": "Expenses",
        "description": "Household and trucking money tracker",
        "start_url": "/?source=pwa", "scope": "/", "display": "standalone", "orientation": "portrait",
        "background_color": "#f3f5f3", "theme_color": "#166534",
        "icons": [icon(192, "icon-192.png"), icon(512, "icon-512.png"), icon(512, "icon-maskable-512.png", "maskable")],
        "shortcuts": [
            {"name": "Add entry", "url": reverse("core:transaction_create"), "icons": [icon(192, "icon-192.png")]},
            {"name": "Notifications", "url": reverse("notifications:inbox"), "icons": [icon(192, "icon-192.png")]},
            {"name": "Offline entry", "url": reverse("pwa:offline"), "icons": [icon(192, "icon-192.png")]},
        ],
    }, content_type="application/manifest+json")


@require_GET
def offline(request):
    """Public on purpose: it holds no data, so it can be stored on the device ahead of time."""
    return render(request, "pwa/offline.html")


@api_login_required
@require_GET
def lookups(request):
    ensure_workspaces(request.user)
    workspaces = list(request.user.workspaces.all())
    work = next((w for w in workspaces if w.type == "work"), None)
    if work:
        default_truck(work)
    last_state = None
    if work:
        last_state = (FuelDetail.objects.filter(transaction__workspace=work, transaction__deleted_at__isnull=True)
                      .order_by("-transaction__date", "-pk").values_list("state", flat=True).first())
    return JsonResponse({
        "user": request.user.pk,
        "workspaces": [{
            "type": w.type, "name": w.name, "currency": w.currency,
            "categories": [{"id": c.pk, "name": c.name, "kind": c.kind}
                           for c in w.categories.filter(is_active=True).order_by("sort_order", "name")],
        } for w in workspaces],
        "methods": [[v, l] for v, l in Transaction.Method.choices],
        "states": [c for c, _ in US_STATES],
        "trucks": [{"id": t.pk, "name": t.name} for t in work.trucks.filter(is_active=True)] if work else [],
        "brokers": list(Party.objects.filter(workspace=work, kind="broker").order_by("-last_used_at").values_list("name", flat=True)[:100]) if work else [],
        "last_state": last_state or "",
    })


# ---- syncing queued entries: every item goes through the same forms as the normal screens ----

class FormErrors(Exception):
    def __init__(self, messages):
        self.messages = messages


def _errors(form):
    out = []
    for field, errs in form.errors.items():
        label = form.fields[field].label if field in form.fields else ""
        out += [f"{label}: {e}" if label else str(e) for e in errs]
    return out or ["The entry is not valid."]


def _workspace(user, kind):
    ensure_workspaces(user)
    return Workspace.objects.get(owner=user, type=kind)


def _entry(user, data):
    ws = _workspace(user, "work" if data.get("workspace") == "work" else "household")
    form = TransactionForm({
        "category": data.get("category"), "date": data.get("date"), "amount": data.get("amount"),
        "currency": ws.currency, "payment_method": data.get("payment_method") or "cash", "note": data.get("note", ""),
    }, workspace=ws)
    if not form.is_valid():
        raise FormErrors(_errors(form))
    return reverse("core:transaction_detail", args=[form.save().pk])


def _fuel(user, data):
    ws = _workspace(user, "work")
    default_truck(ws)
    keys = ("date", "gallons", "price_per_gallon", "total", "state", "station", "payment_method", "odometer", "truck", "note")
    form = FuelForm({k: data.get(k, "") for k in keys}, workspace=ws, entry=None)
    if not form.is_valid():
        raise FormErrors(_errors(form))
    return reverse("core:transaction_detail", args=[form.save().pk])


def _job(user, data):
    ws = _workspace(user, "work")
    default_truck(ws)
    keys = ("date", "gross_pay", "broker_name", "reference", "origin", "destination", "miles", "truck", "notes")
    form = JobForm({k: data.get(k, "") for k in keys}, workspace=ws)
    if not form.is_valid():
        raise FormErrors(_errors(form))
    return reverse("work:job_detail", args=[form.save().pk])


HANDLERS = {"entry": _entry, "fuel": _fuel, "job": _job}


def _process(user, item):
    client_id, kind = str(item.get("client_id", ""))[:64], item.get("kind")
    if not client_id or kind not in HANDLERS:
        return {"client_id": client_id, "status": "error", "errors": ["Unknown item."]}
    done = OfflineItem.objects.filter(owner=user, client_id=client_id).first()
    if done:
        return {"client_id": client_id, "status": "ok", "url": done.url}
    try:
        with db_transaction.atomic():
            url = HANDLERS[kind](user, item.get("data") or {})
            OfflineItem.objects.create(owner=user, client_id=client_id, kind=kind, url=url)
    except FormErrors as exc:
        return {"client_id": client_id, "status": "error", "errors": exc.messages}
    return {"client_id": client_id, "status": "ok", "url": url}


@api_login_required
@require_POST
def sync(request):
    try:
        items = json.loads(request.body).get("items", [])[:50]
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)
    return JsonResponse({"results": [_process(request.user, i) for i in items if isinstance(i, dict)]})