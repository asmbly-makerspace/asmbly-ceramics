"""`Records`' contract, run against the in-memory fake and the DynamoDB adapter on moto,
so the fake the use cases are tested with can't drift from the adapter the app runs."""

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.domain.dropoff import DropOff, DropOffState
from asmbly_ceramics.domain.email import (
    EmailKind,
    EmailStatus,
    claim,
    holds_claim,
    mark_sent,
    new_email,
    rejection_occasion,
    retry,
)
from asmbly_ceramics.domain.firing import FiringRecord, Program
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import LOAD_CAPACITY, SUBMISSION_LIFETIME
from asmbly_ceramics.domain.load import Load, LoadStatus, fire
from asmbly_ceramics.domain.studio import (
    CatalogList,
    SettingChange,
    change_email_settings,
    starting_studio,
)
from asmbly_ceramics.ports.records import (
    BadCursor,
    Change,
    Conflict,
    HistoryPage,
    Put,
    Records,
    Submission,
    Update,
)
from tests.adapters.conftest import TABLE
from tests.domain.builders import NOW, STAFF, a_drop_off, a_load, a_sending_address, a_studio

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
else:
    DynamoDBClient = Any

DAY = timedelta(days=1)
TOKEN_HASH = "made-up-token-hash-value"


@pytest.fixture(params=["memory", "dynamodb"])
def records(request: pytest.FixtureRequest) -> Iterator[Records]:
    if request.param == "memory":
        yield MemoryRecords()
    else:
        client: DynamoDBClient = request.getfixturevalue("dynamodb")
        yield DynamoDbRecords(client, TABLE)


def a_submission(number: int = 1) -> Submission:
    return Submission(
        token_hash=TOKEN_HASH,
        drop_off_id=DropOffId(number),
        pieces=3,
        firing_type="Bisque",
        glaze_type=None,
        created_at=NOW,
        expires_at=NOW + SUBMISSION_LIFETIME,
    )


def ids(items: Sequence[DropOff | Load]) -> list[str]:
    return [str(item.id) for item in items]


def test_records_commit_new_item_then_conflict_on_second_put(records: Records) -> None:
    records.commit([Put(a_drop_off(1))])
    stored = records.drop_off(DropOffId(1))
    assert stored == replace(a_drop_off(1), version=1)
    with pytest.raises(Conflict) as refused:
        records.commit([Put(replace(a_drop_off(1), pieces=9)), Put(a_drop_off(2))])
    assert refused.value.ids == ("AC-1",)
    assert records.drop_off(DropOffId(1)) == stored  # nothing written, AC-2 included
    assert records.drop_off(DropOffId(2)) is None


def test_records_update_with_stale_version_raises_conflict_naming_the_id(records: Records) -> None:
    records.commit([Put(a_drop_off(1)), Put(a_load(4))])
    drop_off, load = records.drop_off(DropOffId(1)), records.load(LoadId(4))
    assert drop_off is not None
    assert load is not None
    records.commit([Update(replace(drop_off, pieces=5))])
    with pytest.raises(Conflict) as refused:
        records.commit([Update(replace(load, kiln=ItemId("helios"))), Update(replace(drop_off, pieces=6))])
    assert refused.value.ids == ("AC-1",)
    assert records.load(LoadId(4)) == load  # all or nothing
    stored = records.drop_off(DropOffId(1))
    assert stored is not None
    assert (stored.pieces, stored.version) == (5, 2)


def test_records_update_of_a_missing_item_conflicts(records: Records) -> None:
    with pytest.raises(Conflict) as refused:
        records.commit([Update(replace(a_load(7), version=1))])
    assert refused.value.ids == ("L-7",)


def test_records_empty_commit_is_a_no_op(records: Records) -> None:
    records.commit([])
    assert records.drop_offs_in(set(DropOffState)) == []


def test_records_refuse_two_changes_on_one_key_and_more_than_100(records: Records) -> None:
    with pytest.raises(ValueError, match="one key"):
        records.commit([Put(a_drop_off(1)), Put(a_drop_off(1))])
    with pytest.raises(ValueError, match="100"):
        records.commit([Put(a_drop_off(n)) for n in range(1, 102)])
    assert records.drop_off(DropOffId(1)) is None


