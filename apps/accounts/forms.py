# apps/accounts/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm, PasswordChangeForm
from apps.core.forms import INPUT, StyledFormMixin
from .constants import TIMEZONES
from .models import User


class LoginForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget = forms.EmailInput(
            attrs={"class": INPUT, "autofocus": True, "autocomplete": "email", "placeholder": "you@example.com"}
        )
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"


class ResetRequestForm(StyledFormMixin, PasswordResetForm):
    pass


class ResetConfirmForm(StyledFormMixin, SetPasswordForm):
    pass

class ProfileForm(StyledFormMixin, forms.ModelForm):
    timezone = forms.ChoiceField(choices=TIMEZONES, label="Time zone", help_text="Decides what counts as today for dates, bills and alerts.")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "timezone"]
        labels = {"first_name": "First name", "last_name": "Last name"}


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    pass