---
phase_id: 4
title: "Records: events, notes and date ranges, in the fake and DynamoDB"
epic: 1
implements: [42, 17]
depends_on: [3]
domain: [app, infra]
estimated_size: L
---

# Phase 4: Records: events, notes and date ranges, in the fake and DynamoDB

> **Status:** [ ] Pending

## Required reading

- [README](README.md), its Domain model and Rollout.
- [Phase 3](phase-3-load-history-and-notes-domain.md)'s hand-off.
- `src/asmbly_ceramics/ports/records.py`: the contract (keys, `Put`, `Update`, ranges
  half-open, lists in order, history by cursor).
- `src/asmbly_ceramics/adapters/aws/keys.py`: the key table in its docstring, and the
  `SettingChange` key with its random suffix (`HISTORY#<at>#<16 hex>`): events copy it.
- `src/asmbly_ceramics/adapters/aws/records.py`: `loads_in`, `history`, `_pages`,
  `is_item_used`, `commit`.
- `src/asmbly_ceramics/adapters/memory/records.py` and
  `tests/adapters/contract/test_records.py`: every contract test runs on the fake (and
  on the DynamoDB adapter against stubs, where the suite does so).
- `src/asmbly_ceramics/adapters/aws/ids.py` and `ports/ids.py`.
- `infra/app.yaml`, `ConsoleFunction`'s `QueryByPartition` and `CountLoadIds`;
  `tests/repo/test_app_template.py`, which pins them.
- AWS: DynamoDB Developer Guide, "Query operations" (key conditions with `BETWEEN` and
  `begins_with` on the sort key, pagination at 1 MB) and "Using IAM policy conditions for
  fine-grained access control" (`dynamodb:LeadingKeys` on a table `Query`).

## Goal

The store keeps a load's history and its notes, and lists them; loads and notes are
read by date range from the index, so the firing log and the notes search cost the same
in year ten as in year one. The console's role may query a load's partition and take
note numbers. Nothing calls the new methods yet but tests and phase 2's
`RecordNewElements` (switched to the date range).

## Files to create