def test_a_fire_of_48_drop_offs_fits_one_transaction(records: Records) -> None:
    members = range(1, LOAD_CAPACITY + 1)
    in_load = [a_drop_off(n, DropOffState.IN_LOAD) for n in members]
    load = a_load(1, LoadStatus.FIRING, members)
    for start in range(0, LOAD_CAPACITY, 24):
        records.commit([Put(d) for d in in_load[start : start + 24]])
    records.commit([Put(load)])
    stored_load = records.load(LoadId(1))
    assert stored_load is not None
    stored = [records.drop_off(DropOffId(n)) for n in members]
    result = fire(stored_load, [d for d in stored if d is not None], STAFF, NOW)
    changes: list[Change] = [
        Update(result.load),
        *(Update(d) for d in result.drop_offs),
        *(Put(e) for e in result.emails),
    ]
    assert len(changes) == 97
    records.commit(changes)
    assert len(records.drop_offs_in({DropOffState.FIRED})) == LOAD_CAPACITY
    assert len(records.emails_in({EmailStatus.PENDING})) == LOAD_CAPACITY


def test_records_waiting_list_is_oldest_first(records: Records) -> None:
    records.commit(
        [
            Put(a_drop_off(3, at=NOW)),
            Put(a_drop_off(10, at=NOW)),  # the same instant: by ID, 3 before 10
            Put(a_drop_off(1, at=NOW + DAY)),
            Put(a_drop_off(2, at=NOW - DAY)),
            Put(a_drop_off(4, DropOffState.REJECTED, at=NOW - DAY)),
        ]
    )
    assert ids(records.drop_offs_in({DropOffState.WAITING})) == ["AC-2", "AC-3", "AC-10", "AC-1"]


def test_records_lists_filter_and_sort(records: Records) -> None:
    records.commit(
        [
            Put(a_drop_off(3, at=NOW)),
            Put(a_drop_off(2, at=NOW)),
            Put(a_drop_off(1, at=NOW + DAY)),
            Put(a_drop_off(4, DropOffState.REJECTED, at=NOW - DAY)),
            Put(a_drop_off(5, DropOffState.FIRED, at=NOW + 2 * DAY)),
            Put(a_drop_off(6, DropOffState.CLOSED, at=NOW - DAY / 2)),
            Put(a_load(2, at=NOW)),
            Put(a_load(10, at=NOW)),
            Put(a_load(1, at=NOW)),
            Put(a_load(3, LoadStatus.FIRED, at=NOW + DAY)),
        ]
    )
    assert ids(records.drop_offs_created_between(NOW, NOW + DAY)) == ["AC-2", "AC-3"]  # NOW + DAY is out
    assert ids(records.drop_offs_created_between(NOW - DAY, NOW)) == ["AC-4", "AC-6"]
    assert ids(records.drop_offs_rejected_between(NOW - DAY, NOW)) == ["AC-4", "AC-6"]  # closed kept
    assert records.drop_offs_rejected_between(NOW, NOW + 3 * DAY) == []
    assert ids(records.loads_in({LoadStatus.LOADING})) == ["L-1", "L-2", "L-10"]
    assert ids(records.loads_in({LoadStatus.LOADING, LoadStatus.FIRED})) == ["L-1", "L-2", "L-10", "L-3"]
    with pytest.raises(ValueError, match="aware"):
        records.drop_offs_created_between(NOW.replace(tzinfo=None), NOW)


def test_records_emails_by_drop_off_and_by_status(records: Records) -> None:
    ac1, ac2 = DropOffId(1), DropOffId(2)
    sent = mark_sent(
        claim(new_email(ac1, EmailKind.READY, NOW + DAY), NOW + DAY), NOW + DAY, pickup_window_days=14
    )
    rejected_at = NOW - DAY
    occasion = rejection_occasion(rejected_at)
    records.commit(
        [
            Put(sent),
            Put(new_email(ac1, EmailKind.RECEIVED, NOW)),
            Put(new_email(ac2, EmailKind.RECEIVED, NOW - DAY)),
            Put(new_email(ac2, EmailKind.REJECTED, NOW, occasion)),
        ]
    )
    assert [e.kind for e in records.emails_for(ac1)] == [EmailKind.RECEIVED, EmailKind.READY]
    pending = records.emails_in({EmailStatus.PENDING})
    assert [(str(e.drop_off_id), e.kind) for e in pending] == [
        ("AC-2", EmailKind.RECEIVED),
        ("AC-1", EmailKind.RECEIVED),
        ("AC-2", EmailKind.REJECTED),
    ]
    stored = records.email(ac1, EmailKind.READY)
    assert stored is not None
    assert (stored.pickup_window_days, stored.sent_at, stored.version) == (14, NOW + DAY, 1)
    assert records.email(ac2, EmailKind.REJECTED, occasion) is not None
    assert records.email(ac2, EmailKind.REJECTED) is None
    assert records.email(ac2, EmailKind.RECEIVED, occasion) is None


