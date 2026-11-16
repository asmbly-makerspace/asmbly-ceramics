---
phase_id: 8
title: "Use cases: firing notes"
epic: 1
implements: [17]
depends_on: [5]
domain: [app]
estimated_size: M
---

# Phase 8: Use cases: firing notes

> **Status:** [ ] Pending

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

Nothing else. (Wiring is phase 9's, so this phase shares no file with 6 or 7.)

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
        `Put(note)`. `NotFound` (no load, or deleted), `LoadNotNotable`, `InvalidNote`,
        `UnknownItem`, `ItemRetired`. Log: `note_written` with load_id, note_id, user,
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
    def __init__(self, records: Records) -> None: ...

    def __call__(
        self, load_ids: Collection[LoadId], start: datetime, end: datetime
    ) -> Mapping[LoadId, NoteCount]:
        """For the firing log (phase 9): how many notes each load has, and how many are
        "not allowed" rulings, from one `notes_written_between(start, end)` read (the
        log's range, widened by 30 days at the end, since a note can be written after
        its firing)."""


@dataclass(frozen=True, slots=True)
class NoteCount:
    total: int
    not_allowed: int
```

A note on a load that was later deleted: `LoadNotes` isn't reached (the load page is
`NotFound`), and `SearchNotes` leaves it out (it reads the load once per row, or keeps a
set of the deleted loads' IDs from `loads_in({DELETED})`, whichever reads less; say which
in the hand-off).

## Tests

`tests/use_cases/test_notes.py`:

- `test_write_note`; `test_write_on_fired_load`; `test_write_on_deleted_load_not_found`;
  `test_write_invalid_text_spends_no_number`; `test_write_retired_tag_refused`.
- `test_edit_note`; `test_edit_keeps_written_by`; `test_edit_conflict`;
  `test_edit_removed_not_found`; `test_edit_wrong_load_not_found` (a note ID under
  another load).
- `test_remove_note`; `test_remove_conflict`; `test_removed_not_listed_or_found`.
- `test_load_notes_newest_first_with_names`.
- `test_search_default_range`; `test_search_each_filter`; `test_search_no_ruling`;
  `test_search_unknown_item`; `test_search_range_too_long`;
  `test_search_leaves_out_deleted_loads`.
- `test_note_counts`.
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

Nothing reaches AWS: nothing calls these use cases until phase 9.

## Admin actions

None.

## Hand-off

- [ ] `WriteNote`, `EditNote`, `RemoveNote`, `LoadNotes`, `SearchNotes`, `NoteCounts`;
      `NoteInput`, `NoteRow`, `NoteSearchView`, `NoteCount`; not yet wired.
- [ ] How `SearchNotes` leaves out deleted loads' notes.
