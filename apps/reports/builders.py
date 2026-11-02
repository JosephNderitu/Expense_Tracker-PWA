from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.constants import CURRENCY_SYMBOLS
from apps.core.dates import add_months
from apps.core.selectors import BASE, GROSS, ZERO, _household_income, _jobs, _ledger, _monthly, _out, _sum
from apps.work.models import FactoringDeal, FuelDetail, Invoice, InvoiceEntry

ENTRY_LIMIT = 3000
SCOPE_LABELS = {"all": "Household and work", "household": "Household", "work": "Work"}


@dataclass
class Params:
    kind: str
    scope: str
    date_from: date
    date_to: date
    detail: bool = False


@dataclass
class Table:
    title: str
    columns: list                 # [(header, kind)] kind: text, date, money, price, qty, num, pct
    rows: list
    totals: list = None           # same length as columns


@dataclass
class Report:
    title: str
    period: str
    scope_label: str
    symbol: str
    kpis: list = field(default_factory=list)      # [(label, value, kind)]
    tables: list = field(default_factory=list)
    chart: dict = None
    notes: list = field(default_factory=list)


def _period(p):
    return f"{p.date_from:%b %d, %Y} to {p.date_to:%b %d, %Y}"


def _symbol(workspaces):
    currency = workspaces[0].currency
    return CURRENCY_SYMBOLS.get(currency, f"{currency} ")


def _work(user):
    return list(user.workspaces.filter(type="work"))


def _pct(part, whole):
    return (part / whole * 100) if whole else None


def build_statement(user, p):
    workspaces = list(user.workspaces.all() if p.scope == "all" else user.workspaces.filter(type=p.scope))
    ledger = _ledger(workspaces).filter(date__gte=p.date_from, date__lte=p.date_to)
    jobs = _jobs(workspaces).filter(date__gte=p.date_from, date__lte=p.date_to)
    income = _sum(_household_income(ledger)) + _sum(jobs, GROSS)
    spent = _sum(_out(ledger))
    net = income - spent

    report = Report("Income and expense statement", _period(p), SCOPE_LABELS[p.scope], _symbol(workspaces))
    report.kpis = [("Earned" if p.scope == "work" else "Income", income, "money"), ("Expenses", spent, "money"), ("Net", net, "money")]
    rate = _pct(net, income)
    if rate is not None:
        report.kpis.append(("Kept", rate, "pct"))

    cats = list(_out(ledger).values("category__name").annotate(tot=Sum(BASE), cnt=Count("pk")).order_by("-tot"))
    report.tables.append(Table(
        "Expenses by category", [("Category", "text"), ("Amount", "money"), ("Share", "pct"), ("Entries", "num")],
        [[c["category__name"], c["tot"], _pct(c["tot"], spent), c["cnt"]] for c in cats],
        ["Total", spent, 100 if spent else None, sum(c["cnt"] for c in cats)],
    ))

    months, m = [], p.date_from.replace(day=1)
    while m <= p.date_to:
        months.append(m)
        m = add_months(m, 1)
    inc_l, inc_j, out_m = _monthly(_household_income(ledger), BASE), _monthly(jobs, GROSS), _monthly(_out(ledger), BASE)
    month_rows = []
    for mo in months:
        key = (mo.year, mo.month)
        i, o = inc_l.get(key, ZERO) + inc_j.get(key, ZERO), out_m.get(key, ZERO)
        month_rows.append([mo.strftime("%b %Y"), i, o, i - o])
    report.tables.append(Table(
        "By month", [("Month", "text"), ("Income", "money"), ("Expenses", "money"), ("Net", "money")],
        month_rows, ["Total", income, spent, net],
    ))
    if 2 <= len(months) <= 24:
        report.chart = {"labels": [mo.strftime("%b %y") for mo in months],
                        "series": [("Income", [r[1] for r in month_rows]), ("Expenses", [r[2] for r in month_rows])]}

    if p.detail:
        entries = list(ledger.select_related("category", "workspace").order_by("date", "id")[: ENTRY_LIMIT + 1])
        if len(entries) > ENTRY_LIMIT:
            entries = entries[:ENTRY_LIMIT]
            report.notes.append(f"Only the first {ENTRY_LIMIT:,} entries are listed. Narrow the dates to see the rest.")
        cols = [("Date", "date"), ("Description", "text"), ("Category", "text"), ("Method", "text")]
        if p.scope == "all":
            cols.append(("Workspace", "text"))
        cols.append(("Amount", "money"))
        rows = []
        for e in entries:
            row = [e.date, e.note or e.category.name, e.category.name, e.get_payment_method_display()]
            if p.scope == "all":
                row.append(e.workspace.name)
            row.append(e.base_amount if e.direction == "in" else -e.base_amount)
            rows.append(row)
        report.tables.append(Table("All entries (money in and out)", cols, rows))
        job_list = list(jobs.select_related("broker").order_by("date", "id"))
        if job_list:
            report.tables.append(Table(
                "Jobs earned", [("Date", "date"), ("Load", "text"), ("Route", "text"), ("Broker", "text"), ("Pay", "money")],
                [[j.date, j.reference, " to ".join(x for x in (j.origin, j.destination) if x), j.broker.name if j.broker else "", j.gross_pay] for j in job_list],
                ["Total", None, None, None, sum((j.gross_pay for j in job_list), ZERO)],
            ))
    if not (income or spent):
        report.notes.append("Nothing was recorded in this period.")
    return report


