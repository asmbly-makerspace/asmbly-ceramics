"""The records table's key design and the item <-> entity conversions."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from asmbly_ceramics.adapters.aws import keys
from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, claim, mark_sent, new_email, rejection_occasion
from asmbly_ceramics.domain.firing import EMPTY_RECORD, NO_CONE, FiringRecord, Program, Speed
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.load import Load, LoadStatus
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


@pytest.mark.parametrize("kind", list(EmailKind))
def test_parse_email_key_takes_back_every_email_the_domain_makes(kind: EmailKind) -> None:
    occasion = rejection_occasion(NOW) if kind is EmailKind.REJECTED else ""
    email = new_email(DropOffId(12), kind, NOW, occasion)
    stored = keys.email_key(email.drop_off_id, email.kind, email.occasion)
    assert keys.parse_email_key(stored) == (email.drop_off_id, email.kind, email.occasion)


def test_parse_email_key_applies_the_domains_occasion_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = keys.email_key(DropOffId(12), EmailKind.RECEIVED)
    monkeypatch.setattr(keys, "is_email_occasion", lambda kind, occasion: False)
    with pytest.raises(ValueError, match=r"^not an email key$"):
        keys.parse_email_key(stored)


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


# A load's test flag, its firing stamps and its firing record (#42)

FULL_RECORD = FiringRecord(
    percent_full=85,
    firing_number=98,
    all_time_number=252,
    program=Program(preheat_hours=0, cone=ItemId("cone-6"), speed=Speed.MEDIUM, hold_minutes=7),
    firing_minutes=698,
    max_temp_f=2236,
    board_temp_f=156,
    cost_cents=819,
    cone_top=100,
    cone_center=0,
    cone_bottom=NO_CONE,
)


def stored(load: Load) -> dict[str, Any]:
    return keys.to_item(load, keys.item_key(load), load.version)


def test_load_round_trips_with_record_and_stamps() -> None:
    load = replace(a_load(4, LoadStatus.FIRED, members=(1,), test=True, record=FULL_RECORD), version=3)
    item = stored(load)
    assert keys.from_item(item) == load
    assert (item["test"], item["firing_started_by"], item["fired_by"]) == (
        {"BOOL": True},
        {"S": STAFF},
        {"S": STAFF},
    )
    assert item["firing_started_at"] == {"S": "2026-11-13T18:30:00.000000Z"}
    record = item["record"]["M"]
    assert (record["cost_cents"], record["cone_bottom"], record["cone_center"]) == (
        {"N": "819"},
        {"S": "none"},
        {"N": "0"},
    )
    assert record["program"]["M"]["speed"] == {"S": "medium"}
    partial = replace(load, record=FiringRecord(max_temp_f=2236, program=Program(hold_minutes=7)))
    assert keys.from_item(stored(partial)) == partial
    assert set(stored(partial)["record"]["M"]) == {"max_temp_f", "program"}


def test_empty_record_stores_no_record() -> None:
    item = stored(a_load(4, LoadStatus.LOADING))
    assert not {"record", "program_cone", "test", "firing_started_by", "firing_started_at", "fired_by"} & set(
        item
    )
    load = keys.from_item(item)
    assert isinstance(load, Load)
    assert load.record == EMPTY_RECORD
    no_program = replace(a_load(4), record=FiringRecord(percent_full=0))
    assert stored(no_program)["record"] == {"M": {"percent_full": {"N": "0"}}}


def test_old_load_item_reads_with_defaults() -> None:
    old = replace(a_load(4, LoadStatus.FIRED, members=(1,), before_42=True), version=2)
    item = stored(old)
    # As phase 1's code found it: none of the attributes #42 adds.
    for name in ("test", "firing_started_by", "firing_started_at", "fired_by", "record", "program_cone"):
        assert name not in item
    load = keys.from_item(item)
    assert isinstance(load, Load)
    assert load == old
    assert (load.test, load.firing_started_by, load.firing_started_at, load.fired_by, load.record) == (
        False,
        None,
        None,
        None,
        EMPTY_RECORD,
    )


@pytest.mark.parametrize(
    "record",
    [
        {"M": {"max_temp_f": {"S": "hot"}}},  # a number as text
        {"M": {"max_temp_f": {"BOOL": True}}},
        {"M": {"cone_top": {"S": "half"}}},
        {"M": {"program": {"M": {"speed": {"S": "warp"}}}}},
        {"M": {"program": {"M": {"cone": {"N": "6"}}}}},
        {"M": {"program": {"S": "fast"}}},
        {"S": "a record"},
    ],
)
def test_bad_record_map_names_only_the_load(record: dict[str, Any]) -> None:
    item = stored(a_load(4, LoadStatus.FIRED, members=(1,)))
    item["record"] = record
    with pytest.raises(ValueError, match=r"^load L-4's firing record doesn't parse$"):
        keys.from_item(item)


def test_unknown_record_keys_are_ignored() -> None:
    load = a_load(4, LoadStatus.FIRED, members=(1,), record=FULL_RECORD)
    item = stored(load)
    item["record"]["M"]["colour"] = {"S": "red"}
    item["record"]["M"]["program"]["M"]["flavour"] = {"N": "6"}
    assert keys.from_item(item) == load


def test_record_keys_name_every_field() -> None:
    assert {field.name for field in fields(FiringRecord)} == keys._RECORD_KEYS
    assert {field.name for field in fields(Program)} == keys._PROGRAM_KEYS


def test_program_cone_is_top_level() -> None:
    load = a_load(
        4, LoadStatus.FIRING, members=(1,), record=FiringRecord(program=Program(cone=ItemId("cone-6")))
    )
    assert stored(load)["program_cone"] == {"S": "cone-6"}
    assert "program_cone" not in stored(replace(load, record=FiringRecord(percent_full=50)))
