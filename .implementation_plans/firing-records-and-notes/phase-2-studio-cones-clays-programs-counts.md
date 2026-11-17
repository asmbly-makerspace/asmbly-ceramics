---
phase_id: 2
title: "The studio: cones, clay bodies, default programs, kiln counts"
epic: 1
implements: [42, 17]
depends_on: [1]
domain: [app, web]
estimated_size: L
---

# Phase 2: The studio: cones, clay bodies, default programs, kiln counts

> **Status:** [~] In progress

## Required reading

- [README](README.md), its Domain model.
- [Phase 1](phase-1-load-record-and-steps.md)'s hand-off: `Program`, `FiringRecord`,
  `read_firing_record`.
- `src/asmbly_ceramics/domain/studio.py` and `tests/domain/test_studio.py`: `CatalogList`,
  `CatalogItem`, `Studio`, `starting_studio`, `add_item`, `retire_item`, `delete_item`,
  `SettingChange`. The new lists and fields follow them exactly.
- `src/asmbly_ceramics/use_cases/settings.py` and its `_save`: how a settings change is
  committed with its history.
- `src/asmbly_ceramics/adapters/aws/keys.py` (`_catalog_item` and its reverse) and
  `adapters/aws/records.py` (`is_item_used`, `_any_with`); `adapters/memory/records.py`
  (`is_item_used`).
- `src/asmbly_ceramics/web/console/settings.py`: `LISTS`, `SLUGS`, `TITLES`. The page
  iterates `CatalogList`, so each new list needs its slug and title here.
- Issue #32: `ViewStudio` checks every item's use on every render; this phase adds two
  lists to that, behind the existing `with_used`.
- Story #42's criteria "Firing number" and "Program"; #17's "tagged with … clay bodies".

## Goal

The studio has a cone list and a clay body list, managed in Settings like the other
lists. A firing type can carry a default program, which fills a new load's record. A
kiln can carry its firing counts, and the domain suggests each new firing's numbers from
them and the kiln's fired loads. All of it is stored, read with defaults from an older
studio item, and recorded in the settings history. The pages for programs and counts
come in phase 7; the two lists appear on the settings page now, through its existing
list form.

## Files to create

None.

## Files to modify

- `src/asmbly_ceramics/domain/studio.py`: the two lists, `KilnCounts`, the new item
  fields and functions below.
- `src/asmbly_ceramics/domain/firing.py`: `read_program`, `suggest_numbers`.
- `src/asmbly_ceramics/domain/load.py`: `start_load` and `change_load` apply the firing
  type's default program.
- `src/asmbly_ceramics/domain/errors.py`: nothing new (`InvalidSetting`, `InvalidRecord`
  cover it).
- `src/asmbly_ceramics/use_cases/settings.py`: `SetDefaultProgram`, `SetKilnCounts`,
  `RecordNewElements`.
- `src/asmbly_ceramics/use_cases/loads.py`: `StartLoad` and `ChangeLoad` pass the studio
  (they already do) so the default program applies.
- `src/asmbly_ceramics/composition.py`: wire the three use cases.
- `src/asmbly_ceramics/adapters/aws/keys.py`: store and read the new lists and fields.
- `src/asmbly_ceramics/adapters/aws/records.py` and `adapters/memory/records.py`:
  `is_item_used` for `CONES` and `CLAY_BODIES`.
- `src/asmbly_ceramics/web/console/settings.py`: `LISTS`, `SLUGS` and `TITLES` gain
  `cones` / "Cones" and `clay-bodies` / "Clay bodies".
- `tests/domain/builders.py`: `a_studio(...)` builds the new lists.
- Tests listed below.

## Implementation details

### app: `domain/studio.py`

