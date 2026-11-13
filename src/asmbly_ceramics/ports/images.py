"""Checking a photo's real type and size and re-encoding it without EXIF (#2)."""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

from typing import Protocol

from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRefusal
from asmbly_ceramics.ports.errors import PortError


class PhotoRefused(PortError):
    def __init__(self, kind: PhotoRefusal) -> None:
        self.kind = kind
        super().__init__(f"photo refused: {kind}")


class PhotoInspector(Protocol):
    def inspect(self, data: bytes) -> CheckedPhoto:
        """`PhotoRefused`."""
        ...
