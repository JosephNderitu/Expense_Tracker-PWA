# apps/core/signals.py
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import ensure_workspaces
from django.db.models.signals import post_delete
from .models import Attachment


@receiver(post_delete, sender=Attachment)
def delete_attachment_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_workspaces_for_new_user(sender, instance, created, **kwargs):
    if created:
        ensure_workspaces(instance)