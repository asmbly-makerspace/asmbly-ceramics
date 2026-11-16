---
phase_id: 7
title: "Console: the firing log, its CSV, and the new settings"
epic: 1
implements: [42]
depends_on: [6]
domain: [web, docs]
estimated_size: L
---

# Phase 7: Console: the firing log, its CSV, and the new settings

> **Status:** [~] In progress

## Required reading

- [README](README.md); phases [2](phase-2-studio-cones-clays-programs-counts.md),
  [5](phase-5-use-cases-record-and-log.md) and [6](phase-6-console-load-page.md)'s
  hand-offs.
- The design, artboard "Firing log and notes search":
  https://claude.ai/artifact/7FTCn2AgGzoXEA3RhrMKpi (the filters, the table, "Download
  CSV", the "Test" tag).
- `src/asmbly_ceramics/web/console/counts.py` and `templates/console/counts.html`: a
  read-only console page with query parameters.
- `src/asmbly_ceramics/web/console/settings.py`, `templates/console/settings.html`,
  `tests/web/console/test_settings.py`: the settings forms, their CSRF and version
  checks.
- `src/asmbly_ceramics/web/templates/console/layout.html`: the tabs.
- `docs/architecture.md`, "The domain, as the stories describe it".
- Python's `csv` module documentation; OWASP's "CSV Injection" page (cells starting with
  `=`, `+`, `-`, `@`, tab or carriage return).
- Story #42, "The firing log" and "Firing number", "Program".

## Goal

A "Firing log" tab lists fired loads by kiln, date range and kind, with the record's main
fields as columns and a CSV download. Settings lets staff set each firing type's default
program, each kiln's counts, and "New elements", and the docs describe them. This phase
refs #42; #42's firing log also has a notes count column, which phase 9 adds, so phase 9
is the one that closes #42 (with #17).

## Files to create

- `src/asmbly_ceramics/web/console/firing_log.py`: the page and the CSV.
- `src/asmbly_ceramics/web/templates/console/firing_log.html`.
- `tests/web/console/test_firing_log.py`.

## Files to modify

- `src/asmbly_ceramics/web/console/__init__.py`: routes.
- `src/asmbly_ceramics/web/templates/console/layout.html`: the "Firing log" tab.
- `src/asmbly_ceramics/web/console/settings.py`, `templates/console/settings.html`:
  programs, counts, new elements.
- `tests/web/console/test_settings.py`.
- `docs/architecture.md`: the load's test flag, steps, record and history; the firing log;
  the studio's new lists and fields.
- `docs/README.md`: nothing unless it indexes pages (check).
- `CLAUDE.md`: "What this repository serves" (the settings that are data) and "The shape
  of the code" ("Settings as data") gain the cones, clay bodies, default programs and kiln
  counts. Add or correct only; no rule is cut.
- `README.md`: the Status paragraph names the firing record and the firing log among the
  console's pages, and #42 in the stories table.
- `.implementation_plans/firing-records-and-notes/README.md`: phase tracker.

## Implementation details

### web: routes

| Method and path | Who | Use case |
| --- | --- | --- |
| `GET /console/firing-log` | `ceramics` | `FiringLog` |
| `GET /console/firing-log.csv` | `ceramics` | `FiringLog` |
| `POST /console/settings/firing-types/{item}/program` | `ceramics`, CSRF | `SetDefaultProgram` |
| `POST /console/settings/kilns/{item}/counts` | `ceramics`, CSRF | `SetKilnCounts` |
| `POST /console/settings/kilns/{item}/new-elements` | `ceramics`, CSRF | `RecordNewElements` |

Register the two settings item routes before the generic `/console/settings/{list}/…`
routes if Starlette would match those first; `{item}` is checked with `is_item_id`.

### web: the firing log page

Query parameters, each checked on the server and ignored-with-a-message when bad, never
echoed into a log:

- `kiln`: an item ID of the studio's kilns, or empty for all; an unknown one shows "Pick
  a kiln from the list." and the default list.
- `from`, `to`: `YYYY-MM-DD` (`parse_date`); defaults from `FiringLog`. `InvalidLogRange`
  shows its message.
- `kind`: `all`, `tests` or `regular`; anything else is `all`.

