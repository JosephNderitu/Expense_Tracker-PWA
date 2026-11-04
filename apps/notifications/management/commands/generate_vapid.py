import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the key pair that identifies this server to phones for push notifications"

    def handle(self, *args, **opts):
        path = settings.VAPID_PRIVATE_KEY_PATH
        if path.exists():
            raise CommandError(f"{path} already exists. Delete it only if you want new keys, because every phone would then need to re-enable alerts.")
        key = ec.generate_private_key(ec.SECP256R1())
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        public = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        self.stdout.write(f"Private key saved to {path}\n\nAdd these lines to your .env file, then restart the server:\nVAPID_PUBLIC_KEY={public}\nVAPID_SUBJECT=mailto:you@example.com")