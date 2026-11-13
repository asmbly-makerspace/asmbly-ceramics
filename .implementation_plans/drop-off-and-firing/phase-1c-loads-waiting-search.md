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

> **Status:** [x] Complete — 2026-11-13 on branch feat/drop-off-and-firing-phase-1

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
| `domain/search.py` | `Query`, `QUERY_MAX`, `fold`, `parse_query`, `matches` |
| `domain/waiting.py` | `WaitingTotals`, `oldest_first`, `waiting_order`, `totals`, `days_waiting`, `is_overdue` |

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
  `LOADING` (`LoadNotLoading`). `change_load` checks only what changes: a kiln retired
  since the load started doesn't block a date change. Changing the firing type of a load
  with members raises `FiringTypeLocked` (decided at review: each member was added, and
  any mismatch confirmed, against the firing type it has, so #4's confirmation would be
  skipped); an empty load's firing type, and any load's kiln and date, can change.
- `add_to_load`: `LoadNotLoading` unless `LOADING`; `AlreadyInLoad` when the drop-off
  is `IN_LOAD`, naming the drop-off and the load it is in ("AC-7 is already in load
  L-3."); `NotWaiting` for any other
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
  "Exactly" means the same IDs, each once, in any order; the returned drop-offs follow
  the load's `members` order.
- Times: `start_load`'s `at` and `fire`'s `at` must be aware (else `ValueError`), and
  `start_load` needs a non-empty `by` (else `ValueError`), as in phase 1b.
- Bugs, not refusals (`ValueError`): `add_to_load` given a waiting drop-off whose ID is
  already in `members`, or an `IN_LOAD` drop-off with no `load_id`.
- `FiringTypeMismatch` names the two firing types by their `ItemId` (`bisque`, `glaze`):
  `add_to_load` has no `Studio`, and an item ID holds no personal detail. It keeps both
  as `.drop_off_firing_type` and `.load_firing_type`, so a page names them from the
  studio's items.

### `domain/search.py` (#3)

```python
@dataclass(frozen=True, slots=True)
class Query:
    id: DropOffId | None  # from "AC-12", "ac12", "ac 12", "12"
    text: str  # folded; "" when the query has an ID form


def parse_query(raw: str) -> Query: ...
def matches(drop_off: DropOff, query: Query) -> bool: ...  # by number, or the name contains the text
```

A query of more than 100 characters is cut to 100 before parsing. A number is
`(ac)?[ -]?[0-9]+` after stripping and casefolding, ASCII digits only; one that can't
be an ID (`0`, `AC-000`, more than `ID_DIGITS_MAX` digits after leading zeros) gives
`Query(id=None, text="")`, which matches nothing, so no use case builds `DropOffId(0)`. A closed
drop-off has no name and matches by number only. An empty query matches nothing.

Text is compared folded on both sides, by one function `fold(s)`: Unicode NFC, then
`casefold()`, then NFC again (casefolding can undo NFC), format characters (`Cf`, as
`DropOffDetails.create` drops from names) dropped, with whitespace runs collapsed to one
space. The stored name is folded at match time, so it doesn't matter whether
phase 1b's `DropOffDetails.create` normalised it (it strips control characters but
doesn't apply NFC). `Query.text` is what staff typed and may be a person's name, so it
is `field(repr=False)`, with a test that `repr(parse_query(name))` doesn't hold it.

### `domain/waiting.py` (#3, #7)

```python
@dataclass(frozen=True, slots=True)
class WaitingTotals:
    drop_offs: Mapping[ItemId, int]  # per firing type
    pieces: Mapping[ItemId, int]  # per firing type
    pieces_by_glaze: Mapping[ItemId, int]  # per glaze type
    overdue: int


def oldest_first(drop_offs: Iterable[DropOff]) -> list[DropOff]: ...  # oldest created_at first, then by ID
def waiting_order(drop_offs: Iterable[DropOff]) -> list[DropOff]: ...  # WAITING only, oldest_first
def totals(drop_offs: Iterable[DropOff], now: datetime) -> WaitingTotals: ...  # WAITING only
def days_waiting(drop_off: DropOff, now: datetime) -> int: ...  # whole Austin days since created_at
def is_overdue(drop_off: DropOff, now: datetime) -> bool: ...  # WAITING and days_waiting >= 60
```

`days_waiting` counts the studio's calendar days (`STUDIO_TZ`) from the day it was made:
0 that day, 1 from the next Austin midnight, one per calendar day across a
daylight-saving change. Overdue uses it, so the console's "60 days" and its "overdue"
tag agree (decided at review). `totals`, `days_waiting` and `is_overdue` raise
`ValueError` on a naive `now`.

## Tests

`tests/domain/` (no fakes, no AWS):

- `test_start_load_refuses_a_retired_kiln_or_firing_type`; `test_change_load_only_while_loading`;
  `test_change_load_refuses_a_new_firing_type_once_it_has_members`;
  `test_change_load_checks_only_what_changes`.
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
  `test_a_closed_drop_off_matches_by_number_only`; `test_a_long_query_is_cut_to_100`;
  `test_search_folds_nfc_and_case_on_both_sides`; `test_a_query_repr_holds_no_text`.
- `test_naive_times_are_refused` (in `test_load.py` and `test_waiting.py`; search takes no time).
- `test_waiting_is_oldest_first`; `test_totals_count_pieces_per_firing_type_and_glaze`;
  `test_overdue_at_60_days_waiting_not_59`; `test_overdue_counts_austin_days_not_elapsed_hours`;
  `test_days_waiting_are_whole_austin_days`; `test_days_waiting_across_a_daylight_saving_change`.

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

Built on 2026-11-13. What phase 1d and later can rely on:

- `domain/load.py`: `LoadStatus` (`LOADING`, `FIRING`, `FIRED`), `Load` (fields as above,
  `version=0` when started), `FireResult(load, drop_offs, emails)`; `start_load`,
  `change_load`, `add_to_load(load, drop_off, *, confirmed)`, `remove_from_load`,
  `start_firing`, `fire(load, members, at)`. `fire` returns the drop-offs in the load's
  `members` order and one pending `READY` email each; a fired load raises
  `AlreadyFired`. `change_load` checks only the values that change, and raises
  `FiringTypeLocked(load_id)` for a new firing type on a load with members.
  `FiringTypeMismatch(drop_off_id, drop_off_firing_type, load_firing_type)` keeps both
  firing types' `ItemId`s as attributes for the confirm panel to name. Records that
  disagree: `add_to_load` raises `AlreadyInLoad` for an `IN_LOAD` drop-off naming any
  load (this one included, listed or not) and `ValueError` for a waiting drop-off already
  in `members` or an `IN_LOAD` one with no `load_id`; `remove_from_load` raises
  `NotInLoad` unless the drop-off is `IN_LOAD`, names this load and is in `members` (so
  also for one naming this load but not listed, and a waiting one that is listed);
  `fire` raises `ValueError` when `members` isn't exactly the load's, each `IN_LOAD` in
  it.
- `domain/search.py`: `QUERY_MAX = 100`, `Query(id: DropOffId | None, text)` (`text`
  not in the `repr`), `fold(text)` (NFC, casefold, NFC, `Cf` dropped, whitespace
  collapsed), `parse_query`, `matches` (the name only, never email or phone). An ID form
  that can't be an ID (`0`, more than 12 digits) is `Query(None, "")` and matches
  nothing; a use case reads `records.drop_off(query.id)` and never builds the ID itself. A use case filters with `matches`; the name is folded at match time, so
  stored names need no migration.
- `domain/waiting.py`: `WaitingTotals` (read-only mappings keyed by `ItemId`),
  `oldest_first` (any drop-offs), `waiting_order` (waiting ones, `oldest_first`),
  `totals(drop_offs, now)`, `days_waiting(drop_off, now)` (whole Austin days),
  `is_overdue(drop_off, now)` (waiting and `days_waiting` at least 60); each `now` must
  be aware.
- `tests/domain/builders.py`: `a_load(number=1, status=LOADING, members=(), *, kiln,
  firing_type, at)`, `members` as drop-off numbers.
- Days waiting per row is `days_waiting` (phases 2 and 8 call it rather than doing the
  arithmetic).
