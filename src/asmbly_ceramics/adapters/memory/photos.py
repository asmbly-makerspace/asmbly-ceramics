"""`PhotoStore` in memory: uploads by slot, kept photos by drop-off, index and size."""

import secrets
from collections.abc import Sequence
from datetime import datetime

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, PHOTOS_MAX, PHOTOS_MIN, UPLOAD_SLOT_LIFETIME
from asmbly_ceramics.domain.photos import (
    CheckedPhoto,
    PhotoRef,
    PhotoSize,
    PresignedPost,
    UploadSlot,
    is_slot_id,
)
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, UploadMissing

UPLOAD_URL = "https://uploads.example.org/memory"


class MemoryPhotoStore:
    def __init__(self) -> None:
        self._slots: dict[str, datetime] = {}  # slot ID -> expires_at
        self._uploads: dict[str, bytes] = {}
        self._discarded: set[str] = set()  # slots used up by `discard_uploads`
        self.read_uploads: list[str] = []  # every slot `read_upload` was asked for, in order
        self._kept: dict[tuple[DropOffId, int, PhotoSize], bytes] = {}
        self.fail_with: Exception | None = None

    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]:
        if now.utcoffset() is None:
            raise ValueError("an upload slot's time is aware")
        if not PHOTOS_MIN <= count <= PHOTOS_MAX:
            raise ValueError(f"{PHOTOS_MIN} to {PHOTOS_MAX} upload slots at a time")
        self._fail()
        slots = []
        for _ in range(count):
            slot_id = secrets.token_urlsafe(16)  # 22 characters: `is_slot_id`'s shape
            expires_at = now + UPLOAD_SLOT_LIFETIME
            self._slots[slot_id] = expires_at
            post = PresignedPost(url=UPLOAD_URL, fields={"key": f"uploads/{slot_id}"})
            slots.append(UploadSlot(slot_id=slot_id, post=post, expires_at=expires_at))
        return slots

    def put_upload(self, slot_id: str, data: bytes) -> None:
        """What the browser's post does. Empty or over `PHOTO_MAX_BYTES` is refused, as
        S3's `content-length-range` condition (1 byte to 10 MB) refuses it, so nothing is
        kept for the slot. A discarded slot still takes the post, as S3 does until the
        slot expires, but `read_upload` never returns it."""
        if slot_id not in self._slots:
            raise ValueError("not a slot this store issued")
        if not 1 <= len(data) <= PHOTO_MAX_BYTES:
            self._uploads.pop(slot_id, None)
            return
        self._uploads[slot_id] = data

    def read_upload(self, slot_id: str) -> bytes:
        self._fail()
        self.read_uploads.append(slot_id)
        if not is_slot_id(slot_id) or slot_id in self._discarded or slot_id not in self._uploads:
            raise UploadMissing()
        return self._uploads[slot_id]

    def discard_uploads(self, slot_ids: Sequence[str]) -> None:
        if isinstance(slot_ids, str):
            raise TypeError("slot_ids is a sequence of slot IDs, not one string")
        self._fail()
        for slot_id in slot_ids:
            if not is_slot_id(slot_id):
                continue  # as the S3 adapter does: no storage call for another shape
            self._uploads.pop(slot_id, None)
            if slot_id in self._slots:
                self._discarded.add(slot_id)

    def upload_count(self) -> int:
        """How many uploads are held, for tests that raw uploads don't linger."""
        return sum(1 for slot_id in self._uploads if slot_id not in self._discarded)

    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]:
        if not PHOTOS_MIN <= len(photos) <= PHOTOS_MAX:
            raise ValueError(f"a drop-off keeps {PHOTOS_MIN} to {PHOTOS_MAX} photos")
        self._fail()
        if self.kept_count(drop_off_id):
            raise PhotosAlreadyKept(drop_off_id)
        # Nothing below can fail, so this is all or nothing, as the port requires.
        refs = []
        for index, photo in enumerate(photos, start=1):
            self._kept[drop_off_id, index, PhotoSize.FULL] = photo.full
            self._kept[drop_off_id, index, PhotoSize.THUMB] = photo.thumb
            refs.append(PhotoRef(drop_off_id, index))
        return tuple(refs)

    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes:
        self._fail()
        key = (ref.drop_off_id, ref.index, size)
        if key not in self._kept:
            raise UploadMissing()
        return self._kept[key]

    def delete_drop_off(self, drop_off_id: DropOffId) -> None:
        self._fail()
        for key in [key for key in self._kept if key[0] == drop_off_id]:
            del self._kept[key]

    def kept_count(self, drop_off_id: DropOffId) -> int:
        """How many stored copies (both sizes) a drop-off has, for tests of the close."""
        return sum(1 for key in self._kept if key[0] == drop_off_id)

    def _fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
