# apps/notifications/middleware.py
import logging
import time

from .services import sync_alerts

log = logging.getLogger(__name__)
INTERVAL = 600     # seconds between automatic checks


class AlertsMiddleware:
    """Creates alerts when the owner opens a page, at most once every ten minutes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.method == "GET" and not request.headers.get("x-requested-with"):
            now = time.time()
            if now - request.session.get("alerts_synced_at", 0) > INTERVAL:
                try:
                    sync_alerts(request.user)
                except Exception:       # alerts must never break a page
                    log.exception("Alert sync failed")
                request.session["alerts_synced_at"] = now
        return self.get_response(request)