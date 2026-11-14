"""The records table's key design and the item <-> entity conversions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, claim, mark_sent, new_email, rejection_occasion
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.studio import SettingChange, starting_studio
from asmbly_ceramics.ports.records import Item, Submission
from tests.domain.builders import (
    NOW,
    STAFF,
    TEST_EMAIL,
    TEST_MESSAGE,
    TEST_NAME,
    TEST_PHONE_DIGITS,
    a_drop_off,
    a_load,
    a_sending_address,
)


def a_submission() -> Submission:
    return Submission(
        token_hash="made-up-token-hash",
        drop_off_id=DropOffId(7),
        pieces=2,
        firing_type="Glaze",
        glaze_type="House dip",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


def every_kind() -> list[Item]:
    studio, change = starting_studio(a_sending_address(), NOW)
    ready = mark_sent(claim(new_email(DropOffId(1), EmailKind.READY, NOW), NOW), NOW, pickup_window_days=14)
    return [
        *(replace(a_drop_off(n, state), version=3) for n, state in enumerate(DropOffState, start=1)),
        *(
            replace(a_load(n, status, members=(1, 2)), version=2)
            for n, status in enumerate(LoadStatus, start=1)
        ),
        replace(studio, version=5),
        change,
        replace(ready, version=4),
        new_email(DropOffId(2), EmailKind.REJECTED, NOW, rejection_occasion(NOW)),
        a_submission(),
    ]


@pytest.mark.parametrize("entity", every_kind(), ids=lambda e: type(e).__name__)
def test_keys_round_trip_every_item_kind(entity: Item) -> None:
    version = getattr(entity, "version", None)
    item = keys.to_item(entity, keys.item_key(entity), version)
    assert keys.from_item(item) == entity
    assert isinstance(item["type"]["S"], str)
    assert ("version" in item) == (version is not None)


def test_drop_off_item_puts_personal_details_in_their_own_attributes() -> None:
    rejected = a_drop_off(12, DropOffState.REJECTED)
    item = keys.to_item(rejected, keys.item_key(rejected), 1)
    assert item["contact_name"] == {"S": TEST_NAME}
    assert item["contact_email"] == {"S": TEST_EMAIL}
    assert item["contact_phone"] == {"S": TEST_PHONE_DIGITS}
    assert item["rejection_message"] == {"S": TEST_MESSAGE}
    keyed = {item[name]["S"] for name in ("PK", "SK", "GSI1PK", "GSI1SK")}
    for detail in (TEST_NAME, TEST_EMAIL, TEST_PHONE_DIGITS, TEST_MESSAGE):
        assert not [k for k in keyed if detail in k]  # never in a key
    assert (item["PK"], item["SK"], item["GSI1PK"]) == (
        {"S": "DROPOFF#AC-12"},
        {"S": "META"},
        {"S": "DROPOFF#rejected"},
    )
    assert item["GSI1SK"] == {"S": "2026-11-13T18:30:00.000000Z#AC-12"}


def test_email_item_status_is_a_top_level_string_for_the_stream_filter() -> None:
    email = new_email(DropOffId(12), EmailKind.RECEIVED, NOW)
    item = keys.to_item(email, keys.item_key(email), 1)
    # Phase 7's filter: {"dynamodb": {"NewImage": {"type": {"S": ["email"]}, "status": {"S": ["pending"]}}}}
    assert (item["type"], item["status"]) == ({"S": "email"}, {"S": "pending"})
    assert (item["PK"], item["SK"]) == ({"S": "EMAIL#AC-12"}, {"S": "received"})
    assert (item["GSI2PK"], item["GSI2SK"]) == (
        {"S": "EMAIL#pending"},
        {"S": "2026-11-13T18:30:00.000000Z#AC-12#received"},
    )
    rejected = new_email(DropOffId(12), EmailKind.REJECTED, NOW, rejection_occasion(NOW))
    assert keys.item_key(rejected)["SK"] == {"S": "rejected#2026-11-13T18:30:00.000000+00:00"}


def test_a_submission_expires_by_ttl_and_holds_no_contact() -> None:
    submission = a_submission()
    item = keys.to_item(submission, keys.item_key(submission), None)
    assert item["ttl"] == {"N": str(int((NOW + timedelta(days=1)).timestamp()))}
    assert item["PK"] == {"S": "SUBMISSION#made-up-token-hash"}
    assert not {"contact_name", "contact_email", "contact_phone"} & set(item)


def test_times_sort_as_strings_with_fixed_microseconds() -> None:
    whole = datetime(2026, 11, 13, 18, 30, tzinfo=UTC)
    later = whole + timedelta(microseconds=1)
    assert keys.iso(whole) == "2026-11-13T18:30:00.000000Z"
    assert keys.iso(whole) < keys.iso(later)
    austin = whole.astimezone(timezone(timedelta(hours=-6)))
    assert keys.iso(austin) == keys.iso(whole)  # any offset, one string
    assert keys.parse_iso(keys.iso(later)) == later
    with pytest.raises(ValueError, match="aware"):
        keys.iso(whole.replace(tzinfo=None))


def test_two_history_keys_at_one_instant_differ_and_are_cursors() -> None:
    change = SettingChange(NOW, STAFF, "Pickup window: 10 → 14 days")
    first, second = keys.item_key(change)["SK"]["S"], keys.item_key(change)["SK"]["S"]
    assert first != second
    assert first.startswith("HISTORY#2026-11-13T18:30:00.000000Z#")
    assert keys.is_history_cursor(first.removeprefix("HISTORY#"))
    assert not keys.is_history_cursor(first)


def test_an_item_of_no_entity_type_is_refused() -> None:
    with pytest.raises(ValueError, match="entity"):
        keys.from_item({"PK": {"S": "COUNTER#dropoff"}, "type": {"S": "counter"}})
    with pytest.raises(ValueError, match="whole numbers"):
        keys.from_item({"type": {"S": "studio"}, "version": {"N": "1.5"}})


def test_a_drop_off_holding_anothers_photos_is_refused() -> None:
    drop_off = a_drop_off(1)
    other: Any = replace(drop_off, photos=a_drop_off(2).photos)
    with pytest.raises(ValueError, match="own"):
        keys.to_item(other, keys.item_key(other), 1)


@pytest.mark.parametrize(
    ("kind", "occasion"),
    [(EmailKind.RECEIVED, ""), (EmailKind.READY, ""), (EmailKind.REJECTED, rejection_occasion(NOW))],
)
def test_parse_email_key_inverts_email_key(kind: EmailKind, occasion: str) -> None:
    stored = keys.email_key(DropOffId(12), kind, occasion)
    assert keys.parse_email_key(stored) == (DropOffId(12), kind, occasion)


@pytest.mark.parametrize(
    "stored",
    [
        keys.drop_off_key(DropOffId(12)),
        keys.studio_key(),
        keys.key("EMAIL#AC-012", "received"),
        keys.key("EMAIL#AC-12", "sent"),
        keys.key("EMAIL#AC-12", "received#" + rejection_occasion(NOW)),
        keys.key("EMAIL#AC-12", "rejected"),
        keys.key("EMAIL#AC-12", "rejected#yesterday"),
        keys.key("EMAIL#AC-12", "received#"),
        {"PK": {"S": "EMAIL#AC-12"}},
        {"PK": {"N": "12"}, "SK": {"S": "received"}},
        {},
    ],
)
def test_parse_email_key_refuses_any_other_key(stored: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"^not an? (email|records) key$"):
        keys.parse_email_key(stored)