def build_invoices(user, p):
    ws = _work(user)
    today = timezone.localdate()
    base = Invoice.objects.filter(workspace__in=ws, job__deleted_at__isnull=True)
    ranged = list(base.filter(issue_date__gte=p.date_from, issue_date__lte=p.date_to)
                  .with_balance().select_related("job", "job__broker").order_by("issue_date", "id"))
    fee_rows = (InvoiceEntry.objects.filter(invoice_id__in=[i.pk for i in ranged], kind="fee", transaction__deleted_at__isnull=True)
                .values("invoice_id").annotate(tot=Sum("transaction__amount")))
    fees = {r["invoice_id"]: r["tot"] for r in fee_rows}

    rows, t_amount, t_received, t_fees, t_bal = [], ZERO, ZERO, ZERO, ZERO
    for i in ranged:
        received, fee = i.inflow - i.back, fees.get(i.pk, ZERO)
        status = "Overdue" if i.status == "open" and i.due_date < today else i.get_status_display()
        rows.append([i.issue_date, i.job.broker.name if i.job.broker else "", i.job.reference, i.due_date, status, i.amount, received, fee, i.bal])
        t_amount, t_received, t_fees = t_amount + i.amount, t_received + received, t_fees + fee
        t_bal += i.bal if i.status != "paid" else ZERO

    report = Report("Invoices and receivables", _period(p), "Work", _symbol(ws))
    report.kpis = [("Invoiced", t_amount, "money"), ("Received", t_received, "money"), ("Fees paid", t_fees, "money"), ("Still to come", t_bal, "money")]
    report.tables.append(Table(
        "Invoices issued in this period",
        [("Issued", "date"), ("Customer", "text"), ("Load", "text"), ("Due", "date"), ("Status", "text"),
         ("Amount", "money"), ("Received", "money"), ("Fees", "money"), ("To come", "money")],
        rows, ["Total", None, None, None, None, t_amount, t_received, t_fees, t_bal],
    ))

    deals = list(FactoringDeal.objects.filter(invoice__workspace__in=ws, invoice__job__deleted_at__isnull=True,
                                              sold_on__gte=p.date_from, sold_on__lte=p.date_to)
                 .select_related("invoice", "factor").order_by("sold_on", "id"))
    d_rows, d_amt, d_adv, d_fee = [], ZERO, ZERO, ZERO
    for d in deals:
        n = d.numbers
        d_rows.append([d.sold_on, d.factor.name, d.invoice.amount, n["advance"], n["fee"], d.cost_pct, "Recourse" if d.recourse else "Non-recourse"])
        d_amt, d_adv, d_fee = d_amt + d.invoice.amount, d_adv + n["advance"], d_fee + n["fee"]
    report.tables.append(Table(
        "Invoices sold to a factoring company",
        [("Sold", "date"), ("Factoring company", "text"), ("Invoice", "money"), ("Advance", "money"), ("Fee", "money"), ("Cost", "pct"), ("Terms", "text")],
        d_rows, ["Total", None, d_amt, d_adv, d_fee, _pct(d_fee, d_amt), None],
    ))

    waiting = list(base.exclude(status="paid").with_balance())
    buckets, aging = (("0 to 30 days", 0, 30), ("31 to 60 days", 31, 60), ("61 to 90 days", 61, 90), ("Over 90 days", 91, 10**6)), []
    for label, lo, hi in buckets:
        group = [i for i in waiting if lo <= (today - i.issue_date).days <= hi]
        aging.append([label, len(group), sum((i.bal for i in group), ZERO)])
    report.tables.append(Table(
        f"Unpaid invoices by age, as of {today:%b %d, %Y}", [("Age since issue", "text"), ("Invoices", "num"), ("Still to come", "money")],
        aging, ["Total", sum(a[1] for a in aging), sum((a[2] for a in aging), ZERO)],
    ))
    if not ranged:
        report.notes.append("No invoices were issued in this period.")
    return report


