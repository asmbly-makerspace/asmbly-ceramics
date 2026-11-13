"""Where uploads land and drop-offs' photos are kept, privately (#2)."""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize, UploadSlot
from asmbly_ceramics.ports.errors import PortError


class UploadMissing(PortError):
    """No upload for that slot (never sent, expired, empty, too large, or discarded), or a
    kept photo is gone."""

    def __init__(self) -> None:
        super().__init__("no such upload or photo")


class PhotosAlreadyKept(PortError):
    """`keep` found photos already kept for this drop-off; nothing was overwritten."""

    def __init__(self, drop_off_id: DropOffId) -> None:
        self.drop_off_id = drop_off_id
        super().__init__(f"photos already kept for {drop_off_id}")


class PhotoStore(Protocol):
    """Every method raises `PhotosUnavailable(code)` when the store can't be reached."""

    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]:
        """`count` slots, each expiring `UPLOAD_SLOT_LIFETIME` after `now`. `count` is
        `PHOTOS_MIN` to `PHOTOS_MAX` (1 to 6) and `now` is aware, else `ValueError`.

        An upload is 1 byte to `PHOTO_MAX_BYTES`: an empty or larger one is refused by
        the store, so nothing is kept for the slot."""
        ...

    def read_upload(self, slot_id: str) -> bytes:
        """The slot's upload; never more than `PHOTO_MAX_BYTES`. `UploadMissing` when
        there is none, including after `discard_uploads` for that slot, and for a
        `slot_id` without `is_slot_id`'s shape (checked before any storage call)."""
        ...

    def discard_uploads(self, slot_ids: Sequence[str]) -> None:
        """Deletes these slots' uploads and uses the slots up: `read_upload` of any of
        them raises `UploadMissing` from then on, even if the browser posts to the slot
        again before it expires. Called once a drop-off made from them is committed, so
        raw uploads (EXIF included) don't wait for the bucket's lifecycle rule and a slot
        can't make a second drop-off. Idempotent; an unknown slot, or one without
        `is_slot_id`'s shape, is ignored without a storage call."""
        ...

    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]:
        """Stores each photo's full and thumbnail copies; returns refs indexed from 1.

        1 to 6 photos (`PHOTOS_MIN` to `PHOTOS_MAX`), else `ValueError`. Never
        overwrites: if photos are already kept for `drop_off_id`, raises
        `PhotosAlreadyKept` and stores nothing. Leaves the uploads alone
        (`discard_uploads` removes them).

        All or nothing: when it raises, for any reason, nothing is left under
        `drop_off_id` (the S3 adapter deletes the copies it wrote before raising). Once it
        has returned, the photos have no record until the caller's commit lands, so a
        caller whose commit then fails, in any way (`Conflict`, `RecordsUnavailable`, or
        anything else), calls `delete_drop_off(drop_off_id)` before it returns or raises:
        the close (#7) only deletes the photos of a drop-off that has a record. If that
        delete fails too, the photos are orphaned until the store's own backstop removes
        them (phase 4/7: the form's role needs `s3:DeleteObject` on `dropoffs/*`, and a
        sweep or lifecycle rule for `dropoffs/` keys with no record)."""
        ...

    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes:
        """`UploadMissing` when gone."""
        ...

    def delete_drop_off(self, drop_off_id: DropOffId) -> None:
        """Both sizes of every photo; idempotent. The close (#7) calls it, and so does the
        submit when its commit fails after `keep` (see `keep`)."""
        ...
