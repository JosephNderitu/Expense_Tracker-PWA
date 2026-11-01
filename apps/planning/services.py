from datetime import timedelta
from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.dates import add_months
from apps.core.models import Transaction
from apps.core.selectors import BASE

from .models import Bill, BillPayment


def default_amount(bill):
    """Fixed bills use their amount; variable ones start from what you paid last time."""
    if bill.amount_varies:
        last = bill.payments.filter(transaction__isnull=False).select_related("transaction").order_by("-id").first()
        if last:
            return last.transaction.amount
    return bill.amount


@db_transaction.atomic
def pay_bill(bill, *, date, amount, method, note=""):
    entry = Transaction.objects.create(
        workspace=bill.workspace, category=bill.category, date=date, amount=amount,
        currency=bill.workspace.currency, payment_method=method, note=note or bill.name,
        source=Transaction.Source.RECURRING,
    )
    BillPayment.objects.create(bill=bill, due_date=bill.next_due, transaction=entry)
    bill.next_due = bill.following(bill.next_due)
    bill.save(update_fields=["next_due", "updated_at"])
    return entry


@db_transaction.atomic
def skip_bill(bill):
    BillPayment.objects.create(bill=bill, due_date=bill.next_due, skipped=True)
    bill.next_due = bill.following(bill.next_due)
    bill.save(update_fields=["next_due", "updated_at"])


@db_transaction.atomic
def undo_last(bill):
    last = bill.payments.select_related("transaction").order_by("-id").first()
    if not last:
        return False
    due = last.due_date
    if last.transaction:
        last.transaction.delete()      # removes the ledger entry and this payment record with it
    else:
        last.delete()
    bill.next_due = due
    bill.save(update_fields=["next_due", "updated_at"])
    return True


def three_month_average(workspaces):
    """Average monthly spending per category over the last three full months."""
    end = timezone.localdate().replace(day=1)
    start = add_months(end, -3)
    rows = (
        Transaction.objects.filter(workspace__in=workspaces, direction="out", date__gte=start, date__lt=end)
        .exclude(invoice_link__kind="chargeback")
        .order_by().values("category_id").annotate(t=Sum(BASE))
    )
    return {r["category_id"]: (r["t"] / 3).quantize(Decimal("0.01")) for r in rows}