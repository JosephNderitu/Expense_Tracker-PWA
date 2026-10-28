# apps/accounts/views.py
from django.contrib.auth.views import LoginView
from .forms import LoginForm
from django.contrib.auth.views import PasswordResetView
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit


@method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=True), name="dispatch")
class ThrottledPasswordResetView(PasswordResetView):
    pass

class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True