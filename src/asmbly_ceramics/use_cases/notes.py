"""Firing notes (#17): what the console's notes on a load and the notes search call.

A note is written on a load at any stage but deleted, edited and removed by staff, each
change stamped with the staff username and the clock's time. Every change reads what it
changes (strongly consistent) and commits it under a version check, so two staff acting
at once can't both win: the loser gets `Conflict`.

Logs carry note IDs (`N-12`), load IDs, staff usernames and the ruling's value only:
never a note's text or its tags' names. Reads log nothing. A note holds no personal
details (its text is refused when it holds something shaped like an email address or a
phone number: `domain.notes.check_note_text`), and the close (#7) never touches it.
"""

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType

from asmbly_ceramics.domain.errors import NotFound
from asmbly_ceramics.domain.ids import ItemId, LoadId, NoteId
from asmbly_ceramics.domain.limits import NOTE_LOAD_SLACK, NOTES_DEFAULT_RANGE, STUDIO_TZ
from asmbly_ceramics.domain.load import LIVE_STATUSES, Load, LoadStatus
from asmbly_ceramics.domain.notes import (
    FiringNote,
    NoteFilter,
    Ruling,
    edit_note,
    matches,
    remove_note,
    write_note,
)
from asmbly_ceramics.domain.ranges import log_range
from asmbly_ceramics.domain.studio import CatalogList, Studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.records import Conflict, Put, Records, Update
from asmbly_ceramics.ports.staff import StaffMember
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.studio import CurrentStudio, item_name

_EARLIEST = datetime.min.replace(tzinfo=UTC)
_TICK = timedelta(microseconds=1)  # a read's half-open end just after `now` keeps `now`
_UNNUMBERED = NoteId(1)  # stands in while the note is checked, so a refused one spends no number


@dataclass(frozen=True, slots=True)
class NoteInput:
    text: str
    glaze_types: tuple[ItemId, ...]
    clay_bodies: tuple[ItemId, ...]
    ruling: Ruling | None


def _live_load(records: Records, id: LoadId) -> Load:
    """The load, or `NotFound`: a deleted load is gone for every use case and page."""
    load = records.load(id)
    if load is None or load.status is LoadStatus.DELETED:
        raise NotFound(id)
    return load


def _live_note(records: Records, load_id: LoadId, note_id: NoteId) -> FiringNote:
    """The note on its live load, or `NotFound`: no note under that load, a removed one, or
    its load deleted."""
    _live_load(records, load_id)
    note = records.note(load_id, note_id)
    if note is None or note.removed:
        raise NotFound(note_id)
    return note


def _check_version(note: FiringNote, version: int) -> None:
    """The note is still at the version the staff member saw, else the page reloads."""
    if note.version != version:
        raise Conflict([str(note.id)])


def _stored(note: FiringNote) -> FiringNote:
    """The note as `Records` stores it after the commit: at its version plus one."""
    return replace(note, version=note.version + 1)


def _outcome(ruling: Ruling | None) -> str:
    return "none" if ruling is None else ruling.value


class WriteNote:
    def __init__(self, records: Records, ids: IdNumbers, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._ids = ids
        self._clock = clock
        self._studio = studio

    def __call__(self, load_id: LoadId, note: NoteInput, staff: StaffMember) -> FiringNote:
        """A new note on the load, at any stage but deleted (#17). It is checked before a
        number is spent, then committed with the load as it was read (`Update`), so the
        commit fails with `Conflict` if the load moved since: a kiln change between the
        read and the commit (`ChangeLoad` moves the notes it finds) can't leave this note
        filed under the old kiln. The load's version goes up by one, so a load page open
        elsewhere reloads on its next save. `NotFound` (no load, or deleted),
        `InvalidNote`, `UnknownItem`, `ItemRetired`, `Conflict`."""
        load = _live_load(self._records, load_id)
        studio = self._studio()
        now = self._clock.now()
        checked = write_note(
            _UNNUMBERED,
            load,
            note.text,
            note.glaze_types,
            note.clay_bodies,
            note.ruling,
            staff.username,
            now,
            studio,
        )
        written = replace(checked, id=self._ids.next_note_id())
        self._records.commit([Put(written), Update(load)])
        log_event(
            "note_written",
            load_id=str(load.id),
            note_id=str(written.id),
            user=staff.username,
            outcome=_outcome(written.ruling),
        )
        return _stored(written)


class EditNote:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(
        self, load_id: LoadId, note_id: NoteId, note: NoteInput, version: int, staff: StaffMember
    ) -> FiringNote:
        """Text, tags and ruling replaced at the version the page showed, stamped with who
        and when; who wrote it and when stay. A tag already on the note may be retired
        since. Nothing changed: no commit and no log, the note returned as it is.
        `NotFound` (no note under that load, removed, or its load deleted), `InvalidNote`,
        `UnknownItem`, `ItemRetired`, `Conflict`."""
        current = _live_note(self._records, load_id, note_id)
        edited = edit_note(
            current,
            note.text,
            note.glaze_types,
            note.clay_bodies,
            note.ruling,
            staff.username,
            self._clock.now(),
            self._studio(),
        )
        _check_version(current, version)
        if edited is current:
            return current
        self._records.commit([Update(edited)])
        log_event(
            "note_edited",
            load_id=str(load_id),
            note_id=str(note_id),
            user=staff.username,
            outcome=_outcome(edited.ruling),
        )
        return _stored(edited)


class RemoveNote:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, load_id: LoadId, note_id: NoteId, version: int, staff: StaffMember) -> None:
        """The note stamped removed, by whom and when, at the version the page showed; it is
        kept but listed nowhere again. `NotFound`, `Conflict`."""
        current = _live_note(self._records, load_id, note_id)
        removed = remove_note(current, staff.username, self._clock.now())
        _check_version(current, version)
        self._records.commit([Update(removed)])
        log_event("note_removed", load_id=str(load_id), note_id=str(note_id), user=staff.username)


