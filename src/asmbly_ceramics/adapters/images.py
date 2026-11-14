"""`PhotoInspector` with Pillow: a photo's real type and size, re-encoded without EXIF.

What a browser says a file is counts for nothing; Pillow opens the bytes as JPEG, PNG or
WebP only. The pixels are copied to a new RGB image (transparency onto white) with an
empty `info` and saved as JPEG, so nothing from the source (EXIF with its location, XMP,
comments, colour profiles) reaches the writer. The size is checked against
`PHOTO_MAX_PIXELS` before anything is decoded; Pillow's own `MAX_IMAGE_PIXELS` (about
89.5 million) stays as a second guard. The source is freed before the copies are
encoded, and both are resized in place.
"""

import warnings
from io import BytesIO

from PIL import Image, ImageOps

from asmbly_ceramics.domain.limits import (
    PHOTO_FULL_LONG_SIDE,
    PHOTO_MAX_BYTES,
    PHOTO_MAX_PIXELS,
    PHOTO_THUMB_LONG_SIDE,
)
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRefusal
from asmbly_ceramics.ports.errors import error_code
from asmbly_ceramics.ports.images import PhotoRefused
from asmbly_ceramics.use_cases.log import log_event

FORMATS = ("JPEG", "PNG", "WEBP")
FULL_QUALITY = 85
THUMB_QUALITY = 80
# ISO base media files Pillow can't open here: HEIC/HEIF (a phone camera's default) and
# AVIF, by the brand after `ftyp` at offset 4.
_ISOBMFF_BRANDS = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"}
)
_GIF = (b"GIF87a", b"GIF89a")


def _unsupported_type(data: bytes) -> bool:
    return data.startswith(_GIF) or (data[4:8] == b"ftyp" and data[8:12] in _ISOBMFF_BRANDS)


class PillowPhotoInspector:
    def inspect(self, data: bytes) -> CheckedPhoto:
        if len(data) > PHOTO_MAX_BYTES:
            raise PhotoRefused(PhotoRefusal.TOO_LARGE)
        if _unsupported_type(data):
            raise PhotoRefused(PhotoRefusal.UNSUPPORTED_TYPE)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                clean = _decoded(data)
        except Image.DecompressionBombWarning, Image.DecompressionBombError:
            raise PhotoRefused(PhotoRefusal.TOO_MANY_PIXELS) from None
        except Exception as error:  # hostile bytes: any decoder error is "not an image"
            # A crafted file can make a plugin raise anything (struct.error, IndexError...),
            # and some messages quote the file's bytes: the class name only is logged.
            log_event("photo_refused", reason="decoder_error", error_code=error_code(type(error).__name__))
            raise PhotoRefused(PhotoRefusal.NOT_IMAGE) from None
        # The source image is gone by now: only `clean` is held, resized in place.
        clean.thumbnail((PHOTO_FULL_LONG_SIDE, PHOTO_FULL_LONG_SIDE), Image.Resampling.LANCZOS)
        full = _jpeg(clean, FULL_QUALITY)
        clean.thumbnail((PHOTO_THUMB_LONG_SIDE, PHOTO_THUMB_LONG_SIDE), Image.Resampling.LANCZOS)
        return CheckedPhoto(full=full, thumb=_jpeg(clean, THUMB_QUALITY))


def _decoded(data: bytes) -> Image.Image:
    """The photo upright as plain RGB; the decoded source is freed when this returns."""
    with Image.open(BytesIO(data), formats=FORMATS) as probe:
        probe.verify()
    # `verify` leaves the image unusable: open it again to decode it.
    with Image.open(BytesIO(data), formats=FORMATS) as image:
        width, height = image.size
        if width * height > PHOTO_MAX_PIXELS:  # before decoding a byte of it
            raise Image.DecompressionBombError("too many pixels")
        image.load()  # a truncated file fails here
        ImageOps.exif_transpose(image, in_place=True)
        return _plain_rgb(image)


def _plain_rgb(image: Image.Image) -> Image.Image:
    """The pixels alone as RGB, transparency on white, with an empty `info`, so the JPEG
    writer finds no EXIF, XMP, comment or colour profile to carry over."""
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        clean = Image.new("RGB", rgba.size, "white")
        clean.paste(rgba, mask=rgba.getchannel("A"))
        del rgba
    else:
        clean = image.convert("RGB")
    clean.info = {}
    return clean


def _jpeg(image: Image.Image, quality: int) -> bytes:
    out = BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()
