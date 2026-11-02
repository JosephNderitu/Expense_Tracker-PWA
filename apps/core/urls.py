# apps/core/urls.py
from django.urls import path
from . import views
from . import manage_views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("workspace/switch/", views.switch_workspace, name="switch_workspace"),
    path("transactions/new/", views.transaction_create, name="transaction_create"),
    
    path("transactions/<int:pk>/", views.transaction_detail, name="transaction_detail"),
    path("attachments/<int:pk>/", views.attachment_file, name="attachment_file"),
    path("attachments/<int:pk>/delete/", views.attachment_delete, name="attachment_delete"),

    # apps/core/urls.py  (add to urlpatterns)
    path("transactions/", views.TransactionListView.as_view(), name="transaction_list"),
    path("transactions/trash/", views.transaction_trash, name="transaction_trash"),
    path("transactions/<int:pk>/edit/", views.transaction_edit, name="transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete, name="transaction_delete"),
    path("transactions/<int:pk>/restore/", views.transaction_restore, name="transaction_restore"),


    path("settings/categories/", manage_views.category_list, name="category_list"),
    path("settings/categories/new/", manage_views.category_create, name="category_create"),
    path("settings/categories/<int:pk>/", manage_views.category_edit, name="category_edit"),
    path("settings/categories/<int:pk>/toggle/", manage_views.category_toggle, name="category_toggle"),
    path("settings/categories/<int:pk>/delete/", manage_views.category_delete, name="category_delete"),
]