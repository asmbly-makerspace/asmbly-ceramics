---
plan: firing-records-and-notes
epic: 1
---

# Firing records and notes: implementation plan

**Created:** 2026-11-16

## Overview

The ceramics studio keeps a firing log per kiln in its workbook spreadsheet (the Helios,
Athena and Vulcan tabs): who loaded and unloaded each firing, how full it was, its firing
number, the program, the result, what it cost and how far the witness cones bent. Staff
also want to keep notes on firings (whether a glaze or clay may be tested, and why) and
find them again. This plan moves the log into the console as an optional firing record on
each load (#42), with a history of who moved the load from state to state and test
firings that need no drop-off, and adds firing notes with glaze and clay tags and rulings
(#17). The design is at https://claude.ai/artifact/7FTCn2AgGzoXEA3RhrMKpi.

What was found on 16 November 2026, before planning:

- **This repository:** epic #1's app is built (`drop-off-and-firing`, phases 1 to 9
  complete). A `Load` records who started it and when, when it was fired, and who deleted
  it; not who started the firing or marked it fired. A load needs a drop-off to start
  firing (`EmptyLoad`). There is no per-load history: the settings have one
  (`SettingChange`, `STUDIO/HISTORY#…`).
- **The console's role** (`infra/app.yaml`, `ConsoleFunction`): it reads and writes by key
  under `DROPOFF#*`, `EMAIL#*`, `LOAD#*` and `STUDIO`, queries any index, and queries
  partitions only under `EMAIL#*` and `STUDIO`; it takes load numbers only
  (`COUNTER#load`).
- **Volume:** about 4,000 drop-offs, 300 firings and a few hundred notes a year. The
  maintainer asked (16 November 2026) that the design hold for years. DynamoDB stays
  (decision 0002); the firing log and the notes search read by date range from an index,
  so their cost doesn't grow with the years kept.

## Domain model

What this plan adds to the model of `drop-off-and-firing`, without reworking it:

- **`Load`** gains `test: bool` (chosen when the load is started, changeable only while
  it is loading), `firing_started_by` / `firing_started_at`, `fired_by` (beside the
  existing `started_by` / `started_at`, `fired_at`, `deleted_by` / `deleted_at`), and
  `record: FiringRecord`.
  - `start_firing` accepts an empty load only when it is a test. A test with no drop-offs
    fires with no emails; one with drop-offs fires as any load does.
  - `set_firing_record` works on any live load (loading, firing or fired) and never
    touches its drop-offs: "a fired load can't change" stays true of its contents.
  - `correct_step_time` changes when a reached step (started, firing, fired) happened,
    keeping started ≤ firing ≤ fired and never in the future. The username can't change.
- **`FiringRecord`** (`domain/firing.py`), every field optional: % full, the firing number
  since the kiln's elements and all time, a `Program` (preheat hours, cone, `Speed` slow,
  medium or fast, hold minutes), firing time in minutes, max and board temperature in °F,
  cost in cents, and the top, center and bottom witness cones, each a % bent (0 to 100)
  or `NO_CONE`. `read_firing_record` checks every field the page sends against
  `domain/limits.py` and the studio's cone list, and reports every refused field at once.
- **`LoadEvent`**: one line of a load's history (`load_id`, `at`, `by`, `what`), like a
  `SettingChange`. Every use case that changes a load writes one in the same commit:
  started, kiln/firing/date changed, test changed, firing started, fired, deleted, the
  firing record saved (the fields changed, with their new values), a step's time
  corrected (the old and new times). Adding or removing a drop-off writes none.
  "Fired" on a full load becomes 1 + 48 + 48 + 1 = 98 changes, under `MAX_CHANGES` (100).
