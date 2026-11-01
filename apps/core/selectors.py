from datetime import date, timedelta 
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.work.models import RECEIVED_KINDS, FuelDetail, Invoice, InvoiceEntry, Job
from apps.planning.models import Bill, Budget

from .constants import CURRENCY_SYMBOLS
from .models import Transaction
from .templatetags.money import money
from .dates import add_months

ZERO = Decimal("0")
BASE = ExpressionWrapper(F("amount") * F("rate_to_base"), output_field=DecimalField(max_digits=24, decimal_places=8))
GROSS = F("gross_pay")

_GENERAL = {"income": "Total income", "spent": "Total spent", "saved": "Saved this month"}
LABELS = {"all": _GENERAL, "household": _GENERAL,
          "work": {"income": "Total earned", "spent": "Total spent", "saved": "Net profit"}}


def parse_month(raw, today):
    current = today.replace(day=1)
    try:
        year, month = (int(part) for part in raw.split("-"))
        return min(date(year, month, 1), current)   # never a future month
    except (AttributeError, ValueError):
        return current


def _delta(current, previous, *, higher_is_better):
    if not previous:
        return None
    pct = (current - previous) / abs(previous) * 100
    return {"pct": abs(pct).quantize(Decimal("0.1")), "up": pct >= 0, "good": (pct >= 0) == higher_is_better}


def _sum(qs, expr=BASE):
    return qs.aggregate(t=Sum(expr))["t"] or ZERO


def _ledger(workspaces):
    return Transaction.objects.filter(workspace__in=workspaces)


def _jobs(workspaces):
    return Job.objects.filter(workspace__in=workspaces)


def _household_income(qs):
    # Work income comes from jobs (earned), so work-workspace ledger income never double counts
    return qs.filter(direction="in", workspace__type="household")


def _out(qs):
    # An advance repaid to a factor is a repayment, not an expense
    return qs.filter(direction="out").exclude(invoice_link__kind="chargeback")


def _period(workspaces, start, end):
    ledger = _ledger(workspaces).filter(date__gte=start, date__lt=end)
    jobs = _jobs(workspaces).filter(date__gte=start, date__lt=end)
    income = _sum(_household_income(ledger)) + _sum(jobs, GROSS)
    return income, _sum(_out(ledger))


def _monthly(qs, expr):
    rows = qs.annotate(m=TruncMonth("date")).values("m").annotate(t=Sum(expr)).order_by("m")
    return {(r["m"].year, r["m"].month): r["t"] or ZERO for r in rows}


def _by_category(qs):
    return list(
        _out(qs).values("category__name")
        .annotate(total=Sum(BASE), color=Max("category__color"), icon=Max("category__icon"))
        .order_by("-total")
    )


def _work_stats(workspaces, start, end, spent, symbol):
    jobs = _jobs(workspaces).filter(date__gte=start, date__lt=end)
    agg = jobs.aggregate(
        n=Count("pk"),
        total_miles=Sum("miles"),
        pay_with_miles=Sum("gross_pay", filter=Q(miles__isnull=False)),
    )
    fuel = FuelDetail.objects.filter(
        transaction__workspace__in=workspaces, transaction__deleted_at__isnull=True,
        transaction__date__gte=start, transaction__date__lt=end,
    ).aggregate(total_gallons=Sum("gallons"), total_cost=Sum("transaction__amount"))
    miles = agg["total_miles"] or 0
    gallons = fuel["total_gallons"] or ZERO
    return [
        {"label": "Jobs", "icon": "fa-route", "value": str(agg["n"]), "hint": f"{miles:,} miles logged"},
        {"label": "Revenue per mile", "icon": "fa-gauge-high",
         "value": money(agg["pay_with_miles"] / miles, symbol) if miles else "n/a", "hint": "Jobs with miles only"},
        {"label": "Cost per mile", "icon": "fa-scale-balanced",
         "value": money(spent / miles, symbol) if miles else "n/a", "hint": "All expenses ÷ job miles"},
        {"label": "Avg fuel price", "icon": "fa-gas-pump",
         "value": f"{symbol}{fuel['total_cost'] / gallons:.3f}" if gallons else "n/a",
         "hint": f"{gallons:,.1f} gal bought" if gallons else "No fuel logged"},
    ]


