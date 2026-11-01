# apps/planning/views.py
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.constants import CURRENCY_SYMBOLS
from apps.core.models import Transaction
from apps.core.nav import crumbs
from apps.core.services import ensure_workspaces, get_active_workspace, scoped_workspaces

from .forms import BillForm, PayForm
from .models import Bill, Budget
from .services import pay_bill, skip_bill, three_month_average, undo_last

ZERO = Decimal("0")


def _bill(request, pk):
    return get_object_or_404(Bill.objects.select_related("category", "workspace"), pk=pk, workspace__owner=request.user)


def _bills_crumb():
    return ("Bills", reverse("planning:bill_list"))


@login_required
def bill_list(request):
    ensure_workspaces(request.user)
    workspaces = list(scoped_workspaces(request))
    bills = list(Bill.objects.filter(workspace__in=workspaces).select_related("category", "workspace"))
    active = [b for b in bills if b.is_active]
    groups = {"overdue": [], "soon": [], "later": []}
    for b in active:
        groups["overdue" if b.days_to_due < 0 else "soon" if b.days_to_due <= b.remind_days else "later"].append(b)
    spending = [b for b in active if not b.is_income]
    undo_pk = request.session.pop("undo_bill", None)
    currency = workspaces[0].currency
    return render(request, "planning/bill_list.html", {
        "sections": [("Overdue", "overdue", groups["overdue"]), ("Due soon", "soon", groups["soon"]), ("Later", "later", groups["later"])],
        "archived": [b for b in bills if not b.is_active],
        "has_active": bool(active),
        "monthly": sum((b.monthly_equivalent for b in spending), ZERO),
        "next30": sum((b.amount for b in spending if b.days_to_due <= 30), ZERO),
        "overdue_total": sum((b.amount for b in groups["overdue"] if not b.is_income), ZERO),
        "overdue_count": len(groups["overdue"]),
        "mixed_currency": len({w.currency for w in workspaces}) > 1,
        "symbol": CURRENCY_SYMBOLS.get(currency, f"{currency} "),
        "undo_bill": Bill.objects.filter(pk=undo_pk, workspace__owner=request.user).first() if undo_pk else None,
        "crumbs": crumbs(("Bills", None)),
    })


def _bill_form(request, pk=None):
    bill = _bill(request, pk) if pk else None
    workspace = bill.workspace if bill else get_active_workspace(request)
    form = BillForm(request.POST or None, instance=bill, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, "Bill updated." if bill else f"{saved.name} added. Next due {saved.next_due:%b %d}.")
        return redirect("planning:bill_detail", pk=saved.pk) if bill else redirect("planning:bill_list")
    trail = crumbs(_bills_crumb(), (bill.name, reverse("planning:bill_detail", args=[bill.pk])), ("Edit", None)) if bill \
        else crumbs(_bills_crumb(), ("Add bill", None))
    return render(request, "planning/bill_form.html", {"form": form, "bill": bill, "workspace": workspace, "crumbs": trail})


@login_required
def bill_create(request):
    return _bill_form(request)


@login_required
def bill_edit(request, pk):
    return _bill_form(request, pk)


@login_required
def bill_detail(request, pk):
    bill = _bill(request, pk)
    payments = list(bill.payments.select_related("transaction").order_by("-id")[:24])
    return render(request, "planning/bill_detail.html", {
        "bill": bill, "payments": payments,
        "symbol": CURRENCY_SYMBOLS.get(bill.workspace.currency, f"{bill.workspace.currency} "),
        "crumbs": crumbs(_bills_crumb(), (bill.name, None)),
    })


