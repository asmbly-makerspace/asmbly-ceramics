"""`Records`' contract for a load's history, firing notes and date ranges (#42, #17), run
against the in-memory fake and the DynamoDB adapter on moto, as `test_records` is."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.adapters.memory.ids import MemoryIdNumbers
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.notes import FiringNote, Ruling, remove_note
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.records import Conflict, Put, Records, Update
from tests.adapters.conftest import TABLE
from tests.domain.builders import NOW, STAFF, a_load, a_note, an_event

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
else:
    DynamoDBClient = Any

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


@pytest.fixture(params=["memory", "dynamodb"])
def records(request: pytest.FixtureRequest) -> Iterator[Records]:
    if request.param == "memory":
        yield MemoryRecords()
    else:
        client: DynamoDBClient = request.getfixturevalue("dynamodb")
        yield DynamoDbRecords(client, TABLE)


@pytest.fixture(params=["memory", "dynamodb"])
def ids(request: pytest.FixtureRequest) -> Iterator[IdNumbers]:
    if request.param == "memory":
        yield MemoryIdNumbers()
    else:
        client: DynamoDBClient = request.getfixturevalue("dynamodb")
        yield DynamoDbIdNumbers(client, TABLE)


def load_ids(loads: list[Load]) -> list[str]:
    return [str(load.id) for load in loads]


def note_ids(notes: list[FiringNote]) -> list[str]:
    return [str(note.id) for note in notes]


def stored(note: FiringNote, version: int = 1) -> FiringNote:
    return replace(note, version=version)


# A load's history -----------------------------------------------------------------------


def test_event_put_and_listed_oldest_first(records: Records) -> None:
    records.commit([Put(a_load(1)), Put(an_event(1, "Started", at=NOW))])
    records.commit(
        [Put(an_event(1, "Fired", at=NOW + 2 * HOUR)), Put(an_event(1, "Started firing", at=NOW + HOUR))]
    )
    events = records.load_events(LoadId(1))
    assert [e.what for e in events] == ["Started", "Started firing", "Fired"]
    assert events[0] == an_event(1, "Started", at=NOW)
    assert records.load(LoadId(1)) == replace(a_load(1), version=1)  # the load is untouched


def test_two_events_same_instant_both_land(records: Records) -> None:
    records.commit([Put(an_event(1, "Fired")), Put(an_event(1, "Fired"))])
    records.commit([Put(an_event(1, "Fired"))])
    assert [e.what for e in records.load_events(LoadId(1))] == ["Fired"] * 3


def test_load_events_only_that_load(records: Records) -> None:
    records.commit([Put(a_load(1)), Put(a_load(12)), Put(an_event(1, "Started")), Put(an_event(12, "Fired"))])
    records.commit([Put(a_note(1, a_load(1)))])
    assert [e.load_id for e in records.load_events(LoadId(1))] == [LoadId(1)]
    assert [e.what for e in records.load_events(LoadId(12))] == ["Fired"]
    assert records.load_events(LoadId(404)) == []


# Loads by date --------------------------------------------------------------------------


def test_loads_dated_between_half_open(records: Records) -> None:
    start = NOW.date()
    records.commit(
        [
            Put(a_load(1, LoadStatus.FIRED, at=NOW - DAY)),  # the day before: out
            Put(a_load(2, LoadStatus.FIRED, at=NOW)),  # the first day: in
            Put(a_load(10, LoadStatus.FIRED, at=NOW + 2 * DAY)),  # the last day: in
            Put(a_load(3, LoadStatus.FIRED, at=NOW + 2 * DAY)),  # in, before L-10 by ID
            Put(a_load(4, LoadStatus.FIRED, at=NOW + 3 * DAY)),  # the end: out
        ]
    )
    found = records.loads_dated_between({LoadStatus.FIRED}, start, start + 3 * DAY)
    assert load_ids(found) == ["L-2", "L-3", "L-10"]
    assert found[0] == replace(a_load(2, LoadStatus.FIRED, at=NOW), version=1)
    assert records.loads_dated_between({LoadStatus.FIRED}, start, start) == []
    assert records.loads_dated_between({LoadStatus.FIRED}, start + DAY, start) == []  # reversed: none
    with pytest.raises(TypeError):
        records.loads_dated_between({LoadStatus.FIRED}, NOW, NOW + DAY)


def test_loads_dated_between_statuses(records: Records) -> None:
    records.commit(
        [
            Put(a_load(1, LoadStatus.LOADING)),
            Put(a_load(2, LoadStatus.FIRING)),
            Put(a_load(3, LoadStatus.FIRED)),
            Put(a_load(4, LoadStatus.DELETED)),
        ]
    )
    day = NOW.date()
    assert load_ids(records.loads_dated_between({LoadStatus.FIRED}, day, day + DAY)) == ["L-3"]
    assert load_ids(records.loads_dated_between({LoadStatus.FIRING, LoadStatus.FIRED}, day, day + DAY)) == [
        "L-2",
        "L-3",
    ]
    assert records.loads_dated_between(set(), day, day + DAY) == []
    assert records.loads_dated_between(set(LoadStatus), date(2020, 1, 1), date(2020, 1, 2)) == []


# Notes ----------------------------------------------------------------------------------


def test_note_put_get_update(records: Records) -> None:
    note = a_note(12, a_load(4, LoadStatus.FIRED))
    records.commit([Put(note)])
    assert records.note(LoadId(4), NoteId(12)) == stored(note)
    assert records.note(LoadId(5), NoteId(12)) is None  # a note is found under its own load
    assert records.note(LoadId(4), NoteId(13)) is None
    edited = replace(
        stored(note), text="Crawled at the rim.", ruling=None, edited_by=STAFF, edited_at=NOW + HOUR
    )
    records.commit([Update(edited)])
    assert records.note(LoadId(4), NoteId(12)) == stored(edited, 2)
    no_tags = a_note(13, a_load(4, LoadStatus.FIRED), glaze_types=(), clay_bodies=(), ruling=None)
    records.commit([Put(no_tags)])
    assert records.note(LoadId(4), NoteId(13)) == stored(no_tags)


def test_note_put_twice_conflict(records: Records) -> None:
    records.commit([Put(a_note(12))])
    with pytest.raises(Conflict) as refused:
        records.commit([Put(a_note(12, text="Another note under the same ID."))])
    assert refused.value.ids == ("N-12",)


def test_note_update_wrong_version_conflict(records: Records) -> None:
    note = a_note(12)
    with pytest.raises(Conflict):
        records.commit([Update(note)])  # nothing stored yet
    records.commit([Put(note)])
    with pytest.raises(Conflict) as refused:
        records.commit([Update(replace(note, text="A stale edit."))])  # version 0, stored at 1
    assert refused.value.ids == ("N-12",)
    assert records.note(LoadId(1), NoteId(12)) == stored(note)


def test_notes_for_newest_first_without_removed(records: Records) -> None:
    load = a_load(1, LoadStatus.FIRED)
    removed = remove_note(a_note(3, load, at=NOW + 2 * HOUR), STAFF, NOW + 3 * HOUR)
    records.commit(
        [
            Put(a_note(1, load, at=NOW)),
            Put(a_note(2, load, at=NOW + HOUR)),
            Put(a_note(10, load, at=NOW + HOUR)),  # the same instant as N-2: the higher ID first
            Put(removed),
            Put(a_note(4, a_load(2, LoadStatus.FIRED), at=NOW + 4 * HOUR)),  # another load's
        ]
    )
    assert note_ids(records.notes_for(LoadId(1))) == ["N-10", "N-2", "N-1"]
    assert records.notes_for(LoadId(404)) == []
    assert records.note(LoadId(1), NoteId(3)) == stored(removed)  # a removed note is still read by key


def test_notes_written_between_half_open_without_removed(records: Records) -> None:
    start, end = NOW, NOW + DAY
    records.commit(
        [
            Put(a_note(1, a_load(1), at=start - HOUR)),  # before: out
            Put(a_note(2, a_load(1), at=start)),  # the start: in
            Put(a_note(3, a_load(2), at=start + HOUR)),  # another load's: in
            Put(a_note(4, a_load(2), at=end)),  # the end: out
            Put(remove_note(a_note(5, a_load(1), at=start + 2 * HOUR), STAFF, start + 3 * HOUR)),
        ]
    )
    assert note_ids(records.notes_written_between(start, end)) == ["N-3", "N-2"]
    note = records.note(LoadId(1), NoteId(2))
    assert note is not None
    records.commit([Update(remove_note(note, STAFF, start + 4 * HOUR))])  # removed later: gone
    assert note_ids(records.notes_written_between(start, end)) == ["N-3"]
    assert records.notes_written_between(end, start) == []
    with pytest.raises(ValueError, match="aware"):
        records.notes_written_between(start.replace(tzinfo=None), end)


def test_clay_body_used_by_note(records: Records) -> None:
    records.commit([Put(a_note(1, clay_bodies=("cinco-blanco", "buffalo-wallow"), glaze_types=()))])
    assert records.is_item_used(CatalogList.CLAY_BODIES, ItemId("buffalo-wallow"))
    assert records.is_item_used(CatalogList.CLAY_BODIES, ItemId("cinco-blanco"))
    assert not records.is_item_used(CatalogList.CLAY_BODIES, ItemId("cinco"))  # whole IDs only
    assert not records.is_item_used(CatalogList.CLAY_BODIES, ItemId("cone-5-porcelain"))


def test_glaze_type_used_by_note(records: Records) -> None:
    records.commit([Put(a_note(1, glaze_types=("house-dip-glaze",), clay_bodies=()))])
    assert records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip-glaze"))
    assert not records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip"))
    assert not records.is_item_used(CatalogList.CLAY_BODIES, ItemId("house-dip-glaze"))  # not its list


def test_removed_note_uses_nothing(records: Records) -> None:
    note = a_note(
        1, glaze_types=("house-dip-glaze",), clay_bodies=("cinco-blanco",), ruling=Ruling.NOT_ALLOWED
    )
    records.commit([Put(remove_note(note, STAFF, NOW + HOUR))])
    assert not records.is_item_used(CatalogList.GLAZE_TYPES, ItemId("house-dip-glaze"))
    assert not records.is_item_used(CatalogList.CLAY_BODIES, ItemId("cinco-blanco"))


def test_next_note_id_increments(ids: IdNumbers) -> None:
    assert [ids.next_note_id(), ids.next_note_id()] == [NoteId(1), NoteId(2)]
    assert ids.next_load_id() == LoadId(1)  # its own counter
