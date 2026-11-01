# apps/planning/urls.py
from django.urls import path
from . import views

app_name = "planning"

urlpatterns = [
    path("bills/", views.bill_list, name="bill_list"),
    path("bills/new/", views.bill_create, name="bill_create"),
    path("bills/<int:pk>/", views.bill_detail, name="bill_detail"),
    path("bills/<int:pk>/edit/", views.bill_edit, name="bill_edit"),
    path("bills/<int:pk>/pay/", views.bill_pay, name="bill_pay"),
    path("bills/<int:pk>/quickpay/", views.bill_quickpay, name="bill_quickpay"),
    path("bills/<int:pk>/skip/", views.bill_skip, name="bill_skip"),
    path("bills/<int:pk>/undo/", views.bill_undo, name="bill_undo"),
    path("bills/<int:pk>/archive/", views.bill_archive, name="bill_archive"),
    path("budgets/", views.budget_edit, name="budget_edit"),
]