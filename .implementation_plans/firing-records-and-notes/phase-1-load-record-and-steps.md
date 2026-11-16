---
phase_id: 1
title: "The load: test firings, who moved it, the firing record"
epic: 1
implements: [42]
depends_on: []
domain: [app]
estimated_size: L
---

# Phase 1: The load: test firings, who moved it, the firing record

> **Status:** [ ] Pending

## Required reading

- [README](README.md), its Domain model.
- `CLAUDE.md`, "The shape of the code" and "Rules".
- `src/asmbly_ceramics/domain/load.py` and `tests/domain/test_load.py`: the load's states
  and rules this phase extends. Copy their style: frozen dataclasses, `replace`, one
  `DomainError` per refusal.
- `src/asmbly_ceramics/domain/studio.py`, `change_email_settings` and `_pickup_window`:
  the pattern for checking text a page sends (length first, then a whole-number regex,
  then the range) and raising `InvalidSetting(field, message)`.
- `src/asmbly_ceramics/use_cases/loads.py`, `StartFiring` and `MarkFired`: their calls to
  `start_firing` and `fire` change signature here.
- `src/asmbly_ceramics/adapters/aws/keys.py`, the `Load()` cases of `_attributes` and of
  the item-to-entity conversion: the new fields are stored here, so nothing is lost.
- Story #42's criteria, "Who moved the load", "Test firings" and "The firing record".

## Goal

A load knows whether it is a test, who started its firing and when, and who marked it
fired. It carries an optional firing record whose every field is checked by the domain.
A test load can be fired with no drop-offs. A reached step's time can be corrected,
in order and not in the future. The DynamoDB item stores all of it, and old items read
with the defaults. The use cases pass the username and time to the new signatures; the
pages are unchanged (phase 6 shows it).

## Files to create

- `src/asmbly_ceramics/domain/firing.py`: `Speed`, `NoCone`, `Program`, `FiringRecord`,
  `EMPTY_RECORD`, `read_firing_record`, `record_changes`.
- `tests/domain/test_firing.py`: the record's checks.

## Files to modify

- `src/asmbly_ceramics/domain/load.py`: the new fields and rules below.
- `src/asmbly_ceramics/domain/errors.py`: `InvalidRecord`, `StepNotReached`,
  `StepTimeOutOfOrder`, `StepTimeInFuture`.
- `src/asmbly_ceramics/domain/limits.py`: the record's limits.
- `src/asmbly_ceramics/use_cases/loads.py`: `StartLoad` takes `test`, `ChangeLoad` takes
  `test`, `StartFiring` and `MarkFired` pass `staff.username` and the clock's time.
- `src/asmbly_ceramics/composition.py`: give `StartFiring` the clock.
- `src/asmbly_ceramics/web/console/loads.py`: pass `test=False` for now where it calls
  `StartLoad` and `ChangeLoad`, so the pages behave as before until phase 6.
- `src/asmbly_ceramics/adapters/aws/keys.py`: store and read the new load fields.
- `tests/domain/builders.py`: `a_load(...)` takes `test`, `record`, and the step stamps.
- `tests/domain/test_load.py`, `tests/use_cases/test_loads.py`,
  `tests/adapters/aws/test_keys.py`: the new cases below.

## Implementation details

### app: `domain/limits.py`

```python
PERCENT_MIN, PERCENT_MAX = 0, 100          # % full and each witness cone
TEMP_F_MIN, TEMP_F_MAX = 0, 2500           # max temperature
BOARD_TEMP_F_MIN, BOARD_TEMP_F_MAX = 0, 400
COST_CENTS_MAX = 10_000                    # $100.00
PREHEAT_HOURS_MAX = 48                     # whole hours
HOLD_MINUTES_MAX = 600
FIRING_MINUTES_MAX = 72 * 60               # "72:00"
FIRING_NUMBER_MIN, FIRING_NUMBER_MAX = 1, 100_000
```

These are checks the story states, not settings.

### app: `domain/firing.py`

