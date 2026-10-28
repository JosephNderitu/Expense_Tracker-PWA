# apps/accounts/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from apps.core.forms import INPUT, StyledFormMixin


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