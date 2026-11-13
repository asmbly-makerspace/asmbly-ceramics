"""Photo values. Storing and decoding them is the `PhotoStore` and `PhotoInspector` ports' job."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from asmbly_ceramics.domain.ids import DropOffId


class PhotoSize(StrEnum):
    FULL = "full"
    THUMB = "thumb"


@dataclass(frozen=True, slots=True)
class PhotoRef:
    """A kept photo; the adapter maps it to dropoffs/AC-n/<index>[-thumb].jpg."""

    drop_off_id: DropOffId
    index: int  # 1..6


@dataclass(frozen=True, slots=True)
class PresignedPost:
    """What the browser posts to; opaque to the domain."""

    url: str
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class UploadSlot:
    slot_id: str  # random, URL-safe, 22+ characters; the only handle the form sends back
    post: PresignedPost
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CheckedPhoto:
    """What the inspector returns: re-encoded JPEGs without EXIF."""

    full: bytes
    thumb: bytes


class PhotoRefusal(StrEnum):
    NOT_IMAGE = "not_image"
    TOO_LARGE = "too_large"
    TOO_MANY_PIXELS = "too_many_pixels"
    MISSING = "missing"