def test_records_keep_a_retried_emails_time(records: Records) -> None:
    ac1 = DropOffId(1)
    records.commit([Put(new_email(ac1, EmailKind.RECEIVED, NOW))])
    queued = records.email(ac1, EmailKind.RECEIVED)
    assert queued is not None
    stuck = claim(queued, NOW)
    records.commit([Update(stuck)])
    stored = records.email(ac1, EmailKind.RECEIVED)
    assert stored is not None
    retried = retry(stored, NOW + DAY)
    records.commit([Update(retried)])
    again = records.email(ac1, EmailKind.RECEIVED)
    assert again is not None
    assert (again.status, again.retried_at, again.claimed_at, again.attempts) == (
        EmailStatus.PENDING,
        NOW + DAY,
        None,
        1,
    )


def test_a_claim_read_back_holds_its_sub_second_claimed_at(records: Records) -> None:
    ac1 = DropOffId(1)
    records.commit([Put(new_email(ac1, EmailKind.RECEIVED, NOW))])
    queued = records.email(ac1, EmailKind.RECEIVED)
    assert queued is not None
    claimed = claim(queued, NOW + timedelta(microseconds=7))
    records.commit([Update(claimed)])
    stored = records.email(ac1, EmailKind.RECEIVED)
    assert stored is not None
    assert stored.claimed_at == NOW + timedelta(microseconds=7)
    assert holds_claim(stored, claimed)
    assert not holds_claim(stored, replace(claimed, claimed_at=NOW))


def test_records_history_pages_newest_first(records: Records) -> None:
    changes = [SettingChange(NOW + timedelta(minutes=n), STAFF, f"change {n}") for n in range(5)]
    records.commit([Put(change) for change in changes])
    first = records.history(3)
    assert first.changes == (changes[4], changes[3], changes[2])
    assert first.older is not None
    assert records.history(10, before=first.older) == HistoryPage((changes[1], changes[0]), None)
    assert records.history(5).older is None  # exactly the last page: nothing older
    with pytest.raises(ValueError, match="limit"):
        records.history(0)


def test_history_pages_by_the_sort_key_and_keeps_one_instant_together(records: Records) -> None:
    _, saved = change_email_settings(
        a_studio(),
        sending_address=a_sending_address("kiln-room"),
        pickup_window_days="21",
        pickup_hours_text="Weekdays only.",
        received_emails_per_day="300",
        by=STAFF,
        at=NOW,
    )
    assert len(saved) == 3
    assert len({change.at for change in saved}) == 1
    earlier = SettingChange(NOW - timedelta(minutes=1), STAFF, "Added kiln Kiln Four")
    records.commit([Put(earlier)])
    records.commit([Put(change) for change in saved])
    seen: list[SettingChange] = []
    cursor: str | None = None
    for _ in range(10):
        page = records.history(2, before=cursor)
        seen.extend(page.changes)
        cursor = page.older
        if cursor is None:
            break
    assert len(seen) == 4
    assert set(seen[:3]) == set(saved)
    assert seen[3] == earlier


@pytest.mark.parametrize("cursor", ["", "yesterday", "2026-11-13T18:30:00#x", "HISTORY#2026"])
def test_history_refuses_a_malformed_cursor(records: Records, cursor: str) -> None:
    with pytest.raises(BadCursor):
        records.history(5, before=cursor)


def test_records_is_item_used_for_each_list(records: Records) -> None:
    assert not records.is_item_used(CatalogList.KILNS, ItemId("athena"))
    glazed = replace(a_drop_off(1), firing_type=ItemId("glaze"), glaze_type=ItemId("house-dip"))
    records.commit(
        [
            Put(glazed),
            Put(a_drop_off(2, DropOffState.CLOSED, reason="cracked")),
            Put(a_drop_off(3, DropOffState.REJECTED, reason="too-wet")),
            Put(a_load(1, LoadStatus.FIRED, kiln="helios", firing_type="raku")),
            Put(a_load(2, LoadStatus.DELETED, kiln="vulcan", firing_type="pit")),
            Put(replace(a_drop_off(4, DropOffState.DELETED), glaze_type=ItemId("commercial"))),
        ]
    )
    assert not records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("commercial"))  # a deleted drop-off's
    assert not records.is_item_used(CatalogList.KILNS, ItemId("vulcan"))  # only a deleted load's
    assert records.is_item_used(CatalogList.KILNS, ItemId("helios"))
    assert not records.is_item_used(CatalogList.KILNS, ItemId("athena"))
    assert records.is_item_used(CatalogList.FIRING_TYPES, ItemId("glaze"))  # by a drop-off
    assert records.is_item_used(CatalogList.FIRING_TYPES, ItemId("raku"))  # by a load
    assert not records.is_item_used(CatalogList.FIRING_TYPES, ItemId("pit"))
    assert records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip"))
    assert not records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("commercial"))
    assert records.is_item_used(CatalogList.REASONS, ItemId("cracked"))  # a closed drop-off's
    assert records.is_item_used(CatalogList.REASONS, ItemId("too-wet"))
    assert not records.is_item_used(CatalogList.REASONS, ItemId("other"))


