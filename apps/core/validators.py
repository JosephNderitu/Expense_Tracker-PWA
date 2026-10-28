import io
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_PER_UPLOAD = 5
MAX_PER_ENTRY = 10
MAX_IMAGE_SIDE = 2400

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv", ".txt": "text/plain",
}
IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
ACCEPT = ",".join(CONTENT_TYPES)


def _matches_signature(ext, head):
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".heic":
        return head[4:8] == b"ftyp"
    if ext in (".docx", ".xlsx"):
        return head.startswith(b"PK\x03\x04")
    if ext in (".csv", ".txt"):
        return b"\x00" not in head
    return False


def _clean_image(upload, ext):
    fmt = IMAGE_FORMATS[ext]
    name = Path(upload.name).name
    try:
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError(f"{name}: this is not a readable image.")
    image = ImageOps.exif_transpose(image)       # apply the rotation, then drop all metadata on re-save
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    if fmt == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    options = {"JPEG": {"quality": 88, "optimize": True}, "PNG": {"optimize": True}, "WEBP": {"quality": 88}}[fmt]
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    size = buffer.tell()
    buffer.seek(0)
    return InMemoryUploadedFile(buffer, None, name, CONTENT_TYPES[ext], size, None)


def validate_and_clean_upload(upload):
    name = Path(upload.name).name
    ext = Path(name).suffix.lower()
    if ext not in CONTENT_TYPES:
        raise ValidationError(f"{name}: this file type is not allowed.")
    if upload.size > MAX_BYTES:
        raise ValidationError(f"{name}: larger than 10 MB.")
    upload.seek(0)
    head = upload.read(2048)
    upload.seek(0)
    if not _matches_signature(ext, head):
        raise ValidationError(f"{name}: the file contents do not match its type.")
    return _clean_image(upload, ext) if ext in IMAGE_FORMATS else upload


def clean_uploads(files):
    files = [f for f in (files or []) if f]
    if len(files) > MAX_PER_UPLOAD:
        raise ValidationError(f"Upload up to {MAX_PER_UPLOAD} files at a time.")
    cleaned, errors = [], []
    for upload in files:
        try:
            cleaned.append(validate_and_clean_upload(upload))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)
    return cleaned