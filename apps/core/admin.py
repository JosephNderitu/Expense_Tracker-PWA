# apps/core/admin.py
from django.contrib import admin
from .models import Category, Transaction, Workspace

admin.site.register(Workspace)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "workspace", "is_active", "sort_order")
    list_filter = ("workspace", "kind")

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "amount", "currency", "direction", "workspace")
    list_filter = ("workspace", "direction", "currency")
    
    def get_queryset(self, request):
        return Transaction.all_objects.all()