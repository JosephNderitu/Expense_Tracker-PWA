# apps/accounts/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm

INPUT = (
    "block w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-sm "
    "placeholder-slate-400 focus:border-household focus:outline-none focus:ring-2 focus:ring-household/30"
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)


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