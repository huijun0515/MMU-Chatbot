"""Validate, resize and store event poster images (Pillow)."""

import io
import os
import uuid

from PIL import Image, ImageOps

from core import config
from core.logging_setup import logger

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PosterError(ValueError):
    """Raised with a message that is safe to show to the admin."""


def save_poster(data, directory=None, name=None, max_width=None):
    """Validate image bytes, downscale to max_width (default POSTER_MAX_WIDTH), store as JPEG.
    Returns the stored file name."""
    if len(data) > config.POSTER_MAX_BYTES:
        raise PosterError(f"Image is larger than {config.POSTER_MAX_BYTES // (1024 * 1024)} MB.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.verify()
        img = Image.open(io.BytesIO(data))  # verify() invalidates the handle
    except Exception as exc:
        raise PosterError("That file is not a readable image.") from exc
    if fmt not in ALLOWED_FORMATS:
        raise PosterError("Only PNG, JPEG or WEBP images are allowed.")

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")
    width = max_width or config.POSTER_MAX_WIDTH
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)

    directory = directory or config.ANNOUNCE_DIR
    os.makedirs(directory, exist_ok=True)
    name = name or f"poster_{uuid.uuid4().hex[:10]}.jpg"
    img.save(os.path.join(directory, name), "JPEG", quality=85, optimize=True)
    return name


def poster_path(name):
    """Absolute-ish path of a stored poster, or None if missing."""
    if not name:
        return None
    path = os.path.join(config.ANNOUNCE_DIR, os.path.basename(name))
    return path if os.path.isfile(path) else None


def delete_poster(name):
    path = poster_path(name)
    if path:
        try:
            os.remove(path)
        except OSError:
            logger.exception("Could not delete poster %s", path)
