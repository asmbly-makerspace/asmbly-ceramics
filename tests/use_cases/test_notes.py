"""Firing notes (#17), against the fakes: writing, editing and removing a note, a load's
notes, the search and the firing log's counts, as the `world` fixture builds them."""

import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from asmbly_ceramics.domain.errors import InvalidLogRange, InvalidNote, ItemRetired, NotFound, UnknownItem
from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import LOG_RANGE_MAX, NOTE_LOAD_SLACK, NOTES_DEFAULT_RANGE, STUDIO_TZ
from asmbly_ceramics.domain.load import LoadStatus
from asmbly_ceramics.domain.notes import TEXT_PERSONAL, FiringNote, NoteFilter, Ruling
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.errors import IdsUnavailable, RecordsUnavailable
from asmbly_ceramics.ports.records import Conflict, Put
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.notes import (
    NoteCount,
    NoteInput,
)
from tests.domain.builders import NOW, STAFF, TEST_NOTE_TEXT, a_load, an_address
from tests.use_cases.conftest import World
from tests.use_cases.flows import ATHENA, BISQUE, HELIOS, STAFF_MEMBER, version

OTHER_STAFF = StaffMember("robin", an_address("robin.kiln"))
HOUSE_DIP = ItemId("house-dip-glaze")
COMMERCIAL = ItemId("commercial-glaze")
CINCO = ItemId("cinco-blanco")
BUFFALO = ItemId("buffalo-wallow")
TODAY = date(2026, 11, 13)  # NOW, in Austin
N_1, N_2, N_3 = NoteId(1), NoteId(2), NoteId(3)


class Notes:
    """The note use cases, as the `world` fixture builds them (the console's are the same)."""

    def __init__(self, world: World) -> None:
        self.write = world.write_note
        self.edit = world.edit_note
        self.remove = world.remove_note
        self.for_load = world.load_notes
        self.search = world.search_notes
        self.counts = world.note_counts


@pytest.fixture
def notes(world: World) -> Notes:
    return Notes(world)


def an_input(
    text: str = TEST_NOTE_TEXT,
    glaze_types: tuple[ItemId, ...] = (HOUSE_DIP,),
    clay_bodies: tuple[ItemId, ...] = (CINCO,),
    ruling: Ruling | None = Ruling.ALLOWED,
) -> NoteInput:
    return NoteInput(text, glaze_types, clay_bodies, ruling)


def a_loading_load(world: World, kiln: ItemId = ATHENA, on: date | None = None) -> LoadId:
    return world.start_load(kiln, BISQUE, on, STAFF_MEMBER, test=True).id


def a_fired_load(world: World, kiln: ItemId = ATHENA, on: date | None = None) -> LoadId:
    load_id = a_loading_load(world, kiln, on)
    world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
    world.mark_fired(load_id, version(world, load_id), STAFF_MEMBER)
    return load_id


def stored(world: World, load_id: LoadId, note_id: NoteId) -> FiringNote:
    note = world.records.note(load_id, note_id)
    assert note is not None
    return note


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, object]]:
    return [vars(r) for r in caplog.records if r.getMessage() == name]


# --- WriteNote -----------------------------------------------------------------------------