- **`FiringNote`** (#17): `id` (`N-12`, from its own counter), `load_id`, `kiln` (copied
  from the load, for the filter), `text` (1 to 2,000 characters of plain text, refused if
  it holds something shaped like an email address or a phone number), `glaze_types` and
  `clay_bodies` (studio items), `ruling` (`Ruling`: allowed, allowed with conditions, not
  allowed; or none), `written_by` / `written_at`, `edited_by` / `edited_at`,
  `removed_by` / `removed_at` (a soft delete, as a load's), `version`. A deleted load
  takes no new note. A note isn't personal data and the close (#7) never touches it.
- **The studio** (settings as data, #6): two new lists, `CatalogList.CONES` (starting
  ^06, ^5, ^6) and `CatalogList.CLAY_BODIES` (starting Buffalo Wallow, Cinco Blanco,
  Cone 5 Porcelain); a firing type's `default_program: Program | None`, copied into a new
  load's record when it is started (and swapped while loading if the firing type
  changes and the program is still the old default); a kiln's
  `counts: KilnCounts | None` (`since_elements`, `all_time`, `as_of`), set by hand once
  and reset by "New elements". `suggest_numbers` suggests each firing number as the
  kiln's latest fired load after `as_of` that has one, plus 1, or else the counts plus 1.
  A typed number is never overwritten.
- **Ports.** No new port. `Records` gains `load_events(load_id)`,
  `loads_dated_between(statuses, start, end)`, `note(load_id, note_id)`,
  `notes_for(load_id)` and `notes_written_between(start, end)`; `Put` takes a
  `LoadEvent` or a `FiringNote` and `Update` a `FiringNote`. `IdNumbers` gains
  `next_note_id()`. Each has its in-memory fake and its DynamoDB adapter (phase 4).
  In the table, a load's events and notes live in its own partition (`LOAD#L-4`,
  `EVENT#<at>#<16 hex>` and `NOTE#N-12`); a note also has `GSI1PK=NOTE`,
  `GSI1SK=<written_at>#N-12`, so the search reads a date range from the index.
