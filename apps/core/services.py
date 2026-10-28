# apps/core/services.py
from django.db import transaction as db_transaction

from .models import Category, Workspace

# (name, kind, Font Awesome icon, color)
DEFAULT_CATEGORIES = {
    Workspace.Type.HOUSEHOLD: [
        ("Groceries", "expense", "fa-basket-shopping", "#16a34a"),
        ("Water", "expense", "fa-droplet", "#0ea5e9"),
        ("Electricity", "expense", "fa-bolt", "#eab308"),
        ("Gas", "expense", "fa-fire-flame-simple", "#f97316"),
        ("Rent", "expense", "fa-house", "#8b5cf6"),
        ("Data and airtime", "expense", "fa-wifi", "#06b6d4"),
        ("Shopping", "expense", "fa-bag-shopping", "#ec4899"),
        ("Transport", "expense", "fa-bus", "#64748b"),
        ("Health", "expense", "fa-heart-pulse", "#ef4444"),
        ("School fees", "expense", "fa-graduation-cap", "#6366f1"),
        ("Family support", "expense", "fa-hand-holding-heart", "#14b8a6"),
        ("Savings", "expense", "fa-piggy-bank", "#22c55e"),
        ("Other", "expense", "fa-ellipsis", "#94a3b8"),
        ("Salary", "income", "fa-money-bill-wave", "#16a34a"),
        ("Other income", "income", "fa-plus", "#0d9488"),
    ],
    Workspace.Type.WORK: [],  # seeded in Sprint 3 (fuel, maintenance, jobs...)
}


@db_transaction.atomic
def ensure_workspaces(user):
    for ws_type, label in Workspace.Type.choices:
        workspace, created = Workspace.objects.get_or_create(
            owner=user, type=ws_type, defaults={"name": label}
        )
        if created:
            for order, (name, kind, icon, color) in enumerate(DEFAULT_CATEGORIES[ws_type]):
                Category.objects.create(
                    workspace=workspace, name=name, kind=kind, icon=icon,
                    color=color, is_default=True, sort_order=order,
                )


def get_active_workspace(request):
    ws_type = request.session.get("active_workspace", "household")
    try:
        return Workspace.objects.get(owner=request.user, type=ws_type)
    except Workspace.DoesNotExist:
        ensure_workspaces(request.user)
        return Workspace.objects.get(owner=request.user, type=ws_type)