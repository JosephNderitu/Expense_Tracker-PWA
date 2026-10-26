# apps/accounts/views.py
from django.contrib.auth.views import LoginView
from .forms import LoginForm


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True