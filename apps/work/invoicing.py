import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction as db_transaction

from apps.core.models import Category, Transaction

from .models import FactoringDeal, Invoice, InvoiceEntry, Job

PAYMENTS = ("Invoice payments", Category.Kind.INCOME, "fa-money-check-dollar", "#16a34a")
FEES = ("Factoring and quick-pay fees", Category.Kind.EXPENSE, "fa-percent", "#eab308")
CHARGEBACKS = ("Advance chargebacks", Category.Kind.EXPENSE, "fa-rotate-left", "#ef4444")


def create_invoice_for_job(job):
    terms = job.broker.terms_days if job.broker_id else 90
    return Invoice.objects.create(
        job=job, workspace=job.workspace, issue_date=job.date,
        due_date=job.date + timedelta(days=terms), amount=job.gross_pay,
    )


def backfill_invoices(user):
    """Every job has an invoice; this catches jobs created before invoices existed."""
    for job in Job.objects.filter(workspace__owner=user, invoice__isnull=True).select_related("broker"):
        create_invoice_for_job(job)


def _label(invoice):
    return invoice.job.reference or f"{invoice.job.date:%b %d}"


def post_entry(invoice, kind, category, date, amount, note, step):
    name, cat_kind, icon, color = category
    cat, _ = Category.objects.get_or_create(
        workspace=invoice.workspace, kind=cat_kind, name=name,
        defaults={"icon": icon, "color": color, "is_default": True},
    )
    entry = Transaction.objects.create(
        workspace=invoice.workspace, category=cat, date=date, amount=amount,
        currency=invoice.workspace.currency, payment_method=Transaction.Method.BANK,
        note=note, source=Transaction.Source.SYSTEM,
    )
    InvoiceEntry.objects.create(invoice=invoice, transaction=entry, kind=kind, step=step)
    return entry


@db_transaction.atomic
def perform_sale(invoice, factor, *, sold_on, advance_pct, fee_rate_pct, fee_flat, fee_timing, recourse, notes):
    deal = FactoringDeal.objects.create(
        invoice=invoice, factor=factor, sold_on=sold_on, advance_pct=advance_pct,
        fee_rate_pct=fee_rate_pct, fee_flat=fee_flat or Decimal("0"),
        fee_timing=fee_timing, recourse=recourse, notes=notes,
    )
    n, step, label = deal.numbers, uuid.uuid4(), _label(invoice)
    post_entry(invoice, "advance", PAYMENTS, sold_on, n["advance"], f"Advance from {factor.name} · {label}", step)
    if fee_timing == "upfront" and n["fee"] > 0:
        post_entry(invoice, "fee", FEES, sold_on, n["fee"], f"Fee taken by {factor.name} · {label}", step)
    invoice.refresh_status()
    return deal


@db_transaction.atomic
def record_settlement(invoice, mode, date, received, fee_withheld):
    """mode 'release' = reserve released by the factor; 'payment' = the customer (or a quick-pay) paid."""
    step, label = uuid.uuid4(), _label(invoice)
    fee_withheld = fee_withheld or Decimal("0")
    if mode == "release":
        who, kind, text = invoice.deal.factor.name, "reserve_release", "Reserve released by"
    else:
        who = invoice.job.broker.name if invoice.job.broker_id else "customer"
        kind, text = "payment", "Payment from"
    post_entry(invoice, kind, PAYMENTS, date, received + fee_withheld, f"{text} {who} · {label}", step)
    if fee_withheld > 0:
        post_entry(invoice, "fee", FEES, date, fee_withheld, f"Fee withheld by {who} · {label}", step)
    invoice.refresh_status()


@db_transaction.atomic
def record_chargeback(invoice, date, amount):
    post_entry(invoice, "chargeback", CHARGEBACKS, date, amount,
               f"Advance charged back by {invoice.deal.factor.name} · {_label(invoice)}", uuid.uuid4())
    invoice.refresh_status()


@db_transaction.atomic
def undo_last_step(invoice):
    last = invoice.entries.order_by("-id").first()
    if not last:
        return False
    group = list(invoice.entries.filter(step=last.step).select_related("transaction"))
    had_sale = any(e.kind == "advance" for e in group)
    for e in group:
        e.transaction.delete()          # removes the ledger entry and its invoice link
    if had_sale:
        FactoringDeal.objects.filter(invoice=invoice).delete()
    invoice.refresh_status()
    return True