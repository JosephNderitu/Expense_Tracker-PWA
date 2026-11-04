# apps/pwa/models.py
from django.conf import settings
from django.db import models


class OfflineItem(models.Model):
    """Remembers entries already created from the offline queue, so a retry never duplicates them."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offline_items")
    client_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=10)
    url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="one_result_per_offline_item")]