def build_fuel(user, p):
    ws = _work(user)
    qs = FuelDetail.objects.filter(transaction__workspace__in=ws, transaction__deleted_at__isnull=True,
                                   transaction__date__gte=p.date_from, transaction__date__lte=p.date_to)
    states = list(qs.values("state").annotate(tot_gal=Sum("gallons"), tot_cost=Sum("transaction__amount"), fills=Count("pk")).order_by("state"))
    gal = sum((s["tot_gal"] for s in states), ZERO)
    cost = sum((s["tot_cost"] for s in states), ZERO)
    fills = sum(s["fills"] for s in states)

    report = Report("Fuel by state", _period(p), "Work", _symbol(ws))
    report.kpis = [("Gallons", gal, "qty"), ("Fuel cost", cost, "money"), ("Average per gallon", (cost / gal) if gal else None, "price"), ("Fill-ups", fills, "num")]
    report.tables.append(Table(
        "Fuel purchased by state", [("State", "text"), ("Gallons", "qty"), ("Cost", "money"), ("Avg per gallon", "price"), ("Fill-ups", "num")],
        [[s["state"], s["tot_gal"], s["tot_cost"], s["tot_cost"] / s["tot_gal"], s["fills"]] for s in states],
        ["Total", gal, cost, (cost / gal) if gal else None, fills],
    ))
    if p.detail:
        fills_list = qs.select_related("transaction", "truck").order_by("transaction__date", "id")
        report.tables.append(Table(
            "Every fill-up",
            [("Date", "date"), ("State", "text"), ("Station", "text"), ("Gallons", "qty"), ("Per gallon", "price"), ("Total", "money"), ("Truck", "text"), ("Odometer", "num")],
            [[f.transaction.date, f.state, f.station, f.gallons, f.price_per_gallon, f.transaction.amount, f.truck.name, f.odometer] for f in fills_list],
        ))
    report.notes += [
        "Gallons are fuel purchased at each fill-up, grouped by the state of purchase.",
        "A quarterly IFTA return also needs miles driven in each state. This app does not record those, so take them from your ELD or trip sheets.",
    ]
    if not states:
        report.notes.append("No fuel was recorded in this period.")
    return report


def build_jobs(user, p):
    ws = _work(user)
    jobs = list(_jobs(ws).filter(date__gte=p.date_from, date__lte=p.date_to).select_related("broker").order_by("date", "id"))
    earned = sum((j.gross_pay for j in jobs), ZERO)
    miles = sum((j.miles or 0) for j in jobs)
    mile_jobs = [j for j in jobs if j.miles]
    per_mile = (sum((j.gross_pay for j in mile_jobs), ZERO) / sum(j.miles for j in mile_jobs)) if mile_jobs else None

    report = Report("Jobs and earnings", _period(p), "Work", _symbol(ws))
    report.kpis = [("Jobs", len(jobs), "num"), ("Earned", earned, "money"), ("Miles", miles, "num"), ("Per mile", per_mile, "money")]
    report.tables.append(Table(
        "Jobs", [("Date", "date"), ("Load", "text"), ("From", "text"), ("To", "text"), ("Broker", "text"), ("Miles", "num"), ("Pay", "money"), ("Per mile", "money")],
        [[j.date, j.reference, j.origin, j.destination, j.broker.name if j.broker else "", j.miles, j.gross_pay,
          (j.gross_pay / j.miles) if j.miles else None] for j in jobs],
        ["Total", None, None, None, None, miles, earned, per_mile],
    ))
    groups = {}
    for j in jobs:
        g = groups.setdefault(j.broker.name if j.broker else "No broker", [0, ZERO])
        g[0] += 1
        g[1] += j.gross_pay
    report.tables.append(Table(
        "Earnings by broker", [("Broker", "text"), ("Jobs", "num"), ("Earned", "money"), ("Share", "pct")],
        [[name, g[0], g[1], _pct(g[1], earned)] for name, g in sorted(groups.items(), key=lambda kv: kv[1][1], reverse=True)],
        ["Total", len(jobs), earned, 100 if earned else None],
    ))
    if not jobs:
        report.notes.append("No jobs were recorded in this period.")
    return report


BUILDERS = {"statement": build_statement, "invoices": build_invoices, "fuel": build_fuel, "jobs": build_jobs}