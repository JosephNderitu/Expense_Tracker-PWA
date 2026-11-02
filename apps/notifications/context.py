# apps/notifications/context.py
from .models import Notification


def unread(request):
    if request.user.is_authenticated:
        return {"unread_count": Notification.objects.filter(owner=request.user, read_at__isnull=True).count()}
    return {"unread_count": 0}