- **Room to grow.** The kiln schedule (#9) reads `Load.test` and shows a test as the kiln
  in use, with nothing from the record or the notes. Kiln maintenance (#43) replaces "New
  elements" with a maintenance task that resets `KilnCounts`. A glaze log would be its own
  entity and use cases, reusing the glaze type list. None is built here.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #42 | Staff keep a firing record on each load, and read each kiln's firing log | 1, 2, 3, 4, 5, 6, 7, 9 |
| #17 | Staff keep firing notes they can look up later | 2, 3, 4, 8, 9 |

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| [1](phase-1-load-record-and-steps.md) | The load: test firings, who moved it, the firing record | app | L | [~] In progress |
| [2](phase-2-studio-cones-clays-programs-counts.md) | The studio: cones, clay bodies, default programs, kiln counts | app, web | L | [~] In progress |
| [3](phase-3-load-history-and-notes-domain.md) | The domain: a load's history and firing notes | app | L | [x] Complete |
| [4](phase-4-records-events-notes-ranges.md) | Records: events, notes and date ranges, in the fake and DynamoDB | app, infra | L | [~] In progress |
| [5](phase-5-use-cases-record-and-log.md) | Use cases: test loads, history, the firing record, corrections, the firing log | app | L | [~] In progress |
| [6](phase-6-console-load-page.md) | Console: the load page's steps, firing record, test and history | web | L | [~] In progress |
| [7](phase-7-console-firing-log-and-settings.md) | Console: the firing log, its CSV, and the new settings | web, docs | L | [~] In progress |
| [8](phase-8-use-cases-notes.md) | Use cases: firing notes | app | L | [x] Complete |
| [9](phase-9-console-notes.md) | Console: notes on a load and the notes search | web, docs | L | [~] In progress |

## Dependencies

- Nothing outside this repository. No other plan, no work in asmbly-staff-login,
  AsmblyMCPs or the facilities repository, no by-hand AWS step.
- `drop-off-and-firing` is complete; this plan builds on its domain, ports, adapters and
  console.
- Phases: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 9, and 5 → 8 → 9.

## Parallelism

- **1, 2, 3, 4** run in order: they share `domain/errors.py`, `domain/limits.py`,
  `domain/load.py` or `domain/studio.py`, `adapters/aws/keys.py` and
  `tests/domain/builders.py`.
- **5, 6, 7** run in order: 6 and 7 share `web/console/__init__.py`,
  `web/console/loads.py` and `web/templates/console/`; 5 changes the use cases both call.
- **8 and 6, 8 and 7: parallel-safe.** 8 creates `use_cases/notes.py` and
  `tests/use_cases/test_notes.py` only, with its fixtures in its own test module; it
  doesn't touch `composition.py` (phase 9 wires it) or `tests/use_cases/conftest.py`.
  It waits for 5, whose `InvalidLogRange` and `LOG_RANGE_MAX` it reuses.
- **9** waits for 7 and 8: it shares the load page and the firing log with 7, and wires
  8's use cases.
- `docs/architecture.md` is changed by 7 and 9, which are sequential anyway.

## Admin actions

- None in AWS or GitHub. Infrastructure clearance: phase 4 changes two conditions in
  `infra/app.yaml` (the console's `QueryByPartition` gains `LOAD#*`, its counter grant
  gains `COUNTER#note`), deployed by the normal merge; no new resource, name or tag, and
  no bootstrap change.
- After phase 7 merges: tell ceramics staff that the firing record and the firing log are
  in the console, to enter each kiln's current counts once (Settings › Kilns), to check
  the firing types' default programs, and that the workbook's firing log tabs can stop.
- After phase 9 merges: tell ceramics staff about notes and the notes search.

## Rollout

Every phase reaches the live app through the normal merge and deploy (stage, its smoke
test, prod, its smoke test). What each changes in AWS:

1. **Phase 1** writes four new load attributes (`test`, `firing_started_by`,
   `firing_started_at`, `fired_by`), a `record` map and a top-level `program_cone`. Old
   code ignores them; old items read with the defaults. Check: on stage, start a load with
   a made-up drop-off, start firing, mark it fired; the load still opens and its emails
   are queued as before (the console can't start a test load until phase 6). Undo: revert.
2. **Phase 2** writes the studio's new lists and fields. An old studio item reads with
   the starting cones and clay bodies and no programs or counts. Undo: revert. An old
   reader ignores the new attributes, but the first settings save under the reverted
   code rewrites the whole studio item and drops `cones`, `clay_bodies`, the default
   programs and the kilns' counts; staff set any they changed again after the fix.
3. **Phase 3** reaches nothing in AWS.
4. **Phase 4** writes event and note items and changes the console role's two
   conditions. Check: both smoke tests pass, and a load page and the settings page open
   on stage. Undo: revert; the event items stay in the table, unread.
5. **Phases 5 to 9** change code only. The staff-facing parts appear with phase 6 (the
   load page), 7 (the firing log and settings) and 9 (notes).

## Related work

- #32 (ViewStudio reads every item's use on every render): two more lists add two more
  scans per settings page; phase 2 keeps them behind `with_used`. Worth doing soon after
  this plan.
- #9 (Members see the kiln schedule): reads `Load.test` once it is built; shows a test as
  the kiln in use.
- #43 (kiln maintenance, future): takes over "New elements" and `KilnCounts`.
- #21 (a repeated "Start load"): unchanged; the test checkbox goes through the same
  route.
- #12 (a long-term anonymized record): separate; firing records and notes are kept with
  their loads and aren't anonymized, as they hold no personal details.

## Out of scope

- Importing the workbook's past firings (decided 16 November 2026, #42).
- Kiln maintenance tasks, reminders and kilns out of service (#43).
- Notes or rulings on a glaze type or clay with no firing (#17's decision).
- Reporting beyond the firing log's CSV; a table export for analysis is a later choice.
- Changing `ListLoads` (fired loads of the last 8 weeks) to read by date range; it stays
  as it is.

## Security

- **Personal data:** none added. A firing record holds numbers and studio items; a load's
  history and notes hold staff usernames, never a name, email address, phone number,
  rejection message or photo. A note's text is refused if it holds something shaped like
  an email address or phone number, and the form says notes hold no personal details.
  The close (#7) doesn't touch any of it, and logs carry load IDs, note IDs and usernames
  only, never a note's text.
- **The public form:** unchanged. The form function gains no right, reads nothing new and
  shows nothing new. The ready email is unchanged, and no email carries a record, a note
  or a ruling.
- **Who can open the console:** unchanged. Every new route checks the token and the
  `ceramics` group, and every POST checks the CSRF token. The CSV download needs the same
  sign-in, and its cells can't start a formula.
- **Escaping:** every note's text and every value shown is escaped by Jinja2's
  autoescape; no `|safe` on anything staff typed.
- **AWS:** the console role can query a load's partition and take note numbers; no other
  role changes. No new resource, name or tag.
