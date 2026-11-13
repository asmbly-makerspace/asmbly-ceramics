from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRefusal
from asmbly_ceramics.ports.images import PhotoRefused

_MARKERS = {
    b"NOT-IMAGE": PhotoRefusal.NOT_IMAGE,
    b"TOO-LARGE": PhotoRefusal.TOO_LARGE,
    b"TOO-MANY-PIXELS": PhotoRefusal.TOO_MANY_PIXELS,
}


class MemoryPhotoInspector:
    def inspect(self, data: bytes) -> CheckedPhoto:
        for marker, kind in _MARKERS.items():
            if data.startswith(marker):
                raise PhotoRefused(kind)
        return CheckedPhoto(full=data, thumb=data[:16])
