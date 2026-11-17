---
phase_id: 5
title: "Use cases: test loads, history, the firing record, corrections, the firing log"
epic: 1
implements: [42]
depends_on: [4]
domain: [app]
estimated_size: L
---

# Phase 5: Use cases: test loads, history, the firing record, corrections, the firing log

> **Status:** [~] In progress

## Required reading

- [README](README.md); phases [1](phase-1-load-record-and-steps.md),
  [2](phase-2-studio-cones-clays-programs-counts.md) and
  [4](phase-4-records-events-notes-ranges.md)'s hand-offs.
- `src/asmbly_ceramics/use_cases/loads.py` and `tests/use_cases/test_loads.py`: every
  load use case gains its history line here. Keep its read, domain call, version check,
  one commit shape.
- `src/asmbly_ceramics/use_cases/settings.py`, `ViewStudio` and `HISTORY_PAGE`: the
  settings history this mirrors.
- `src/asmbly_ceramics/use_cases/log.py`: `log_event`.
- `tests/use_cases/test_no_personal_details_logged.py`: extend it to the new use cases.
- Story #42, all of it.

## Goal

Every change to a load writes one history line in its commit. Staff can save a load's
firing record, correct a step's time, and start a test load. `ViewLoad` returns the
steps with who and when, the record, the suggested numbers and the history. A new
`FiringLog` use case returns a kiln's fired loads in a date range as rows, which the
page shows and the CSV downloads (phase 7).

## Files to create

- `src/asmbly_ceramics/use_cases/firing_log.py`: `FiringLog`, `FiringLogRow`,
  `FiringKind`.
- `tests/use_cases/test_firing_log.py`.

## Files to modify

- `src/asmbly_ceramics/use_cases/loads.py`: history lines; `SaveFiringRecord`,
  `CorrectStepTime`; `ViewLoad` additions.
- `src/asmbly_ceramics/domain/limits.py`: `LOG_RANGE_MAX`, `LOG_DEFAULT_RANGE`.
- `src/asmbly_ceramics/domain/errors.py`: `InvalidLogRange`, `TooManyNotesToMove`.
- `src/asmbly_ceramics/domain/firing.py`: `record_values`.
- `src/asmbly_ceramics/composition.py`: wire `SaveFiringRecord`, `CorrectStepTime`,
  `FiringLog`; `ChangeLoad(records, clock, studio)` (it now takes the clock for its
  history line).
