---
phase_id: 8
title: "Use cases: firing notes"
epic: 1
implements: [17]
depends_on: [5]
domain: [app]
estimated_size: L
---

# Phase 8: Use cases: firing notes

> **Status:** [x] Complete — 2026-11-16 on branch feat/firing-records-and-notes

## Required reading

- [README](README.md), its Parallelism (this phase may run beside 6 and 7: it touches
  only the files below).
- Phases [3](phase-3-load-history-and-notes-domain.md),
  [4](phase-4-records-events-notes-ranges.md) and
  [5](phase-5-use-cases-record-and-log.md)'s hand-offs (`InvalidLogRange`,
  `LOG_RANGE_MAX`).
- `src/asmbly_ceramics/use_cases/loads.py`: the read, domain call, version check, one
  commit shape, and `_load` (a deleted load is `NotFound`).
- `tests/use_cases/conftest.py`: the fixtures this phase's tests build their own copies
  of, in their module, so `conftest.py` isn't touched.
- Story #17's criteria.

## Goal

Staff can write, edit and remove a note on a load, list a load's notes, and search all
notes by kiln, glaze type, clay body, ruling and date range. Each change records who and
when. The use cases exist and are tested; phase 9 wires them into `composition.py` and
the pages.

## Files to create

- `src/asmbly_ceramics/use_cases/notes.py`.
- `tests/use_cases/test_notes.py` (its own fixtures: an in-memory `Records`,
  `IdNumbers`, a fixed `Clock`, a `CurrentStudio` from `a_studio()`).

## Files to modify

- `src/asmbly_ceramics/use_cases/log.py`: `note_id` in `_SHAPES` (so in `LOG_FIELDS`).
- `tests/use_cases/test_log.py`: `note_id`'s shape.
- `src/asmbly_ceramics/use_cases/loads.py`: `DeleteLoad` removes the load's notes in its
  commit (the decision point below, decided at prep).
- `src/asmbly_ceramics/domain/errors.py`: `TooManyNotesToMove` takes what can't be done,
  so a delete's refusal reads "can't be deleted", not "its kiln can't be changed".
- `src/asmbly_ceramics/web/console/loads.py`: the delete route shows that refusal on the
  load page (400), as the change route does, instead of a 500.
- `tests/use_cases/test_loads.py`, `tests/domain/test_errors.py`,
  `tests/web/console/test_loads.py`: the above.

Wiring is phase 9's. Phases 6 and 7 are built (their status stays `[~] In progress`
until the maintainer's stage checks), so the console file this phase touches is shared
with no running phase.