def test_write_note(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load_id = a_loading_load(world)
    world.clock.advance(timedelta(minutes=5))

    note = notes.write(load_id, an_input(), STAFF_MEMBER)

    assert note.id == N_1
    assert note == stored(world, load_id, N_1)
    assert (note.load_id, note.kiln, note.text) == (load_id, ATHENA, TEST_NOTE_TEXT)
    assert (note.glaze_types, note.clay_bodies, note.ruling) == ((HOUSE_DIP,), (CINCO,), Ruling.ALLOWED)
    assert (note.written_by, note.written_at) == (STAFF, NOW + timedelta(minutes=5))
    assert note.edited_by is None
    assert note.removed_by is None
    [line] = events(caplog, "note_written")
    assert (line["load_id"], line["note_id"], line["user"], line["outcome"]) == (
        str(load_id),
        "N-1",
        STAFF,
        "allowed",
    )


def test_write_note_with_no_ruling_logs_none(
    world: World, notes: Notes, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    note = notes.write(
        a_loading_load(world), an_input(ruling=None, glaze_types=(), clay_bodies=()), STAFF_MEMBER
    )
    assert note.ruling is None
    assert events(caplog, "note_written")[0]["outcome"] == "none"


def test_write_on_fired_load(world: World, notes: Notes) -> None:
    load_id = a_fired_load(world)
    note = notes.write(load_id, an_input(ruling=Ruling.NOT_ALLOWED), STAFF_MEMBER)
    assert stored(world, load_id, note.id).ruling is Ruling.NOT_ALLOWED
    load = world.records.load(load_id)
    assert load is not None
    assert load.status is LoadStatus.FIRED


def test_write_on_deleted_load_not_found(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    world.delete_load(load_id, version(world, load_id), STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.write(load_id, an_input(), STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.write(LoadId(99), an_input(), STAFF_MEMBER)
    assert world.records.notes_written_between(NOW - timedelta(days=1), NOW + timedelta(days=1)) == []


@pytest.mark.parametrize(
    "note",
    [
        an_input(text="   "),
        an_input(text="Call " + " ".join(["512", "555", "01" + "42"])),
        an_input(text="Ask " + an_address("someone")),
        an_input(glaze_types=(HOUSE_DIP, HOUSE_DIP)),
    ],
)
def test_write_invalid_text_spends_no_number(world: World, notes: Notes, note: NoteInput) -> None:
    load_id = a_loading_load(world)
    commits = len(world.records.commits)
    with pytest.raises(InvalidNote):
        notes.write(load_id, note, STAFF_MEMBER)
    assert len(world.records.commits) == commits
    assert notes.write(load_id, an_input(), STAFF_MEMBER).id == N_1  # no number was spent


def test_write_refuses_personal_details_without_quoting_them(world: World, notes: Notes) -> None:
    address = an_address("someone")
    with pytest.raises(InvalidNote) as refused:
        notes.write(a_loading_load(world), an_input(text="Ask " + address), STAFF_MEMBER)
    assert refused.value.errors == {"text": TEXT_PERSONAL}
    assert address not in str(refused.value)


def test_write_retired_tag_refused(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    world.retire_item(CatalogList.GLAZE_TYPES, COMMERCIAL, world.studio().version, STAFF_MEMBER)
    with pytest.raises(ItemRetired):
        notes.write(load_id, an_input(glaze_types=(COMMERCIAL,)), STAFF_MEMBER)
    with pytest.raises(UnknownItem):
        notes.write(load_id, an_input(clay_bodies=(ItemId("made-up-clay"),)), STAFF_MEMBER)
    assert notes.write(load_id, an_input(), STAFF_MEMBER).id == N_1


def test_write_bumps_the_load_version(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    before = version(world, load_id)
    notes.write(load_id, an_input(), STAFF_MEMBER)
    assert version(world, load_id) == before + 1
    assert sorted(type(change.item).__name__ for change in world.records.commits[-1]) == [
        "FiringNote",
        "Load",
    ]
    with pytest.raises(Conflict):  # a load page open elsewhere reloads on its next save
        world.start_firing(load_id, before, STAFF_MEMBER)


def test_write_conflicts_when_the_load_moved_kiln(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world, ATHENA)
    real_load = world.records.load

    def kiln_changed_after_the_read(id: LoadId) -> object:
        """The note's read of the load, then another staff member's kiln change, before the
        note's commit."""
        read = real_load(id)
        world.records.load = real_load  # type: ignore[method-assign]  # once
        assert read is not None
        world.change_load(id, HELIOS, BISQUE, read.date, read.version, OTHER_STAFF, test=True)
        return read

    world.records.load = kiln_changed_after_the_read  # type: ignore[method-assign,assignment]

    with pytest.raises(Conflict):
        notes.write(load_id, an_input(), STAFF_MEMBER)

    assert world.records.notes_for(load_id) == []
    load = world.records.load(load_id)
    assert load is not None
    assert load.kiln == HELIOS
    # Written again on the load as it is now, the note is filed under its new kiln.
    assert notes.write(load_id, an_input(), STAFF_MEMBER).kiln == HELIOS


def test_write_conflicts_when_the_load_was_deleted_meanwhile(world: World, notes: Notes) -> None:
    """The note's read of the load, then another staff member's delete, before the note's
    commit: no note lands on a deleted load."""
    load_id = a_loading_load(world)
    real_load = world.records.load

    def deleted_after_the_read(id: LoadId) -> object:
        read = real_load(id)
        world.records.load = real_load  # type: ignore[method-assign]  # once
        assert read is not None
        world.delete_load(id, read.version, OTHER_STAFF)
        return read

    world.records.load = deleted_after_the_read  # type: ignore[method-assign,assignment]

    with pytest.raises(Conflict):
        notes.write(load_id, an_input(), STAFF_MEMBER)

    assert world.records.note(load_id, N_1) is None
    assert not world.records.is_item_used(CatalogList.CLAY_BODIES, CINCO)


# --- EditNote ------------------------------------------------------------------------------


def test_edit_note(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load_id = a_fired_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    world.clock.advance(timedelta(hours=2))

    edited = notes.edit(
        load_id,
        note.id,
        an_input("Crawled at ^6: retest first.", (COMMERCIAL,), (BUFFALO,), Ruling.ALLOWED_WITH_CONDITIONS),
        note.version,
        OTHER_STAFF,
    )

    assert edited == stored(world, load_id, note.id)
    assert edited.version == note.version + 1
    assert (edited.text, edited.glaze_types, edited.clay_bodies) == (
        "Crawled at ^6: retest first.",
        (COMMERCIAL,),
        (BUFFALO,),
    )
    assert edited.ruling is Ruling.ALLOWED_WITH_CONDITIONS
    assert (edited.edited_by, edited.edited_at) == ("robin", NOW + timedelta(hours=2))
    [line] = events(caplog, "note_edited")
    assert (line["load_id"], line["note_id"], line["user"], line["outcome"]) == (
        str(load_id),
        "N-1",
        "robin",
        "allowed_with_conditions",
    )


def test_edit_keeps_written_by(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    world.clock.advance(timedelta(days=1))
    edited = notes.edit(load_id, note.id, an_input(ruling=None), note.version, OTHER_STAFF)
    assert (edited.written_by, edited.written_at) == (STAFF, NOW)


def test_edit_with_nothing_changed_commits_nothing(
    world: World, notes: Notes, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    commits = len(world.records.commits)
    assert notes.edit(load_id, note.id, an_input(), note.version, OTHER_STAFF) == note
    assert len(world.records.commits) == commits
    assert events(caplog, "note_edited") == []


def test_edit_keeps_a_tag_retired_since(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(glaze_types=(COMMERCIAL,)), STAFF_MEMBER)
    world.retire_item(CatalogList.GLAZE_TYPES, COMMERCIAL, world.studio().version, STAFF_MEMBER)
    edited = notes.edit(load_id, note.id, an_input("Kept.", (COMMERCIAL,)), note.version, STAFF_MEMBER)
    assert edited.glaze_types == (COMMERCIAL,)
    with pytest.raises(InvalidNote):
        notes.edit(load_id, note.id, an_input(text=""), edited.version, STAFF_MEMBER)


def test_edit_conflict(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    notes.edit(load_id, note.id, an_input("First edit."), note.version, OTHER_STAFF)
    with pytest.raises(Conflict) as conflict:
        notes.edit(load_id, note.id, an_input("Second edit."), note.version, STAFF_MEMBER)
    assert conflict.value.ids == ("N-1",)
    assert stored(world, load_id, note.id).text == "First edit."


def test_edit_conflicts_after_the_load_moved_kiln(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world, ATHENA)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    load = world.records.load(load_id)
    assert load is not None
    world.change_load(load_id, HELIOS, BISQUE, load.date, load.version, OTHER_STAFF, test=True)
    with pytest.raises(Conflict):  # the page showed the note before it moved
        notes.edit(load_id, note.id, an_input("Edited."), note.version, STAFF_MEMBER)
    assert stored(world, load_id, note.id).kiln == HELIOS


def test_edit_removed_not_found(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    notes.remove(load_id, note.id, note.version, STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.edit(load_id, note.id, an_input("Edited."), note.version + 1, STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.edit(load_id, N_2, an_input("Edited."), 1, STAFF_MEMBER)


def test_edit_wrong_load_not_found(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    other = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.edit(other, note.id, an_input("Edited."), note.version, STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.remove(other, note.id, note.version, STAFF_MEMBER)
    assert stored(world, load_id, note.id) == note


def test_edit_on_a_deleted_load_not_found(world: World, notes: Notes) -> None:
    """A note written on a load before its delete (`DeleteLoad` removes the notes it finds
    now; this one is put by hand, as one written before that change would be)."""
    load = a_load(1, status=LoadStatus.DELETED)
    world.records.commit([Put(load)])
    note = FiringNote(N_1, load.id, ATHENA, TEST_NOTE_TEXT, (), (), None, STAFF, NOW)
    world.records.commit([Put(note)])
    with pytest.raises(NotFound):
        notes.edit(load.id, N_1, an_input("Edited."), 1, STAFF_MEMBER)
    with pytest.raises(NotFound):
        notes.for_load(load.id)


# --- RemoveNote ----------------------------------------------------------------------------


def test_remove_note(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load_id = a_fired_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    world.clock.advance(timedelta(hours=3))

    notes.remove(load_id, note.id, note.version, OTHER_STAFF)

    removed = stored(world, load_id, note.id)
    assert (removed.removed_by, removed.removed_at) == ("robin", NOW + timedelta(hours=3))
    assert removed.text == TEST_NOTE_TEXT  # kept, listed nowhere
    [line] = events(caplog, "note_removed")
    assert (line["load_id"], line["note_id"], line["user"]) == (str(load_id), "N-1", "robin")


def test_remove_conflict(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    notes.edit(load_id, note.id, an_input("Edited."), note.version, OTHER_STAFF)
    with pytest.raises(Conflict):
        notes.remove(load_id, note.id, note.version, STAFF_MEMBER)
    assert not stored(world, load_id, note.id).removed


def test_removed_not_listed_or_found(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    notes.remove(load_id, note.id, note.version, STAFF_MEMBER)
    assert notes.for_load(load_id) == ()
    assert notes.search(NoteFilter(), None, None).rows == ()
    load = world.records.load(load_id)
    assert load is not None
    assert notes.counts([load]) == {load_id: NoteCount(0, 0)}
    with pytest.raises(NotFound):
        notes.remove(load_id, note.id, note.version + 1, STAFF_MEMBER)


# --- LoadNotes -----------------------------------------------------------------------------


def test_load_notes_newest_first_with_names(
    world: World, notes: Notes, caplog: pytest.LogCaptureFixture
) -> None:
    load_id = a_fired_load(world, HELIOS)
    other = a_fired_load(world)
    first = notes.write(load_id, an_input(glaze_types=(COMMERCIAL,)), STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=1))
    notes.write(other, an_input(), STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=1))
    second = notes.write(load_id, an_input(clay_bodies=(CINCO, BUFFALO)), OTHER_STAFF)
    world.retire_item(CatalogList.GLAZE_TYPES, COMMERCIAL, world.studio().version, STAFF_MEMBER)
    caplog.set_level(logging.DEBUG)
    caplog.clear()

    rows = notes.for_load(load_id)

    assert [row.note.id for row in rows] == [second.id, first.id]
    assert (rows[0].kiln, rows[0].firing_type) == ("Helios", "Bisque")
    assert rows[0].clay_bodies == ("Cinco Blanco", "Buffalo Wallow")
    assert rows[1].glaze_types == ("Commercial glaze",)  # retired since, still named
    assert caplog.records == []  # a read logs nothing


def test_load_notes_of_a_missing_load_not_found(world: World, notes: Notes) -> None:
    with pytest.raises(NotFound):
        notes.for_load(LoadId(99))


# --- SearchNotes ---------------------------------------------------------------------------


def write_at(
    world: World, notes: Notes, load_id: LoadId, at: datetime, note: NoteInput | None = None
) -> NoteId:
    """A note written at `at` (the clock set there, then put back)."""
    world.clock.advance(at - world.clock.now())
    written = notes.write(load_id, note or an_input(), STAFF_MEMBER)
    world.clock.advance(NOW - world.clock.now())
    return written.id


def austin(on: date, hour: int = 12) -> datetime:
    return datetime(on.year, on.month, on.day, hour, tzinfo=STUDIO_TZ)


def test_search_default_range(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    load_id = a_fired_load(world)
    old = write_at(world, notes, load_id, austin(TODAY - NOTES_DEFAULT_RANGE - timedelta(days=1), 23))
    first = write_at(world, notes, load_id, austin(TODAY - NOTES_DEFAULT_RANGE, 0))
    last = write_at(world, notes, load_id, austin(TODAY, 1))
    caplog.set_level(logging.DEBUG)
    caplog.clear()

    view = notes.search(NoteFilter(), None, None)

    assert (view.start, view.end) == (TODAY - NOTES_DEFAULT_RANGE, TODAY)
    assert [row.note.id for row in view.rows] == [last, first]
    assert old not in [row.note.id for row in view.rows]
    assert view.filter == NoteFilter()
    assert caplog.records == []  # a read logs nothing


def test_search_range_is_inclusive_in_austin_days(world: World, notes: Notes) -> None:
    load_id = a_fired_load(world)
    day = date(2026, 6, 1)
    before = write_at(world, notes, load_id, austin(day - timedelta(days=1), 23))
    on_start = write_at(world, notes, load_id, austin(day, 0))
    on_end = write_at(world, notes, load_id, austin(day + timedelta(days=2), 23))
    after = write_at(world, notes, load_id, austin(day + timedelta(days=3), 0))
    view = notes.search(NoteFilter(), day, day + timedelta(days=2))
    found = [row.note.id for row in view.rows]
    assert found == [on_end, on_start]
    assert before not in found
    assert after not in found


def test_search_each_filter(world: World, notes: Notes) -> None:
    athena = a_fired_load(world, ATHENA)
    helios = a_fired_load(world, HELIOS)
    world.clock.advance(timedelta(minutes=1))
    a = notes.write(athena, an_input(glaze_types=(HOUSE_DIP,), clay_bodies=(CINCO,)), STAFF_MEMBER).id
    world.clock.advance(timedelta(minutes=1))
    b = notes.write(
        helios,
        an_input(glaze_types=(COMMERCIAL,), clay_bodies=(BUFFALO,), ruling=Ruling.NOT_ALLOWED),
        STAFF_MEMBER,
    ).id
    world.clock.advance(timedelta(minutes=1))
    c = notes.write(
        helios, an_input(glaze_types=(HOUSE_DIP, COMMERCIAL), clay_bodies=(), ruling=None), STAFF_MEMBER
    ).id

    def found(f: NoteFilter) -> list[NoteId]:
        return [row.note.id for row in notes.search(f, None, None).rows]

    assert found(NoteFilter()) == [c, b, a]
    assert found(NoteFilter(kiln=HELIOS)) == [c, b]
    assert found(NoteFilter(glaze_type=HOUSE_DIP)) == [c, a]
    assert found(NoteFilter(clay_body=BUFFALO)) == [b]
    assert found(NoteFilter(ruling=Ruling.NOT_ALLOWED)) == [b]
    assert found(NoteFilter(ruling=Ruling.ALLOWED)) == [a]
    assert found(NoteFilter(kiln=HELIOS, glaze_type=COMMERCIAL, ruling=Ruling.NOT_ALLOWED)) == [b]
    assert found(NoteFilter(kiln=ATHENA, clay_body=BUFFALO)) == []
    [row] = notes.search(NoteFilter(clay_body=BUFFALO), None, None).rows
    assert (row.kiln, row.firing_type, row.glaze_types, row.clay_bodies) == (
        "Helios",
        "Bisque",
        ("Commercial glaze",),
        ("Buffalo Wallow",),
    )


def test_search_no_ruling(world: World, notes: Notes) -> None:
    load_id = a_fired_load(world)
    notes.write(load_id, an_input(ruling=Ruling.ALLOWED), STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=1))
    none = notes.write(load_id, an_input(ruling=None), STAFF_MEMBER)
    assert [row.note.id for row in notes.search(NoteFilter(ruling=None), None, None).rows] == [none.id]


@pytest.mark.parametrize(
    "f",
    [
        NoteFilter(kiln=ItemId("made-up-kiln")),
        NoteFilter(glaze_type=ItemId("made-up-glaze")),
        NoteFilter(clay_body=ItemId("made-up-clay")),
    ],
)
def test_search_unknown_item(world: World, notes: Notes, f: NoteFilter) -> None:
    with pytest.raises(UnknownItem):
        notes.search(f, None, None)
    assert "notes_written_between" not in world.records.reads


def test_search_finds_a_retired_item(world: World, notes: Notes) -> None:
    load_id = a_fired_load(world)
    note = notes.write(load_id, an_input(glaze_types=(COMMERCIAL,)), STAFF_MEMBER)
    world.retire_item(CatalogList.GLAZE_TYPES, COMMERCIAL, world.studio().version, STAFF_MEMBER)
    assert [row.note.id for row in notes.search(NoteFilter(glaze_type=COMMERCIAL), None, None).rows] == [
        note.id
    ]


def test_search_range_too_long(world: World, notes: Notes) -> None:
    start = TODAY - LOG_RANGE_MAX
    assert notes.search(NoteFilter(), start, TODAY).start == start
    with pytest.raises(InvalidLogRange):
        notes.search(NoteFilter(), start - timedelta(days=1), TODAY)
    with pytest.raises(InvalidLogRange):
        notes.search(NoteFilter(), TODAY, TODAY - timedelta(days=1))
    with pytest.raises(InvalidLogRange):
        notes.search(NoteFilter(), None, date.max)
    with pytest.raises(InvalidLogRange):
        notes.search(NoteFilter(), None, date.min)


def test_search_reads_the_loads_around_its_range_in_one_go(world: World, notes: Notes) -> None:
    near = a_fired_load(world)
    far = a_fired_load(world, on=TODAY - timedelta(days=200))
    notes.write(near, an_input(), STAFF_MEMBER)
    world.clock.advance(timedelta(minutes=1))
    notes.write(far, an_input(), STAFF_MEMBER)
    reads = len(world.records.reads)

    view = notes.search(NoteFilter(), TODAY - timedelta(days=7), None)

    assert {row.note.load_id for row in view.rows} == {near, far}
    assert world.records.date_ranges[-1] == (
        TODAY - timedelta(days=7) - NOTE_LOAD_SLACK,
        TODAY + timedelta(days=1) + NOTE_LOAD_SLACK,
    )
    assert world.records.reads[reads:].count("load") == 1  # only the load dated outside it


def test_search_with_no_notes_reads_no_loads(world: World, notes: Notes) -> None:
    a_fired_load(world)
    reads = len(world.records.reads)
    assert notes.search(NoteFilter(), None, None).rows == ()
    assert world.records.reads[reads:] == ["studio", "notes_written_between"]


def test_search_leaves_out_deleted_loads(world: World, notes: Notes) -> None:
    """A note left on a deleted load (one written before `DeleteLoad` removed them) is
    found nowhere."""
    live = a_fired_load(world)
    kept = notes.write(live, an_input(), STAFF_MEMBER)
    deleted = a_load(50, status=LoadStatus.DELETED)
    world.records.commit([Put(deleted)])
    world.records.commit([Put(FiringNote(N_2, deleted.id, ATHENA, TEST_NOTE_TEXT, (), (), None, STAFF, NOW))])
    assert [row.note.id for row in notes.search(NoteFilter(), None, None).rows] == [kept.id]


# --- NoteCounts ----------------------------------------------------------------------------


def test_note_counts(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    first = a_fired_load(world)
    second = a_fired_load(world)
    empty = a_fired_load(world)
    outside = a_fired_load(world)
    notes.write(first, an_input(ruling=Ruling.NOT_ALLOWED), STAFF_MEMBER)
    notes.write(first, an_input(ruling=Ruling.ALLOWED), STAFF_MEMBER)
    notes.write(first, an_input(ruling=Ruling.NOT_ALLOWED), STAFF_MEMBER)
    gone = notes.write(first, an_input(ruling=Ruling.NOT_ALLOWED), STAFF_MEMBER)
    notes.remove(first, gone.id, gone.version, STAFF_MEMBER)
    notes.write(second, an_input(ruling=None), STAFF_MEMBER)
    notes.write(outside, an_input(), STAFF_MEMBER)
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    loads = [world.records.load(id) for id in (first, second, empty)]
    reads = len(world.records.reads)

    counts = notes.counts([load for load in loads if load is not None])

    assert counts == {first: NoteCount(3, 2), second: NoteCount(1, 0), empty: NoteCount(0, 0)}
    assert world.records.reads[reads:] == ["notes_written_between"]
    assert caplog.records == []
    assert notes.counts([]) == {}


def test_note_counts_include_a_note_written_long_after_the_firing(world: World, notes: Notes) -> None:
    """A note or a "not allowed" ruling added to an old load a year on is still counted:
    the read runs up to the clock's now, not to a slack after the log's range."""
    old = a_fired_load(world, on=TODAY - timedelta(days=400))
    notes.write(old, an_input(ruling=Ruling.ALLOWED), STAFF_MEMBER)
    world.clock.advance(timedelta(days=365))
    late = notes.write(old, an_input(ruling=Ruling.NOT_ALLOWED), STAFF_MEMBER)
    load = world.records.load(old)
    assert load is not None

    assert notes.counts([load]) == {old: NoteCount(2, 1)}
    assert late.written_at == world.clock.now()  # written at the read's very end, kept


def test_note_counts_read_from_the_slack_before_the_earliest_start(world: World, notes: Notes) -> None:
    """No note is written on a load before it is started; the read starts
    `NOTE_LOAD_SLACK` before the earliest start, for a started time corrected later."""
    load = a_load(50, LoadStatus.FIRED)
    within = FiringNote(N_1, load.id, ATHENA, TEST_NOTE_TEXT, (), (), None, STAFF, NOW - NOTE_LOAD_SLACK)
    before = replace(within, id=N_2, written_at=NOW - NOTE_LOAD_SLACK - timedelta(microseconds=1))
    world.records.commit([Put(load), Put(within), Put(before)])
    assert notes.counts([load]) == {load.id: NoteCount(1, 0)}


def test_note_counts_hold_at_the_calendar_edge(notes: Notes) -> None:
    ancient = a_load(1, at=datetime.min.replace(tzinfo=UTC) + timedelta(days=1))
    assert notes.counts([ancient]) == {ancient.id: NoteCount(0, 0)}


# --- Privacy -------------------------------------------------------------------------------


def test_logs_hold_no_text(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    text = "Made-up note: Zanzibar glaze crawled on Cinco Blanco"
    load_id = a_fired_load(world)
    note = notes.write(load_id, an_input(text=text, glaze_types=(COMMERCIAL,)), STAFF_MEMBER)
    edited = notes.edit(load_id, note.id, an_input(text + ", edited"), note.version, STAFF_MEMBER)
    notes.remove(load_id, note.id, edited.version, STAFF_MEMBER)
    notes.for_load(load_id)
    notes.search(NoteFilter(), None, None)

    logged = str([vars(record) for record in caplog.records])
    for word in ("Zanzibar", "crawled", "Cinco", "Commercial", "glaze"):
        assert word not in logged
    assert "N-1" in logged


@pytest.mark.parametrize(
    ("start", "end", "written"),
    [
        (date.min, date.min + timedelta(days=9), datetime(1, 1, 2, tzinfo=UTC)),
        (date.max - timedelta(days=9), date.max - timedelta(days=1), datetime(9999, 12, 30, tzinfo=UTC)),
    ],
)
def test_search_holds_at_the_calendar_edge(
    world: World, notes: Notes, start: date, end: date, written: datetime
) -> None:
    load_id = a_fired_load(world)
    world.records.commit(
        [Put(FiringNote(N_1, load_id, ATHENA, TEST_NOTE_TEXT, (), (), None, STAFF, written))]
    )
    assert [row.note.id for row in notes.search(NoteFilter(), start, end).rows] == [N_1]


# --- Ports unavailable ---------------------------------------------------------------------


def test_write_with_numbers_unavailable_stores_nothing(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    world.ids.fail_with = IdsUnavailable("ThrottlingException")
    with pytest.raises(IdsUnavailable):
        notes.write(load_id, an_input(), STAFF_MEMBER)
    assert world.records.notes_for(load_id) == []


def test_a_failed_commit_logs_nothing(world: World, notes: Notes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load_id = a_loading_load(world)
    world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
    with pytest.raises(RecordsUnavailable):
        notes.write(load_id, an_input(), STAFF_MEMBER)
    note = notes.write(load_id, an_input(), STAFF_MEMBER)
    for change in (
        lambda: notes.edit(load_id, note.id, an_input("Edited."), note.version, STAFF_MEMBER),
        lambda: notes.remove(load_id, note.id, note.version, STAFF_MEMBER),
    ):
        world.records.fail_next_commit_with = RecordsUnavailable("ThrottlingException")
        with pytest.raises(RecordsUnavailable):
            change()
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("note_")] == ["note_written"]
    assert stored(world, load_id, note.id) == note


def test_reads_with_records_unavailable_raise(world: World, notes: Notes) -> None:
    load_id = a_loading_load(world)
    load = world.records.load(load_id)
    assert load is not None
    world.studio()  # seeded before the reads fail
    world.records.fail_reads_with = RecordsUnavailable("ThrottlingException")
    for read in (
        lambda: notes.for_load(load_id),
        lambda: notes.search(NoteFilter(), None, None),
        lambda: notes.counts([load]),
    ):
        with pytest.raises(RecordsUnavailable):
            read()
