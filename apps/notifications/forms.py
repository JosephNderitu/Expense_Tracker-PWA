# apps/notifications/forms.py
from django import forms

from apps.core.forms import StyledFormMixin

from .models import NotificationPrefs


class PrefsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = NotificationPrefs
        fields = ["bills", "invoices", "budgets", "weekly"]