import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

log = logging.getLogger(__name__)


def push_ready():
    return bool(settings.VAPID_PUBLIC_KEY) and settings.VAPID_PRIVATE_KEY_PATH.exists()


def send_to_user(user, title, body, url, tag=None):
    """Sends to every device the person enabled. Returns how many devices accepted it."""
    if not push_ready():
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    sent = 0
    for sub in list(user.push_subscriptions.all()):
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload, vapid_private_key=str(settings.VAPID_PRIVATE_KEY_PATH),
                vapid_claims={"sub": settings.VAPID_SUBJECT}, ttl=3600,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):          # the device uninstalled or revoked permission
                sub.delete()
            else:
                log.warning("Push failed (%s): %s", status, exc)
    return sent