def _work_cash(workspaces, start, end, symbol, today):
    entries = InvoiceEntry.objects.filter(
        invoice__workspace__in=workspaces, invoice__job__deleted_at__isnull=True, transaction__deleted_at__isnull=True,
    )
    month = entries.filter(transaction__date__gte=start, transaction__date__lt=end).aggregate(
        inflow=Sum("transaction__amount", filter=Q(kind__in=RECEIVED_KINDS)),
        charged=Sum("transaction__amount", filter=Q(kind="chargeback")),
        fees=Sum("transaction__amount", filter=Q(kind="fee")),
    )
    received = (month["inflow"] or ZERO) - (month["charged"] or ZERO)
    waiting = list(
        Invoice.objects.filter(workspace__in=workspaces, job__deleted_at__isnull=True)
        .exclude(status="paid").with_balance().select_related("job", "job__broker")
    )
    overdue = [i for i in waiting if i.status == "open" and i.due_date < today]
    stats = [
        {"label": "Received this month", "icon": "fa-hand-holding-dollar", "value": money(received, symbol), "hint": "Cash from invoices"},
        {"label": "Waiting to be paid", "icon": "fa-hourglass-half",
         "value": money(sum((i.bal for i in waiting), ZERO), symbol), "hint": f"{len(waiting)} open or sold"},
        {"label": "Overdue", "icon": "fa-triangle-exclamation",
         "value": money(sum((i.bal for i in overdue), ZERO), symbol),
         "hint": f"{len(overdue)} invoice{'s' if len(overdue) != 1 else ''}"},
        {"label": "Fees paid", "icon": "fa-percent", "value": money(month["fees"] or ZERO, symbol), "hint": "This month"},
    ]
    attention = []
    for i in sorted(waiting, key=lambda x: x.due_date):
        late = (today - i.due_date).days
        if late <= 0:
            continue
        who = i.job.broker.name if i.job.broker_id else "Invoice"
        days = f"{late} day{'s' if late != 1 else ''}"
        text = f"Overdue by {days}" if i.status == "open" else f"Customer was due {days} ago. Check your reserve"
        attention.append({"job_id": i.job_id, "title": f"{who} · {money(i.bal, symbol)}", "text": text})
    return stats, attention[:5]

def _budget_panel(workspaces, ledger_month, spent, scope):
    budgets = list(Budget.objects.filter(workspace__in=workspaces, category__is_active=True).select_related("category", "workspace"))
    if not budgets:
        return None
    actual = {r["category_id"]: r["t"] for r in _out(ledger_month).order_by().values("category_id").annotate(t=Sum(BASE))}
    rows, total, used_total = [], ZERO, ZERO
    for b in budgets:
        used = actual.get(b.category_id, ZERO)
        pct = used / b.amount * 100
        total += b.amount
        used_total += used
        rows.append({
            "name": b.category.name, "workspace": b.workspace.name, "color": b.category.color, "icon": b.category.icon,
            "budget": b.amount, "actual": used, "left": b.amount - used, "pct": pct, "bar": int(min(pct, 100)),
            "state": "over" if pct >= 100 else "near" if pct >= 80 else "ok",
        })
    rows.sort(key=lambda r: r["pct"], reverse=True)
    overall = used_total / total * 100 if total else ZERO
    return {
        "rows": rows[:6], "more": max(len(rows) - 6, 0), "show_workspace": scope == "all",
        "total": total, "spent": used_total, "left": total - used_total, "pct": overall, "bar": int(min(overall, 100)),
        "state": "over" if overall >= 100 else "near" if overall >= 80 else "ok",
        "unbudgeted": spent - used_total,
    }


def _bills_due(workspaces, today):
    bills = Bill.objects.filter(
        workspace__in=workspaces, is_active=True, next_due__lte=today + timedelta(days=30)
    ).select_related("category", "workspace")
    return [b for b in bills if b.days_to_due <= b.remind_days]

