# apps/work/admin.py
from django.contrib import admin
from .models import FuelDetail, Job, MaintenanceDetail, Party, Truck

admin.site.register([Party, Truck, FuelDetail, MaintenanceDetail])

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("date", "reference", "broker", "gross_pay", "deleted_at")

    def get_queryset(self, request):
        return Job.all_objects.all()