Added by the review: `src/asmbly_ceramics/domain/ranges.py` (`log_range`, the one range
rule the firing log and the notes search call) with `tests/domain/test_ranges.py`;
`domain/limits.py` (`NOTES_DEFAULT_RANGE`, `NOTE_LOAD_SLACK`); `use_cases/firing_log.py`
(calls `log_range`); `templates/console/load.html` (the delete confirmation says the
load's notes are removed with it).

## Implementation details

### app: `use_cases/notes.py`

```python
@dataclass(frozen=True, slots=True)
class NoteInput:
    text: str
    glaze_types: tuple[ItemId, ...]
    clay_bodies: tuple[ItemId, ...]
    ruling: Ruling | None


class WriteNote:
    def __init__(self, records: Records, ids: IdNumbers, clock: Clock, studio: CurrentStudio) -> None: ...

    def __call__(self, load_id: LoadId, note: NoteInput, staff: StaffMember) -> FiringNote:
        """A new note on the load: `write_note` is checked before a number is spent, then
        one commit of `Put(note)` and `Update(load)` with the load as it was read, so the
        commit fails with `Conflict` if the load's version moved since: otherwise a
        `ChangeLoad` moving the load to another kiln between the read and the commit
        (phase 5, which rewrites the notes it finds) would leave this note under the old
        kiln. The cost: the load's version goes up by one, so a load page open elsewhere
        gets "changed by someone else" on its next save, and reloads. A `Conflict` here
        is shown as on any other page ("reload and try again"), with no number reused. `NotFound` (no load, or deleted: the domain's
        `LoadNotNotable` is never reached, as the deleted load is `NotFound` first),
        `InvalidNote`, `UnknownItem`, `ItemRetired`. Log: `note_written` with load_id, note_id, user,
        and `outcome` (the ruling's value, or `none`); never the text or the tags' names.
        `note_id` is not in `use_cases/log.py`'s `LOG_FIELDS`: this phase adds it to
        `_SHAPES` with phase 3's `NoteId` parse as its shape (`N-12` only), with a test
        in `tests/use_cases/test_log.py` that `N-12` logs and any other text logs as
        `invalid`. `log_event` raises on an unknown field after the write commits, so
        this lands in the same change as `WriteNote`."""


class EditNote:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...

    def __call__(
        self, load_id: LoadId, note_id: NoteId, note: NoteInput, version: int, staff: StaffMember
    ) -> FiringNote:
        """`edit_note` then `Update(note)` at the version the page showed. `NotFound`
        (no note, removed, or its load deleted), `InvalidNote`, `UnknownItem`,
        `ItemRetired`, `Conflict`. Log: `note_edited`."""


class RemoveNote:
    def __init__(self, records: Records, clock: Clock) -> None: ...

    def __call__(self, load_id: LoadId, note_id: NoteId, version: int, staff: StaffMember) -> None:
        """`remove_note` then `Update`. `NotFound`, `Conflict`. Log: `note_removed`."""


@dataclass(frozen=True, slots=True)
class NoteRow:
    note: FiringNote
    kiln: str
    firing_type: str
    glaze_types: tuple[str, ...]  # names, retired ones included
    clay_bodies: tuple[str, ...]


class LoadNotes:
    def __init__(self, records: Records, studio: CurrentStudio) -> None: ...

    def __call__(self, load_id: LoadId) -> tuple[NoteRow, ...]:
        """The load's notes, newest first. A read: logs nothing."""


@dataclass(frozen=True, slots=True)
class NoteSearchView:
    rows: tuple[NoteRow, ...]
    filter: NoteFilter
    start: date
    end: date  # inclusive


class SearchNotes:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...

    def __call__(self, f: NoteFilter, start: date | None, end: date | None) -> NoteSearchView:
        """Notes written `start..end` inclusive, Austin days (default: the last 365
        days), matching `f`, newest first. `records.notes_written_between` only, then
        `matches`. An unknown kiln, glaze type or clay body is `UnknownItem`; a range over
        `LOG_RANGE_MAX` or backwards is `InvalidLogRange` (phase 5's, reused). A read:
        logs nothing."""


class NoteCounts:
    def __init__(self, records: Records, clock: Clock) -> None: ...

    def __call__(self, loads: Collection[Load]) -> Mapping[LoadId, NoteCount]:
        """For the firing log (phase 9): how many notes each load has, and how many are
        "not allowed" rulings, from one `notes_written_between` read from
        `NOTE_LOAD_SLACK` before the earliest of the loads was started up to the clock's
        now, so a note or ruling added long after a firing is counted."""


@dataclass(frozen=True, slots=True)
class NoteCount:
    total: int
    not_allowed: int
```

A note on a load that was later deleted: `LoadNotes` isn't reached (the load page is
`NotFound`), and `SearchNotes` leaves it out (it reads the load once per row, or keeps a
set of the deleted loads' IDs from `loads_in({DELETED})`, whichever reads less; say which
in the hand-off).

Decision point (decided at prep: `DeleteLoad` removes the notes): a note on a deleted
load must not keep its glaze types and clay bodies "used" forever. Today `is_item_used` counts every note that isn't removed, whatever its
load's status (phase 4), so a deleted load's notes would stop staff from deleting a tag
nobody can see used. Either `DeleteLoad` removes the load's notes in the same commit (an
`Update` of each to removed, which `is_item_used` already leaves out), or `is_item_used`
leaves out notes on deleted loads (the port's docstring, the fake and the adapter
together) and that is said in the port. Pick one, test it, and say which in the
hand-off.

