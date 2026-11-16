---
phase_id: 9
title: "Console: notes on a load and the notes search"
epic: 1
implements: [17, 42]
depends_on: [7, 8]
domain: [web, docs]
estimated_size: L
---

# Phase 9: Console: notes on a load and the notes search

> **Status:** [ ] Pending

## Required reading

- [README](README.md); phases [7](phase-7-console-firing-log-and-settings.md) and
  [8](phase-8-use-cases-notes.md)'s hand-offs.
- The design: https://claude.ai/artifact/7FTCn2AgGzoXEA3RhrMKpi, the load page's
  "Notes" section (a card per note with its ruling tag, its glaze and clay tags, who and
  when, Edit and Remove; "Add a note") and the "Firing log and notes search" artboard's
  Notes section.
- `src/asmbly_ceramics/web/console/loads.py` and `templates/console/load.html` after
  phase 6; `web/console/firing_log.py` after phase 7.
- `src/asmbly_ceramics/web/console/dropoffs.py`, the reject and delete confirm flows: a
  two-step confirm for "Remove".
- `docs/architecture.md`.
- Story #17's criteria.

## Goal

The load page shows its notes and lets staff add, edit and remove them. The "Firing log"
tab has a Notes view to search notes by kiln, glaze type, clay body, ruling and date, each
linking to its load. The firing log shows each load's note count, the last of #42's
criteria. With this phase #17 and #42 are done.

## Files to create

- `src/asmbly_ceramics/web/console/notes.py`: the note handlers and the search page.
- `src/asmbly_ceramics/web/templates/console/_notes.html`: the load page's notes and the
  add form.
- `src/asmbly_ceramics/web/templates/console/note_edit.html`.
- `src/asmbly_ceramics/web/templates/console/notes.html`: the search.
- `tests/web/console/test_notes.py`.

## Files to modify

- `src/asmbly_ceramics/composition.py`: wire phase 8's use cases.
- `src/asmbly_ceramics/web/console/__init__.py`: routes.
- `src/asmbly_ceramics/web/console/loads.py`, `templates/console/load.html`: include the
  notes.
- `src/asmbly_ceramics/web/console/firing_log.py`, `templates/console/firing_log.html`:
  the notes column; links between the Firings and Notes views.
- `tests/test_composition.py`, `tests/web/console/test_firing_log.py`,
  `tests/web/console/test_privacy.py`.
- `docs/architecture.md`: notes.
- The plan's README: phase tracker.

## Implementation details

### web: routes

| Method and path | Who | Use case |
| --- | --- | --- |
| `POST /console/loads/{load}/notes` | `ceramics`, CSRF | `WriteNote` |
| `GET /console/loads/{load}/notes/{note}/edit` | `ceramics` | `LoadNotes` (the one note) |
| `POST /console/loads/{load}/notes/{note}/edit` | `ceramics`, CSRF | `EditNote` |
| `POST /console/loads/{load}/notes/{note}/remove` | `ceramics`, CSRF | `RemoveNote` (after a confirm) |
| `GET /console/notes` | `ceramics` | `SearchNotes` |

`{note}` is parsed as a `NoteId`, else 404. Each POST answers 303 to
`/console/loads/{load}?saved=note#notes` (or `removed=note`), or the page again with the
messages (422) and the values typed kept.

### web: the note form

