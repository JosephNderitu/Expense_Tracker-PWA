from django import forms

from apps.core.forms import StyledFormMixin

from .models import NotificationPrefs

TIME = lambda: forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class PrefsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = NotificationPrefs
        fields = ["bills", "invoices", "budgets", "weekly", "entry_reminder", "reminder_time", "quiet_start", "quiet_end"]
        widgets = {"reminder_time": TIME(), "quiet_start": TIME(), "quiet_end": TIME()}