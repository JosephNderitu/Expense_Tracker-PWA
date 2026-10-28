from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .constants import CURRENCY_SYMBOLS
from .forms import AttachmentUploadForm, TransactionForm
from .models import Attachment, Transaction
from .selectors import add_months, dashboard_data, parse_month
from .services import SCOPES, ensure_workspaces, get_active_workspace, get_scope
from .validators import MAX_PER_ENTRY

INLINE_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


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
    form = TransactionForm(request.POST or None, request.FILES or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entry saved.")
        return redirect("core:transaction_create" if "another" in request.POST else "core:dashboard")
    return render(request, "core/transaction_form.html", {"form": form, "workspace": workspace})

@login_required
def transaction_detail(request, pk):
    entry = get_object_or_404(
        Transaction.objects.select_related("category", "workspace"), pk=pk, workspace__owner=request.user
    )
    attachments = list(entry.attachments.all())
    form = AttachmentUploadForm(request.POST or None, request.FILES or None, transaction=entry)
    if request.method == "POST" and form.is_valid():
        added = form.save()
        messages.success(request, f"{added} file{'s' if added != 1 else ''} added.")
        return redirect("core:transaction_detail", pk=entry.pk)
    base = entry.workspace.currency
    display_rate = None
    if entry.currency != base and entry.rate_to_base:
        display_rate = (Decimal(1) / entry.rate_to_base).quantize(Decimal("0.0001"))
    return render(request, "core/transaction_detail.html", {
        "entry": entry,
        "attachments": attachments,
        "form": form,
        "can_add": len(attachments) < MAX_PER_ENTRY,
        "entry_symbol": CURRENCY_SYMBOLS.get(entry.currency, f"{entry.currency} "),
        "base_symbol": CURRENCY_SYMBOLS.get(base, f"{base} "),
        "display_rate": display_rate,
    })


@login_required
def attachment_file(request, pk):
    attachment = get_object_or_404(Attachment, pk=pk, transaction__workspace__owner=request.user)
    as_download = request.GET.get("download") == "1" or attachment.content_type not in INLINE_TYPES
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError:
        raise Http404("The file is missing from storage.")
    response = FileResponse(handle, content_type=attachment.content_type)
    response["Content-Disposition"] = content_disposition_header(as_download, attachment.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300"
    return response


@login_required
@require_POST
def attachment_delete(request, pk):
    attachment = get_object_or_404(Attachment, pk=pk, transaction__workspace__owner=request.user)
    entry_pk = attachment.transaction_id
    attachment.delete()
    messages.success(request, "File removed.")
    return redirect("core:transaction_detail", pk=entry_pk)