The form is a `GET` form (no CSRF: it changes nothing). The table, in an
`overflow-x: auto` box: Load (link, with a "Test" tag), Fired (Austin day), Firing #,
Full, Cone, Speed, Hold, Max temp, Cost, and "Started / fired by" (usernames). A missing
value is "–". The notes column comes in phase 9. When one kiln is chosen and it has
counts: "Firing # counts from <date> (<n> since elements then)." Empty: "No firings match."

"Download CSV" links to `/console/firing-log.csv` with the same query.

### web: the CSV

`text/csv; charset=utf-8`, `Content-Disposition: attachment;
filename="firing-log-<kiln or all>-<from>-<to>.csv"` (built from the checked values
only), `Cache-Control: no-store`. Columns: load, kiln, firing type, test (yes/no), date,
started at, started by, firing started at, firing started by, fired at, fired by,
percent full, firing number, all time number, preheat hours, cone, speed, hold minutes,
firing time, max temp f, board temp f, cost, cone top, cone center, cone bottom. Times in
Austin, ISO 8601 with offset. Written with `csv.writer`. Every cell passes `csv_cell`:
a value starting with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with
`'`. (Kiln, firing type and cone names are staff-typed settings, so this matters.) No
personal details: usernames only.

### web: settings

On the settings page, in each list's rows:

- **Firing types:** "Default program" (`<details>`): cone, speed, preheat, hold, with the
  current program; "Save program"; all blank clears it. `InvalidRecord`'s messages next
  to each field.
