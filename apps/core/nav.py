# apps/core/nav.py
from django.urls import reverse


def crumbs(*items):
    """crumbs(("Jobs", url), ("Job 123", None)): the last item is the current page. Overview is always first."""
    trail = [{"label": "Overview", "url": reverse("core:dashboard")}]
    trail += [{"label": label, "url": url} for label, url in items]
    return trail