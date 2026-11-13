from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Unpack, cast

import pytest

from asmbly_ceramics.domain import errors
from asmbly_ceramics.domain.dropoff import (
    DropOff,
    DropOffState,
    new_drop_off,
    reject,
    undo_rejection,
)
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import MESSAGE_MAX, NAME_MAX, STUDIO_TZ
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import CatalogItem, CatalogList, ItemStatus, Studio, retire_item
from tests.domain.builders import (
    NOW,
    STAFF,
    TEST_EMAIL,
    TEST_MESSAGE,
    TEST_NAME,
    TEST_PHONE,
    TEST_PHONE_DIGITS,
    DetailsArgs,
    a_drop_off,
    a_studio,
    an_address,
    details,
    photo_refs,
)

AC1 = DropOffId(1)
OTHER = ItemId("other")
DRYING = ItemId("needs-more-time-to-dry")


def retired(which: CatalogList, id: str) -> Studio:
    studio, _ = retire_item(a_studio(), which, ItemId(id), STAFF, NOW)
    return studio


def a_reason(id: ItemId = DRYING) -> CatalogItem:
    return a_studio().item(CatalogList.REASONS, id)


def refusal(**overrides: Unpack[DetailsArgs]) -> errors.InvalidDetails:
    with pytest.raises(errors.InvalidDetails) as caught:
        details(**overrides)
    return caught.value


def assert_no_personal_detail(text: str) -> None:
    for detail in (
        TEST_NAME,
        "Test",
        "Person",
        TEST_EMAIL,
        "test.person",
        TEST_PHONE,
        TEST_PHONE_DIGITS,
        "0100",
    ):
        assert detail not in text
    assert TEST_MESSAGE not in text
    assert "unglazed" not in text
    assert "@" not in text


# The details the form sends (#2)


def test_details_accept_a_valid_bisque_and_a_valid_glaze_drop_off() -> None:
    bisque = details()
    assert (bisque.pieces, bisque.firing_type, bisque.glaze_type) == (3, "bisque", None)
    assert (bisque.contact.name, bisque.contact.email, bisque.contact.phone) == (
        TEST_NAME,
        TEST_EMAIL,
        TEST_PHONE_DIGITS,
    )
    glaze = details(firing_type="glaze", glaze_type="house-dip-glaze", pieces=" 50 ", photo_count=6)
    assert (glaze.pieces, glaze.firing_type, glaze.glaze_type) == (50, "glaze", "house-dip-glaze")


def test_fields_are_stripped_and_an_empty_glaze_is_none_for_bisque() -> None:
    checked = details(name="  " + TEST_NAME + " ", email=" " + TEST_EMAIL + " ", glaze_type="", pieces="1")
    assert (checked.contact.name, checked.contact.email, checked.glaze_type, checked.pieces) == (
        TEST_NAME,
        TEST_EMAIL,
        None,
        1,
    )


def test_item_ids_are_stripped_and_a_blank_glaze_type_is_none() -> None:
    assert details(firing_type=" bisque ", glaze_type="  ").glaze_type is None
    glaze = details(firing_type="glaze\n", glaze_type=" commercial-glaze ")
    assert (glaze.firing_type, glaze.glaze_type) == ("glaze", "commercial-glaze")
    assert refusal(firing_type="  ").errors == {"firing_type": "firing_type.required"}
    assert refusal(firing_type="glaze", glaze_type=" ").errors == {"glaze_type": "glaze_type.required"}


def test_a_phone_is_kept_as_its_digits() -> None:
    assert details(phone="+1 " + "512.555." + "0100").contact.phone == "1" + TEST_PHONE_DIGITS
    assert details(phone="5125550" + "100").contact.phone == TEST_PHONE_DIGITS


def test_control_characters_are_removed_from_the_name() -> None:
    assert details(name="Test\r\nPer​son\x00").contact.name == "TestPerson"
    assert details(name="\tTest Person\x7f").contact.name == TEST_NAME


def test_line_and_paragraph_separators_are_removed_from_the_name() -> None:
    assert details(name="Test\u2028 Person\u2029").contact.name == TEST_NAME


def test_the_longest_name_is_accepted() -> None:
    assert details(name="n" * NAME_MAX).contact.name == "n" * NAME_MAX


