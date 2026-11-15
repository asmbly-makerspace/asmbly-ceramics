# Manual QA: Drop-offs and firings (phases 7 to 9)

Manual acceptance steps for `feat/drop-off-and-firing-phases-7-9`, organized by story so
each check maps back to an issue (#2, #3, #4, #5, #6, #7).

> **Automated coverage** already passed the integration gate: 2797 tests passed, coverage
> 99.15% (the floor is in `pyproject.toml`), nothing skipped. The domain's rules are
> tested against the in-memory fakes. The steps below cover what a person should confirm
> on a phone and in the console before merging, and on stage right after it.

## Prerequisites

A merge of this branch deploys: the Deploy workflow deploys stage, runs the smoke test,
then deploys prod and runs the smoke test again. Each step says where it runs: locally,
stage (`ceramics-stage.asmbly.org`) or prod (`ceramics.asmbly.org`).

- **Admin actions before the merge** (by an admin in Asmbly's AWS account, when the
  maintainer asks; none of these is done by this branch):
  - [the AWS bootstrap runbook](../../../../docs/runbooks/aws-bootstrap.md), steps 5 to 8:
    the GitHub environment secrets and variables (5), the app's keys (6), the two
    addresses (7), the boundary check (8).
  - In asmbly-staff-login: the `ceramics-staff` client (scope `openid`) and
    its client-id parameter.
  - The answer to question 2 in issue #20.
- **Admin actions after the first deploy:** confirm the alarm topic's email subscription
  (the email AWS sends to the maintainers' alert address; see
  [operations](../../../../docs/runbooks/operations.md#things-that-dont-change-with-a-deploy)).
  Stage's first `close_run` proves the close role's `GSI1` `LeadingKeys` condition
  (step 48).
- **Locally**, for steps 1 to 8: `uv run uvicorn asmbly_ceramics.web.local:app --reload`,
  then open `http://127.0.0.1:8000/` in a phone-sized window. This runs on in-memory
  fakes; no email is sent and nothing reaches AWS. The console is not part of it.
- **Accounts:** for stage steps, a staff account in the `ceramics` group and one signed
  in but outside it. No account for the public form.
- **Data (stage):** the studio's kilns (Athena, Helios, Vulcan), firing types and glaze
  types exist after first use. Make test drop-offs with the form as in #2, bisque and
  glaze, so the console steps have waiting drop-offs (at least 3 glaze, 1 bisque).
- Made-up details only: a name like "Test Potter", an address at `example.org` or your
  own inbox to receive the emails, a made-up phone number, and test photos you took for
  the purpose, never a member's.
- **Devices:** a phone (the form and the load page at the kiln) and a desktop browser
  for the console.

---

## #2: Drop off a piece and get an ID on screen (phases 1b, 1d, 2a, 2b, 2c, 4, 6, 7)

1. (Locally) Open `/` on a phone-sized window, no sign-in → the form shows the Asmbly logo
   and ceramics colours, with name, email, phone, pieces, firing type and photos.
2. (Locally) Choose "glaze" as the firing type → the glaze type field appears and is
   required; choose "bisque" → it disappears.
3. (Locally) Fill in "Test Potter", a made-up email at `example.org`, a made-up phone,
   2 pieces, bisque, one photo, and Submit → a page shows an ID like `AC-1`.
4. (Locally) Submit a second drop-off straight away → it shows the next ID, `AC-2`.
5. (Locally) Submit with an invalid email, then an invalid phone, then a missing name →
   a message appears next to each field and nothing is saved.
6. (Locally) Choose a file that isn't an image, then a photo over 10 MB, then a seventh
   photo → each is refused with a message next to the photos field.
7. (Stage, after the deploy) On a phone open `https://ceramics-stage.asmbly.org/`, fill
   in the form with an inbox you own and two photos, and Submit → the ID page appears.
8. (Stage) Wait up to a minute → "We received your drop-off" arrives from the studio's
   sending address at `asmbly.org`, with the ID, what was dropped off, and both photos
   inside the email.
9. (Stage) Save an emailed photo and open it in an EXIF viewer → no GPS fields.
10. (Stage) On an iPhone, pick a photo from the library → it is accepted (HEIC is
    converted under the form's `accept` list).
11. (Stage) Submit 11 drop-offs from one device within 10 minutes → the eleventh is
    refused with "Too many drop-offs from here in the last few minutes. Try again
    later." and takes no ID.
12. (Stage) Open a photo's storage address (from the console, step 18) in a private
    window → "access denied", not the photo.
13. (Stage and prod) Watch the Deploy run to the end → both smoke tests pass (health,
    console health, the form's headers, the console's redirect to the staff sign-in,
    an upload slot and a refused 10 MB + 1 byte upload, private photo addresses).

## #3: Ceramics staff sign in and see what's waiting (phases 1c, 2d, 8)

14. (Stage, after the admin actions) On a phone open
    `https://ceramics-stage.asmbly.org/console` signed out → you are sent to the staff
    sign-in page, and after signing in as a `ceramics` staff member you land on "Waiting to
    fire".
15. (Stage) Sign in as an account outside the `ceramics` group → "Not allowed", with
    "Sign in as someone else" and a link to the drop-off form.
16. (Stage) In the waiting list → drop-offs are oldest first, each with ID, name, pieces,
    firing type, glaze type, a photo thumbnail and days waiting; bisque and glaze are each
    totalled in pieces.
17. (Stage) Find a test drop-off in the search box by `AC-12`-style ID, by just the number,
    and by part of the name → each finds it.
18. (Stage) Open the drop-off → all its photos show at full size.
19. (Stage) With 30 or more waiting test drop-offs, open the list on two devices and
    scroll to the end → every thumbnail loads (this is the console's role meeting real
    IAM for the first time).
20. (Stage) Copy a photo's console address into a private window → it asks to sign in
    (401) and shows no photo.
21. (Stage) Read the console's log group for the session → no name, email, phone or
    message; drop-offs appear by ID and staff by username.

## #5: Reject a drop-off with a reason and a message (phases 1b, 2c, 2d, 8)

22. (Stage) On a waiting test drop-off choose a reason "Other" and leave the message empty,
    then "Preview the email" → the message field says it is needed.
23. (Stage) Write a message of more than 1,000 characters → it is refused with a message.
24. (Stage) Write a short message and "Preview the email" → the preview shows the email
    as it will go out; nothing is sent yet.
25. (Stage) Send → "Your drop-off needs attention" arrives from the studio's address with
    the ID, photos, reason, message and what to do next, and the drop-off has left the
    waiting list.
26. (Stage) Try to add the rejected drop-off to a load (step 28's page) → it is refused
    with the reason.
27. (Stage) "Undo rejection" the same day → the drop-off is waiting again and no email
    arrives.

## #4: Build a kiln load and fire it (phases 1c, 1d, 3, 7, 9)

28. (Stage) Under loads, start a load in Athena for glaze, dated today → its page opens,
    showing the kiln, firing type and date.
29. (Stage) Add a drop-off by typing its number → it appears with ID, name, pieces and
    thumbnail, and the totals for drop-offs and pieces update.
30. (Stage) Add another by searching its name and choosing the result, and a third with
    "Add" in the waiting list (filtered to glaze by default) → both appear.
31. (Stage) Type an ID that isn't waiting, then one already in a load → each is refused
    with the reason.
32. (Stage) Add a bisque drop-off → you are asked to confirm; "Add anyway" adds it.
33. (Stage) "Remove" one row → it returns to the waiting list.
34. (Stage) Open the load on a phone or tablet → the rows and buttons are readable.
35. (Stage) "Start firing", then try to add or remove → both are refused.
36. (Stage) "Mark fired" and confirm with "Yes, mark fired" → each drop-off gets one
    "Ready for pickup" email with the ID, photos, pickup window and pickup hours.
37. (Stage) Mark it fired again → no more emails arrive; the fired load can't be changed.
38. (Stage) Open the past load from the loads list → its contents are still shown.
39. (Stage) Failed-email alarm: make one test drop-off, then (the maintainer, by hand, on
    stage only, only when he asks for it in the conversation) delete its first photo from
    the stage bucket and re-mark the email `pending` → the email is marked failed, the
    load's page and the drop-off's page show it by ID, and the `email-failures` alarm
    notifies the maintainers' mailbox within about 5 minutes (needs the subscription
    confirmed).
40. (Stage) Restore the situation and use "Try sending again" on the load's page and on the
    drop-off's page → it goes only to that drop-off and the failure clears.

## #6: Staff manage the studio's settings in the console (phases 1a, 3, 9)

41. (Stage) Open Settings, type a sending address outside `asmbly.org` and save → refused
    with a message.
42. (Stage) Type a new address at `asmbly.org` and choose "Send a test email to me" → the
    test arrives in the signed-in staff member's inbox from the new address, before it is
    saved. Save.
43. (Stage) Change the pickup window and the pickup hours, save, then mark another test
    load fired → its email uses the new settings.
44. (Stage) Open the settings history → the changes show with your username and the time.
45. (Stage) Retire Helios → it is not offered for a new load and still shows on a past
    load; a kiln used by a drop-off or load has no usable "Delete".
46. (Stage) Add a glaze type, a rejection reason "Needs a message", and retire one → each
    appears in the lists.

## #7: Finished drop-offs close and personal details are deleted (phases 1b, 1c, 3, 9)

47. (Stage) Set the pickup window to 1 day before marking a test load fired (a fired
    drop-off keeps the window its ready email gave).
48. (Stage, the second morning after the firing) Look at the close's log group → a
    `close_run` line has `count` of at least the fired test drop-offs. This first run
    also proves the close role's `GSI1` `LeadingKeys` condition against real IAM.
49. (Stage) Open a closed test drop-off → it says "Closed", with no name, email, phone,
    message or photos; ID, dates, firing type, pieces, load and reason remain.
50. (Stage) Open a photo's old storage address → "access denied" or not found.
51. (Stage) Set the pickup window back to 14.
52. (Stage) Open Weekly counts → the test drop-offs and pieces by firing type, the load
    per kiln and the rejection by reason are counted; the Overdue section lists drop-offs
    waiting 60 days or more instead of deleting them.

---

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

Prod: after the stage steps pass and the maintainer says so, open
`https://ceramics.asmbly.org/` and `/console` signed out → the form loads and the console
sends you to the staff sign-in. Don't make test drop-offs on prod.