- `src/asmbly_ceramics/web/console/services.py`: `ConsoleServices` gains
  `save_firing_record`, `correct_step_time` and `firing_log` (their pages come in phases
  6 and 7, as `set_default_program`'s did), so composition can wire them.
- `tests/web/console/conftest.py`: builds `ConsoleServices` on the fakes; gains the three
  new fields and `ChangeLoad`'s clock.
- `tests/use_cases/test_loads.py`, `tests/use_cases/test_no_personal_details_logged.py`,
  `tests/use_cases/conftest.py` (fixtures for the new use cases), `tests/test_composition.py`.

## Implementation details

### app: history lines in `use_cases/loads.py`

A helper `_event(load, staff, now, what) -> Put` builds `Put(event(load.id,
staff.username, now, what))`. Each use case adds one to its existing commit:

| Use case | `what` |
| --- | --- |
| `StartLoad` | "Started the load" (+ " as a test firing" when `test`) |
| `ChangeLoad` | one line per change, joined with "; ": "Kiln: Athena → Helios", "Firing type: Bisque → Glaze", "Date: Nov 12 → Nov 13", "Marked a test firing" / "No longer a test firing"; no line when nothing changed, and then no commit and no log (today it always commits; after the domain's checks and the version check, an unchanged load is returned as it is) |
| `StartFiring` | "Started firing" |
| `MarkFired` | "Marked fired" (the commit grows to at most 98 changes) |
| `DeleteLoad` | "Deleted the load" |
| `SaveFiringRecord` | `"Firing record: " + "; ".join(record_changes(...))` |
| `CorrectStepTime` | "Corrected when it started firing: Nov 12, 4:10 pm → Nov 12, 3:55 pm" (Austin time, the step's label) |

`AddToLoad` and `RemoveFromLoad` write none (README, Domain model). `StartLoad` and
`MarkFired` now take the clock's time once and use it for the load and its line.

### app: new use cases in `use_cases/loads.py`

```python
class SaveFiringRecord:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...

    def __call__(self, load_id: LoadId, values: Mapping[str, str], version: int, staff: StaffMember) -> Load:
        """The record from the page (`read_firing_record`, passed the studio's active
        cones plus the cone the record's program already names, as `set_default_program`
        does, so a retired cone already on the record still saves but no other retired
        or deleted cone can be picked). Nothing
        changed: no commit, the load returned as it is. `NotFound`, `InvalidRecord`,
        `Conflict`. Log: `firing_record_saved` with load_id, user, and `fields` (the
        changed fields' names only)."""


class CorrectStepTime:
    def __init__(self, records: Records, clock: Clock) -> None: ...

    def __call__(self, load_id: LoadId, step: Step, at: datetime, version: int, staff: StaffMember) -> Load:
        """`correct_step_time`; the old and new times in the history line. `NotFound`,
        `StepNotReached`, `StepTimeInFuture`, `StepTimeOutOfOrder`, `Conflict`. Log:
        `step_time_corrected` with load_id, `kind` (the step's value: `started`,
        `firing` or `fired`; `log.py`'s `LOG_FIELDS` has no `step`), user."""
```

`StartLoad(..., test=)` and `ChangeLoad(..., test=)` already exist from phase 1; their
history lines say so.

### app: `ViewLoad` additions

`LoadView` gains:

```python
steps: tuple[StepView, ...]  # STARTED, FIRING, FIRED in order
history: tuple[LoadEvent, ...]  # oldest first (records.load_events)
suggested: tuple[int | None, int | None]  # (firing #, all time #) for the record form
cones: tuple[CatalogItem, ...]  # the cone list, for the form's select
record_fields: Mapping[str, str]  # the record as the form shows it ("11:38", "8.19", "none")


@dataclass(frozen=True, slots=True)
class StepView:
    step: Step
    label: str  # "Loading", "Firing", "Fired"
    reached: bool
    by: str | None  # None with reached True: "not recorded"
    at: datetime | None
```

- `suggested`: only when the record has no firing number and no all-time number yet;
  from `suggest_numbers(kiln.counts, fired)`, with `fired` the kiln's fired loads from
  `loads_dated_between({FIRED}, since, until)` over `numbers_window` (`since`
  `NUMBERS_DATE_MARGIN` before the counts' Austin day, or `NUMBERS_LOOKBACK` back, to
  `NUMBERS_READ_AHEAD` after the load's `fired_at`, or now while unfired; the window
  `RecordNewElements` uses, phase 4), this load left out. Read only for a loading or firing load, or a fired load with
  no numbers, so a fired load's page reads no more than it needs.
- `cones`: the studio's active cones plus the cone the record's program already names
  (retired or not), in the studio's order: the same set `SaveFiringRecord` accepts.
- `record_fields`: the domain's formatting, so the page and the history line agree (put
  `record_values(record) -> dict[str, str]` in `domain/firing.py` if it isn't there).

### app: `use_cases/firing_log.py`

```python
class FiringKind(StrEnum):
    ALL = "all"
    TESTS = "tests"
    REGULAR = "regular"


@dataclass(frozen=True, slots=True)
class FiringLogRow:
    load: Load
    kiln: str
    firing_type: str
    cone: str | None
    started_by: str
    firing_started_by: str | None
    fired_by: str | None
    notes: int | None  # phase 9 fills it; None until then (the page leaves the column out)


@dataclass(frozen=True, slots=True)
class FiringLogView:
    rows: tuple[FiringLogRow, ...]  # newest fired first
    kiln: ItemId | None
    start: date
    end: date  # inclusive, as the page shows it
    kind: FiringKind
    counts: KilnCounts | None  # for "Firing # counts from …", when one kiln is chosen


class FiringLog:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...

    def __call__(
        self, kiln: ItemId | None, start: date | None, end: date | None, kind: FiringKind
    ) -> FiringLogView:
        """Fired loads dated `start..end` inclusive (defaults: the last 12 weeks to today,
        Austin), of `kiln` (or every kiln), of `kind`. `UnknownItem` for a kiln the studio
        doesn't have. A range longer than LOG_RANGE_MAX (5 years) or ending before it
        starts is `InvalidLogRange`; so is an `end` of `date.max` (the read's half-open
        end is `end + 1 day`). Reads `loads_dated_between` only. A read: logs
        nothing."""
```

`LOG_RANGE_MAX = timedelta(days=5 * 366)` and `LOG_DEFAULT_RANGE = timedelta(weeks=12)`
go in `domain/limits.py`; `InvalidLogRange` in `domain/errors.py` ("Choose a date range
of at most 5 years, ending after it starts.").

### Privacy

The use cases log load IDs (`L-4`) and note IDs (`N-12`) and staff usernames only. An
event's wording (`what`) names loads, studio items, steps, times and record values: a
use case never words one with a person's name, email address or phone number, a
rejection message's text, or a note's text, since the history is kept with the load
after the close (#7) deletes those details.

### app: a kiln change carries the load's notes with it

`FiringNote.kiln` is copied from the load when the note is written (phase 3), and
`ChangeLoad` can move a loading load to another kiln. So when `ChangeLoad` changes the
kiln it reads the load's notes (phase 4's `notes_for`, which leaves removed ones out: a removed note is listed nowhere, so it needs no new kiln) and adds
an `Update` of each, with `kiln` set to the new kiln, to the same commit as the load
and its history line, so the notes search by kiln (phase 8) finds them under the kiln
the load is now in. Chosen over phase 8 reading each note's kiln from its load, which
would read a load for every note a search returns. A loading load holds few notes; the
commit stays within DynamoDB's 100 items per transaction as long as a loading load has
at most 98 notes (the load and its history line are the other two), and `ChangeLoad` refuses a kiln change past that with
`TooManyNotesToMove(load_id, limit)` (`domain/errors.py`, chosen by prep: "Load L-4 has
more than 98 notes, so its kiln can't be changed."), the limit being `MAX_CHANGES - 2`.

## Tests

`tests/use_cases/test_loads.py`:

- One per row of the history table: the line is in the same commit (a commit failure
  writes neither), with the username and the clock's time.
- `test_change_load_without_changes_writes_no_line`.
- `test_change_load_kiln_moves_its_notes` (each of the load's notes that isn't removed
  has the new kiln after the same commit; a removed note keeps its old kiln, as
  `notes_for` leaves it out and it is listed nowhere; another load's notes don't change).
- `test_change_load_kiln_with_too_many_notes_refused` (`TooManyNotesToMove`, nothing
  written); `test_change_load_date_only_reads_no_notes`.
- `test_mark_fired_full_load_commits_98_changes`.
- `test_save_firing_record`; `..._unchanged_no_commit`; `..._invalid_names_fields`;
  `..._conflict`; `..._on_fired_load_keeps_members_and_sends_nothing` (no email `Put`);
  `..._deleted_load_not_found`; `..._retired_cone_already_on_record_saves`.
- `test_correct_step_time_writes_old_and_new`; each refusal.
- `test_view_load_steps_with_who`; `test_view_load_old_load_firing_not_recorded`;
  `test_view_load_history_oldest_first`; `test_view_load_suggested_numbers`;
  `test_view_load_no_suggestion_once_numbered`.

A test that checks the order of a load's history advances the clock between the steps
it takes: `Records.load_events` promises no order for two events at one instant, and the
fake scrambles them.

`tests/use_cases/test_firing_log.py`:

- `test_default_range_last_12_weeks`; `test_one_kiln`; `test_all_kilns`;
  `test_tests_only`; `test_regular_only`; `test_newest_fired_first`;
  `test_unknown_kiln`; `test_range_too_long`; `test_range_backwards`;
  `test_deleted_and_unfired_loads_left_out`.

`tests/use_cases/test_no_personal_details_logged.py`: the new use cases log no value
staff typed in a record (no temperatures, no costs), only field names.

## Acceptance criteria

1. Every change of a load's state is logged with username and time, in the load's
   history, in the same commit (#42 "Who moved the load").
2. Saving the firing record records who and when, never changes drop-offs and never
   queues an email (#42).
3. A step's time correction keeps the original in the history, and the username can't be
   changed (#42).
4. A test can be fired with no drop-offs; marking or unmarking a test (while loading) is
   in the history (#42 "Test firings").
5. The suggested numbers follow phase 2's rule and stop once the record has numbers
   (#42 "Firing number").
6. `FiringLog` lists fired loads by kiln, date range and kind, newest first, reading a
   bounded range (#42 "The firing log").

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] `use_cases/` imports no AWS library and no web framework.

## Rollout

The merge deploys code that writes history lines on every load change. Check: on stage,
start, fire and mark fired a made-up load; its items include `EVENT#` items (seen in phase
6's page, or by the maintainer with a read-only `aws dynamodb query` on that load's
partition, which holds no personal details). Undo: a revert pull request; the lines
already written stay and phase 6 shows them.

## Admin actions

None.

## Hand-off

Status stays `[~] In progress` until the maintainer confirms the rollout check after the
merge (stage: a made-up load started, fired and marked fired has `EVENT#` items in its
partition); a later pull request sets `[x]`.

- [x] Every load use case writes its history line in its commit (`StartLoad` "Started the
      load" / "… as a test firing", `ChangeLoad` one line per change joined with "; ",
      plus "Firing record: …" when a new firing type's default program swapped in,
      `StartFiring` "Started firing", `MarkFired` "Marked fired", `DeleteLoad` "Deleted
      the load"); add and remove write none. `MarkFired` on a full load commits 98.
- [x] `ChangeLoad(records, clock, studio)`: nothing changed means no commit and no log;
      a kiln change `Update`s each of `notes_for(load)` (removed notes keep their kiln)
      in the same commit; more than `NOTES_MOVED_MAX` (98) is `TooManyNotesToMove`.
- [x] `SaveFiringRecord(load_id, values, version, staff)` (cones: active ones plus the
      record's own; nothing changed, no commit; log `firing_record_saved` with `fields`),
      `CorrectStepTime(load_id, step, at, version, staff)` (the same time again, no
      commit; log `step_time_corrected` with `kind`), in `use_cases/loads.py`, wired in
      `composition.py` and `ConsoleServices` (`save_firing_record`, `correct_step_time`).
- [x] `LoadView.steps` (`StepView`: step, label, reached, by, at, can_correct; `by` None with
      `reached` is "not recorded"), `history` (oldest first), `suggested` (only with no
      numbers on the record; a fired load counts only loads fired before it), `cones`
      (`record_cones`), `record_fields` (`domain.firing.record_values`, which reads back
      to the same record). `STEP_LABELS`.
- [x] `FiringLog(kiln, start, end, kind)` → `FiringLogView` (`rows` newest fired first,
      `FiringLogRow.notes` None for phase 9), `FiringKind`, in `use_cases/firing_log.py`,
      wired as `ConsoleServices.firing_log`; `InvalidLogRange`, `LOG_RANGE_MAX`,
      `LOG_DEFAULT_RANGE`.
- `domain.load.numbers_window(counts, at)` (was `numbers_read_from`, made bounded after
  the review: `NUMBERS_LOOKBACK` back at most, `NUMBERS_READ_AHEAD` ahead) is the
  numbering window `ViewLoad` and `RecordNewElements` share; `domain.firing.changed_fields` names a save's changed fields.
- For phase 8: a note written between `ChangeLoad`'s `notes_for` read and its commit
  keeps the old kiln (no item in that commit covers it). `WriteNote` could put the load's
  version in its own commit to close the race; it's narrow and staff can edit the note.
- `sam validate` and `sam build` weren't run (no `sam` here; no template change).
