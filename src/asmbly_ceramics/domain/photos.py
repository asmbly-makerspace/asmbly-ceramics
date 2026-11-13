"""A drop-off's photos, as the domain sees them.

The bytes are checked and re-encoded by the `PhotoInspector` port and stored by the
`PhotoStore` port (phase 1d); this module only names what passes between them. Nothing
here prints a photo's contents or an upload's signed fields in its `repr`, so neither
reaches a log by accident.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTOS_MAX, PHOTOS_MIN

SLOT_ID_LENGTH = 22  # `secrets.token_urlsafe(16)`: 16 random bytes in unpadded base64url
_SLOT_ID = re.compile(rf"[A-Za-z0-9_-]{{{SLOT_ID_LENGTH}}}", flags=re.ASCII)


PHOTO_COUNT_KEY = "photos.count"  # the message key for a count outside 1 to 6, under "photos"


def is_photo_count(count: int) -> bool:
    """An `int` (not a `bool`) from `PHOTOS_MIN` to `PHOTOS_MAX`: how many photos a
    drop-off may have and how many upload slots one request may ask for. The one check
    both use, refused as `PHOTO_COUNT_KEY`."""
    return not isinstance(count, bool) and isinstance(count, int) and PHOTOS_MIN <= count <= PHOTOS_MAX


def is_slot_id(text: str) -> bool:
    """Exactly 22 of `[A-Za-z0-9_-]`: the one shape an upload slot's ID has, which the use
    case checks before any read and the photo stores check before any storage call, so a
    browser-sent value can never name another key."""
    return isinstance(text, str) and _SLOT_ID.fullmatch(text) is not None


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
    # `is_slot_id`'s shape (22 random URL-safe characters); the only handle the form sends
    # back, so a bearer handle that stays out of a repr.
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