```python
class CatalogList(StrEnum):
    KILNS = "kilns"
    FIRING_TYPES = "firing_types"
    GLAZE_TYPES = "glaze_types"
    REASONS = "reasons"
    CONES = "cones"
    CLAY_BODIES = "clay_bodies"


# _KIND gains "cone" and "clay body".


@dataclass(frozen=True, slots=True)
class KilnCounts:
    since_elements: int  # firings since the kiln's last new elements, as of `as_of`
    all_time: int
    as_of: datetime  # aware


@dataclass(frozen=True, slots=True)
class CatalogItem:
    ...  # as now
    default_program: Program | None = None  # firing types only
    counts: KilnCounts | None = None  # kilns only


@dataclass(frozen=True, slots=True)
class Studio:
    ...  # as now, then:
    cones: tuple[CatalogItem, ...] = STARTING_CONES
    clay_bodies: tuple[CatalogItem, ...] = STARTING_CLAY_BODIES
    version: int = 0
```

- `STARTING_CONES = _catalog("^06", "^5", "^6")` and
  `STARTING_CLAY_BODIES = _catalog("Buffalo Wallow", "Cinco Blanco", "Cone 5 Porcelain")`.
  `new_item_id` must make an ID for `^06` (check what it does with `^`; if it gives an
  empty ID, map `^` to `cone-` there and test it).
- `starting_studio` gives the starting firing types their default programs: Bisque
  `Program(preheat_hours=8, cone=^06, speed=SLOW, hold_minutes=0)` and Glaze
  `Program(preheat_hours=0, cone=^6, speed=MEDIUM, hold_minutes=7)`, as the workbook's
  logs show. A studio already stored keeps its firing types without programs: staff set
  them (phase 7).
- `items`, `_with_items` and `item` cover the two lists.

```python
def set_default_program(
    studio: Studio, firing_type: ItemId, values: Mapping[str, str], by: str, at: datetime
) -> tuple[Studio, SettingChange | None]:
    """The firing type's default program from the page's preheat_hours, cone, speed and
    hold_minutes (`firing.read_program`, cone from the studio's active cones). All blank
    clears it. `UnknownItem`; `InvalidRecord` for a refused field. None when unchanged.
    History: "Default program for Glaze: ^6, medium, preheat 0 h, hold 7 min"."""


def set_kiln_counts(
    studio: Studio, kiln: ItemId, since_elements: str, all_time: str, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    """Counts typed by staff, as of `at`: whole numbers, 0 to FIRING_NUMBER_MAX, and
    since_elements ≤ all_time, else `InvalidSetting(field, message)`. History:
    "Helios counts: 97 since elements, 251 all time"."""


def record_new_elements(
    studio: Studio, kiln: ItemId, all_time_so_far: int, by: str, at: datetime
) -> tuple[Studio, SettingChange]:
    """New elements in the kiln: counts become (0, all_time_so_far, at). History:
    "New elements in Helios"."""
```

A retired kiln or firing type can still have its counts or program changed (nothing new
uses it). `delete_item` and the used checks treat the new lists as the others.

### app: `domain/firing.py`

```python
def read_program(values: Mapping[str, str], cones: Collection[ItemId]) -> Program:
    """The four program fields, checked as `read_firing_record` checks them (it calls this)."""


def suggest_numbers(counts: KilnCounts | None, fired: Sequence[Load]) -> tuple[int | None, int | None]:
    """(firing_number, all_time_number) for the kiln's next firing.

    `fired` is the kiln's fired loads (the use case filters them). Each number is the
    latest of those, by fired_at, fired after `counts.as_of` and holding that number,
    plus 1; else the count plus 1; else None (no counts and no numbered firing: the page
    leaves the field blank). Never more than FIRING_NUMBER_MAX."""
```

`suggest_numbers` takes loads but stays in `firing.py`; if that makes an import cycle
with `load.py`, put it in `load.py` and say so in the hand-off.

### app: `domain/load.py`

- `start_load` sets `record=FiringRecord(program=default)` when the firing type has a
  `default_program`.
- `change_load`, when the firing type changes: if the load's program equals the old
  firing type's default (or is empty), it becomes the new firing type's default (or
  empty); a program staff changed is kept.

### app: `use_cases/settings.py`

Each reads the studio, applies the domain function, checks the version the page showed
(`Conflict`), and commits through `_save` with its `SettingChange`, as `AddItem` does.
Logs `setting_changed` with the username and the item ID.

