# apps/work/urls.py
from django.urls import path
from . import views

app_name = "work"

urlpatterns = [
    path("add/", views.add, name="add"),
    path("jobs/", views.JobListView.as_view(), name="job_list"),
    path("jobs/new/", views.job_create, name="job_create"),
    path("jobs/<int:pk>/edit/", views.job_edit, name="job_edit"),
    path("jobs/<int:pk>/delete/", views.job_delete, name="job_delete"),
    path("jobs/<int:pk>/restore/", views.job_restore, name="job_restore"),
    path("fuel/new/", views.fuel_create, name="fuel_create"),
    path("fuel/<int:pk>/edit/", views.fuel_edit, name="fuel_edit"),
    path("maintenance/new/", views.maintenance_create, name="maintenance_create"),
    path("maintenance/<int:pk>/edit/", views.maintenance_edit, name="maintenance_edit"),
    
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<int:pk>/sell/", views.invoice_sell, name="invoice_sell"),
    path("invoices/<int:pk>/release/", views.invoice_release, name="invoice_release"),
    path("invoices/<int:pk>/pay/", views.invoice_pay, name="invoice_pay"),
    path("invoices/<int:pk>/chargeback/", views.invoice_chargeback, name="invoice_chargeback"),
    path("invoices/<int:pk>/edit/", views.invoice_edit, name="invoice_edit"),
    path("invoices/<int:pk>/undo/", views.invoice_undo, name="invoice_undo"),
]