def with_program_cone(load: Load, cone: str) -> Load:
    return replace(load, record=FiringRecord(program=Program(cone=ItemId(cone))))


def test_cone_used_by_load_program(records: Records) -> None:
    records.commit(
        [
            Put(with_program_cone(a_load(1, LoadStatus.LOADING), "item-5")),
            Put(with_program_cone(a_load(2, LoadStatus.FIRED), "item-04")),
            Put(with_program_cone(a_load(3, LoadStatus.DELETED), "item-10")),
        ]
    )
    assert records.is_item_used(CatalogList.CONES, ItemId("item-5"))  # a loading load's
    assert records.is_item_used(CatalogList.CONES, ItemId("item-04"))  # a fired load's
    assert not records.is_item_used(CatalogList.CONES, ItemId("item-10"))  # only a deleted load's
    assert not records.is_item_used(CatalogList.CONES, ItemId("item-9"))  # no studio stored: no program


def test_cone_used_by_default_program(records: Records) -> None:
    studio, change = starting_studio(a_sending_address(), NOW)
    records.commit([Put(studio), Put(change)])
    assert records.is_item_used(CatalogList.CONES, ItemId("item-6"))  # Glaze's default program
    assert records.is_item_used(CatalogList.CONES, ItemId("item-06"))  # Bisque's
    assert not records.is_item_used(CatalogList.CONES, ItemId("item-5"))


def test_clay_body_not_used(records: Records) -> None:
    studio, change = starting_studio(a_sending_address(), NOW)
    records.commit([Put(studio), Put(change), Put(a_load(1, LoadStatus.FIRED))])
    assert not records.is_item_used(CatalogList.CLAY_BODIES, ItemId("buffalo-wallow"))


def test_records_keep_the_studio_and_submissions(records: Records) -> None:
    assert records.studio() is None
    studio, change = starting_studio(a_sending_address(), NOW)
    records.commit([Put(studio), Put(change), Put(a_submission())])
    stored = records.studio()
    assert stored == replace(studio, version=1)
    with pytest.raises(Conflict) as refused:
        records.commit([Put(studio)])
    assert refused.value.ids == ()
    records.commit([Update(replace(stored, pickup_window_days=10))])
    updated = records.studio()
    assert updated is not None
    assert (updated.pickup_window_days, updated.version) == (10, 2)
    assert records.submission(TOKEN_HASH) == a_submission()
    assert records.submission("another-hash") is None
    with pytest.raises(Conflict) as again:
        records.commit([Put(a_submission(2))])  # one drop-off per submission token
    assert again.value.ids == ("AC-2",)


def test_a_closed_drop_off_keeps_no_personal_details(records: Records) -> None:
    rejected = a_drop_off(1, DropOffState.REJECTED)
    records.commit([Put(rejected)])
    stored = records.drop_off(DropOffId(1))
    assert stored is not None
    assert stored.contact is not None
    closed = replace(a_drop_off(1, DropOffState.CLOSED), version=stored.version)
    assert closed.contact is None
    assert closed.rejection is not None
    records.commit([Update(closed)])
    after = records.drop_off(DropOffId(1))
    assert after is not None
    assert after.contact is None
    assert after.rejection is not None
    assert after.rejection.message is None
    assert after == replace(closed, version=2)


def test_reads_of_an_unknown_key_are_none(records: Records) -> None:
    assert records.drop_off(DropOffId(404)) is None
    assert records.load(LoadId(404)) is None
    assert records.email(DropOffId(404), EmailKind.RECEIVED) is None
    assert records.emails_for(DropOffId(404)) == []
