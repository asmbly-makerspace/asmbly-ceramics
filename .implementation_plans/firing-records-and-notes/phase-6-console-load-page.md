---
phase_id: 6
title: "Console: the load page's steps, firing record, test and history"
epic: 1
implements: [42]
depends_on: [5]
domain: [web]
estimated_size: L
---

# Phase 6: Console: the load page's steps, firing record, test and history

> **Status:** [ ] Pending

## Required reading

- [README](README.md); [phase 5](phase-5-use-cases-record-and-log.md)'s hand-off.
- The design, artboard "Load page: firing record and notes":
  https://claude.ai/artifact/7FTCn2AgGzoXEA3RhrMKpi (the status steps with a person
  icon, username and time; the firing record's four groups; "Correct time").
- `src/asmbly_ceramics/web/console/loads.py`, `web/console/__init__.py`,
  `web/templates/console/load.html` and `loads.html`, `tests/web/console/test_loads.py`:
  the routes, the Post/Redirect/Get, `form_version`, `require_staff_post`, and how each
  `DomainError` becomes a message.
- `src/asmbly_ceramics/web/console/settings.py` and `templates/console/_history.html`: a
  history list on a console page.
- `src/asmbly_ceramics/web/console/common.py`: `parse_date`, `render`, `services`.
- Story #42's criteria "Who moved the load", "Test firings" and "The firing record".

## Goal

On a load's page, staff see who moved the load through each step and when, can correct
a step's time, can fill in and save the firing record at any stage, and can read the
load's history. "Start a load" and "Change kiln, firing or date" have a "This is a test
firing" checkbox, and an empty test load can start firing. The loads list tags tests.

## Files to create

- `src/asmbly_ceramics/web/templates/console/_record.html`: the firing record form.
- `src/asmbly_ceramics/web/templates/console/_steps.html`: the status steps with who and
  when.

## Files to modify

- `src/asmbly_ceramics/web/console/__init__.py`: two routes.
- `src/asmbly_ceramics/web/console/loads.py`: the record and step-time handlers; `test` on
  start and change; the view's new parts in the page's context.
- `src/asmbly_ceramics/web/templates/console/load.html`: the steps, the record, the
  history, the test tag; "Start firing" enabled for an empty test.
- `src/asmbly_ceramics/web/templates/console/loads.html`: the checkbox on "Start a load";
  a "Test" tag in both lists.