```python
class Speed(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"

class NoCone(StrEnum):
    NO_CONE = "none"   # "no cone at this spot", not "not recorded" (that is None)

ConeReading = int | NoCone   # a % bent, 0 to 100, or NO_CONE

@dataclass(frozen=True, slots=True)
class Program:
    preheat_hours: int | None = None
    cone: ItemId | None = None          # a CatalogList.CONES item (phase 2 adds the list)
    speed: Speed | None = None
    hold_minutes: int | None = None

@dataclass(frozen=True, slots=True)
class FiringRecord:
    percent_full: int | None = None
    firing_number: int | None = None    # since the kiln's last elements
    all_time_number: int | None = None
    program: Program = Program()
    firing_minutes: int | None = None
    max_temp_f: int | None = None
    board_temp_f: int | None = None
    cost_cents: int | None = None
    cone_top: ConeReading | None = None
    cone_center: ConeReading | None = None
    cone_bottom: ConeReading | None = None

EMPTY_RECORD = FiringRecord()

RECORD_FIELDS: tuple[str, ...]  # the form's field names, in the order the page shows them:
# percent_full, firing_number, all_time_number, preheat_hours, cone, speed, hold_minutes,
# firing_time, max_temp_f, board_temp_f, cost, cone_top, cone_center, cone_bottom

def read_firing_record(values: Mapping[str, str], cones: Collection[ItemId]) -> FiringRecord:
    """The record the page sent. Every field is optional: a missing or blank one is None.

    Each is stripped and checked, length first (so `int()` never sees thousands of digits):
    - whole numbers in range for percent_full, the two numbers, preheat_hours,
      hold_minutes, max_temp_f, board_temp_f (limits above);
    - firing_time as `H:MM` or `HH:MM` (minutes 00 to 59), at most FIRING_MINUTES_MAX;
    - cost as dollars, `8`, `8.1` or `8.19`, at most COST_CENTS_MAX cents, stored as cents;
    - cone, an ID in `cones` (phase 2 passes the active and retired cones; until then
      the caller passes ()), and speed, a `Speed` value;
    - cone_top, cone_center, cone_bottom: a whole % in range, or `none` for NO_CONE.

    Raises `InvalidRecord(errors)` naming every refused field with its message, so the
    page shows them all at once; never quotes the value sent."""

def record_changes(old: FiringRecord, new: FiringRecord, cone_name: Callable[[ItemId], str]) -> tuple[str, ...]:
    """One line per changed field, with its new value as the page shows it ("Max temp:
    2,236 °F", "Cost: $8.19", "Bottom cone: no cone", "Firing time: cleared"). Phase 5
    writes them into the load's history. Empty when nothing changed."""
```

### app: `domain/load.py`

New fields on `Load`, all with defaults so old items and existing callers still build:

```python
test: bool = False
firing_started_by: str | None = None     # staff username
firing_started_at: dt.datetime | None = None
fired_by: str | None = None              # staff username
record: FiringRecord = EMPTY_RECORD
```

`fired_at` already exists. `version` stays the last field.

```python
class Step(StrEnum):
    STARTED = "started"
    FIRING = "firing"
    FIRED = "fired"

def start_load(id, kiln, firing_type, on, by, at, studio, *, test: bool = False) -> Load:
    """As before, with `test` stored."""

def change_load(load, kiln, firing_type, on, studio, *, test: bool) -> Load:
    """As before; `test` changes only while loading (require_loading already ensures it),
    so a load can't become a test once it is firing."""

def start_firing(load: Load, by: str, at: dt.datetime) -> Load:
    """Loading to firing, stamping `firing_started_by` and `firing_started_at`. An empty
    load is refused with `EmptyLoad` unless it is a test."""

def can_start_firing(load: Load) -> bool:
    """Loading, and holding a drop-off or a test."""

def fire(load: Load, members: Sequence[DropOff], by: str, at: dt.datetime) -> FireResult:
    """As before, stamping `fired_by` too. An empty test load fires with no drop-offs and
    no emails."""

def set_firing_record(load: Load, record: FiringRecord) -> Load:
    """The record replaced, on a loading, firing or fired load; members untouched.
    `NotFound` on a deleted load."""

def step_time(load: Load, step: Step) -> dt.datetime | None:
    """started_at, firing_started_at or fired_at."""

def correct_step_time(load: Load, step: Step, at: dt.datetime, now: dt.datetime) -> Load:
    """A reached step's time corrected.

    `StepNotReached(load.id, step)` for a step the load hasn't reached; for FIRING on a
    fired load made before this phase (no firing_started_at) too, so a time is never
    invented for an unknown step. `StepTimeInFuture(load.id)` when `at > now`.
    `StepTimeOutOfOrder(load.id, step)` unless started_at ≤ firing_started_at ≤ fired_at
    holds afterwards, for the steps that have a time. `NotFound` on a deleted load. The
    `*_by` fields never change."""
```