def dashboard_data(user, scope, month_start):
    workspaces = list(user.workspaces.all() if scope == "all" else user.workspaces.filter(type=scope))
    currency = workspaces[0].currency
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")

    next_month = add_months(month_start, 1)
    prev_month = add_months(month_start, -1)
    month_ledger = _ledger(workspaces).filter(date__gte=month_start, date__lt=next_month)
    prev_ledger = _ledger(workspaces).filter(date__gte=prev_month, date__lt=month_start)

    income, spent = _period(workspaces, month_start, next_month)
    p_income, p_spent = _period(workspaces, prev_month, month_start)
    saved, p_saved = income - spent, p_income - p_spent

    previous = {r["category__name"]: r["total"] for r in _by_category(prev_ledger)}
    categories = []
    for row in _by_category(month_ledger):
        prev = previous.get(row["category__name"], ZERO)
        categories.append({
            "name": row["category__name"], "color": row["color"], "icon": row["icon"],
            "total": row["total"], "previous": prev,
            "share": (row["total"] / spent * 100) if spent else ZERO,
            "delta": _delta(row["total"], prev, higher_is_better=False),
        })

    # 12-month trend, running balance since the first record
    window = add_months(month_start, -11)
    opening_income, opening_spent = _period(workspaces, date(1900, 1, 1), window)
    running = opening_income - opening_spent
    ledger_w = _ledger(workspaces).filter(date__gte=window, date__lt=next_month)
    jobs_w = _jobs(workspaces).filter(date__gte=window, date__lt=next_month)
    inc_ledger = _monthly(_household_income(ledger_w), BASE)
    inc_jobs = _monthly(jobs_w, GROSS)
    out_month = _monthly(_out(ledger_w), BASE)

    labels, full_labels, earned, spending, saved_line = [], [], [], [], []
    for i in range(12):
        m = add_months(window, i)
        key = (m.year, m.month)
        inc = inc_ledger.get(key, ZERO) + inc_jobs.get(key, ZERO)
        out = out_month.get(key, ZERO)
        running += inc - out
        labels.append(m.strftime("%b"))
        full_labels.append(m.strftime("%B %Y"))
        earned.append(float(inc))
        spending.append(float(out))
        saved_line.append(float(running))

    work_cash, attention = (None, [])
    if scope != "household":
        work_cash, attention = _work_cash(workspaces, month_start, next_month, symbol, timezone.localdate())

    month_jobs = _jobs(workspaces).filter(date__gte=month_start, date__lt=next_month)
    return {
        "currency": currency,
        "symbol": symbol,
        "labels": LABELS[scope],
        "mixed_currency": len({w.currency for w in workspaces}) > 1,
        "has_any": _ledger(workspaces).exists() or _jobs(workspaces).exists(),
        "has_month": month_ledger.exists() or month_jobs.exists(),
        "income": income, "spent": spent, "saved": saved,
        "saving_rate": (saved / income * 100) if income else None,
        "income_delta": _delta(income, p_income, higher_is_better=True),
        "spent_delta": _delta(spent, p_spent, higher_is_better=False),
        "saved_delta": _delta(saved, p_saved, higher_is_better=True),
        "categories": categories,
        "work_stats": _work_stats(workspaces, month_start, next_month, spent, symbol) if scope == "work" else None,
        "work_cash": work_cash if scope == "work" else None,
        "attention": attention,
        "recent_jobs": list(_jobs(workspaces).select_related("broker")[:5]) if scope == "work" else [],
        "recent": _ledger(workspaces).select_related("category", "workspace")
                    .annotate(num_files=Count("attachments")).order_by("-date", "-id")[:6],
        "chart_data": {
            "symbol": symbol, "labels": labels, "fullLabels": full_labels,
            "earned": earned, "spent": spending, "saved": saved_line,
            "categories": [{"name": c["name"], "color": c["color"], "total": float(c["total"])} for c in categories],
        },
        "budget_panel": _budget_panel(workspaces, month_ledger, spent, scope),
        "bills_due": _bills_due(workspaces, timezone.localdate())[:5],
    }