# deploy.py  (run it after every update: python deploy.py)
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

import django  # noqa: E402
from decouple import config  # noqa: E402

django.setup()
from django.core.management import call_command  # noqa: E402

if not os.path.exists(os.path.join(BASE, "assets", "css", "tailwind.css")):
    print("WARNING: assets/css/tailwind.css is missing, so the site will have no styling.")
    print("Run 'python manage.py tailwind build' on your computer, commit the file and pull again.")

print("Applying database changes...")
call_command("migrate", interactive=False)
print("Collecting static files...")
call_command("collectstatic", interactive=False, verbosity=0)

email, password = config("OWNER_EMAIL", default=""), config("OWNER_PASSWORD", default="")
if email and password:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if not User.objects.exists():
        User.objects.create_superuser(email=email, password=password)
        print(f"Created the owner account {email}. Now delete OWNER_EMAIL and OWNER_PASSWORD from .env.")

print("Done. Restart the app in cPanel.")