from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

GREEN, WHITE = (22, 101, 52), (255, 255, 255)


def draw(size, full_bleed, glyph):
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle((0, 0, big, big), fill=GREEN)
    else:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=GREEN)
    s, c = big * glyph, big / 2
    w, h = s * 0.62, s * 0.46
    x0, y0 = c - w / 2, c - h / 2
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=s * 0.08, fill=WHITE)
    d.rectangle((x0, y0 + h * 0.22, x0 + w, y0 + h * 0.22 + s * 0.03), fill=GREEN)
    d.rounded_rectangle((x0 + w * 0.6, c - s * 0.02, x0 + w + s * 0.03, c + s * 0.12), radius=s * 0.04, fill=GREEN, outline=WHITE, width=int(s * 0.02))
    d.ellipse((x0 + w * 0.7, c + s * 0.02, x0 + w * 0.7 + s * 0.05, c + s * 0.07), fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


class Command(BaseCommand):
    help = "Create the app icons in static/icons"

    def handle(self, *args, **opts):
        out = settings.BASE_DIR / "static" / "icons"
        out.mkdir(parents=True, exist_ok=True)
        draw(192, False, 0.9).save(out / "icon-192.png")
        draw(512, False, 0.9).save(out / "icon-512.png")
        draw(512, True, 0.62).save(out / "icon-maskable-512.png")     # extra padding keeps it inside the "safe zone"
        draw(180, True, 0.8).save(out / "apple-touch-icon.png")
        self.stdout.write(f"Icons written to {out}")