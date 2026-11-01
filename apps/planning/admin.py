# apps/planning/admin.py
from django.contrib import admin
from .models import Bill, BillPayment, Budget

admin.site.register([Bill, BillPayment, Budget])