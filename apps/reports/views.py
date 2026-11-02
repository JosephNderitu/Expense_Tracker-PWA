# apps/reports/views.py
from datetime import date, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.core.nav import crumbs
from apps.core.services import get_scope

from .builders import BUILDERS, SCOPE_LABELS, Params
from .forms import BrandForm, ReportForm
from .models import ReportRun, ShareLink
from .render import render_csv, render_xlsx
from .services import create_report, get_brand

KINDS = [
    ("statement", "fa-scale-balanced", "Income and expense statement", "Income, expenses and net, by category and month"),
    ("invoices", "fa-file-invoice-dollar", "Invoices and receivables", "Invoiced, received, fees, factoring cost, unpaid ages"),
    ("fuel", "fa-gas-pump", "Fuel by state", "Gallons and cost per state, for fuel-tax reporting"),
    ("jobs", "fa-route", "Jobs and earnings", "Every job with pay per mile, earnings by broker"),
]
REPORTS_CRUMB = lambda: ("Reports", reverse("reports:history"))


def _params(form):
    d = form.cleaned_data
    return Params(kind=d["kind"], scope=d["scope"], date_from=d["date_from"], date_to=d["date_to"], detail=d["detail"])


def _download_name(run, ext):
    return f"{slugify(run.title)}-{run.date_from}-to-{run.date_to}.{ext}"


def _builder_page(request, form):
    return render(request, "reports/builder.html", {
        "form": form, "kinds": KINDS, "crumbs": crumbs(REPORTS_CRUMB(), ("New report", None)),
    })


@login_required
def history(request):
    runs = ReportRun.objects.filter(owner=request.user)[:60]
    return render(request, "reports/history.html", {"runs": runs, "crumbs": crumbs(("Reports", None))})


@login_required
def builder(request):
    today = timezone.localdate()
    initial = {"kind": "statement", "scope": get_scope(request), "date_from": today.replace(day=1), "date_to": today}
    for key in ("kind", "scope"):
        if request.GET.get(key):
            initial[key] = request.GET[key]
    for key in ("date_from", "date_to"):
        try:
            initial[key] = date.fromisoformat(request.GET[key])
        except (KeyError, ValueError):
            pass
    return _builder_page(request, ReportForm(initial=initial))


@login_required
@require_POST
def create(request):
    form = ReportForm(request.POST)
    if not form.is_valid():
        return _builder_page(request, form)
    run = create_report(request.user, _params(form))
    messages.success(request, "Report created. You can download or share it below.")
    return redirect("reports:detail", pk=run.pk)


def _export_response(report, fmt, name, brand):
    if fmt == "xlsx":
        content, ctype, ext = render_xlsx(report, brand.accent_color or "#166534"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    else:
        content, ctype, ext = render_csv(report), "text/csv; charset=utf-8", "csv"
    response = HttpResponse(content, content_type=ctype)
    response["Content-Disposition"] = content_disposition_header(True, f"{name}.{ext}")
    return response


@login_required
@require_POST
def export(request):
    form = ReportForm(request.POST)
    if not form.is_valid():
        return _builder_page(request, form)
    params = _params(form)
    report = BUILDERS[params.kind](request.user, params)
    name = f"{slugify(report.title)}-{params.date_from}-to-{params.date_to}"
    return _export_response(report, request.POST.get("fmt", "csv"), name, get_brand(request.user))


@login_required
def detail(request, pk):
    run = get_object_or_404(ReportRun, pk=pk, owner=request.user)
    links = [l for l in run.links.all() if l.is_active]
    return render(request, "reports/detail.html", {
        "run": run, "links": links, "scope_label": SCOPE_LABELS.get(run.scope, run.scope),
        "file_name": _download_name(run, "pdf"),
        "crumbs": crumbs(REPORTS_CRUMB(), (run.title, None)),
    })


@login_required
@xframe_options_sameorigin
def report_file(request, pk):
    run = get_object_or_404(ReportRun, pk=pk, owner=request.user)
    try:
        handle = run.file.open("rb")
    except FileNotFoundError:
        raise Http404("The file is missing from storage.")
    response = FileResponse(handle, content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(request.GET.get("download") == "1", _download_name(run, "pdf"))
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300"
    return response


@login_required
def run_export(request, pk, fmt):
    run = get_object_or_404(ReportRun, pk=pk, owner=request.user)
    if fmt not in ("csv", "xlsx"):
        raise Http404
    params = Params(kind=run.kind, scope=run.scope, date_from=run.date_from, date_to=run.date_to, detail=run.detail)
    report = BUILDERS[run.kind](request.user, params)
    return _export_response(report, fmt, _download_name(run, "x").rsplit(".", 1)[0], get_brand(request.user))


@login_required
@require_POST
def delete(request, pk):
    run = get_object_or_404(ReportRun, pk=pk, owner=request.user)
    run.delete()
    messages.success(request, "Report deleted.")
    return redirect("reports:history")


@login_required
@require_POST
def share_create(request, pk):
    run = get_object_or_404(ReportRun, pk=pk, owner=request.user)
    try:
        days = int(request.POST.get("days", 7))
    except ValueError:
        days = 7
    days = days if days in (1, 7, 30) else 7
    link = ShareLink.objects.create(report=run, expires_at=timezone.now() + timedelta(days=days))
    url = request.build_absolute_uri(reverse("reports:shared", args=[link.token]))
    text = f"{run.title}, {run.date_from:%b %d} to {run.date_to:%b %d, %Y}. Link works until {link.expires_at:%b %d}: {url}"
    return JsonResponse({"url": url, "expires": f"{link.expires_at:%b %d, %Y}", "whatsapp": "https://wa.me/?text=" + quote(text, safe="")})


@login_required
@require_POST
def share_revoke(request, pk):
    link = get_object_or_404(ShareLink, pk=pk, report__owner=request.user)
    link.revoked = True
    link.save(update_fields=["revoked", "updated_at"])
    messages.success(request, "Link revoked. It no longer opens the report.")
    return redirect("reports:detail", pk=link.report_id)


def shared(request, token):
    """Public, unguessable and expiring. No login, so a client or accountant can open it."""
    link = ShareLink.objects.select_related("report").filter(token=token).first()
    if not link or not link.is_active:
        return render(request, "reports/shared_invalid.html", status=410 if link else 404)
    ShareLink.objects.filter(pk=link.pk).update(views=F("views") + 1)
    try:
        handle = link.report.file.open("rb")
    except FileNotFoundError:
        return render(request, "reports/shared_invalid.html", status=404)
    response = FileResponse(handle, content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(False, _download_name(link.report, "pdf"))
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def branding(request):
    brand = get_brand(request.user)
    form = BrandForm(request.POST or None, request.FILES or None, instance=brand)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Branding saved. New reports use it straight away.")
        return redirect("reports:branding")
    return render(request, "reports/branding.html", {
        "form": form, "brand": brand, "crumbs": crumbs(REPORTS_CRUMB(), ("Report branding", None)),
    })


@login_required
@xframe_options_sameorigin
def logo_file(request):
    brand = get_brand(request.user)
    if not brand.logo:
        raise Http404
    response = FileResponse(brand.logo.open("rb"), content_type="image/png")
    response["Cache-Control"] = "private, max-age=60"
    return response