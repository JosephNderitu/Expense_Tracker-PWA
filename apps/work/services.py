# apps/work/services.py
from django.utils import timezone

from apps.core.models import Workspace
from apps.core.services import ensure_workspaces

from .models import Party, Truck


def default_truck(workspace):
    return workspace.trucks.filter(is_active=True).first() or Truck.objects.create(workspace=workspace, name="My truck")


def get_work_workspace(request):
    ensure_workspaces(request.user)
    workspace = Workspace.objects.get(owner=request.user, type=Workspace.Type.WORK)
    default_truck(workspace)
    return workspace


def resolve_party(workspace, kind, name):
    """Find a saved party by name (any capitalisation) or create it. Returns None for a blank name."""
    name = " ".join((name or "").split())
    if not name:
        return None
    party = Party.objects.filter(workspace=workspace, kind=kind, name__iexact=name).first()
    if party is None:
        return Party.objects.create(workspace=workspace, kind=kind, name=name)
    party.last_used_at = timezone.now()
    party.save(update_fields=["last_used_at", "updated_at"])
    return party