---
phase_id: 1c
title: "The domain: loads, the waiting list and search"
epic: 1
implements: [3, 4, 7]
depends_on: [1b]
domain: [app]
estimated_size: M
---

# Phase 1c: The domain: loads, the waiting list and search

> **Status:** [ ] Pending

Part of phase 1, split into 1a to 1d by `/prep` (see
[phase 1a](phase-1a-domain-core-and-studio.md)). The conventions in phase 1a's
**app: conventions** apply here unchanged.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the planned shape.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): one
  transaction per change, so a load holds at most 48 drop-offs.
- This plan's [README](README.md#domain-model),
  [phase 1a](phase-1a-domain-core-and-studio.md) and
  [phase 1b](phase-1b-drop-offs-photos-outbox.md): the errors, `Studio`, `DropOff` and
  `Email` this phase uses.
- Stories #3 (the waiting list and search), #4 (loads), #7 (overdue), and epic #1's
  **Decided** list (waiting list oldest first; search by `AC-12`, `ac12`, `12` or any
  part of a name; staff pick a load's firing type by hand).

## Goal

A kiln load and its moves (`loading → firing → fired`), the waiting list's order,
totals and overdue rule, and search exist as plain Python, with every #3, #4 and #7
rule they carry in one place. Tested with no AWS and no fakes.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `domain/load.py` | `Load`, `LoadStatus`, `FireResult`; `start_load`, `change_load`, `add_to_load`, `remove_from_load`, `start_firing`, `fire` |
| `domain/search.py` | `Query`, `parse_query`, `matches` |
| `domain/waiting.py` | `WaitingTotals`, `waiting_order`, `totals`, `is_overdue` |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/domain/test_load.py`, `test_search.py`, `test_waiting.py` | The rules |

## Files to modify

- `tests/domain/builders.py`: add `a_load(number=1, status=LOADING, members=(), ...)`.

## Implementation details

### `domain/load.py`

```python
class LoadStatus(StrEnum):
    LOADING = "loading"
    FIRING = "firing"
    FIRED = "fired"


@dataclass(frozen=True, slots=True)
class Load:
    id: LoadId
    kiln: ItemId
    firing_type: ItemId
    date: date
    status: LoadStatus
    members: tuple[DropOffId, ...]
    started_by: str
    started_at: datetime
    fired_at: datetime | None = None
    version: int = 0


@dataclass(frozen=True, slots=True)
class FireResult:
    load: Load
    drop_offs: tuple[DropOff, ...]
    emails: tuple[Email, ...]


def start_load(
    id: LoadId, kiln: ItemId, firing_type: ItemId, on: date, by: str, at: datetime, studio: Studio
) -> Load: ...
def change_load(load: Load, kiln: ItemId, firing_type: ItemId, on: date, studio: Studio) -> Load: ...
def add_to_load(load: Load, drop_off: DropOff, *, confirmed: bool) -> tuple[Load, DropOff]: ...
def remove_from_load(load: Load, drop_off: DropOff) -> tuple[Load, DropOff]: ...
def start_firing(load: Load) -> Load: ...
def fire(load: Load, members: Sequence[DropOff], at: datetime) -> FireResult: ...
```

- `start_load`, `change_load` (#4): kiln and firing type must be active items
  (`studio.active_item`: `UnknownItem`, `ItemRetired`); `change_load` only while
  `LOADING` (`LoadNotLoading`). Changing the firing type leaves members already in the
  load as they are (they were confirmed when added).
- `add_to_load`: `LoadNotLoading` unless `LOADING`; `AlreadyInLoad` when the drop-off
  is `IN_LOAD` (naming both IDs: its load and this one); `NotWaiting` for any other
  state (naming it); `LoadFull` at `LOAD_CAPACITY`; `FiringTypeMismatch` when the firing
  types differ and `confirmed` is false. Returns the load with the ID appended and the
  drop-off `IN_LOAD` with `load_id`.
- `remove_from_load`: `LoadNotLoading`; `NotInLoad` unless the drop-off is `IN_LOAD`
  with this `load_id` and in `members`; the drop-off goes back to `WAITING`,
  `load_id=None`.
- `start_firing`: `WrongLoadStatus` unless `LOADING`; `EmptyLoad` with no members.
- `fire`: `AlreadyFired` when `FIRED` (nothing else happens: firing again sends
  nothing); `WrongLoadStatus` when `LOADING`; `members` must be exactly the load's
  members, each `IN_LOAD` in this load (else `ValueError`: a bug, not a refusal).
  Returns the load `FIRED` with `fired_at`, each drop-off `FIRED` with `fired_at`, and
  one `new_email(id, READY, at)` each. The use case commits all of it at once.

### `domain/search.py` (#3)

```python
@dataclass(frozen=True, slots=True)
class Query:
    number: int | None  # from "AC-12", "ac12", "ac 12", "12"
    text: str  # casefolded, stripped; "" when the query is a number


def parse_query(raw: str) -> Query: ...
def matches(drop_off: DropOff, query: Query) -> bool: ...  # by number, or the name contains the text
```

A query of more than 100 characters is cut to 100 before parsing. A number is
`(ac)?[ -]?[0-9]+` after stripping and casefolding, ASCII digits only. A closed
drop-off has no name and matches by number only. An empty query matches nothing.

### `domain/waiting.py` (#3, #7)

```python
@dataclass(frozen=True, slots=True)
class WaitingTotals:
    drop_offs: Mapping[ItemId, int]  # per firing type
    pieces: Mapping[ItemId, int]  # per firing type
    pieces_by_glaze: Mapping[ItemId, int]  # per glaze type
    overdue: int


def waiting_order(
    drop_offs: Iterable[DropOff],
) -> list[DropOff]: ...  # WAITING only, oldest created_at first, then by ID
def totals(drop_offs: Iterable[DropOff], now: datetime) -> WaitingTotals: ...  # WAITING only
def is_overdue(drop_off: DropOff, now: datetime) -> bool: ...  # WAITING and now - created_at >= OVERDUE_AFTER
```

## Tests

`tests/domain/` (no fakes, no AWS):

- `test_start_load_refuses_a_retired_kiln_or_firing_type`; `test_change_load_only_while_loading`.
- `test_add_to_load_moves_a_waiting_drop_off_in`;
  `test_add_refuses_a_drop_off_in_another_load_naming_it` (the message names both IDs);
  `test_add_refuses_fired_rejected_and_closed`;
  `test_add_with_a_different_firing_type_needs_confirmation` and `..._added_when_confirmed`;
  `test_a_load_holds_at_most_48`.
- `test_nothing_is_added_or_removed_once_firing` and `..._once_fired`.
- `test_remove_puts_the_drop_off_back_to_waiting`; `test_remove_refuses_a_drop_off_not_in_this_load`.
- `test_start_firing_refuses_an_empty_load`; `test_start_firing_only_from_loading`.
- `test_fire_marks_every_member_fired_and_queues_one_ready_email_each`.
- `test_firing_again_is_refused_and_queues_nothing`; `test_fire_refuses_a_loading_load`;
  `test_fire_with_the_wrong_members_is_a_bug`.
- `test_search_parses_every_id_form` (`AC-12`, `ac12`, `ac 12`, `12`, ` AC-12 `);
  `test_search_matches_any_part_of_the_name_case_insensitively`;
  `test_a_closed_drop_off_matches_by_number_only`; `test_a_long_query_is_cut_to_100`.
- `test_waiting_is_oldest_first`; `test_totals_count_pieces_per_firing_type_and_glaze`;
  `test_overdue_at_60_days_not_59`.

## Acceptance criteria

1. #4's rules are functions in `domain/load.py`, each refusal tested: add only a
   waiting drop-off; a drop-off already in another load is refused with `AlreadyInLoad`
   naming both IDs; a different firing type needs confirming; nothing is added or
   removed once firing; at most 48.
2. `fire` on a fired load raises `AlreadyFired` and returns no email; firing a firing
   load returns each member fired and one ready email each.
3. Search finds `AC-12`, `ac12`, `ac 12` and `12` by number, and any part of a name
   case-insensitively (#3).
4. The waiting list is oldest first, totals pieces per firing type and per glaze type,
   and counts a drop-off waiting 60 days as overdue (#3, #7).

## Verification

```bash
uv run pytest tests/domain
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

The coverage floor (90) holds with the new code. Nothing to see in production.

## Rollout

Nothing reaches AWS.

## Admin actions

None.

## Hand-off

Filled in when the phase is done.

What phase 1d can rely on, as planned: `Load`, `LoadStatus`, and every entity the
`Records` port stores (`DropOff`, `Load`, `Email`, `Studio`, `SettingChange`), and
`a_load()` in `tests/domain/builders.py`.