- `text`: a `<textarea maxlength="2000">` (from `NOTE_TEXT_MAX`, passed in), with the hint
  "No names, emails, phone numbers or photos. 2,000 characters at most. Write a ramp
  with units or commas (250 °F, 400 °F, 2232 °F)." above it: three numbers shaped like
  a phone number (three numbers of 3, 3 and 4 digits with spaces between) are refused (phase 3's decision), so the hint says how
  to write one that is kept.
- `ruling`: radio buttons "No ruling" (empty value), "Allowed", "Allowed with conditions",
  "Not allowed"; any other value is refused with "Pick a ruling from the list."
- `glaze_types`, `clay_bodies`: checkbox lists (better on a phone than a multi-select),
  from the active items; on edit, a retired item already on the note is listed and
  checked, marked "(retired)". Each value checked with `is_item_id`; at most
  `NOTE_TAGS_MAX` each.
- `InvalidNote`'s messages under their fields; `ItemRetired` and `UnknownItem` at the top.
- Edit: `version` hidden; `Conflict` reloads with "Someone else changed this note. Check
  it and save again."
- Remove: "Remove…" shows a confirm panel ("Remove this note? It disappears from this
  load and from the notes search.") with "Yes, remove" and "Keep it", as the delete
  flows do.

### web: the load page's notes

`<section id="notes">` after the firing record: "Notes (n)", then each note as a card: a
ruling tag (glyph and words, never colour alone: "✕ Not allowed", "! Allowed with
conditions", "✓ Allowed", "No ruling"), its tags ("Glaze: …", "Clay: …"), the text
(escaped, `white-space: pre-line`), "staff.b · Nov 15, 10:20 am", and "edited by staff.a,
Nov 16" when edited; Edit and Remove. Then "Add a note" (`<details>`, open when the load
has no notes). Shown on every live load.

### web: the notes search

`GET /console/notes` with `kiln`, `glaze`, `clay`, `ruling` (`any`, `none`, or a
`Ruling`), `from`, `to`, each checked as the firing log's are (an unknown value shows a
message and is ignored). A `GET` form; results as the same cards with "L-98 · Helios ·
Glaze" linking to the load's `#notes`. Empty: "No notes match." The "Firing log" tab
shows "Firings" and "Notes" as two links (the design's toggle), the current one marked.

### web: the firing log's notes column

`FiringLogRow.notes` is filled from `NoteCounts` (phase 8) in the page handler, or by
passing `NoteCounts` into `FiringLog` (whichever keeps `FiringLog`'s tests simplest; say
which in the hand-off). The column shows the count, with a "✕ n" tag when any is "not
allowed"; the CSV gains `notes` and `not allowed notes` columns.

### docs

`docs/architecture.md`: firing notes (what they hold and don't, their rulings and tags,
the search, kept with the load and never deleted by the close).

## Tests

`tests/web/console/test_notes.py`:

- `test_add_note`; `test_add_note_on_fired_load`; `test_add_note_text_required`;
  `test_add_note_with_email_refused`; `test_add_note_with_phone_refused`;
  `test_add_note_bad_ruling`; `test_add_note_unknown_tag`; `test_add_note_too_many_tags`;
  `test_add_note_text_escaped` (`<script>` shows as text).
- `test_edit_note`; `test_edit_shows_retired_tag_checked`; `test_edit_conflict`;
  `test_edit_unknown_note_404`; `test_edit_note_of_other_load_404`.
- `test_remove_needs_confirm`; `test_remove_note`.
- `test_search_each_filter`; `test_search_bad_values_messages`; `test_search_links_to_load`.
- Each route: `..._needs_csrf` (POSTs), `..._not_in_group_not_allowed`,
  `..._signed_out_redirects`.
- `test_notes_form_limits_match_domain`.
- `test_note_form_says_no_personal_details` (the add and the edit form show "No names,
  emails, phone numbers or photos." above the text box).

`tests/web/console/test_firing_log.py`: `test_notes_column`; `test_csv_notes_columns`.

`tests/web/console/test_privacy.py`: a note's text never appears in a redirect address
or a log line; the public form and the emails never show a note or a ruling (render
the ready and received emails for a load with notes and check).

## Acceptance criteria

1. Staff add a note at any stage, including after firing, and edit or remove it, with who
   and when shown (#17).
2. A note is tagged with glaze types and clay bodies from the studio's lists, and can
   carry a ruling (#17).
3. Staff search and filter notes by kiln, glaze type, clay body, ruling and date, and open
   the load a note came from (#17).
4. The form says notes hold no personal details, and the server refuses an email address
   or phone number in the text (#17).
5. Only signed-in ceramics staff read or write notes; anyone else sees "not allowed"
   (#17).
6. Notes and rulings are never on the public form or in emails (#17).
7. The text is checked for length on the server and escaped wherever it is shown (#17).
8. The firing log shows each load's note count (#42's "number of notes" column).

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] `uv run pytest tests/repo`
- After the merge, on stage and on a phone: add a made-up note with a "not allowed"
  ruling and two tags to a fired load; edit it; search by its clay body; see the count in
  the firing log; remove it.

## Rollout

Code and docs only, through the normal deploy. The first note written on stage is the
first note item in the table. Check: the stage walk-through. Undo: a revert pull request;
notes written stay in the table, unread. After prod's smoke test passes, the maintainer
tells ceramics staff about notes and sets this phase `[x]`.

## Admin actions

- Tell ceramics staff about notes and the notes search.

## Hand-off

- [ ] Note routes and the `/console/notes` search; phase 8's use cases wired.
- [ ] The firing log's notes column and CSV columns.
- [ ] #17's and #42's criteria are all met: its pull request says `Closes #17` and
      `Closes #42`.
- [ ] The plan is complete: move it to `DONE/` in a `chore:` pull request.