REFUSALS: list[tuple[str, DetailsArgs, str, str]] = [
    ("empty name", {"name": "  "}, "name", "name.required"),
    ("name of control characters", {"name": "\r\n\x00​"}, "name", "name.required"),
    ("long name", {"name": "n" * (NAME_MAX + 1)}, "name", "name.too_long"),
    ("missing email", {"email": " "}, "email", "email.required"),
    ("email without @", {"email": "test.person.example.org"}, "email", "email.invalid"),
    ("email with two @", {"email": an_address("test@person")}, "email", "email.invalid"),
    ("email with a space", {"email": an_address("test person")}, "email", "email.invalid"),
    ("email with a CR", {"email": an_address("test\rperson")}, "email", "email.invalid"),
    ("email with an LF", {"email": an_address("test\nperson")}, "email", "email.invalid"),
    ("missing phone", {"phone": ""}, "phone", "phone.required"),
    ("phone with letters", {"phone": "512 555 CALL"}, "phone", "phone.invalid"),
    ("phone of 9 digits", {"phone": "512 555 " + "010"}, "phone", "phone.invalid"),
    ("phone of 16 digits", {"phone": "1" * 16}, "phone", "phone.invalid"),
    ("phone with Arabic digits", {"phone": "٥١٢٥٥٥٠١٠٠"}, "phone", "phone.invalid"),
    ("pieces 0", {"pieces": "0"}, "pieces", "pieces.invalid"),
    ("pieces 51", {"pieces": "51"}, "pieces", "pieces.invalid"),
    ("pieces 2.5", {"pieces": "2.5"}, "pieces", "pieces.invalid"),
    ("pieces two", {"pieces": "two"}, "pieces", "pieces.invalid"),
    ("pieces in another script", {"pieces": "٣"}, "pieces", "pieces.invalid"),
    ("pieces superscript", {"pieces": "³"}, "pieces", "pieces.invalid"),
    ("pieces of many digits", {"pieces": "9" * 5000}, "pieces", "pieces.invalid"),
    ("missing firing type", {"firing_type": ""}, "firing_type", "firing_type.required"),
    ("unknown firing type", {"firing_type": "raku"}, "firing_type", "firing_type.unknown"),
    ("glaze missing for Glaze", {"firing_type": "glaze"}, "glaze_type", "glaze_type.required"),
    ("glaze given for Bisque", {"glaze_type": "house-dip-glaze"}, "glaze_type", "glaze_type.not_allowed"),
    (
        "unknown glaze type",
        {"firing_type": "glaze", "glaze_type": "celadon"},
        "glaze_type",
        "glaze_type.unknown",
    ),
    ("0 photos", {"photo_count": 0}, "photos", "photos.count"),
    ("7 photos", {"photo_count": 7}, "photos", "photos.count"),
    ("photo count True", {"photo_count": True}, "photos", "photos.count"),
    ("photo count 2.0", {"photo_count": cast(int, 2.0)}, "photos", "photos.count"),
]


@pytest.mark.parametrize(
    ("overrides", "field", "key"), [r[1:] for r in REFUSALS], ids=[r[0] for r in REFUSALS]
)
def test_each_field_refusal_has_its_key(overrides: DetailsArgs, field: str, key: str) -> None:
    assert refusal(**overrides).errors == {field: key}


def test_a_retired_firing_type_is_refused() -> None:
    studio = retired(CatalogList.FIRING_TYPES, "bisque")
    assert refusal(studio=studio).errors == {"firing_type": "firing_type.unknown"}


def test_a_retired_glaze_type_is_refused() -> None:
    studio = retired(CatalogList.GLAZE_TYPES, "house-dip-glaze")
    assert refusal(studio=studio, firing_type="glaze", glaze_type="house-dip-glaze").errors == {
        "glaze_type": "glaze_type.unknown"
    }


def test_with_a_refused_firing_type_only_a_given_glaze_type_is_checked() -> None:
    assert refusal(firing_type="raku").errors == {"firing_type": "firing_type.unknown"}
    assert refusal(firing_type="raku", glaze_type="house-dip-glaze").errors == {
        "firing_type": "firing_type.unknown"
    }
    assert refusal(firing_type="raku", glaze_type="celadon").errors == {
        "firing_type": "firing_type.unknown",
        "glaze_type": "glaze_type.unknown",
    }


def test_several_bad_fields_are_reported_together() -> None:
    caught = refusal(name="", email="nobody", phone="12", pieces="0", firing_type="glaze", photo_count=9)
    assert caught.errors == {
        "name": "name.required",
        "email": "email.invalid",
        "phone": "phone.invalid",
        "pieces": "pieces.invalid",
        "glaze_type": "glaze_type.required",
        "photos": "photos.count",
    }


@pytest.mark.parametrize("overrides", [r[1] for r in REFUSALS], ids=[r[0] for r in REFUSALS])
def test_a_refusal_message_holds_no_personal_detail(overrides: DetailsArgs) -> None:
    # Every other field holds the made-up person's details, which must not come back.
    caught = refusal(**overrides)
    for text in (caught.message, str(caught), repr(caught), repr(caught.args), repr(dict(caught.errors))):
        assert_no_personal_detail(text)


