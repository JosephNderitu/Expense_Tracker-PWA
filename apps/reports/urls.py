# apps/reports/urls.py
from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.history, name="history"),
    path("new/", views.builder, name="builder"),
    path("create/", views.create, name="create"),
    path("export/", views.export, name="export"),
    path("branding/", views.branding, name="branding"),
    path("branding/logo/", views.logo_file, name="logo"),
    path("share/<str:token>/", views.shared, name="shared"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/file/", views.report_file, name="file"),
    path("<int:pk>/export/<str:fmt>/", views.run_export, name="run_export"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/share/", views.share_create, name="share_create"),
    path("links/<int:pk>/revoke/", views.share_revoke, name="share_revoke"),
]