- `tests/adapters/contract/test_events_and_notes.py` (or new cases in
  `test_records.py`, if that file's layout reads better).

## Files to modify

- `src/asmbly_ceramics/ports/records.py`: `Item` gains `LoadEvent` and `FiringNote`;
  `Update` gains `FiringNote`; the new methods below; the key list in the docstring.
- `src/asmbly_ceramics/ports/ids.py`: `next_note_id()`.
- `src/asmbly_ceramics/adapters/memory/records.py`, `adapters/memory/ids.py`: the fake.
- `src/asmbly_ceramics/adapters/aws/keys.py`: keys and conversions for events and notes;
  the docstring's table.
- `src/asmbly_ceramics/adapters/aws/records.py`, `adapters/aws/ids.py`: the adapter.
- `src/asmbly_ceramics/use_cases/settings.py`: `RecordNewElements` reads by date range.
- `infra/app.yaml`: two conditions.
- `tests/repo/test_app_template.py`: their pins.
- `tests/adapters/aws/test_keys.py`, `test_records.py`, `test_ids.py`,
  `tests/adapters/test_memory.py`.

## Implementation details

### app: the port

```python
Item = DropOff | Load | Email | Studio | SettingChange | Submission | LoadEvent | FiringNote


@dataclass(frozen=True, slots=True)
class Update:
    item: DropOff | Load | Email | Studio | FiringNote


class Records(Protocol):
    ...

    def load_events(self, load_id: LoadId) -> list[LoadEvent]:
        """The load's history, oldest first (two at one instant in their key's order)."""

    def loads_dated_between(self, statuses: Collection[LoadStatus], start: date, end: date) -> list[Load]:
        """Loads in `statuses` dated `start <= date < end`, by date then ID. Reads only
        that range of each status's index partition."""

    def note(self, load_id: LoadId, note_id: NoteId) -> FiringNote | None:
        """Strongly consistent; removed notes are returned (the use case decides)."""

    def notes_for(self, load_id: LoadId) -> list[FiringNote]:
        """The load's notes, removed ones left out, newest `written_at` first."""

    def notes_written_between(self, start: datetime, end: datetime) -> list[FiringNote]:
        """Every load's notes written `start <= written_at < end`, removed ones left out,
        newest first."""

    def is_item_used(self, which, id) -> bool:
        """... a clay body by any note that isn't removed, glaze types by notes too."""


class IdNumbers(Protocol):
    def next_note_id(self) -> NoteId:
        """As `next_load_id`, from its own counter."""
```

`Put(LoadEvent)` and `Put(FiringNote)` are refused with `Conflict` if the key exists
(the event key has a random suffix, so two events at one instant both land, as two
setting changes do). A glaze type is now also used by a note: a note-tagged glaze type
can be retired, not deleted.

### app: keys (`adapters/aws/keys.py`)

New rows in the key table:

| Item | `PK` | `SK` | `GSI1PK` / `GSI1SK` |
| --- | --- | --- | --- |
| Load event | `LOAD#L-4` | `EVENT#<at>#<16 hex>` | |
| Firing note | `LOAD#L-4` | `NOTE#N-12` | `NOTE` (removed: `NOTE#removed`) / `<written_at>#N-12` |
| Note counter | `COUNTER#note` | `META` | |

- An event item: `type="load_event"`, `load_id`, `at`, `by`, `what`, no `version`.
- A note item: `type="note"`, `id`, `load_id`, `kiln`, `text`, `glaze_types` and
  `clay_bodies` (lists of strings; empty lists are stored as empty lists, which
  DynamoDB allows), `ruling` (left out when none), `written_by`, `written_at`, the
  `edited_*` and `removed_*` stamps when set, `version`. A removed note moves to
  `GSI1PK=NOTE#removed`, so the search's range read skips it.
- A load's `META` item is unchanged; a query for a load's partition reads its `META`,
  events and notes, and the adapter keeps only the ones asked for (`begins_with(SK, ...)`
  in the key condition, so the others aren't read).

### app: the adapter (`adapters/aws/records.py`)

- `load_events`: `Query` `PK = LOAD#L-4 AND begins_with(SK, "EVENT#")`, all pages,
  strongly consistent not needed.
- `loads_dated_between`: per status, `Query` on `GSI1` with
  `GSI1PK = LOAD#<status> AND GSI1SK BETWEEN "<start>#" AND "<end-1 day>#~"` (the sort
  key is `<date>#L-n`; `~` sorts after every ID character), all pages; then the Python
  sort the contract states.
- `note`: `GetItem` by key, strongly consistent.
- `notes_for`: `Query` `PK = LOAD#L-4 AND begins_with(SK, "NOTE#")`, then leave out
  removed ones and sort.
- `notes_written_between`: `Query` on `GSI1`, `GSI1PK = NOTE AND GSI1SK BETWEEN
  "<iso(start)>" AND "<iso(end)>"` (exclusive end: drop items at `end`), all pages.
- `is_item_used`: `CLAY_BODIES` and `GLAZE_TYPES` add a `Query` of `GSI1PK = NOTE` with
  `FilterExpression="contains(#a, :v)"` on `clay_bodies` / `glaze_types`,
  `Select="COUNT"`, as `_any_with` does for scalar attributes.
- `next_note_id`: the counter `COUNTER#note`, as the load counter.
- AWS errors map to the port's as now: `RecordsUnavailable(code)`, `Conflict` from a
  cancelled transaction; codes only, never AWS's message.

### app: the fake (`adapters/memory/records.py`)

The same methods over its dicts, keeping every contract statement above (order, ranges,
removed notes, `Put` refusals), and the failure switch the fake already has.

### app: `RecordNewElements`

Reads `records.loads_dated_between({FIRED}, since, tomorrow)` filtered by kiln, where
`since` is the kiln's `counts.as_of` date (or 400 days back when it has no counts), in
place of `loads_in({FIRED})`.

### infra: `infra/app.yaml`, `ConsoleFunction`

- `QueryByPartition`: `dynamodb:LeadingKeys: [EMAIL#*, STUDIO, LOAD#*]`, and the comment
  says it covers a load's history and notes.
- `CountLoadIds` becomes `CountIds` (Sid only), `dynamodb:LeadingKeys: [COUNTER#load,
  COUNTER#note]`, comment "load and note numbers only".
- `ReadRecords` and `WriteRecords` already cover `LOAD#*` (events and notes are under it)
  and need no change. `QueryIndexes` already covers `GSI1`.
- No other function's role changes; the form, the mailer and the close never read
  events or notes. No new resource, name or tag; the function boundary already allows
  the table (decision 0003), so the bootstrap is unchanged.

`tests/repo/test_app_template.py` updates its pins for the two statements and checks the
form's and the close's statements are unchanged.

### Privacy

The adapters log a note by its ID (`N-12`) and a load by its ID (`L-4`), and AWS's
errors by their code only: never a note's text, an event's `what`, or a request or item
that holds them. `FiringNote.text` and `LoadEvent.what` are left out of their `repr`
(phase 3), so a traceback of either doesn't show them either.

## Tests

- Contract (fake, and adapter against stubs): `test_event_put_and_listed_oldest_first`;
  `test_two_events_same_instant_both_land`; `test_load_events_only_that_load`;
  `test_loads_dated_between_half_open`; `test_loads_dated_between_statuses`;
  `test_note_put_get_update`; `test_note_put_twice_conflict`;
  `test_note_update_wrong_version_conflict`; `test_notes_for_newest_first_without_removed`;
  `test_notes_written_between_half_open_without_removed`;
  `test_clay_body_used_by_note`; `test_glaze_type_used_by_note`;
  `test_removed_note_uses_nothing`; `test_next_note_id_increments`.
- `tests/adapters/aws/test_keys.py`: `test_event_item`; `test_note_item_round_trip`;
  `test_removed_note_leaves_the_note_partition`; `test_note_with_no_ruling`.
- `tests/adapters/aws/test_records.py` (Stubber): each new `Query`'s exact key condition;
  pagination; an AWS error gives `RecordsUnavailable(code)` with no message.
- `tests/repo/test_app_template.py`: `test_console_queries_load_partitions`;
  `test_console_counts_loads_and_notes_only`.
- `tests/use_cases/test_settings.py`: `test_record_new_elements_reads_since_counts`.

## Acceptance criteria

1. A load's history is stored with the load and listed oldest first; two lines at one
   instant both land (#42 "in the load's history").
2. Notes are stored with their load, listed per load and by date range, and a removed
   note is listed nowhere (#17).
3. The firing log's and the notes search's reads are bounded by date range, from an index
   (README, Overview).
4. A clay body or glaze type a note names can't be deleted (#6's rule).
5. The console role queries `LOAD#*` partitions and takes `COUNTER#note`; no other role
   changes (Security).

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] `uvx cfn-lint==1.57.1 infra/*.yaml`
- [ ] `sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml`
- After the merge: both smoke tests pass; on stage, a load page and the settings page open.

## Rollout

The merge deploys the two condition changes and starts writing nothing new until phase 5
(only tests write events and notes). Check: the deploy's stage and prod smoke tests pass;
on stage, open a load and the settings page (the console's queries still succeed). Who:
the maintainer. Undo: a revert pull request restores both conditions; any event or note
items written by then stay in the table, unread.

## Admin actions

None.

## Hand-off

- [ ] `Records.load_events`, `loads_dated_between`, `note`, `notes_for`,
      `notes_written_between`; `Put` of a `LoadEvent` or `FiringNote`; `Update` of a
      `FiringNote`; `IdNumbers.next_note_id`, in the fake and DynamoDB.
- [ ] `is_item_used` counts notes for clay bodies and glaze types.
- [ ] The console role queries `LOAD#*` and counts `COUNTER#note`.