def test_a_drop_off_repr_holds_no_personal_detail() -> None:
    rejected = a_drop_off(state=DropOffState.REJECTED)
    assert rejected.contact is not None
    assert rejected.rejection is not None
    assert rejected.rejection.message == TEST_MESSAGE
    for value in (rejected, rejected.contact, rejected.rejection, details()):
        assert_no_personal_detail(repr(value))
        assert_no_personal_detail(str(value))
    assert "AC-1" not in repr(rejected)  # the dataclass repr shows DropOffId(number=1)
    assert "DropOffId(number=1)" in repr(rejected)


# A new drop-off


def test_a_new_drop_off_is_waiting_at_version_0() -> None:
    checked = details(firing_type="glaze", glaze_type="commercial-glaze")
    drop_off = new_drop_off(AC1, checked, photo_refs(AC1, 3), NOW)
    assert drop_off == DropOff(
        id=AC1,
        contact=checked.contact,
        pieces=3,
        firing_type=ItemId("glaze"),
        glaze_type=ItemId("commercial-glaze"),
        photos=(PhotoRef(AC1, 1), PhotoRef(AC1, 2), PhotoRef(AC1, 3)),
        created_at=NOW,
        state=DropOffState.WAITING,
    )
    assert drop_off.version == 0


@pytest.mark.parametrize(
    "photos",
    [
        (),
        (*photo_refs(AC1, 6), PhotoRef(AC1, 6)),  # seven
        (PhotoRef(AC1, 2),),
        (PhotoRef(AC1, 1), PhotoRef(AC1, 1)),
        (PhotoRef(DropOffId(2), 1),),
    ],
)
def test_a_new_drop_off_needs_its_own_photos_indexed_from_1(photos: tuple[PhotoRef, ...]) -> None:
    with pytest.raises(ValueError, match="photos"):
        new_drop_off(AC1, details(), photos, NOW)


@pytest.mark.parametrize("index", [0, 7, True, cast(int, 2.0)])
def test_a_photo_index_is_from_1_to_6(index: int) -> None:
    with pytest.raises(ValueError, match="index"):
        PhotoRef(AC1, index)


def test_a_new_drop_off_needs_an_aware_time() -> None:
    with pytest.raises(ValueError, match="aware"):
        new_drop_off(AC1, details(), photo_refs(AC1), datetime(2026, 11, 13))  # noqa: DTZ001


# Rejection (#5)


def test_reject_a_waiting_drop_off() -> None:
    rejected = reject(a_drop_off(), a_reason(), "  " + TEST_MESSAGE + "\r\n", STAFF, NOW)
    assert rejected.state is DropOffState.REJECTED
    assert rejected.rejection is not None
    assert (rejected.rejection.reason, rejected.rejection.message, rejected.rejection.by) == (
        DRYING,
        TEST_MESSAGE,
        STAFF,
    )
    assert rejected.rejection.at == NOW


def test_reject_keeps_the_messages_lines_as_lf() -> None:
    rejected = reject(a_drop_off(), a_reason(), "First.\r\nSecond.\rThird.", STAFF, NOW)
    assert rejected.rejection is not None
    assert rejected.rejection.message == "First.\nSecond.\nThird."


def test_reject_removes_control_characters_but_keeps_lf_and_tab() -> None:
    typed = "\x00First.\x1b[2J\r\n\tSecond\x08.\x7f\x85"
    rejected = reject(a_drop_off(), a_reason(), typed, STAFF, NOW)
    assert rejected.rejection is not None
    assert rejected.rejection.message == "First.[2J\n\tSecond."


def test_reject_with_only_control_characters_has_no_message() -> None:
    rejected = reject(a_drop_off(), a_reason(), "\x00\x1b\x08", STAFF, NOW)
    assert rejected.rejection is not None
    assert rejected.rejection.message is None
    with pytest.raises(errors.MessageRequired) as caught:
        reject(a_drop_off(), a_reason(OTHER), "\x00\x1b", STAFF, NOW)
    assert "\x00" not in repr(caught.value)


@pytest.mark.parametrize("message", [None, "", "  \r\n "])
def test_reject_stores_an_empty_message_as_none(message: str | None) -> None:
    rejected = reject(a_drop_off(), a_reason(), message, STAFF, NOW)
    assert rejected.rejection is not None
    assert rejected.rejection.message is None


