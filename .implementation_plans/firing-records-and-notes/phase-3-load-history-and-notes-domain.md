---
phase_id: 3
title: "The domain: a load's history and firing notes"
epic: 1
implements: [42, 17]
depends_on: [2]
domain: [app]
estimated_size: M
---

# Phase 3: The domain: a load's history and firing notes

> **Status:** [ ] Pending

## Required reading

- [README](README.md), its Domain model.
- [Phase 2](phase-2-studio-cones-clays-programs-counts.md)'s hand-off: the clay body
  list.
- `src/asmbly_ceramics/domain/studio.py`, `SettingChange`: `LoadEvent` is its twin.
- `src/asmbly_ceramics/domain/ids.py`: `LoadId`'s parse and format (`L-4`); `NoteId`
  follows it (`N-12`).
- `src/asmbly_ceramics/domain/dropoff.py`, the contact checks: how text a person types
  is checked for control characters and length.
- `src/asmbly_ceramics/domain/load.py`, `delete_load` and `LIVE_STATUSES`: a note's soft
  delete follows a load's.
- Story #17's criteria; #42's "in the load's history".

## Goal

The domain has a load's history line (`LoadEvent`) and a firing note (`FiringNote`) with
its ruling, its tags and its checks, as plain Python with tests and no storage. Phase 4
stores them; phases 5 and 8 write them.

## Files to create

- `src/asmbly_ceramics/domain/history.py`: `LoadEvent`.
- `src/asmbly_ceramics/domain/notes.py`: `Ruling`, `FiringNote`, `write_note`,
  `edit_note`, `remove_note`, `check_note_text`, `matches`.
- `tests/domain/test_history.py`, `tests/domain/test_notes.py`.

## Files to modify

- `src/asmbly_ceramics/domain/ids.py`: `NoteId`.
- `src/asmbly_ceramics/domain/errors.py`: `InvalidNote`, `LoadNotNotable`.
- `src/asmbly_ceramics/domain/limits.py`: `NOTE_TEXT_MAX = 2000`, `NOTE_TAGS_MAX = 20`.
- `tests/domain/builders.py`: `a_note(...)`, `an_event(...)`.
- `tests/domain/test_ids.py`: `NoteId`.

## Implementation details

### app: `domain/history.py`

```python
@dataclass(frozen=True, slots=True)
class LoadEvent:
    """One line of a load's history: who did what, and when. `what` names load IDs,
    studio items, steps, times and record values; never a person's details (it is shown
    to staff and kept with the load)."""
    load_id: LoadId
    at: datetime     # aware
    by: str          # staff username
    what: str        # "Started firing", "Fired", "Max temp: 2,236 °F", ...

def event(load_id: LoadId, by: str, at: datetime, what: str) -> LoadEvent:
    """`ValueError` for an empty `by` or `what`, or a naive `at`."""
```

The wording of each event is decided by the use case that writes it (phase 5); the domain
only builds and checks.

### app: `domain/ids.py`

`NoteId`, formatted `N-12`, parsed like `LoadId` (`N-` then a number, no leading zero, at
most 12 digits, nothing around it). `IdNumbers.next_note_id` comes in phase 4.

### app: `domain/notes.py`