`delete_load` is unchanged. `_check_aware` covers every new time.

### app: `domain/errors.py`

Each message names only the load and the field or step, never a value staff typed:

- `InvalidRecord(errors: FieldErrors)`: "Check the firing record: N fields need fixing."
  `errors` maps field names to messages such as "Enter a whole number from 0 to 100." or
  "Enter the firing time as hours and minutes, like 11:38." (the page shows each one by
  its field).
- `StepNotReached(load_id, step)`: "L-4 hasn't reached firing yet."
- `StepTimeOutOfOrder(load_id, step)`: "L-4 can't have started firing before it was
  started, or have been fired before it started firing."
- `StepTimeInFuture(load_id)`: "That time is in the future."

### app: `use_cases/loads.py`

- `StartLoad.__call__(kiln, firing_type, on, staff, *, test: bool = False)`.
- `ChangeLoad.__call__(load_id, kiln, firing_type, on, version, staff, *, test: bool)`.
- `StartFiring` takes a `Clock` (wire it in `composition.py`) and calls
  `start_firing(load, staff.username, self._clock.now())`.
- `MarkFired` calls `fire(load, members, staff.username, now)`.
- Logs unchanged, plus `test=True` on `load_started` for a test.

No other use case changes. Phase 5 adds the history, the record and the corrections.

### app: `adapters/aws/keys.py`

The load's item gains `test` (a boolean, stored only when true), `firing_started_by`,
`firing_started_at`, `fired_by`, and `record` (a map of the fields that are set; an empty
record stores no `record` attribute). Reading an item without them gives the defaults.
Times use `iso` and `parse_iso`; a cone reading is a number or the string `none`; cost is
a number of cents. A `record` map with an unknown key or a value of the wrong type is a
`ValueError` naming the load's ID only, like the other conversions.

The program's cone is also a top-level `program_cone` string when set, for phase 2's
`is_item_used` filter.

## Tests

`tests/domain/test_firing.py`:

- `test_blank_form_is_an_empty_record`: every field blank or missing gives `EMPTY_RECORD`.
- `test_reads_a_full_record`: the design's values (85, 98, 252, 0, ^6, medium, 7,
  `11:38`, 2236, 156, `8.19`, 100, 100, `none`) give the expected record, cost in cents.
- `test_refuses_out_of_range_numbers`: -1, 101 for percent; 2501 °F; 401 board; 100.01
  cost; 49 preheat; 601 hold; `72:01`; 0 and 100001 firing numbers: each named in
  `InvalidRecord.errors`.
- `test_refuses_non_numbers`: `abc`, `1.5` for a whole number, `11:60`, `8.199`, a
  5,000-digit string (refused before `int()`).
- `test_reports_every_refused_field_at_once`.
- `test_unknown_cone_and_speed_refused`.
- `test_error_messages_never_quote_the_value`.
- `test_record_changes_lists_each_changed_field`, `..._cleared_field`,
  `..._nothing_changed_is_empty`.

`tests/domain/test_load.py`:

- `test_start_load_stores_test`.
- `test_change_load_changes_test_while_loading`; `..._refused_once_firing`
  (`LoadNotLoading`).
