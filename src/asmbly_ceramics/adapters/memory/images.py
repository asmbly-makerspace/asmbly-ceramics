"""`PhotoInspector` in memory: refuses data that starts with a marker, passes the rest."""

from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRefusal
from asmbly_ceramics.ports.images import PhotoRefused

NOT_IMAGE = b"NOT-IMAGE"
TOO_LARGE = b"TOO-LARGE"
TOO_MANY_PIXELS = b"TOO-MANY-PIXELS"
_MARKERS = {
    NOT_IMAGE: PhotoRefusal.NOT_IMAGE,
    TOO_LARGE: PhotoRefusal.TOO_LARGE,
    TOO_MANY_PIXELS: PhotoRefusal.TOO_MANY_PIXELS,
}


class MemoryPhotoInspector:
    def inspect(self, data: bytes) -> CheckedPhoto:
        for marker, kind in _MARKERS.items():
            if data.startswith(marker):
                raise PhotoRefused(kind)
        return CheckedPhoto(full=data, thumb=data[:16])
