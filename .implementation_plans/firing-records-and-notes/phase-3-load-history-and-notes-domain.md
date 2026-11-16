---
phase_id: 3
title: "The domain: a load's history and firing notes"
epic: 1
implements: [42, 17]
depends_on: [2]
domain: [app]
estimated_size: L
---

# Phase 3: The domain: a load's history and firing notes

> **Status:** [x] Complete — 2026-11-16 on branch feat/firing-records-and-notes

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

- `src/asmbly_ceramics/domain/ids.py`: `NoteId`, `is_note_id`.
- `src/asmbly_ceramics/domain/errors.py`: `InvalidNote`, `LoadNotNotable`.
- `src/asmbly_ceramics/domain/limits.py`: `NOTE_TEXT_MAX = 2000`, `NOTE_TAGS_MAX = 20`.
- `tests/domain/builders.py`: `a_note(...)`, `an_event(...)`.
- `tests/domain/test_ids.py`: `NoteId`.
- `tests/domain/test_errors.py`: `InvalidNote`, `LoadNotNotable` and `NotFound(NoteId)` in
  `EXPECTED` (`test_every_domain_error_class_is_checked` fails without them), and
  `InvalidNote`'s read-only, non-empty `errors`.

## Implementation details

### app: `domain/history.py`

```python
@dataclass(frozen=True, slots=True)
class LoadEvent:
    """One line of a load's history: who did what, and when. `what` names load IDs,
    studio items, steps, times and record values; never a person's details (it is shown
    to staff and kept with the load)."""

    load_id: LoadId
    at: datetime  # aware
    by: str  # staff username
    what: str  # "Started firing", "Fired", "Max temp: 2,236 °F", ...


def event(load_id: LoadId, by: str, at: datetime, what: str) -> LoadEvent:
    """`ValueError` for an empty `by` or `what`, or a naive `at`."""
```

The wording of each event is decided by the use case that writes it (phase 5); the domain
only builds and checks.

### app: `domain/ids.py`

`NoteId`, formatted `N-12`, parsed like `LoadId` (`N-` then a number, no leading zero, at
most 12 digits, nothing around it), with `is_note_id(text)` beside `is_load_id`.
`IdNumbers.next_note_id` comes in phase 4.

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
    kiln: ItemId  # the load's kiln when written, for the search
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
    """The text to store: CRLF to LF, stripped, NFC. `InvalidNote({"text": message})` when
    empty ("Write the note."), longer than NOTE_TEXT_MAX, holding a control character but
    newline or tab ("Write the note as plain text."), or holding something shaped like an
    email address (`\\S+@\\S+\\.\\S+`) or a phone number: "Notes can't hold an email
    address or phone number." A phone number is found by its shape, not by counting
    digits, so a note's dates and temperatures, and ramps written with units or commas,
    are kept (a ramp shaped 3-3-4, three numbers of 3, 3 and 4 digits with spaces or slashes between, is refused as a
    phone number: a decision, pinned in `test_ramp_shaped_like_a_phone_number_refused`):
    on a copy of the text made NFKC, with every Unicode decimal digit as its ASCII digit,
    every dash (and the minus sign) as `-` and every space, tab or newline as ` `, it is
    a North American 3-3-4
    number with an optional leading 1 (area code and exchange starting 2 to 9, the area
    code never N00 or N11; leaving out toll-free N00 numbers is intended), one unbroken group of `PHONE_DIGITS_MIN` (10) or more
    digits, or a `+` and that many digits; the groups may be joined by any number of
    spaces, dots, dashes, slashes, colons, underscores and brackets. A clock time (an
    hour of one or two digits, `:`, two-digit minutes, optional seconds) is cut out
    first, so `2026-11-16 10:30` is kept, and `NNNNNNNNNN:N` is still refused.
    The email shape is looked for on the same copy, so a fullwidth or small `@` and a
    fullwidth dot count. Before any check, a line or paragraph separator (Zl, Zp) becomes
    a newline and an invisible character (Cf, Co, Cn, Cs: a zero-width space, soft
    hyphen, word joiner, bidi override) is dropped, as a drop-off's name drops them.
    The length is checked after NFC. The message never quotes the text."""


def write_note(
    id: NoteId,
    load: Load,
    text: str,
    glaze_types: Sequence[ItemId],
    clay_bodies: Sequence[ItemId],
    ruling: Ruling | None,
    by: str,
    at: datetime,
    studio: Studio,
) -> FiringNote:
    """A new note on `load`. `LoadNotNotable(load.id)` for a deleted load. Each tag must
    be an active item of its list (`UnknownItem`, `ItemRetired`: only a tampered form
    sends one), each list without repeats and at most NOTE_TAGS_MAX. The text's, the
    repeats' and the counts' refusals are gathered into one `InvalidNote`, keyed `text`,
    `glaze_types` and `clay_bodies`. Text by `check_note_text`."""


