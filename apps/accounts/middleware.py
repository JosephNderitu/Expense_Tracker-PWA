# apps/accounts/middleware.py
import zoneinfo

from django.utils import timezone


class UserTimezoneMiddleware:
    """Every 'today' in the app follows the signed-in user's time zone."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        name = getattr(request.user, "timezone", None) if request.user.is_authenticated else None
        try:
            timezone.activate(zoneinfo.ZoneInfo(name)) if name else timezone.deactivate()
        except zoneinfo.ZoneInfoNotFoundError:
            timezone.deactivate()
        return self.get_response(request)