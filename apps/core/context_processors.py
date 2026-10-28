from .services import get_scope

SCOPE_OPTIONS = [
    ("all", "Overview", "fa-layer-group"),
    ("household", "Household", "fa-house"),
    ("work", "Work", "fa-truck"),
]


def workspace(request):
    return {"scope": get_scope(request), "scope_options": SCOPE_OPTIONS}