```python
class Ruling(StrEnum):
    ALLOWED = "allowed"
    ALLOWED_WITH_CONDITIONS = "allowed_with_conditions"
    NOT_ALLOWED = "not_allowed"

@dataclass(frozen=True, slots=True)
class FiringNote:
    id: NoteId
    load_id: LoadId
    kiln: ItemId                    # the load's kiln when written, for the search
    text: str
    glaze_types: tuple[ItemId, ...]
    clay_bodies: tuple[ItemId, ...]
    ruling: Ruling | None
    written_by: str
    written_at: datetime
    edited_by: str | None = None
    edited_at: datetime | None = None
    removed_by: str | None = None
    removed_at: datetime | None = None
    version: int = 0

    @property
    def removed(self) -> bool: ...

def check_note_text(text: str) -> str:
    """The text to store: CRLF to LF, stripped, NFC. `InvalidNote("text", message)` when
    empty ("Write the note."), longer than NOTE_TEXT_MAX, holding a control character but
    newline or tab ("Write the note as plain text."), or holding something shaped like an
    email address (`\\S+@\\S+\\.\\S+`) or a phone number (10 or more digits, allowing
    spaces, dots, dashes, parentheses and a leading +, between them): "Notes can't hold
    an email address or phone number." The message never quotes the text."""

def write_note(
    id: NoteId, load: Load, text: str, glaze_types: Sequence[ItemId], clay_bodies: Sequence[ItemId],
    ruling: Ruling | None, by: str, at: datetime, studio: Studio,
) -> FiringNote:
    """A new note on `load`. `LoadNotNotable(load.id)` for a deleted load. Each tag must
    be an active item of its list (`UnknownItem`, `ItemRetired`), each list without
    repeats and at most NOTE_TAGS_MAX (`InvalidNote`). Text by `check_note_text`."""

def edit_note(
    note: FiringNote, text: str, glaze_types: Sequence[ItemId], clay_bodies: Sequence[ItemId],
    ruling: Ruling | None, by: str, at: datetime, studio: Studio,
) -> FiringNote:
    """Text, tags and ruling replaced, stamped `edited_by`/`edited_at`; `written_*` kept.
    A tag already on the note may be retired since; a new one must be active.
    `NotFound(note.id)` for a removed note."""

def remove_note(note: FiringNote, by: str, at: datetime) -> FiringNote:
    """Stamped removed; listed nowhere again. `NotFound` if removed already."""

@dataclass(frozen=True, slots=True)
class NoteFilter:
    kiln: ItemId | None = None
    glaze_type: ItemId | None = None
    clay_body: ItemId | None = None
    ruling: Ruling | None | Literal["any"] = "any"   # None means "no ruling"

def matches(note: FiringNote, f: NoteFilter) -> bool:
    """Not removed, and every set part of the filter holds. The date range is the
    store's (phase 4 reads by `written_at`)."""
```

### app: `domain/errors.py`

- `InvalidNote(errors: FieldErrors)`: "Check the note." with a message per field.
- `LoadNotNotable(load_id)`: "L-4 was deleted: it takes no notes."

`NotFound` already takes an ID; it gains `NoteId` in its accepted types.

## Tests

`tests/domain/test_history.py`: `test_event_needs_by_and_what`;
`test_event_needs_aware_time`.

`tests/domain/test_notes.py`:

- `test_write_note_on_loading_firing_and_fired_loads`; `test_no_note_on_deleted_load`.
- `test_text_required`; `test_text_max_length`; `test_text_crlf_to_lf`;
  `test_text_control_characters_refused`; `test_text_with_email_refused`;
  `test_text_with_phone_refused` (several formats: `512 555 0100`, `(512) 555-0100`,
  `+1.512.555.0100`, built in code); `test_text_with_cone_and_temperature_numbers_kept`
  (`^6 at 2,236 °F for 7 min` is fine); `test_messages_never_quote_text`.
- `test_tags_must_be_active_items`; `test_repeated_tag_refused`; `test_too_many_tags`.
- `test_edit_note_keeps_written_and_stamps_edited`; `test_edit_keeps_retired_tag`;
  `test_edit_removed_not_found`.
- `test_remove_note`; `test_remove_twice_not_found`.
- `test_matches_each_filter_part`; `test_matches_no_ruling`; `test_removed_never_matches`.

`tests/domain/test_ids.py`: `test_note_id_round_trip`; `test_note_id_refuses_other_shapes`.

## Acceptance criteria

1. A note can be written on any load but a deleted one, at any stage (#17 "at any stage,
   including after it is fired").
2. A note's tags come from the studio's glaze type and clay body lists (#17).
3. A note has one ruling of three, or none (#17).
4. A note records who wrote it and when; an edit and a removal record who and when
   (#17).
5. The text is checked for length and plain text, and refused when it holds an email
   address or a phone number (#17 "Notes hold no name, email, phone number or photo").
6. No message quotes a note's text.

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] `tests/domain/test_imports.py` passes for the two new modules.

## Rollout

Nothing reaches AWS.

## Admin actions

None.

## Hand-off

- [ ] `domain/history.py`: `LoadEvent`, `event(load_id, by, at, what)`.
- [ ] `domain/ids.py`: `NoteId`.
- [ ] `domain/notes.py`: `Ruling`, `FiringNote`, `check_note_text`, `write_note`,
      `edit_note`, `remove_note`, `NoteFilter`, `matches`.
- [ ] Errors `InvalidNote`, `LoadNotNotable`; `NotFound` takes a `NoteId`.
