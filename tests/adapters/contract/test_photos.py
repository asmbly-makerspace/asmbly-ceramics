"""`PhotoStore`'s contract, on the fake and the S3 adapter on moto. The browser's upload
is the fake's `put_upload` and, for S3, a `PutObject` to the slot's key."""

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from asmbly_ceramics.adapters.aws.photos import S3PhotoStore, upload_key
from asmbly_ceramics.adapters.memory.photos import MemoryPhotoStore
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import PHOTO_MAX_BYTES, UPLOAD_SLOT_LIFETIME
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoSize
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, PhotoStore, UploadMissing
from tests.adapters.conftest import BUCKET
from tests.domain.builders import NOW

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
else:
    S3Client = Any

Upload = Callable[[str, bytes], None]
AC12 = DropOffId(12)


@pytest.fixture(params=["memory", "s3"])
def store(request: pytest.FixtureRequest) -> Iterator[tuple[PhotoStore, Upload]]:
    if request.param == "memory":
        memory = MemoryPhotoStore()
        yield memory, memory.put_upload
    else:
        client: S3Client = request.getfixturevalue("s3")

        def upload(slot_id: str, data: bytes) -> None:
            client.put_object(Bucket=BUCKET, Key=upload_key(slot_id), Body=data)

        yield S3PhotoStore(client, BUCKET), upload


def photo(n: int) -> CheckedPhoto:
    return CheckedPhoto(full=b"FULL-%d" % n, thumb=b"THUMB-%d" % n)


def test_photo_store_keep_then_read_then_delete(store: tuple[PhotoStore, Upload]) -> None:
    photos, _ = store
    refs = photos.keep(AC12, [photo(1), photo(2)])
    assert refs == (PhotoRef(AC12, 1), PhotoRef(AC12, 2))
    assert photos.read(refs[1], PhotoSize.FULL) == b"FULL-2"
    assert photos.read(refs[0], PhotoSize.THUMB) == b"THUMB-1"
    with pytest.raises(PhotosAlreadyKept):
        photos.keep(AC12, [photo(9)])
    assert photos.read(refs[0], PhotoSize.FULL) == b"FULL-1"  # never overwritten
    photos.delete_drop_off(AC12)
    photos.delete_drop_off(AC12)  # idempotent
    with pytest.raises(UploadMissing):
        photos.read(refs[0], PhotoSize.FULL)
    assert photos.keep(AC12, [photo(3)]) == (PhotoRef(AC12, 1),)


def test_keep_refuses_zero_or_seven_photos(store: tuple[PhotoStore, Upload]) -> None:
    photos, _ = store
    for count in (0, 7):
        with pytest.raises(ValueError, match="1 to 6"):
            photos.keep(AC12, [photo(n) for n in range(count)])


def test_upload_slots_then_read_then_discard(store: tuple[PhotoStore, Upload]) -> None:
    photos, upload = store
    slots = photos.upload_slots(2, NOW)
    assert [slot.expires_at for slot in slots] == [NOW + UPLOAD_SLOT_LIFETIME] * 2
    first, second = (slot.slot_id for slot in slots)
    with pytest.raises(UploadMissing):
        photos.read_upload(first)  # nothing uploaded yet
    upload(first, b"PIXELS")
    assert photos.read_upload(first) == b"PIXELS"
    photos.discard_uploads([first, second, "not-a-slot"])
    photos.discard_uploads([first])  # idempotent
    with pytest.raises(UploadMissing):
        photos.read_upload(first)
    upload(first, b"AGAIN")  # the POST stays valid until the slot expires
    with pytest.raises(UploadMissing):
        photos.read_upload(first)  # but the slot is used up


def test_read_upload_refuses_more_than_10_mb(store: tuple[PhotoStore, Upload]) -> None:
    photos, upload = store
    [slot] = photos.upload_slots(1, NOW)
    upload(slot.slot_id, b"x" * PHOTO_MAX_BYTES)
    assert len(photos.read_upload(slot.slot_id)) == PHOTO_MAX_BYTES
    upload(slot.slot_id, b"x" * (PHOTO_MAX_BYTES + 1))
    with pytest.raises(UploadMissing):
        photos.read_upload(slot.slot_id)


def test_read_upload_refuses_an_empty_upload(store: tuple[PhotoStore, Upload]) -> None:
    photos, upload = store
    [slot] = photos.upload_slots(1, NOW)
    upload(slot.slot_id, b"")
    with pytest.raises(UploadMissing):
        photos.read_upload(slot.slot_id)


@pytest.mark.parametrize("slot_id", ["", "../dropoffs/AC-1/1.jpg", "a" * 21, "a" * 23, "a/" * 11])
def test_a_slot_id_of_another_shape_is_missing(store: tuple[PhotoStore, Upload], slot_id: str) -> None:
    photos, _ = store
    with pytest.raises(UploadMissing):
        photos.read_upload(slot_id)


def test_upload_slots_refuses_zero_or_more_than_six_and_a_naive_time(
    store: tuple[PhotoStore, Upload],
) -> None:
    photos, _ = store
    for count in (0, 7):
        with pytest.raises(ValueError, match="6"):
            photos.upload_slots(count, NOW)
    with pytest.raises(ValueError, match="aware"):
        photos.upload_slots(1, NOW.replace(tzinfo=None))