@pytest.mark.parametrize("message", [None, " "])
def test_reject_needs_a_message_for_other(message: str | None) -> None:
    with pytest.raises(errors.MessageRequired):
        reject(a_drop_off(), a_reason(OTHER), message, STAFF, NOW)
    assert reject(a_drop_off(), a_reason(OTHER), TEST_MESSAGE, STAFF, NOW).state is DropOffState.REJECTED


def test_reject_refuses_a_message_over_1000() -> None:
    assert MESSAGE_MAX == 1000
    accepted = reject(a_drop_off(), a_reason(), "m" * MESSAGE_MAX, STAFF, NOW)
    assert accepted.rejection is not None
    assert accepted.rejection.message == "m" * MESSAGE_MAX
    with pytest.raises(errors.MessageTooLong) as caught:
        reject(a_drop_off(), a_reason(), "m" * (MESSAGE_MAX + 1), STAFF, NOW)
    assert "mmmm" not in repr(caught.value)


@pytest.mark.parametrize(
    ("state", "said"),
    [
        (DropOffState.IN_LOAD, "in load"),
        (DropOffState.FIRED, "fired"),
        (DropOffState.REJECTED, "rejected"),
        (DropOffState.CLOSED, "closed"),
    ],
)
def test_reject_only_from_waiting(state: DropOffState, said: str) -> None:
    with pytest.raises(errors.NotWaiting) as caught:
        reject(a_drop_off(12, state), a_reason(), TEST_MESSAGE, STAFF, NOW)
    assert caught.value.message == f"AC-12 isn't waiting: it is {said}."
    assert_no_personal_detail(repr(caught.value))


def test_reject_refuses_a_retired_reason() -> None:
    reason = replace(a_reason(), status=ItemStatus.RETIRED)
    with pytest.raises(errors.ItemRetired, match="Needs more time to dry is retired"):
        reject(a_drop_off(), reason, None, STAFF, NOW)


def test_reject_needs_a_username_and_an_aware_time() -> None:
    with pytest.raises(ValueError, match="username"):
        reject(a_drop_off(), a_reason(), None, "", NOW)
    with pytest.raises(ValueError, match="aware"):
        reject(a_drop_off(), a_reason(), None, STAFF, datetime(2026, 11, 13))  # noqa: DTZ001


# Undo the same Austin day (#5)


def austin(hour: int, minute: int, day: int = 13) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=STUDIO_TZ)


def test_undo_on_the_same_austin_day() -> None:
    rejected = reject(a_drop_off(), a_reason(), None, STAFF, austin(0, 5))
    undone = undo_rejection(rejected, austin(23, 55))
    assert undone.state is DropOffState.WAITING
    assert undone.rejection is None
    assert undone == a_drop_off()


def test_undo_refused_the_next_austin_day() -> None:
    at = austin(23, 30)
    later = austin(0, 10, day=14)
    # Both fall on the same UTC day, 14 November: the studio's day is what counts.
    assert at.astimezone(UTC).date() == later.astimezone(UTC).date()
    rejected = reject(a_drop_off(12), a_reason(), None, STAFF, at)
    with pytest.raises(errors.UndoTooLate, match="AC-12 was rejected on an earlier day"):
        undo_rejection(rejected, later)


def test_undo_counts_austin_days_even_when_utc_changes_date() -> None:
    # 17:30 and 19:30 in Austin fall on either side of UTC midnight in November.
    rejected = reject(a_drop_off(), a_reason(), None, STAFF, austin(17, 30))
    assert undo_rejection(rejected, austin(19, 30)).state is DropOffState.WAITING
    assert austin(17, 30).astimezone(UTC).date() != austin(19, 30).astimezone(UTC).date()


@pytest.mark.parametrize(
    "state", [DropOffState.WAITING, DropOffState.IN_LOAD, DropOffState.FIRED, DropOffState.CLOSED]
)
def test_undo_only_from_rejected(state: DropOffState) -> None:
    with pytest.raises(errors.NotRejected, match="AC-12 isn't rejected"):
        undo_rejection(a_drop_off(12, state), NOW)


def test_undo_needs_an_aware_time() -> None:
    with pytest.raises(ValueError, match="aware"):
        undo_rejection(a_drop_off(state=DropOffState.REJECTED), NOW.replace(tzinfo=None))


def test_a_rejection_after_an_undo_is_a_new_rejection() -> None:
    first = reject(a_drop_off(), a_reason(), None, STAFF, NOW)
    again = reject(
        undo_rejection(first, NOW + timedelta(minutes=1)), a_reason(), None, STAFF, NOW + timedelta(2)
    )
    assert again.rejection is not None
    assert again.rejection.at == NOW + timedelta(2)
