from datetime import timedelta
from typing import cast

import pytest

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import CheckedPhoto, PhotoRef, PhotoRefusal, PresignedPost, UploadSlot
from tests.domain.builders import NOW

AC1 = DropOffId(1)
# Made-up values that stand for what must never reach a log.
PHOTO_BYTES = b"\xff\xd8\xff\xe0SECRET-PIXELS"
THUMB_BYTES = b"\xff\xd8\xff\xe0SECRET-THUMB"
POST_URL = "https://uploads.example.org/signed-target"
SIGNATURE = "SIGNED-POLICY-VALUE"
SLOT_ID = "slot-handle-abcdefghijklmnop"


def a_post() -> PresignedPost:
    return PresignedPost(url=POST_URL, fields={"key": "uploads/abc", "policy": SIGNATURE})


def shown(value: object) -> str:
    return repr(value) + str(value)


def test_a_checked_photos_repr_holds_none_of_its_bytes() -> None:
    text = shown(CheckedPhoto(full=PHOTO_BYTES, thumb=THUMB_BYTES))
    for secret in ("SECRET", "PIXELS", "THUMB", r"\xff"):
        assert secret not in text


def test_a_presigned_posts_repr_holds_neither_its_url_nor_its_fields() -> None:
    text = shown(a_post())
    for secret in (POST_URL, "example.org", SIGNATURE, "policy", "uploads/abc"):
        assert secret not in text


def test_an_upload_slots_repr_holds_neither_its_handle_nor_its_post() -> None:
    slot = UploadSlot(slot_id=SLOT_ID, post=a_post(), expires_at=NOW + timedelta(minutes=15))
    text = shown(slot)
    for secret in (SLOT_ID, "abcdefghijklmnop", POST_URL, SIGNATURE, "policy"):
        assert secret not in text


def test_a_refusals_message_key_is_its_value() -> None:
    assert {f"photo.{refusal}" for refusal in PhotoRefusal} == {
        "photo.not_image",
        "photo.too_large",
        "photo.too_many_pixels",
        "photo.missing",
    }


@pytest.mark.parametrize("index", [1, 6])
def test_a_photo_index_from_1_to_6_is_kept(index: int) -> None:
    assert PhotoRef(AC1, index).index == index


@pytest.mark.parametrize("index", [0, 7, -1, True, False, cast(int, 1.0), cast(int, "1")])
def test_a_photo_index_outside_1_to_6_or_not_a_whole_number_is_refused(index: int) -> None:
    with pytest.raises(ValueError, match="index"):
        PhotoRef(AC1, index)


def test_photo_refs_order_by_drop_off_then_index() -> None:
    refs = [PhotoRef(DropOffId(2), 1), PhotoRef(AC1, 2), PhotoRef(AC1, 1)]
    assert sorted(refs) == [PhotoRef(AC1, 1), PhotoRef(AC1, 2), PhotoRef(DropOffId(2), 1)]
