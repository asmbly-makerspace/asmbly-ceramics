# Manual QA: Firing records and notes

Manual acceptance steps for `feat/firing-records-and-notes`, organized by story so each
check maps back to an issue (#42, #17).

> **Automated coverage** already passed the integration gate: 3723 tests passed, coverage
> 99.30% (the floor is in `pyproject.toml`). `sam validate --lint` and `sam build` were
> skipped: `sam` is not installed where the gate ran, so the `infra/app.yaml` change
> (the console role's `LOAD#*` query condition and `COUNTER#note` counter grant) was not
> checked by them. The domain's rules are tested against the in-memory fakes. The steps
> below cover what a person should confirm on a phone and in the console before merging.

## Prerequisites

- Where: locally for the steps marked "local", and stage (`ceramics-stage.asmbly.org`)
  for the rest. A merge to `main` deploys stage, then prod
  (`.github/workflows/deploy.yml`); run the stage steps after stage deploys, and watch
  both smoke tests. Locally: `uv run uvicorn asmbly_ceramics.web.local:app --reload`
  from the repository root. It runs on the in-memory fakes, so nothing reaches AWS and no
  email is sent; it can't show the staff sign-in, the "not allowed" page or emails, so
  those steps are stage only. No step here runs in prod.
- Admin actions (from the plan README): none in AWS or GitHub. After the merge and prod's
  smoke test, the maintainer tells ceramics staff about the firing record, the firing log
  and notes; asks them to enter each kiln's counts once (Settings > Kilns) and check each
  firing type's default program. Steps 20 to 24 on stage are a dry run of those
  two settings with made-up numbers; step 25 comes after the staff have been told.
- Accounts: a staff account in the `ceramics` group, and one signed in but outside it
  (to check "not allowed"). No account for the public form.
- Data: a kiln (for example Helios), a firing type with a default program (set it in
  Settings > Firing types), one waiting drop-off made through the public form with a made-up
  name ("Test Potter"), an address at `example.org` (or your own inbox, to receive the
  emails) and a photo you took for the purpose.
- Made-up details only. Never a member's name, address or photo.
- Devices: a phone and a desktop browser. A spreadsheet program for steps 17 and 18.

---

## #42: Staff keep a firing record on each load, and read each kiln's firing log (phases 1, 2, 3, 4, 5, 6, 7, 9)

### A test load with no drop-offs (stage)

1. In the console, open **Loads** (`/console/loads`). In the start-a-load form pick a
   kiln, a firing type and a date, tick **This is a test firing** and start the load →
   the page for the new load opens ("Load started. Add drop-offs below."), with a
   **Test** tag beside its ID, and the loads list shows the same tag.
2. Without adding a drop-off, press **Start firing** → firing starts ("Firing started.
   Nothing can be added or removed now."). The button works only because the load is a
   test.
3. Press **Mark fired**, then **Yes, mark fired** (the page says "The load is empty. No
   one is emailed.") → "Marked fired." No email arrives anywhere.
4. Start a second load without ticking the test box and leave it empty → **Start firing**
   is disabled and its hint says why. Keep this load for step 39.
5. On the fired load, the three status steps (Loading, Firing, Fired) each show a person
   icon with "by <your username>" and a date and time; a step not reached shows nothing.

### The firing record (stage; the same form shows locally)

6. On the fired test load, open the **Firing record** panel and fill in made-up values:
   % full 80, preheat 0 hours, cone ^6, speed Medium, hold 10 min, firing time 11:38,
   cost 8.19, max temperature 2232 °F, board temperature 410 °F, top 20 % bent, center 10 %
   bent, bottom ticked **No cone**. Press **Save firing record** → "Firing record saved.",
   and the record as saved is shown. No email is sent and the load's drop-offs don't change.
7. Enter 101 in **% full**, 2501 in **Max temp** and 101 in **Cost** (dollars), and save
   → the page refuses with a summary at the top and a message under each of those fields
   saying which field and why; the values you typed stay in the form; the saved
   record is unchanged.
8. Clear every field and save → "Firing record saved." with "Nothing is recorded." An
   empty record is allowed, and it doesn't block starting firing or marking fired.
9. On a new load in the loading state, start it with a firing type that has a default
   program → the record's Program fields are already filled in from it, and you can change
   them. Change the load's firing type while loading (**Save changes**) before touching
   the program → the program follows the new type's default.

### Correcting a step time (stage)

10. On the fired load, open **Correct time** under the Fired step, enter a time earlier than
    the Firing step's → refused with a message, nothing changed.
11. Enter a time after the Firing step and before now → "Time corrected."; the step shows
    the new time, with the same username. The username has no field to change.
12. Enter a time in the future → refused, nothing changed.

### The history (stage)

13. Open **History** at the foot of the load page → one line each for: started,
    firing started, fired, the firing record saved (the fields that changed with their
    new values), and the time correction (old and new times), each with a username and
    time. Adding or removing a drop-off from a loading load adds no line.

### Test firing with a drop-off, and the loading-only correction (stage)

14. Start a test load, add the waiting drop-off, start firing, mark fired → the "Ready for
    pickup" email arrives at the example.org address (or your inbox), from the studio's
    address at `asmbly.org`, and carries nothing from the firing record or any note.
15. On a test load that is still loading, **Save changes** after un-ticking "This is a test
    firing" → "Load changed." Once the load is firing, the form is gone and the choice
    can't be changed.

### The firing log and its CSV (stage)

16. Open **Firing log** in the console's navigation (`/console/firing-log`) → fired
    loads with the columns Load, Fired, Firing #, Full, Cone, Speed, Hold, Max temp,
    Cost, Started / fired by, Notes; a field not recorded shows a dash; the test load
    carries **Test**; each load ID opens its load.
17. Set **Firings** to "Tests only", then "No tests", then "All", and a kiln and date range
    (press **Show** each time) → the list narrows to match each time; with nothing
    matching it says "No firings match."
18. Press **Download CSV** with "Tests only" chosen and open the file in a spreadsheet →
    one row per listed firing, with columns including test, started by, firing started by
    and fired by, the record's fields, and the note counts; no names, emails or phone
    numbers.
19. Formula cells: a leading `=`, `+`, `-` or `@` in a cell must not run as a formula.
    Type a made-up firing type name starting with `=` in Settings (for example `=1+1`),
    start a load with it, fire it, and download the CSV again → the cell opens as plain
    text with a leading `'`, never as a formula. Retire the made-up type afterwards.

### Kiln counts and New elements (stage; local shows the page but no sign-in)

20. Open **Settings** and, on a kiln's row, **Firing counts: not set** → set "Firings since
    new elements" to 12 and "All time" to 40 (made-up) and press **Save counts** → the row
    summary shows both numbers.
21. Start a load for that kiln, start firing, mark it fired, and open its record → **% full
    is not touched**, but Firing # and All-time number are prefilled with 13 and 41, with the
    hint "Suggested from <kiln>'s firing count. Change it if it's wrong." Type another
    number over one and save → your number stays. (The suggestions are prefilled as real
    values on a loading load too: see the open calls below.)
22. In Settings, press **New elements…** on that kiln, then **Yes, new elements** → the next
    fired load's suggested Firing # is 1 and its all-time number carries on. Every firing
    counts: a load fired without a saved record (an empty test one too) still moves both
    numbers on by one.
23. In Settings > Firing types, check each type's default program (cone, speed, preheat
    hours, hold minutes), correct it with **Save program**, and see the new load use it.
24. Enter a count over the page's limit, or a negative one → refused with a message under
    the field, and the stored counts are unchanged.
25. After the merge and prod's smoke test, the maintainer tells ceramics staff (the admin
    action), and staff enter each kiln's real counts once in Settings > Kilns → each kiln's
    row shows its counts and the next fired load suggests numbers from them.

### Access (stage)

26. Signed in as the account outside the `ceramics` group, open `/console/firing-log`,
    `/console/firing-log.csv` and a load's page → each shows "Not allowed". No firing data and
    no CSV is returned.

## #17: Staff keep firing notes they can look up later (phases 2, 3, 4, 8, 9)

### Writing and editing notes (stage)

27. In Settings, check the clay body list shows the starting items and add a made-up
    one → it shows in the list.
28. On the fired test load, open **Add a note**. Write "Cone 5 porcelain cracked at
    the base in a fast cool. Needs a slower cool." Tick one glaze type and two clay bodies,
    choose the ruling **Not allowed**, press **Save note** → "Note added." The note
    shows at the top of **Notes (1)**, newest first, with its ruling, tags, your username
    and the time.
29. Add a second note on the same load with **No ruling**, then a third with **Allowed with
    conditions** → three notes, newest first. Notes can be added after the load is fired.
30. **Edit** the first note, change its text and ruling → "Note saved."; it shows who edited
    and when. Add a note to an unfired load too → it saves.
31. Write a note of 2,001 characters → refused ("The note is longer than 2,000 characters.").
    An empty note → "Write the note."

### Notes that look like personal details (stage)

32. Write a note holding an email address at `example.org` → refused with "Notes can't
    hold an email address or phone number."; the note isn't saved and your text stays in
    the form.
33. Write a note holding a phone-number-shaped run of digits (a made-up one) → refused
    with the same message.
34. Write a note containing a ramp as three numbers of 3, 3 and 4 digits separated by
    spaces (the three ramp temperatures of the hint below, with no units or commas) → refused with the same message, as a
    phone number would be. The note form's hint says "Write a ramp with units or commas
    (250 °F, 400 °F, 2232 °F)." Write the ramp that way → the note is saved.

### Searching notes (stage)

35. Open **Notes** (`/console/notes`; the link is on the load's page and the Firing log's
    Notes column) → the filter has Kiln, Glaze type, Clay body, Ruling, Written from and
    Written to. Filter by one of the clay bodies you tagged, then by the ruling, then by
    the kiln, then by a date range → each result lists only matching notes, with the
    load's ID, kiln and firing type; the load ID opens the load at its notes.
36. Filter to something no note has → "No notes match."
37. Open the Firing log → the load's Notes column shows the count, and a "not allowed"
    tag counts the notes with that ruling.

### Removing a note and deleting a load (stage)

38. Press **Remove…** on a note, then **Keep it** → the note stays. Press **Remove…** again,
    then **Yes, remove** → "Note removed."; it is gone from the load and from the notes
    search, and the Firing log's count drops by one. (Product call below: its text is kept.)
39. On a load that has a note and is still loading (or firing), use **Delete this load**,
    type its ID, and confirm → "Load <ID> deleted." and its drop-offs are back in the
    waiting list. Its notes no longer show in `/console/notes`. A deleted load takes no
    new note.

### Access (stage)

40. Signed in as the account outside the `ceramics` group, open `/console/notes` and a
    note's edit page (`/console/loads/<load ID>/notes/<note ID>/edit`) → "Not allowed". A
    post to add, edit or remove a note is refused too.
41. Open the public drop-off form and a drop-off's emails → no note, ruling, firing record
    or history appears anywhere.

---

## Open product calls for the maintainer

These are decisions the diff makes that the stories leave open. Look at them while
working through the steps, and say if any should change.

- **Suggested firing numbers are real values.** On a load that is still loading, the
  firing number and all-time number are prefilled as ordinary values, not as greyed
  placeholders. Saving the record without touching them stores the suggestion. Staff
  never lose a typed number, but a suggestion saved by accident looks like a real count.
- **An empty, unnumbered test firing (decided).** The maintainer decided after the
  merge that any firing counts toward the firing numbers, whether it was empty, a test,
  or not. A follow-up change makes the suggestion count every fired load after the
  kiln's counts, numbered or not: fire an empty test load on a kiln with counts 12 and 40
  without saving a record, and the next load suggests 14 and 42.
- **A removed note keeps its text.** A removed note is hidden (a soft delete with who
  and when), and its text stays in the table. Say if removing should erase the text.

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```
