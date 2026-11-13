from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize, UploadSlot


class UploadMissing(Exception):
    """No upload for that slot (never sent, expired, wrong size), or the photo is gone."""


class PhotoStore(Protocol):
    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]: ...
    def read_upload(self, slot_id: str) -> bytes:
        """Raises UploadMissing; never returns more than PHOTO_MAX_BYTES."""
        ...

    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]: ...
    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes: ...
    def delete_drop_off(self, drop_off_id: DropOffId) -> None:
        """Idempotent."""
        ...