- `SetDefaultProgram(records, clock, studio)(firing_type, values, version, staff)`.
- `SetKilnCounts(records, clock, studio)(kiln, since_elements, all_time, version, staff)`.
- `RecordNewElements(records, clock, studio)(kiln, version, staff)`: reads the kiln's
  fired loads (`records.loads_in({FIRED})`, filtered by kiln; phase 4 changes this to a
  date range) and calls `suggest_numbers` for `all_time_so_far` (the suggested all-time
  number minus 1, or the counts' `all_time`, or 0).

### app: storage

- `keys.py`: the studio item gains `cones` and `clay_bodies` (lists like the others); a
  stored studio without them reads with the starting lists. A catalog item map gains
  `default_program` (a map, as phase 1's program) and `counts` (`since_elements`,
  `all_time`, `as_of`), each only when set.
- `is_item_used`: a cone is used by any live load whose top-level `program_cone` is it
  (phase 1 stores it) or any firing type whose default program names it; a clay body by
  nothing yet (notes arrive in phase 4, which extends this), so it returns `False`. The
  fake matches. Both adapters' `match` stays exhaustive (mypy checks it).

### web: `web/console/settings.py`

`LISTS["cones"] = CatalogList.CONES`, `LISTS["clay-bodies"] = CatalogList.CLAY_BODIES`,
and their titles. The existing list form (add, retire, restore, delete) then works for
both, with the same CSRF and group checks. Nothing else changes on the page in this
phase.

## Tests

- `tests/domain/test_studio.py`: `test_starting_studio_has_cones_and_clay_bodies`;
  `test_starting_firing_types_have_default_programs`; `test_cone_ids_from_caret_names`;
  `test_add_retire_delete_cone_and_clay_body`; `test_set_default_program_and_history`;
  `test_set_default_program_blank_clears`; `test_set_default_program_unknown_cone`;
  `test_set_kiln_counts_checks_numbers`; `test_set_kiln_counts_since_not_above_all_time`;
  `test_record_new_elements_resets_since`.
- `tests/domain/test_firing.py`: `test_suggest_from_counts`;
  `test_suggest_from_latest_numbered_firing_after_counts`;
  `test_suggest_ignores_firings_before_counts`; `test_suggest_skips_unnumbered_firings`;
  `test_suggest_none_without_counts_or_firings`; `test_suggest_after_new_elements_is_1`.
- `tests/domain/test_load.py`: `test_start_load_fills_default_program`;
  `test_change_firing_type_swaps_untouched_default`;
  `test_change_firing_type_keeps_changed_program`.
- `tests/use_cases/test_settings.py`: each new use case's success, `Conflict`, refused
  field, and history line; `test_record_new_elements_counts_fired_loads`.
- `tests/adapters/aws/test_keys.py`: `test_studio_round_trips_new_lists_and_fields`;
  `test_old_studio_item_reads_starting_lists`.
- `tests/adapters/contract/test_records.py`: `test_cone_used_by_load_program`;
  `test_cone_used_by_default_program`; `test_clay_body_not_used`.
- `tests/web/console/test_settings.py`: `test_cones_and_clay_bodies_listed`;
  `test_add_cone`; `test_an_unknown_list_is_404` still passes.

## Acceptance criteria

1. A new studio has the starting cones, clay bodies and default programs; an older stored
   studio reads with the starting lists and no programs or counts (#42, #17).
2. Cones and clay bodies are added, retired, restored and deleted as the other lists are,
   with history; a used cone can't be deleted (#6's rule).
3. A new load's record starts with its firing type's default program (#42 "A firing type
   can carry a default program that fills these in").
4. `suggest_numbers` follows the README's rule, and is 1 for the first firing after new
   elements (#42 "the count restarts at 1 after new elements").
5. Every settings change records who and when in the settings history.

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] No setting is a constant outside `starting_studio` and the `STARTING_*` lists.
- After the merge, on stage: Settings shows Cones and Clay bodies; add and delete a
  made-up cone; start a glaze load and see (in phase 6's page, or in a test) its program.

## Rollout

The merge deploys the studio's new attributes through the normal deploy. Check: the
settings page opens on stage and lists both new lists. Undo: a revert pull request.
Old code ignores the new attributes when it reads, but not when it writes: the first
settings save under reverted code rewrites the whole studio item and drops `cones`,
`clay_bodies`, the default programs and the kilns' counts. After a revert they read
again as the starting cones and clay bodies with no programs or counts, and staff set
any they changed again once the fix is merged.

## Admin actions

None (staff set the counts and programs in phase 7).

## Hand-off

- [x] `domain/studio.py`: `CatalogList.CONES`, `CatalogList.CLAY_BODIES`; `KilnCounts`
      (`since_elements`, `all_time`, `as_of`); `CatalogItem.default_program`,
      `CatalogItem.counts`; `STARTING_CONES` (`item-06`, `item-5`, `item-6`: `^` isn't a
      slug character, so `new_item_id` puts `item-` in front, no mapping needed) and
      `STARTING_CLAY_BODIES`, the defaults of `Studio.cones` and `Studio.clay_bodies`.
      The starting firing types carry Bisque's and Glaze's default programs.
- [x] `set_default_program(studio, firing_type, values, by, at)` takes the studio's
      active cones or the cone the program already names, clears on all blank, and
      returns `(studio, None)` when unchanged; `describe_program(studio, program)` (the
      history's "^6, medium, preheat 0 h, hold 7 min"); `set_kiln_counts(studio, kiln,
      since_elements, all_time, by, at)` (`InvalidSetting` fields `since_elements`,
      `all_time`); `record_new_elements(studio, kiln, all_time_so_far, by, at)`;
      `names_cone(studio, cone)`.
- [x] `domain/firing.py`: `read_program(values, cones)`; `read_firing_record` reads the
      program through it and still reports every refused field at once.
- [x] `suggest_numbers(counts, fired)` is in **`domain/load.py`**, not `firing.py`:
      `firing.py` can't import `Load` (`load.py` imports it). It skips loads that aren't
      fired and is capped at `FIRING_NUMBER_MAX`.
- [x] `start_load` fills the record with the firing type's default program;
      `change_load` swaps it for the new firing type's when the program is still the old
      default (or empty; a deleted old firing type counts as having none) and keeps a
      changed one. A new bisque or glaze load's record is no longer `EMPTY_RECORD`.
- [x] Use cases `SetDefaultProgram(records, clock, studio)(firing_type, values, version,
      staff)`, `SetKilnCounts(...)(kiln, since_elements, all_time, version, staff)`,
      `RecordNewElements(...)(kiln, version, staff)`, wired in `composition.py` and
      `ConsoleServices` (`set_default_program`, `set_kiln_counts`,
      `record_new_elements`) and in the tests' `World`. `RecordNewElements` reads
      `records.loads_in({FIRED})` filtered by kiln; phase 4 changes it to a date range.
- [x] `is_item_used`: a cone is used by a live load's `program_cone` or a firing type's
      default program (the adapters read the stored studio, so the settings page's
      "Used" column and Delete button agree); a clay body returns `False` until phase 4
      extends it. `delete_item` also refuses a cone a default program names
      (`names_cone`) whatever `used` says, so the rule is in the domain too.
- [x] A stored default program that doesn't parse (an unknown speed, a number of the
      wrong type) reads as None and is logged as `unexpected_item` with the firing
      type's ID, instead of making the whole studio item unreadable.
- [x] Rollback: a revert reads safely, but the first settings save under the reverted
      code drops `cones`, `clay_bodies`, the default programs and the counts (see
      Rollout).
- [x] The studio item stores `cones`, `clay_bodies`, and a catalog item's
      `default_program` and `counts` only when set; an older item reads with the starting
      lists and no programs or counts.
- [x] The settings page lists both lists under slugs `cones` and `clay-bodies`, titles
      "Cones" and "Clay bodies".
- [x] `ItemInUse`'s text: "<name> is in use by a drop-off, a load or a default
      program, so it stays retired."
