# apps/notifications/services.py
from datetime import timedelta

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.constants import CURRENCY_SYMBOLS
from apps.core.dates import add_months
from apps.core.selectors import BASE, ZERO, _ledger, _out, _period
from apps.core.templatetags.money import money
from apps.planning.models import Bill, Budget
from apps.work.models import Invoice

from .models import Notification, NotificationPrefs

K, T = Notification.Kind, Notification.Tone


def get_prefs(user):
    prefs, _ = NotificationPrefs.objects.get_or_create(owner=user)
    return prefs


def _add(user, kind, key, tone, title, body, url):
    Notification.objects.get_or_create(
        owner=user, dedupe_key=key,
        defaults={"kind": kind, "tone": tone, "title": title, "body": body, "url": url},
    )


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _bill_alerts(user, workspaces, today, symbol):
    bills = Bill.objects.filter(workspace__in=workspaces, is_active=True, next_due__lte=today + timedelta(days=30))
    for b in bills.select_related("category"):
        days = b.days_to_due
        if days > b.remind_days:
            continue
        if days < 0:
            stage, tone, title = "overdue", T.BAD, f"{b.name} is {_plural(-days, 'day')} overdue"
        elif days == 0:
            stage, tone, title = "due", T.WARN, f"{b.name} is due today"
        else:
            stage, tone, title = "due", T.WARN, f"{b.name} is due in {_plural(days, 'day')}"
        _add(user, K.BILL, f"bill:{b.pk}:{b.next_due}:{stage}", tone, title,
             f"{money(b.amount, symbol)} · due {b.next_due:%b %d}", reverse("planning:bill_detail", args=[b.pk]))


def _invoice_alerts(user, workspaces, today, symbol):
    invoices = (Invoice.objects.filter(workspace__in=workspaces, job__deleted_at__isnull=True).exclude(status="paid")
                .with_balance().select_related("job", "job__broker", "deal", "deal__factor"))
    for i in invoices:
        late = (today - i.due_date).days
        if late <= 0:
            continue
        url = reverse("work:job_detail", args=[i.job_id])
        if i.status == "open":
            who = i.job.broker.name if i.job.broker_id else "A customer"
            _add(user, K.INVOICE, f"inv:{i.pk}:overdue", T.BAD, f"{who} owes {money(i.bal, symbol)}",
                 f"The invoice is {_plural(late, 'day')} overdue.", url)
        elif hasattr(i, "deal"):
            _add(user, K.INVOICE, f"inv:{i.pk}:reserve", T.WARN, f"Check your reserve from {i.deal.factor.name}",
                 f"The customer was due {_plural(late, 'day')} ago. {money(i.bal, symbol)} is still to come.", url)


def _budget_alerts(user, workspaces, today, symbol):
    budgets = list(Budget.objects.filter(workspace__in=workspaces, category__is_active=True).select_related("category"))
    if not budgets:
        return
    month = today.replace(day=1)
    ledger = _ledger(workspaces).filter(date__gte=month, date__lt=add_months(month, 1))
    actual = {r["category_id"]: r["t"] for r in _out(ledger).order_by().values("category_id").annotate(t=Sum(BASE))}
    for b in budgets:
        used = actual.get(b.category_id, ZERO)
        pct = used / b.amount * 100
        if pct >= 100:
            level, tone, title = 100, T.BAD, f"Over budget: {b.category.name}"
        elif pct >= 80:
            level, tone, title = 80, T.WARN, f"{b.category.name} is at {int(pct)}% of its budget"
        else:
            continue
        _add(user, K.BUDGET, f"budget:{b.pk}:{month:%Y-%m}:{level}", tone, title,
             f"{money(used, symbol)} spent of {money(b.amount, symbol)} this month.", reverse("core:dashboard"))


def _weekly_summary(user, workspaces, today, symbol):
    monday = today - timedelta(days=today.weekday())
    year, week, _ = monday.isocalendar()
    key = f"week:{year}-{week}"
    if Notification.objects.filter(owner=user, dedupe_key=key).exists():
        return
    start = monday - timedelta(days=7)
    income, spent = _period(workspaces, start, monday)
    if not (income or spent):
        return
    _add(user, K.SUMMARY, key, T.INFO, f"Last week: {money(income, symbol)} in, {money(spent, symbol)} out",
         f"Net {money(income - spent, symbol)} for the week of {start:%b %d}.", reverse("core:dashboard"))


def sync_alerts(user):
    workspaces = list(user.workspaces.all())
    if not workspaces:
        return
    prefs, today = get_prefs(user), timezone.localdate()
    symbol = CURRENCY_SYMBOLS.get(workspaces[0].currency, f"{workspaces[0].currency} ")
    if prefs.bills:
        _bill_alerts(user, workspaces, today, symbol)
    if prefs.invoices:
        _invoice_alerts(user, workspaces, today, symbol)
    if prefs.budgets:
        _budget_alerts(user, workspaces, today, symbol)
    if prefs.weekly:
        _weekly_summary(user, workspaces, today, symbol)
    Notification.objects.filter(owner=user, read_at__lt=timezone.now() - timedelta(days=90)).delete()