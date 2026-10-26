# apps/core/context_processors.py
def workspace(request):
    return {"active_workspace": request.session.get("active_workspace", "household")}