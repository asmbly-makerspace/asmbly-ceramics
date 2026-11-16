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

> **Status:** [ ] Pending

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
- `src/asmbly_ceramics/domain/errors.py`: `InvalidLogRange`.
- `src/asmbly_ceramics/domain/firing.py`: `record_values`.
- `src/asmbly_ceramics/composition.py`: wire `SaveFiringRecord`, `CorrectStepTime`,
  `FiringLog`.
- `tests/use_cases/test_loads.py`, `tests/use_cases/test_no_personal_details_logged.py`,
  `tests/use_cases/conftest.py` (fixtures for the new use cases), `tests/test_composition.py`.

## Implementation details

### app: history lines in `use_cases/loads.py`

A helper `_event(load, staff, now, what) -> Put` builds `Put(event(load.id,
staff.username, now, what))`. Each use case adds one to its existing commit:

| Use case | `what` |
| --- | --- |
| `StartLoad` | "Started the load" (+ " as a test firing" when `test`) |
| `ChangeLoad` | one line per change, joined with "; ": "Kiln: Athena → Helios", "Firing type: Bisque → Glaze", "Date: Nov 12 → Nov 13", "Marked a test firing" / "No longer a test firing"; no line when nothing changed (and no commit then, as now if it already skips) |
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
        """The record from the page (`read_firing_record`, cones from the studio's cones,
        active and retired, so a retired cone already on the record still saves). Nothing
        changed: no commit, the load returned as it is. `NotFound`, `InvalidRecord`,
        `Conflict`. Log: `firing_record_saved` with load_id, user, and `fields` (the
        changed fields' names only)."""

class CorrectStepTime:
    def __init__(self, records: Records, clock: Clock) -> None: ...

    def __call__(self, load_id: LoadId, step: Step, at: datetime, version: int, staff: StaffMember) -> Load:
        """`correct_step_time`; the old and new times in the history line. `NotFound`,
        `StepNotReached`, `StepTimeInFuture`, `StepTimeOutOfOrder`, `Conflict`. Log:
        `step_time_corrected` with load_id, step, user."""
```

`StartLoad(..., test=)` and `ChangeLoad(..., test=)` already exist from phase 1; their
history lines say so.

### app: `ViewLoad` additions

`LoadView` gains:

```python
steps: tuple[StepView, ...]       # STARTED, FIRING, FIRED in order
history: tuple[LoadEvent, ...]    # oldest first (records.load_events)
suggested: tuple[int | None, int | None]  # (firing #, all time #) for the record form
cones: tuple[CatalogItem, ...]    # the cone list, for the form's select
record_fields: Mapping[str, str]  # the record as the form shows it ("11:38", "8.19", "none")

@dataclass(frozen=True, slots=True)
class StepView:
    step: Step
    label: str                     # "Loading", "Firing", "Fired"
    reached: bool
    by: str | None                 # None with reached True: "not recorded"
    at: datetime | None
```

- `suggested`: only when the record has no firing number and no all-time number yet;
  from `suggest_numbers(kiln.counts, fired)`, with `fired` the kiln's fired loads from
  `loads_dated_between({FIRED}, since, tomorrow)` (`since` the counts' date, or 400 days
  back), this load left out. Read only for a loading or firing load, or a fired load with
  no numbers, so a fired load's page reads no more than it needs.
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
    notes: int | None    # phase 9 fills it; None until then (the page leaves the column out)

@dataclass(frozen=True, slots=True)
class FiringLogView:
    rows: tuple[FiringLogRow, ...]   # newest fired first
    kiln: ItemId | None
    start: date
    end: date                        # inclusive, as the page shows it
    kind: FiringKind
    counts: KilnCounts | None        # for "Firing # counts from …", when one kiln is chosen

class FiringLog:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...

    def __call__(self, kiln: ItemId | None, start: date | None, end: date | None, kind: FiringKind) -> FiringLogView:
        """Fired loads dated `start..end` inclusive (defaults: the last 12 weeks to today,
        Austin), of `kiln` (or every kiln), of `kind`. `UnknownItem` for a kiln the studio
        doesn't have. A range longer than LOG_RANGE_MAX (5 years) or ending before it
        starts is `InvalidLogRange`. Reads `loads_dated_between` only. A read: logs
        nothing."""
```

`LOG_RANGE_MAX = timedelta(days=5 * 366)` and `LOG_DEFAULT_RANGE = timedelta(weeks=12)`
go in `domain/limits.py`; `InvalidLogRange` in `domain/errors.py` ("Choose a date range
of at most 5 years, ending after it starts.").

## Tests

`tests/use_cases/test_loads.py`:

- One per row of the history table: the line is in the same commit (a commit failure
  writes neither), with the username and the clock's time.
- `test_change_load_without_changes_writes_no_line`.
- `test_mark_fired_full_load_commits_98_changes`.
- `test_save_firing_record`; `..._unchanged_no_commit`; `..._invalid_names_fields`;
  `..._conflict`; `..._on_fired_load_keeps_members_and_sends_nothing` (no email `Put`);
  `..._deleted_load_not_found`; `..._retired_cone_already_on_record_saves`.
- `test_correct_step_time_writes_old_and_new`; each refusal.
- `test_view_load_steps_with_who`; `test_view_load_old_load_firing_not_recorded`;
  `test_view_load_history_oldest_first`; `test_view_load_suggested_numbers`;
  `test_view_load_no_suggestion_once_numbered`.

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

- [ ] Every load use case writes its history line; `MarkFired` is ≤ 98 changes.
- [ ] `SaveFiringRecord(load_id, values, version, staff)`,
      `CorrectStepTime(load_id, step, at, version, staff)`, wired.
- [ ] `LoadView.steps`, `history`, `suggested`, `cones`, `record_fields`; `StepView`.
- [ ] `FiringLog(kiln, start, end, kind)` → `FiringLogView`; `FiringKind`;
      `InvalidLogRange`; `LOG_RANGE_MAX`, `LOG_DEFAULT_RANGE`.