- **Kilns:** "Firing counts" (`<details>`): "Firings since new elements" and "All time",
  with "as of <date>" when set; "Save counts". And "New elements…": a confirm step ("Firing
  # for Helios restarts at 1 from its next firing. The all-time count carries on.") then
  "Yes, new elements". Each with `version` and `csrf`; `Conflict` reloads with the
  existing message.

Each saved change shows in the settings history (phase 2 writes it).

### docs

`docs/architecture.md`, "The domain, as the stories describe it", gains: a load's
`test`, who and when for each step, the optional firing record and its history; the
studio's cones, clay bodies, default programs and kiln counts. "Today" mentions the
firing log. Nothing in decision records changes.

`CLAUDE.md`'s list of settings that are data, and its domain model's list, add the cones,
clay bodies, each firing type's default program and each kiln's firing counts. `README.md`'s
Status says the console has the firing record and the firing log, and its stories table
gains #42.

## Tests

`tests/web/console/test_firing_log.py`:

- `test_lists_fired_loads_default_range`; `test_filter_kiln`; `test_filter_kind_tests`;
  `test_filter_kind_regular`; `test_unknown_kiln_message`; `test_bad_dates_message`;
  `test_range_too_long_message`; `test_missing_values_dash`; `test_test_tag`;
  `test_counts_line_for_one_kiln`.
- `test_csv_headers_and_rows`; `test_csv_filename_from_checked_values`;
  `test_csv_formula_cells_prefixed` (a kiln named `=HYPERLINK(...)` via a made-up
  studio); `test_csv_no_personal_details` (a load with made-up drop-offs: no name, email
  or phone in the CSV); `test_csv_no_store`.
- `test_firing_log_not_in_group_not_allowed`; `test_firing_log_signed_out_redirects`;
  `test_csv_signed_out_redirects` (no CSV to anyone signed out).
- `test_tab_shown_and_current`.

`tests/web/console/test_settings.py`:

- `test_set_default_program`; `test_clear_default_program`;
  `test_default_program_invalid_fields`; `test_set_kiln_counts`;
  `test_kiln_counts_invalid`; `test_new_elements_confirm_then_reset`;
  `test_each_needs_csrf`; `test_each_conflict`; `test_unknown_item_404`.

## Acceptance criteria

1. Staff list fired loads by kiln and date range, with the main fields as columns, a dash
   for what wasn't recorded, and a "Test" tag (#42 "The firing log").
2. Staff filter by all, tests only, or no tests (#42 "Test firings").
3. Each row opens its load (#42).
4. The CSV holds the listed firings, whether each was a test, and who started, fired and
   marked each fired; no personal details beyond usernames; no cell can start a formula
   (#42).
5. Staff set each kiln's starting counts and record new elements, and each firing type's
   default program, in Settings, with history (#42 "Firing number", "Program").
6. Only signed-in ceramics staff reach the page and the CSV (#42).

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] `uv run pytest tests/repo` (the docs' links resolve).
- After the merge, on stage: set Helios's counts (made-up numbers), fire a made-up load
  and see its suggested numbers; open the Firing log, filter tests only, download the CSV
  and open it in a spreadsheet; record new elements and see the next suggestion is 1.

## Rollout

Code and docs only, through the normal deploy. Check: the stage walk-through. Undo: a
revert pull request. After prod's smoke test passes, the maintainer tells ceramics staff
(README, Admin actions), and sets this phase `[x]`.

## Admin actions

- Tell ceramics staff the firing record and log are live; ask them to enter each kiln's
  counts and check the firing types' default programs; the workbook's log tabs can stop.

## Hand-off

Status stays `[~] In progress` until the maintainer walks the stage check above after the
merge (counts set, a made-up load fired with its suggested numbers, the log filtered to
tests, the CSV opened in a spreadsheet, new elements recorded); a later pull request sets
`[x]`.

- [x] `GET /console/firing-log` (`firing_log.firing_log_page`) and
      `/console/firing-log.csv` (`firing_log.firing_log_csv`), both behind
      `require_staff`; `firing_log.csv_cell` prefixes `'` to a cell starting with `=`,
      `+`, `-`, `@`, a tab or a carriage return (`FORMULA_STARTS`), and every CSV cell
      passes it. `CSV_COLUMNS` is the header row. Query parameters are read by
      `_query` (an item ID's shape, `parse_date`, `KINDS`) and `_read` (an unknown kiln
      or an `InvalidLogRange` falls back with `PICK_KILN` or the range's message); a
      refused value is never echoed. "Download CSV" carries `LogQuery.as_params()`, the
      checked query as given: with no dates it sends none, so the CSV reads the same
      default range (with `LOG_DEFAULT_AHEAD`) as the page. The page's date fields hold
      only the dates the query gave (blank by default, so the filter form, sent back,
      keeps loads dated ahead), and a line under the filter says the range shown. The
      CSV never falls back: a refused kiln or range answers 400 with its message
      (`PageError`). Its record cells are `domain.firing.record_values`' texts (the cone
      by name). The filename is built from `view.kiln`, `view.start` and `view.end`. The
      Fired column and the counts line show the year (`mail.compose.austin_date`).
- [x] `firing_log.html` has the notes column behind `show_notes` (true once any
      `FiringLogRow.notes` is not None): phase 9 fills `notes` and the column appears.
      A Kiln column shows when all kilns are listed.
- [x] Settings routes `POST /console/settings/firing-types/{item}/program`
      (`settings.set_default_program`), `/console/settings/kilns/{item}/counts`
      (`settings.set_kiln_counts`) and `/console/settings/kilns/{item}/new-elements`
      (`settings.record_new_elements`), each behind `require_staff_post`, `{item}` checked
      with `is_item_id` (404), `UnknownItem` 404, `InvalidRecord` / `InvalidSetting` 400
      with the message next to each field, the typed values kept and a top banner
      (`CHECK_PROGRAM`, `CHECK_COUNTS`), `Conflict` 409 (`CHANGED_ELSEWHERE`, the typed
      program or counts kept, open), `CommitOutcomeUnknown` 503. The program form's cones
      are `domain.studio.nameable_cones`, the rule `set_default_program` and the firing
      record also use. The counts form starts blank (the summary shows the stored counts
      with their date), so saving it untouched can't re-date old counts. All three are in
      `tests/web/console/test_auth.py`'s `POSTS` (signed out, outside the group, CSRF,
      origin). The "New elements…" confirm step is a `<details>` with "Yes, new
      elements".
- [x] The "Firing log" tab in `layout.html` (`tab == "firing-log"`).
- [x] `docs/architecture.md`, `CLAUDE.md` (settings as data) and `README.md` (Status, #42).
- [x] This phase's pull request says `Refs #42`, not `Closes #42`: the notes count
      column of #42's firing log comes with phase 9, which closes #42 and #17.
- `sam validate` and `sam build` weren't run (no `sam` here; no template change).
