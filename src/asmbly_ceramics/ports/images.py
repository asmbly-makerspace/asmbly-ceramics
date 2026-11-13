from typing import Protocol

from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRefusal


class PhotoRefused(Exception):
    def __init__(self, kind: PhotoRefusal) -> None:
        super().__init__(kind.value)
        self.kind = kind


class PhotoInspector(Protocol):
    def inspect(self, data: bytes) -> CheckedPhoto:
        """Raises PhotoRefused."""
        ...