Chosen: `DeleteLoad` reads `notes_for(load)` and commits an `Update` of each to removed
(`remove_note`, by the staff member deleting, at the delete's time) with the load, its
drop-offs and its history line. The DynamoDB adapter already moves a removed note out of
the index partition `is_item_used` and the search read, so no port, fake or adapter
changes, and `is_item_used` needs no extra reads per settings page (#32). The commit holds
at most `MAX_CHANGES`: with 1 + drop-offs + 1 + notes over it, `DeleteLoad` refuses with
`TooManyNotesToMove` ("can't be deleted"); only an unfired load can be deleted, and one
with dozens of notes is not expected. `SearchNotes` still leaves out notes on deleted
loads, for any written before this change: it reads the live loads dated
`NOTE_LOAD_SLACK` around its range in one `loads_dated_between(LIVE_STATUSES, ...)`,
reads any other load a note is on by its ID, and leaves out a note whose load is
deleted or missing.

`NoteCounts` reads from `NOTE_LOAD_SLACK` (30 days, `domain/limits.py`) before the
earliest of its loads was started (no note is written on a load before it is started;
the slack covers a started time corrected later) up to the clock's now: a note or a
"not allowed" ruling can be added to a load long after its firing.

### Privacy

The note use cases log note IDs (`N-12`), load IDs (`L-4`), staff usernames and the
ruling's value only: never a note's text or its tags' names, and no error message that
quotes them (phase 3's messages never do). A note's history line, if one is written,
names the note by its ID and never quotes its text.

## Tests

`tests/use_cases/test_notes.py`:

- `test_write_note`; `test_write_on_fired_load`; `test_write_on_deleted_load_not_found`;
  `test_write_invalid_text_spends_no_number`; `test_write_retired_tag_refused`.
- `test_write_conflicts_when_the_load_moved_kiln` (the load is read in kiln A, a
  `ChangeLoad` to kiln B commits before the note's commit: `WriteNote` raises
  `Conflict` and no note is stored under kiln A); `test_write_bumps_the_load_version`.
- `test_edit_note`; `test_edit_keeps_written_by`; `test_edit_conflict`;
  `test_edit_removed_not_found`; `test_edit_wrong_load_not_found` (a note ID under
  another load).
- `test_remove_note`; `test_remove_conflict`; `test_removed_not_listed_or_found`.
- `test_load_notes_newest_first_with_names`.
- `test_search_default_range`; `test_search_each_filter`; `test_search_no_ruling`;
  `test_search_unknown_item`; `test_search_range_too_long`;
  `test_search_leaves_out_deleted_loads`.
- `test_note_counts`.
- `tests/use_cases/test_loads.py`: `test_delete_load_removes_its_notes` (the notes are
  removed by the deleting staff member, and a tag only they used is no longer
  `is_item_used`); `test_delete_load_with_too_many_notes_is_refused` (nothing written).
- `tests/web/console/test_loads.py`: the delete's refusal shows on the load page, 400.
- `test_logs_hold_no_text` (a note with made-up text: no log line holds any of it).

## Acceptance criteria

1. Staff add a note to a load at any stage, including after it is fired (#17).
2. Tags and a ruling are stored and searchable (#17).
3. Each note records who wrote it and when; an edit or removal records who and when
   (#17).
4. Staff search by kiln, glaze type, clay body, ruling and date, from a bounded read
   (#17).
5. No log holds a note's text (#17, CLAUDE.md).

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov` (the new module is covered by its own tests, so the floor
      holds without wiring).

## Rollout

Nothing reaches AWS: nothing calls the note use cases until phase 9. `DeleteLoad`'s
change is live once merged (the console's delete calls it), as code only: no resource,
right, name or tag changes. Undo: revert.

## Admin actions

None.

## Hand-off

- [x] `use_cases/notes.py`: `WriteNote(records, ids, clock, studio)`,
      `EditNote(records, clock, studio)`, `RemoveNote(records, clock)`,
      `LoadNotes(records, studio)`, `SearchNotes(records, clock, studio)`,
      `NoteCounts(records, clock)`; `NoteInput`, `NoteRow`, `NoteSearchView`,
      `NoteCount`. `NOTES_DEFAULT_RANGE` (365 days) and `NOTE_LOAD_SLACK` (30 days) are
      in `domain/limits.py`, and the range rule both searches share is
      `domain.ranges.log_range`. Not yet wired:
      phase 9 adds them to `composition.py` and `tests/use_cases/conftest.py`
      (`tests/use_cases/test_notes.py` builds them on the `world` fixture's fakes).
- [x] `WriteNote` commits `Put(note)` and `Update(load)` at the version read, so it is
      `Conflict` if the load moved, and the load's version goes up by one: the page
      phase 9 builds re-reads the load after a note is written. `LoadNotes` raises
      `NotFound` for a missing or deleted load. `EditNote` and `RemoveNote` raise
      `Conflict([note id])` at a stale version; an edit that changes nothing commits
      nothing. `RemoveNote` returns `None`.
- [x] Logs: `note_written`, `note_edited` (each with `load_id`, `note_id`, `user`,
      `outcome` = the ruling's value or `none`), `note_removed` (`load_id`, `note_id`,
      `user`). `note_id` is a `LOG_FIELDS` name with `is_note_id` as its shape.
- [x] How `SearchNotes` leaves out deleted loads' notes: it needs each row's load for
      its firing type anyway, so it reads the loads dated `NOTE_LOAD_SLACK` around its
      range in one `loads_dated_between(LIVE_STATUSES, ...)`, reads any other load a
      note is on by its ID, and leaves out a note whose load is deleted or missing. It
      checks the filter's items (`UnknownItem`) before any read, and checks its range
      with `log_range`, as the firing log does (`InvalidLogRange`, `LOG_RANGE_MAX`).
- [x] How a deleted load's notes stop pinning their tags: `DeleteLoad` removes them
      (`remove_note`, by the staff member deleting, at the delete's time) in its commit,
      so `is_item_used` and the search leave them out with no port change. With more
      notes than the commit holds beside the load, its drop-offs and its history line,
      it raises `TooManyNotesToMove(..., deleting=True)` ("so it can't be deleted.
      Remove some of its notes first."), and the console's delete route shows that on
      the load page (400). The delete confirmation says the load's notes are removed
      with it.
- [x] `NoteCounts(loads)` reads `notes_written_between(earliest started_at -
      NOTE_LOAD_SLACK, now)` once (half-open, so its end is just after now) and returns
      a count (zeros included) for every load asked about; the firing log passes its
      rows' loads.
