"""A drop-off's photos, as the domain sees them.

The bytes are checked and re-encoded by the `PhotoInspector` port and stored by the
`PhotoStore` port (phase 1d); this module only names what passes between them. Nothing
here prints a photo's contents or an upload's signed fields in its `repr`, so neither
reaches a log by accident.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTOS_MAX, PHOTOS_MIN


class PhotoSize(StrEnum):
    FULL = "full"
    THUMB = "thumb"


@dataclass(frozen=True, slots=True, order=True)
class PhotoRef:
    """A kept photo; the adapter maps it to `dropoffs/AC-n/<index>[-thumb].jpg`."""

    drop_off_id: DropOffId
    index: int

    def __post_init__(self) -> None:
        index = self.index
        if isinstance(index, bool) or not isinstance(index, int) or not PHOTOS_MIN <= index <= PHOTOS_MAX:
            raise ValueError(f"a photo's index is from {PHOTOS_MIN} to {PHOTOS_MAX}")


@dataclass(frozen=True, slots=True)
class PresignedPost:
    """What the browser posts a photo to; opaque to the domain."""

    url: str = field(repr=False)
    fields: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class UploadSlot:
    # Random, URL-safe, 22+ characters; the only handle the form sends back, so a bearer
    # handle that stays out of a repr.
    slot_id: str = field(repr=False)
    post: PresignedPost
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CheckedPhoto:
    """What the inspector returns: re-encoded JPEGs without EXIF."""

    full: bytes = field(repr=False)
    thumb: bytes = field(repr=False)


class PhotoRefusal(StrEnum):
    """Why the inspector refused a photo; `photo.<value>` is its message key."""

    NOT_IMAGE = "not_image"
    TOO_LARGE = "too_large"
    TOO_MANY_PIXELS = "too_many_pixels"
    MISSING = "missing"
