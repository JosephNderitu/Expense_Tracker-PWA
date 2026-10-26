# apps/core/urls.py
from django.http import HttpResponse
from django.urls import path

app_name = "core"

def dashboard(request):
    return HttpResponse("Dashboard placeholder")

urlpatterns = [
    path("", dashboard, name="dashboard"),
]