- `test_empty_regular_load_cannot_start_firing` (`EmptyLoad`);
  `test_empty_test_load_starts_firing`; `test_can_start_firing_for_empty_test`.
- `test_start_firing_stamps_who_and_when`.
- `test_fire_stamps_fired_by`; `test_empty_test_load_fires_with_no_emails`;
  `test_test_load_with_drop_offs_fires_them_and_queues_their_emails`.
- `test_set_firing_record_on_loading_firing_and_fired`;
  `test_set_firing_record_keeps_members`; `..._deleted_load_not_found`.
- `test_correct_step_time_each_step`; `..._not_reached`; `..._old_fired_load_firing_step_not_reached`;
  `..._in_future`; `..._out_of_order_each_way`; `..._keeps_who`;
  `..._naive_time_refused`.

`tests/use_cases/test_loads.py`:

- `test_start_load_as_test`; `test_start_firing_empty_test_load`;
  `test_start_firing_records_who_and_when`; `test_mark_fired_records_who`.

`tests/adapters/aws/test_keys.py`:

- `test_load_round_trips_with_record_and_stamps`; `test_empty_record_stores_no_record`;
  `test_old_load_item_reads_with_defaults`; `test_bad_record_map_names_only_the_load`;
  `test_program_cone_is_top_level`.

## Acceptance criteria

1. `start_firing` on an empty non-test load raises `EmptyLoad`; on an empty test load it
   returns a firing load stamped with the username and time (#42 "Test firings").
2. `fire` on an empty test load returns no drop-offs and no emails; on a test load with
   drop-offs it fires them and queues one ready email each (#42).
3. `change_load` can change `test` while loading only (#42: "Once the load starts firing,
   it can't be changed").
4. `start_firing` and `fire` record who and when; `started_by` and `started_at` are
   unchanged (#42 "Who moved the load").
5. `correct_step_time` keeps the order, refuses a future time and an unreached step, and
   never changes a username (#42).
6. `read_firing_record` accepts every blank field, checks every set one against the
   limits the story names, and reports every refused field without quoting it (#42).
7. `set_firing_record` changes no member on any live load (#42: "never changes the load's
   drop-offs").
8. A load item without the new attributes reads as before; one with them round-trips.

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`, the floor in `pyproject.toml` holding.
- [ ] `tests/domain/test_imports.py` still passes: `domain/firing.py` imports no AWS
      library and no web framework.
- [ ] No log line or error message holds a value staff typed.
- After the merge, on stage: start a load with a made-up drop-off, start firing, mark it
  fired; the load still opens and its emails are queued as before.

## Rollout

The merge deploys new load attributes (`test`, `firing_started_by`,
`firing_started_at`, `fired_by`) through the normal deploy; nothing else in AWS changes.
Check: the smoke tests pass, and a load fired on stage after the merge opens. Who: the
maintainer, after the deploy. Undo: a revert pull request; the old code ignores the new
attributes.

## Admin actions

None.

## Hand-off

- [ ] `domain/firing.py`: `Speed`, `NoCone`, `ConeReading`, `Program`, `FiringRecord`,
      `EMPTY_RECORD`, `RECORD_FIELDS`, `read_firing_record(values, cones)`,
      `record_changes(old, new, cone_name)`.
- [ ] `domain/load.py`: `Load.test`, `firing_started_by`, `firing_started_at`, `fired_by`,
      `record`; `Step`; `start_firing(load, by, at)`; `fire(load, members, by, at)`;
      `set_firing_record`; `step_time`; `correct_step_time(load, step, at, now)`;
      `can_start_firing` true for an empty test.
- [ ] Errors `InvalidRecord`, `StepNotReached`, `StepTimeOutOfOrder`, `StepTimeInFuture`.
- [ ] `StartLoad(..., test=)`, `ChangeLoad(..., test=)`; `StartFiring` takes a `Clock`.
- [ ] The load item stores all of it, and `program_cone` top-level.
