# apps/reports/admin.py
from django.contrib import admin
from .models import BrandProfile, ReportRun, ShareLink

admin.site.register([BrandProfile, ReportRun, ShareLink])