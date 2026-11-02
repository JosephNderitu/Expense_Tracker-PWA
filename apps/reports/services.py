# apps/reports/services.py
from django.core.files.base import ContentFile

from .builders import BUILDERS
from .models import BrandProfile, ReportRun
from .render import render_pdf


def get_brand(user):
    brand, _ = BrandProfile.objects.get_or_create(owner=user)
    return brand


def logo_bytes(brand):
    if not brand.logo:
        return None
    try:
        with brand.logo.open("rb") as handle:
            return handle.read()
    except (FileNotFoundError, ValueError):
        return None


def create_report(user, params):
    report = BUILDERS[params.kind](user, params)
    brand = get_brand(user)
    pdf = render_pdf(report, brand, logo_bytes(brand))
    run = ReportRun(owner=user, kind=params.kind, title=report.title, scope=params.scope,
                    date_from=params.date_from, date_to=params.date_to, detail=params.detail, size=len(pdf))
    run.file.save("report.pdf", ContentFile(pdf), save=False)
    run.save()
    return run