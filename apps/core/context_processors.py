from datetime import timedelta

from django.utils import timezone

from apps.planning.models import Bill

from .services import get_scope, scoped_workspaces

SCOPE_OPTIONS = [
    ("all", "Overview", "fa-layer-group"),
    ("household", "Household", "fa-house"),
    ("work", "Work", "fa-truck"),
]


def workspace(request):
    context = {"scope": get_scope(request), "scope_options": SCOPE_OPTIONS, "bills_due_count": 0}
    if request.user.is_authenticated:
        today = timezone.localdate()
        rows = Bill.objects.filter(
            workspace__in=scoped_workspaces(request), is_active=True, next_due__lte=today + timedelta(days=30)
        ).values_list("next_due", "remind_days")
        context["bills_due_count"] = sum(1 for due, remind in rows if (due - today).days <= remind)
    return context