@login_required
def bill_pay(request, pk):
    bill = _bill(request, pk)
    if not bill.is_active:
        return redirect("planning:bill_detail", pk=bill.pk)
    form = PayForm(request.POST or None, bill=bill)
    if request.method == "POST" and form.is_valid():
        form.save()
        bill.refresh_from_db()
        messages.success(request, f"{bill.name} recorded. Next due {bill.next_due:%b %d}.")
        return redirect("planning:bill_list")
    return render(request, "planning/bill_pay.html", {
        "bill": bill, "form": form, "following": bill.following(bill.next_due),
        "crumbs": crumbs(_bills_crumb(), (bill.name, reverse("planning:bill_detail", args=[bill.pk])), ("Record payment", None)),
    })


@login_required
@require_POST
def bill_quickpay(request, pk):
    bill = _bill(request, pk)
    if bill.amount_varies or not bill.is_active:
        return redirect("planning:bill_pay", pk=bill.pk)
    pay_bill(bill, date=timezone.localdate(), amount=bill.amount, method=Transaction.Method.BANK)
    request.session["undo_bill"] = bill.pk
    bill.refresh_from_db()
    messages.success(request, f"{bill.name} recorded. Next due {bill.next_due:%b %d}.")
    return redirect("planning:bill_list")


@login_required
@require_POST
def bill_skip(request, pk):
    bill = _bill(request, pk)
    skip_bill(bill)
    bill.refresh_from_db()
    messages.success(request, f"Skipped. Next due {bill.next_due:%b %d}.")
    return redirect("planning:bill_detail", pk=bill.pk)


@login_required
@require_POST
def bill_undo(request, pk):
    bill = _bill(request, pk)
    done = undo_last(bill)
    bill.refresh_from_db()
    messages.success(request, f"Undone. {bill.name} is due again on {bill.next_due:%b %d}." if done else "Nothing to undo.")
    return redirect(request.POST.get("next") or reverse("planning:bill_detail", args=[bill.pk]))


@login_required
@require_POST
def bill_archive(request, pk):
    bill = _bill(request, pk)
    bill.is_active = request.POST.get("restore") == "1"
    bill.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"{bill.name} is back on your list." if bill.is_active else f"{bill.name} is no longer tracked. Its history is kept.")
    return redirect("planning:bill_list")


@login_required
def budget_edit(request):
    ensure_workspaces(request.user)
    workspaces = list(scoped_workspaces(request))
    averages = three_month_average(workspaces)
    existing = {b.category_id: b for b in Budget.objects.filter(workspace__in=workspaces)}
    posting = request.method == "POST"
    sections, parsed, has_error = [], [], False
    for ws in workspaces:
        rows = []
        for cat in ws.categories.filter(kind="expense", is_active=True):
            current = existing.get(cat.pk)
            shown = request.POST.get(f"b_{cat.pk}", "") if posting else (f"{current.amount:.2f}" if current else "")
            row = {"cat": cat, "value": shown, "avg": averages.get(cat.pk), "error": ""}
            if posting:
                raw = shown.strip().replace(",", "")
                if not raw:
                    parsed.append((ws, cat, None))
                else:
                    try:
                        amount = Decimal(raw)
                        if amount < 0 or amount > Decimal("9999999.99"):
                            raise InvalidOperation
                        parsed.append((ws, cat, amount.quantize(Decimal("0.01"))))
                    except InvalidOperation:
                        row["error"], has_error = "Enter an amount like 250.00", True
            rows.append(row)
        sections.append({"workspace": ws, "rows": rows})
    if posting and not has_error:
        with db_transaction.atomic():
            for ws, cat, amount in parsed:
                if not amount:
                    Budget.objects.filter(workspace=ws, category=cat).delete()
                else:
                    Budget.objects.update_or_create(workspace=ws, category=cat, defaults={"amount": amount})
        messages.success(request, "Budgets saved.")
        return redirect("core:dashboard")
    currency = workspaces[0].currency
    return render(request, "planning/budgets.html", {
        "sections": sections, "has_error": has_error,
        "symbol": CURRENCY_SYMBOLS.get(currency, f"{currency} "),
        "crumbs": crumbs(("Budgets", None)),
    })