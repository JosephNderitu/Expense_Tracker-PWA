# apps/accounts/views.py
from django.contrib.auth.views import LoginView
from .forms import LoginForm
from django.contrib.auth.views import PasswordResetView
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy

from apps.core.nav import crumbs

from .forms import ProfileForm, StyledPasswordChangeForm


@method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=True), name="dispatch")
class ThrottledPasswordResetView(PasswordResetView):
    pass

class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def settings_home(request):
    cards = [
        ("Account", [
            ("fa-user", "Profile and time zone", "Your name and the time zone used for dates", reverse("accounts:profile")),
            ("fa-key", "Change password", "Choose a new password", reverse("accounts:password_change")),
        ]),
        ("Your data", [
            ("fa-tags", "Categories", "Add, rename, recolour or hide categories", reverse("core:category_list")),
            ("fa-truck", "Trucks", "Add a truck or retire an old one", reverse("work:truck_list")),
            ("fa-address-book", "Brokers and factoring companies", "Rename, set payment terms, tidy up", reverse("work:party_list")),
            ("fa-palette", "Report branding", "Logo, name and address on your PDFs", reverse("reports:branding")),
        ]),
        ("Alerts", [
            ("fa-bell", "Notifications", "Choose which alerts you receive", reverse("notifications:prefs")),
        ]),
    ]
    return render(request, "accounts/settings_home.html", {"groups": cards, "crumbs": crumbs(("Settings", None))})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("accounts:settings")
    return render(request, "settings/form.html", {
        "form": form, "title": "Profile and time zone", "intro": f"Signed in as {request.user.email}.",
        "cancel_url": reverse("accounts:settings"),
        "crumbs": crumbs(("Settings", reverse("accounts:settings")), ("Profile", None)),
    })


class PasswordChange(SuccessMessageMixin, PasswordChangeView):
    template_name = "settings/form.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:settings")
    success_message = "Password changed."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Change password", intro="Enter your current password, then choose a new one.",
                   button="Change password", cancel_url=reverse("accounts:settings"),
                   crumbs=crumbs(("Settings", reverse("accounts:settings")), ("Password", None)))
        return ctx