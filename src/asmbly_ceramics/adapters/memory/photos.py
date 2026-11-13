import secrets
from collections.abc import Sequence
from datetime import datetime

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, UPLOAD_SLOT_LIFETIME
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize, PresignedPost, UploadSlot
from asmbly_ceramics.ports.photos import UploadMissing


class MemoryPhotoStore:
    def __init__(self) -> None:
        self._uploads: dict[str, bytes] = {}
        self._kept: dict[PhotoRef, CheckedPhoto] = {}

    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]:
        return [
            UploadSlot(
                slot_id=(slot_id := secrets.token_urlsafe(16)),
                post=PresignedPost(url="https://uploads.example.org/", fields={"key": slot_id}),
                expires_at=now + UPLOAD_SLOT_LIFETIME,
            )
            for _ in range(count)
        ]

    def put_upload(self, slot_id: str, data: bytes) -> None:
        """Simulate the browser's upload to a slot."""
        self._uploads[slot_id] = data

    def read_upload(self, slot_id: str) -> bytes:
        data = self._uploads.get(slot_id)
        if data is None or len(data) > PHOTO_MAX_BYTES:
            raise UploadMissing
        return data

    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]:
        refs = tuple(PhotoRef(drop_off_id, i) for i in range(1, len(photos) + 1))
        self._kept.update(zip(refs, photos, strict=True))
        return refs

    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes:
        photo = self._kept.get(ref)
        if photo is None:
            raise UploadMissing
        return photo.full if size is PhotoSize.FULL else photo.thumb

    def delete_drop_off(self, drop_off_id: DropOffId) -> None:
        for ref in [r for r in self._kept if r.drop_off_id == drop_off_id]:
            del self._kept[ref]