- `src/asmbly_ceramics/web/static/` (the console's stylesheet): the step and record
  layout, from the design's tokens already in use.
- `tests/web/console/test_loads.py`, `tests/web/console/test_privacy.py`.

## Implementation details

### web: routes

| Method and path | Who | Use case |
| --- | --- | --- |
| `POST /console/loads/{load}/record` | `ceramics`, CSRF | `SaveFiringRecord` |
| `POST /console/loads/{load}/steps/{step}/time` | `ceramics`, CSRF | `CorrectStepTime` |

Both answer 303 to `/console/loads/{load}?saved=record` or `?saved=time` (a fixed word,
as the other handlers do), or render the load page again with the messages (422) and the
values typed kept. `{step}` is `started`, `firing` or `fired`, else 404. `{load}` is
parsed as the other routes do.

### web: the firing record form (`_record.html`)

Shown on every live load (loading, firing, fired), in the design's four groups: Kiln
(% full, firing #, all time #, with the suggestion as the field's value and a hint "Suggested
from Helios's last firing" when `view.suggested` is used), Program (cone select from
`view.cones`, speed select, preheat, hold), Result (firing time, cost, max temp, board
temp), Witness cones (top, center, bottom, each a number field and a "No cone" checkbox
that sends `none`).

- Field names are `RECORD_FIELDS`. Each input has `inputmode="numeric"` or `decimal`,
  `min`/`max` and `maxlength` matching `domain/limits.py` (passed in the context, never
  typed in the template), and a unit beside it (%, °F, hours, min, $).
- `version` hidden, `csrf` hidden. One "Save firing record" button, and the note "Saving
  changes only the record. Drop-offs and emails aren't touched."
- An `InvalidRecord` shows each message under its field (`field-invalid`,
  `aria-describedby`), with a summary at the top naming how many fields need fixing.
- `Conflict`: the page reloads with "Someone else changed this load. Check it and save
  again." and the values typed kept.
- After `?saved=record`: "Firing record saved."

### web: the steps (`_steps.html`)

An `<ol aria-label="Status">` of `view.steps`: each with its label, and when reached a
person icon (inline SVG, `aria-hidden`, with "by" as visible text), the username (or "not
recorded") and the Austin time (`austin_time`). The current step is `aria-current`.

Each reached step has "Correct time" (a `<details>` holding a form):
`<input type="datetime-local" name="at">` prefilled with the step's Austin time,
`version`, `csrf`. The handler parses it as Austin local time (`STUDIO_TZ`), refuses a
malformed or out-of-range value with "Enter a date and time." next to the field, and
shows `StepNotReached`, `StepTimeInFuture` and `StepTimeOutOfOrder`'s messages there.

### web: test firings

- "Start a load" and "Change kiln, firing or date": `<label><input type="checkbox"
  name="test" value="1"> This is a test firing</label>`, with the hint "A test can be
  fired with no drop-offs. You can't change this once it starts firing." The handler
  reads `test` as `form.get("test") == "1"`; any other value is false. The change form
  shows the checkbox only while loading (the form is only shown then).
- Phase 1 left two literal `test=False` arguments in `web/console/loads.py` (marked
  `# phase 6 asks`): `console.start_load(..., test=False)` in the start handler and
  `console.change_load(..., test=False)` in the change handler. Replace both with the
  value read from the form in the same change as the checkbox, so neither form shows a
  checkbox its handler ignores; a test starts and changes a load with `test=1` and sees
  `load.test` true.
- The load page's head shows a "Test" tag beside the ID; `loads.html` shows it in the
  open and fired lists.
- "Start firing" is enabled when `view.can_start_firing`; for an empty test load the hint
  "Add a drop-off first." isn't shown.
- Marking an empty test load fired: the confirm panel says "No one is emailed." in place
  of the email count.

### web: the history

A "History" `<section>` at the foot of the load page: `view.history`, oldest first, each
"Nov 12, 4:10 pm · staff.a · Started firing", escaped. Long loads stay readable: the
list is in a `<details open>` with its count.

### Phones

The record's groups stack to one column below 40rem (the design's
`minmax(min(100%, 18rem), 1fr)` grid); every control is at least 44px tall; the
`datetime-local` input opens the phone's picker.

## Tests

`tests/web/console/test_loads.py`:

- `test_record_saved_redirects_and_shows`; `test_record_invalid_fields_shown_and_kept`;
  `test_record_conflict_message`; `test_record_on_fired_load`;
  `test_record_needs_csrf`; `test_record_not_in_group_not_allowed`;
  `test_record_signed_out_redirects_to_sign_in`; `test_record_unknown_load_404`.
- `test_step_time_corrected`; `test_step_time_malformed`; `test_step_time_in_future`;
  `test_step_time_out_of_order`; `test_step_unknown_404`; `test_step_needs_csrf`.
- `test_steps_show_who_and_when`; `test_old_load_firing_not_recorded`.
- `test_start_test_load`; `test_test_checkbox_other_value_is_false`;
  `test_empty_test_load_can_start_firing`; `test_test_tag_on_lists_and_page`;
  `test_change_load_marks_test`.
- `test_history_listed_and_escaped` (a kiln name with `<b>` shows escaped). A test
  that checks the history's order advances the clock between steps: two events at one
  instant come in no promised order (`Records.load_events`).
- `test_record_limits_match_domain` (every `min`/`max`/`maxlength` in the form equals
  `domain/limits.py`).

`tests/web/console/test_privacy.py`: the record and history pages hold no drop-off's
name, email or phone beyond what the load page already shows to staff; the redirect
addresses hold no value typed.

## Acceptance criteria

1. Each reached step shows a person icon, the username and the time; a step not reached
   shows nothing; an old load's unknown username shows "not recorded" (#42).
2. Staff correct a reached step's time; the refusals are shown next to the field (#42).
3. The firing record is filled in and saved on a loading, firing or fired load; every
   refused field is shown next to it, and nothing else changes (#42).
4. "This is a test firing" is chosen when the load is started, changeable only while
   loading; an empty test load can start firing; tests are tagged on the page and in the
   loads list (#42).
5. The load's history is shown, escaped (#42).
6. Every new route checks the token, the `ceramics` group and the CSRF token (#42
   "Only signed-in ceramics staff").

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest --cov`
- [ ] No `|safe` on anything staff typed; the CSP and headers are unchanged.
- After the merge, on stage and on a phone: start a test load with no drop-offs, start
  firing, mark it fired (no email), fill in the record with the design's values, correct
  the fired time, and read the history.

## Rollout

Code only, through the normal deploy. Check: the stage walk-through above. Undo: a revert
pull request.

## Admin actions

None (staff are told after phase 7).

## Hand-off

- [ ] Routes `POST …/record`, `POST …/steps/{step}/time`.
- [ ] Templates `_record.html`, `_steps.html`; the load page's history section.
- [ ] The test checkbox on start and change; the "Test" tag in `loads.html` and
      `load.html`.
- [ ] Both `test=False  # phase 6 asks` literals in `web/console/loads.py` (start and
      change) replaced by the form's value in the same change as the checkbox.
- From phase 5's review: correcting the fired step moves `load.fired_at` only; the
  load's drop-offs keep their own `fired_at`, so the page shouldn't say it changed them.
- From phase 5's review: two loads loading on one kiln at once are both suggested the
  same next number (`LoadView.suggested`); a load fired at or before the kiln's
  `counts.as_of` gets no suggestion. Prefill from `suggested` only as a suggestion.
- `StepView.can_correct` says whether to offer the time correction (False for a load
  made before #42's firing step); `CorrectStepTime` treats the same minute as unchanged.