def edit_note(
    note: FiringNote,
    text: str,
    glaze_types: Sequence[ItemId],
    clay_bodies: Sequence[ItemId],
    ruling: Ruling | None,
    by: str,
    at: datetime,
    studio: Studio,
) -> FiringNote:
    """Text, tags and ruling replaced, stamped `edited_by`/`edited_at`; `written_*` kept.
    A tag already on the note may be retired since; a new one must be active.
    `NotFound(note.id)` for a removed note. When text, tags and ruling are all the same
    as the note's, the note is returned unchanged (no stamp)."""


def remove_note(note: FiringNote, by: str, at: datetime) -> FiringNote:
    """Stamped removed; listed nowhere again. `NotFound` if removed already."""


@dataclass(frozen=True, slots=True)
class NoteFilter:
    kiln: ItemId | None = None
    glaze_type: ItemId | None = None
    clay_body: ItemId | None = None
    ruling: Ruling | None | Literal["any"] = "any"  # None means "no ruling"


def matches(note: FiringNote, f: NoteFilter) -> bool:
    """Not removed, and every set part of the filter holds. The date range is the
    store's (phase 4 reads by `written_at`)."""
```

### app: `domain/errors.py`

- `InvalidNote(errors: Mapping[str, str])`: "Check the note." with a message per field,
  as `InvalidRecord`'s: each field's name mapped to fixed text, never the value sent;
  read only, and at least one.
- `LoadNotNotable(load_id)`: "Load L-4 was deleted: it takes no notes."

`NotFound` already takes an ID; it gains `NoteId` in its accepted types ("Note N-12
doesn't exist.").

## Tests

`tests/domain/test_history.py`: `test_event_needs_by_and_what`;
`test_event_needs_aware_time`.

`tests/domain/test_notes.py`:

- `test_write_note_on_loading_firing_and_fired_loads`; `test_no_note_on_deleted_load`.
- `test_text_required`; `test_text_max_length`; `test_text_crlf_to_lf`;
  `test_text_control_characters_refused`; `test_text_with_email_refused`;
  `test_text_with_phone_refused` (ten-digit numbers written with spaces, with an area
  code in parentheses and a dash, and with a leading `+1` and dots, each built in code
  from digits, never a literal in the test file); `test_text_with_cone_and_temperature_numbers_kept`
  (`^6 at 2,236 °F for 7 min` is fine); `test_text_with_date_and_time_kept`
  (`2026-11-16 10:30`); `test_messages_never_quote_text`; `test_errors_gathered_in_one`.
- `test_tags_must_be_active_items`; `test_repeated_tag_refused`; `test_too_many_tags`.
- `test_edit_note_keeps_written_and_stamps_edited`; `test_edit_keeps_retired_tag`;
  `test_edit_removed_not_found`; `test_edit_with_no_change_is_unchanged`.
- `test_remove_note`; `test_remove_twice_not_found`.
- `test_matches_each_filter_part`; `test_matches_no_ruling`; `test_removed_never_matches`.

`tests/domain/test_ids.py`: `test_note_id_round_trip`; `test_note_id_refuses_other_shapes`;
`is_note_id` agrees with `NoteId.parse`.

`tests/domain/test_errors.py`: the three new messages in `EXPECTED`; `InvalidNote` needs
an error and is read only.

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

- [x] `domain/history.py`: `LoadEvent(load_id, at, by, what)`, `event(load_id, by, at, what)`
      (`ValueError` for an empty `by` or `what`, or a naive `at`). The use cases word each
      event.
- [x] `domain/ids.py`: `NoteId` (`N-12`, parsed like `LoadId`) and `is_note_id(text)`.
- [x] `domain/limits.py`: `NOTE_TEXT_MAX = 2000`, `NOTE_TAGS_MAX = 20`.
- [x] `domain/notes.py`: `Ruling`, `FiringNote` (`removed` property), `check_note_text`,
      `write_note`, `edit_note`, `remove_note`, `NoteFilter`, `matches`, and the text
      messages `TEXT_REQUIRED`, `TEXT_PLAIN`, `TEXT_TOO_LONG`, `TEXT_PERSONAL`.
      `InvalidNote.errors` is keyed `text`, `glaze_types` and `clay_bodies`, gathered in
      one refusal; an unknown or retired tag raises `UnknownItem` or `ItemRetired` after
      those. An edit that changes nothing returns the same note, unstamped (phase 8
      writes nothing then); so does one that only reorders the tags. A phone number is
      found by its shape (see `check_note_text`), never by a digit count.
      `FiringNote.text` and `LoadEvent.what` are left out of their `repr`.
- [x] Errors `InvalidNote(errors)`, `LoadNotNotable(load_id)` ("Load L-4 was deleted: it
      takes no notes."); `NotFound` takes a `NoteId` ("Note N-12 doesn't exist.").
- [x] `tests/domain/builders.py`: `an_event(...)`, `a_note(...)`, `TEST_NOTE_TEXT`.
- Deferred to phase 8: refusing an edit or removal of a note whose load was deleted
  afterwards (the domain's `edit_note` takes no load).
