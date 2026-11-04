# apps/core/api.py  (shared helper: JSON endpoints answer 401 instead of redirecting to the login page)
from functools import wraps

from django.http import JsonResponse


def api_login_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "auth"}, status=401)
        return view(request, *args, **kwargs)
    return wrapped