@dataclass(frozen=True, slots=True)
class NoteRow:
    note: FiringNote
    kiln: str
    firing_type: str
    glaze_types: tuple[str, ...]  # names, retired ones included
    clay_bodies: tuple[str, ...]


def _row(studio: Studio, note: FiringNote, load: Load) -> NoteRow:
    return NoteRow(
        note=note,
        kiln=item_name(studio, CatalogList.KILNS, note.kiln),
        firing_type=item_name(studio, CatalogList.FIRING_TYPES, load.firing_type),
        glaze_types=tuple(item_name(studio, CatalogList.GLAZE_TYPES, id) for id in note.glaze_types),
        clay_bodies=tuple(item_name(studio, CatalogList.CLAY_BODIES, id) for id in note.clay_bodies),
    )


class LoadNotes:
    def __init__(self, records: Records, studio: CurrentStudio) -> None:
        self._records = records
        self._studio = studio

    def __call__(self, load_id: LoadId) -> tuple[NoteRow, ...]:
        """The load's notes, newest first, removed ones left out. `NotFound` (no load, or
        deleted). A read: logs nothing."""
        load = _live_load(self._records, load_id)
        studio = self._studio()
        return tuple(_row(studio, note, load) for note in self._records.notes_for(load.id))


@dataclass(frozen=True, slots=True)
class NoteSearchView:
    rows: tuple[NoteRow, ...]
    filter: NoteFilter
    start: date
    end: date  # inclusive


def _austin_midnight(on: date) -> datetime:
    return datetime.combine(on, time(), tzinfo=STUDIO_TZ)


def _shifted(on: date, by: timedelta) -> date:
    """`on` moved by `by`, held at the calendar's edge."""
    try:
        return on + by
    except OverflowError:
        return date.max if by > timedelta(0) else date.min


class SearchNotes:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None:
        self._records = records
        self._clock = clock
        self._studio = studio

    def __call__(self, f: NoteFilter, start: date | None, end: date | None) -> NoteSearchView:
        """Notes written `start..end` inclusive, Austin days (defaults: the last
        `NOTES_DEFAULT_RANGE` to today), matching `f`, newest first. Reads
        `notes_written_between` for the notes, `loads_dated_between` for the loads dated
        around the range, and any other load a note is on by its ID; a note on a deleted
        load is left out. `UnknownItem` for a kiln, glaze type or clay body the studio
        doesn't have. A range longer than `LOG_RANGE_MAX` or ending before it starts is
        `InvalidLogRange`, by the firing log's rule (`domain.ranges.log_range`). A read:
        logs nothing."""
        studio = self._studio()
        for which, id in (
            (CatalogList.KILNS, f.kiln),
            (CatalogList.GLAZE_TYPES, f.glaze_type),
            (CatalogList.CLAY_BODIES, f.clay_body),
        ):
            if id is not None:
                studio.item(which, id)
        today = self._clock.now().astimezone(STUDIO_TZ).date()
        span = log_range(start, end, today, NOTES_DEFAULT_RANGE)
        start, end, read_end = span.start, span.end, span.read_end
        notes = [
            note
            for note in self._records.notes_written_between(
                _austin_midnight(start), _austin_midnight(read_end)
            )
            if matches(note, f)
        ]
        loads = self._loads(notes, start, read_end)
        rows = tuple(
            _row(studio, note, load)
            for note in notes
            if (load := loads.get(note.load_id)) is not None and load.status is not LoadStatus.DELETED
        )
        return NoteSearchView(rows=rows, filter=f, start=start, end=end)

    def _loads(self, notes: list[FiringNote], start: date, read_end: date) -> dict[LoadId, Load]:
        """The loads the notes are on, by ID: those dated around the range from one read,
        any other by its own read (a deleted load among them, for the caller to leave out)."""
        if not notes:
            return {}
        dated = self._records.loads_dated_between(
            LIVE_STATUSES, _shifted(start, -NOTE_LOAD_SLACK), _shifted(read_end, NOTE_LOAD_SLACK)
        )
        loads = {load.id: load for load in dated}
        for id in dict.fromkeys(note.load_id for note in notes):
            if id not in loads and (load := self._records.load(id)) is not None:
                loads[id] = load
        return loads


@dataclass(frozen=True, slots=True)
class NoteCount:
    total: int
    not_allowed: int


class NoteCounts:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, loads: Collection[Load]) -> Mapping[LoadId, NoteCount]:
        """For the firing log (phase 9): how many notes each of `loads` has, removed ones
        left out, and how many of them are "not allowed" rulings. Every load asked about
        is in the answer, with zeros when it has none. One `notes_written_between` read,
        from `NOTE_LOAD_SLACK` before the earliest of the loads was started (no note is
        written on a load before it is started; the slack covers a started time corrected
        later) up to the clock's now, so a note or a ruling added long after a firing is
        still counted. A read: logs nothing."""
        wanted = {load.id: load for load in loads}
        if not wanted:
            return MappingProxyType({})
        earliest = min(load.started_at for load in wanted.values())
        try:
            read_start = earliest - NOTE_LOAD_SLACK
        except OverflowError:
            read_start = _EARLIEST
        read_end = self._clock.now() + _TICK
        notes = [
            note
            for note in self._records.notes_written_between(read_start, read_end)
            if note.load_id in wanted
        ]
        totals = Counter(note.load_id for note in notes)
        refused = Counter(note.load_id for note in notes if note.ruling is Ruling.NOT_ALLOWED)
        return MappingProxyType({id: NoteCount(totals[id], refused[id]) for id in wanted})
