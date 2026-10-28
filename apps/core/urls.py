# apps/core/urls.py
from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("workspace/switch/", views.switch_workspace, name="switch_workspace"),
    path("transactions/new/", views.transaction_create, name="transaction_create"),
    
    path("transactions/<int:pk>/", views.transaction_detail, name="transaction_detail"),
    path("attachments/<int:pk>/", views.attachment_file, name="attachment_file"),
    path("attachments/<int:pk>/delete/", views.attachment_delete, name="attachment_delete"),
]