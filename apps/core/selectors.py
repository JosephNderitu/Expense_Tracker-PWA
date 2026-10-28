from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Max, Q, Sum, Count
from django.db.models.functions import TruncMonth

from .constants import CURRENCY_SYMBOLS
from .models import Transaction

ZERO = Decimal("0")
BASE = ExpressionWrapper(F("amount") * F("rate_to_base"), output_field=DecimalField(max_digits=24, decimal_places=8))


def add_months(d, n):
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def parse_month(raw, today):
    current = today.replace(day=1)
    try:
        year, month = (int(part) for part in raw.split("-"))
        return min(date(year, month, 1), current)   # never a future month
    except (AttributeError, ValueError):
        return current


def _sums(qs):
    agg = qs.aggregate(
        income=Sum(BASE, filter=Q(direction="in")),
        spent=Sum(BASE, filter=Q(direction="out")),
    )
    return agg["income"] or ZERO, agg["spent"] or ZERO


def _delta(current, previous, *, higher_is_better):
    if not previous:
        return None
    pct = (current - previous) / abs(previous) * 100
    return {"pct": abs(pct).quantize(Decimal("0.1")), "up": pct >= 0, "good": (pct >= 0) == higher_is_better}


def _by_category(qs):
    return list(
        qs.filter(direction="out")
        .values("category__name")
        .annotate(total=Sum(BASE), color=Max("category__color"), icon=Max("category__icon"))
        .order_by("-total")
    )


def dashboard_data(user, scope, month_start):
    workspaces = list(user.workspaces.all() if scope == "all" else user.workspaces.filter(type=scope))
    currency = workspaces[0].currency
    qs = Transaction.objects.filter(workspace__in=workspaces)

    next_month = add_months(month_start, 1)
    prev_month = add_months(month_start, -1)
    month_qs = qs.filter(date__gte=month_start, date__lt=next_month)
    prev_qs = qs.filter(date__gte=prev_month, date__lt=month_start)

    income, spent = _sums(month_qs)
    p_income, p_spent = _sums(prev_qs)
    saved, p_saved = income - spent, p_income - p_spent

    # Expenses by category, compared with last month
    previous = {r["category__name"]: r["total"] for r in _by_category(prev_qs)}
    categories = []
    for row in _by_category(month_qs):
        prev = previous.get(row["category__name"], ZERO)
        categories.append({
            "name": row["category__name"], "color": row["color"], "icon": row["icon"],
            "total": row["total"], "previous": prev,
            "share": (row["total"] / spent * 100) if spent else ZERO,
            "delta": _delta(row["total"], prev, higher_is_better=False),
        })

    # 12-month trend: monthly earned/spent plus a running balance since the first record
    window_start = add_months(month_start, -11)
    opening_income, opening_spent = _sums(qs.filter(date__lt=window_start))
    running = opening_income - opening_spent
    rows = (
        qs.filter(date__gte=window_start, date__lt=next_month)
        .annotate(m=TruncMonth("date")).values("m")
        .annotate(income=Sum(BASE, filter=Q(direction="in")), spent=Sum(BASE, filter=Q(direction="out")))
        .order_by("m")
    )
    by_month = {(r["m"].year, r["m"].month): r for r in rows}
    labels, full_labels, earned, spending, saved_line = [], [], [], [], []
    for i in range(12):
        m = add_months(window_start, i)
        row = by_month.get((m.year, m.month))
        inc = (row["income"] or ZERO) if row else ZERO
        out = (row["spent"] or ZERO) if row else ZERO
        running += inc - out
        labels.append(m.strftime("%b"))
        full_labels.append(m.strftime("%B %Y"))
        earned.append(float(inc))
        spending.append(float(out))
        saved_line.append(float(running))

    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    return {
        "currency": currency,
        "symbol": symbol,
        "mixed_currency": len({w.currency for w in workspaces}) > 1,
        "has_any": qs.exists(),
        "has_month": month_qs.exists(),
        "income": income, "spent": spent, "saved": saved,
        "saving_rate": (saved / income * 100) if income else None,
        "income_delta": _delta(income, p_income, higher_is_better=True),
        "spent_delta": _delta(spent, p_spent, higher_is_better=False),
        "saved_delta": _delta(saved, p_saved, higher_is_better=True),
        "categories": categories,
        "recent": qs.select_related("category", "workspace")
            .annotate(num_files=Count("attachments"))
            .order_by("-date", "-id")[:6],
        "chart_data": {
            "symbol": symbol, "labels": labels, "fullLabels": full_labels,
            "earned": earned, "spent": spending, "saved": saved_line,
            "categories": [{"name": c["name"], "color": c["color"], "total": float(c["total"])} for c in categories],
        },
    }