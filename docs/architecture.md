# Architecture

This page says what the app must do (from epic #1's stories), the shape its code must
have, what it needs from other repositories, and what is still to be decided. What is
decided and why is in
[decision 0001](decisions/0001-the-ceramics-studio-has-its-own-repository.md).

## Today

Built, and tested without AWS: the domain model (`src/asmbly_ceramics/domain/`), the
ports (`ports/`), in-memory fakes of them (`adapters/memory/`), the use cases
(`use_cases/`: submit a drop-off, the waiting list, search, one drop-off, rejection,
loads (with each load's firing record and history), firing notes and their search, the
firing log, settings, the daily close, counts, emails needing attention), the email composer
and its templates (`mail/`), the AWS adapters (`adapters/aws/`: DynamoDB records,
counters and rate limiter, the S3 photo store, the SES mailer, Cognito staff tokens,
Parameter Store secrets), the system clock (`adapters/clock.py`), the photo
inspector, which checks and re-encodes photos with Pillow (`adapters/images.py`), and the
public drop-off form and the staff console (`web/`, `web/console/`: Starlette pages rendered with Jinja2, the photo upload
script, the Content-Security-Policy and other headers, same-origin checks and signed
cookies; the console adds sign-in through the staff sign-in, a CSRF check and the pages
for the waiting list, search, one drop-off and its photos, rejection, loads (with each
load's status steps, firing record, notes and history), the notes search, the firing log
and its CSV download,
settings and their history, counts and the emails needing attention; `web/local.py` runs the
form on the fakes on a laptop). The brand colours the pages
and the emails share are in `brand.py`. `infra/bootstrap.yaml` is the bootstrap stack
(deploy roles, boundaries, addresses), deployed by hand with
[its runbook](runbooks/aws-bootstrap.md). `infra/app.yaml` is the app's SAM template
for one environment (the records table, the private photo bucket, the form and the console behind an
HTTP API, the mailer on the table's stream, the daily close, the alarms, among them one on the
mailer's send volume); a merge to `main` deploys it to
stage and then prod (`.github/workflows/deploy.yml`, [the operations runbook](runbooks/operations.md)).
The deployed functions start from `entry/` (`run.sh` for the form and the console through the Lambda
Web Adapter, `mailer.py` for the stream, `close.py` for the daily schedule), read their environment once in
`settings.py`, are built on the AWS adapters in `composition.py`, log JSON lines through
`logs.py`, and bound each web request with `deadline.py`. The bootstrap stack
`asmbly-ceramics-bootstrap` exists in AWS and so do the GitHub environments `stage` and
`prod`; the runbook's later steps are not done, so no app stack is deployed yet. The
switch from ClickUp (#8) is planned in
[.implementation_plans/drop-off-and-firing/](../.implementation_plans/drop-off-and-firing/README.md); the studio takes
drop-offs through a ClickUp form until then.

What the domain code settles, beyond the stories:

- A load refuses a new firing type once it has drop-offs (`FiringTypeLocked`); remove
  them first.
- A catalog item (kiln, firing type, glaze type, rejection reason, cone, clay body) is
  deleted only after it is retired; an active one is refused. An item a drop-off or load
  used can't be deleted, nor can a cone a firing type's default program names.
- The settings history records that the sending address changed, never the address.
- The form's rate limit counts hits in a rolling window, refused hits included, and
  fails closed.
- The form counts each otherwise-acceptable drop-off against the studio's daily cap on
  received emails (a setting, 300 to start) in a rolling 24 hours, and refuses past it
  with one sentence that names no cap (`DropOffNotTaken`, decision 0008).
- The mailer re-reads an email whose claim's outcome is unknown and sends it when the
  stored email holds that claim (`holds_claim`); a claim that lands only after the
  re-read waits for staff, as a stuck email.
- `PhotoStore.keep` stores all of a drop-off's photos or none. A caller whose commit
  fails after `keep` calls `delete_drop_off`.

## What the stories ask for

| Part | Who uses it | Stories |
| --- | --- | --- |
| **Drop-off form**: public, no sign-in, phone-friendly, reached by the studio's QR code; shows the new ID (`AC-1`, `AC-2`, …) at once | Anyone dropping off | #2 |
| **Staff console**: the waiting list, search, loads (with each load's firing record and notes), rejections, the firing log, the notes search, settings and their history, weekly counts | Ceramics staff (the `ceramics` staff group) | #3, #4, #5, #6, #7, #17, #42 |
| **Emails**: received, ready for pickup (after firing), needs attention (rejected); each with the drop-off's photos in the email, from the sending address set in the console | The person who dropped off | #2, #4, #5, #6 |
| **Photo storage**: 1 to 6 photos per drop-off, private in S3, seen only through the console | Ceramics staff | #2, #3 |
| **Closing**: once the pickup window has passed, a drop-off closes and its personal details and photos are deleted | Nobody sees it run | #7 |
| **Kiln schedule**: planned loads for the next 4 weeks, public, no personal details | Anyone | #9 (Could) |

### The domain, as the stories describe it

- A **drop-off** has an ID, the person's name, email and phone, a number of pieces
  (1 to 50), a firing type (bisque or glaze), a glaze type (glaze only), and 1 to 6
  photos. It is *waiting*, then in a load, *fired*, or *rejected* (with a reason and an
  optional message; undoable the same day), and finally *closed*, which keeps the ID,
  dates, firing type, pieces, load and reason and deletes everything personal. A waiting
  drop-off made by mistake (or as a test) can be *deleted* by staff after they type its
  ID: like a close, but at once and with no email, its details and photos are deleted
  and it leaves every list and count, while its ID still finds it. A drop-off still
  waiting after 60 days shows as overdue.
- A **load** is a kiln, a firing type and a date. It goes *loading → firing → fired*;
  drop-offs are added and removed only while it is loading, and a fired load and its
  drop-offs can't change. A load started by mistake (or for a test) can be deleted while
  it is loading or firing, after staff type its ID to confirm: its drop-offs go back to
  waiting, and the load is kept, marked *deleted* with who did it and when, but shown
  nowhere again (a soft delete, so the functions need no `DeleteItem` right). Every
  fired drop-off belongs to exactly one load. With #9, a
  load can be planned ahead with a date.
- A load can be a **test firing** (#42), chosen when it is started and changeable only
  while it is loading. A test can start firing and be marked fired with no drop-offs,
  and then emails no one; one that holds drop-offs fires as any load does. Each step a
  load reaches (started, firing, fired) keeps who reached it, by staff username, and
  when; staff can correct a step's time (never its username), keeping started ≤ firing ≤
  fired and nothing in the future.
- Each live load has an optional **firing record** (#42), every field optional and
  checked on the server: % full, the firing number since the kiln's elements and all
  time (suggested from the kiln's last numbered firing, or its counts, plus every load
  fired since: any firing counts, empty, test or not), the program (preheat,
  cone, speed, hold), the firing time, max and board temperatures, the cost, and how far
  the top, center and bottom witness cones bent (or "no cone"). Saving it never touches
  the load's drop-offs or sends an email, so a fired load's contents still can't change.
- A load has a **history**: one line per change (started, changed, firing started,
  fired, deleted, the record's changed fields with their new values, a step's time
  corrected), with the staff username and the time. Adding or removing a drop-off
  writes none. The record and the history hold no personal details and the close (#7)
  never touches them.
- The **firing log** lists fired loads by kiln, a date range of at most 5 years read
  from an index, and kind (all, tests only, no tests), with the record's main fields as
  columns and each load's number of notes (and how many say "not allowed"), and downloads
  the same rows as a CSV whose cells can't start a spreadsheet formula. Neither holds
  anything but staff usernames, studio items, record values and note counts.
- A load has **firing notes** (#17), any number, written, edited or removed at any stage
  (after firing too) on the load page: plain text of 1 to 2,000 characters, tagged with glaze
  types and clay bodies from the studio's lists, and optionally a **ruling** (allowed,
  allowed with conditions, not allowed). Each keeps who wrote it and when, and who last
  edited or removed it and when; a removed note is kept but listed nowhere again, and
  deleting a load removes its notes. A note holds no personal details: the form says
  so, and the server refuses text holding something shaped like an email address or a
  phone number (a ramp written as three numbers of 3, 3 and 4 digits looks like one, so
  the form says to write it with units or commas). The **notes search** filters notes
  by kiln, glaze type, clay body, ruling and the date written (at most 5 years, read
  from an index), each linking to its load. Notes are kept with their load, never
  deleted by the close (#7), never logged (logs carry note IDs such as `N-12`), and
  never on the public form or in an email; the kiln schedule (#9) must keep them off it
  too. Their text is autoescaped wherever it is shown.
- **Kilns** (Athena, Helios and Vulcan today), **firing types**, **glaze types**,
  **rejection reasons**, **cones** (^06, ^5 and ^6 to start), **clay bodies**, the
  **pickup window and hours**, the **sending address** and the **daily cap on received
  emails** (#30) are settings, edited in the
  console with a history of who changed what. Anything a drop-off or load has used is
  retired, not deleted. A firing type can carry a **default program** that fills each
  new load's record, and a kiln its **firing counts** (since new elements and all time,
  as of when they were set), which "New elements" resets so its next firing is number 1.

## The shape of the code

[CLAUDE.md](../CLAUDE.md#the-shape-of-the-code) has the rules. The domain, the ports and
the in-memory adapters, the use cases, the AWS adapters, the form's and the console's
pages and the scheduled close's handler exist. In short:

```
entry points (the form's and the console's pages, the scheduled close)
        │ call
use cases (drop off, add to load, fire, reject, change a setting, close)
        │ use                         │ through ports
domain model (plain Python)      storage · photos · email · staff sign-in · clock · IDs
                                       │ implemented by
                                 AWS adapters (and in-memory fakes for tests)
```

The domain and the use cases import no AWS library and no web framework. A later
feature, such as the kiln schedule (#9) or a glaze log, is a new use case and page on
the same model and ports.

## What it needs from other repositories

From epic #1's **Work in other repositories**:

| Repository | What | For |
| --- | --- | --- |
| asmbly-staff-login | A sign-in client for this app that admits the `ceramics` group (the group comes from asmbly-staff-login#4) | #3 |
| AsmblyMCPs | Sending rights on the `asmbly.org` email domain, whose SES identity its `mcp-bootstrap` stack owns. The maintainer agreed this app sends from `asmbly.org`; he may move the identity's ownership separately, and nothing here depends on which stack holds it | #2, #4, #5, #6 |
| The facilities repository | Its kiln drop-off viewer retired and pointed at the new form | #8 |

## Still to be decided

Nothing, for epic #1. The plan for it
([.implementation_plans/drop-off-and-firing/](../.implementation_plans/drop-off-and-firing/README.md))
made each choice this section listed, and
[decision 0002](decisions/0002-how-the-app-is-built-and-deployed.md) records them with
the alternatives and the reasons:

| Choice | Decided (0002) |
| --- | --- |
| Framework | Starlette, pages rendered on the server with Jinja2 |
| Hosting and addresses | Lambda (Python 3.14, arm64) behind one HTTP API, one function per job (form, console, mailer, close); `ceramics.asmbly.org` and `ceramics-stage.asmbly.org` |
| Data store and IDs | One DynamoDB table per environment; `AC-n` from an atomic counter, written only if new |
| Photos | Presigned POST straight to a private S3 bucket; re-encoded without EXIF on submit; staff see them only through the console; inline in emails |
| The form's rate limit | Counted in the table per device cookie and per address, under a keyed hash |
| Staff sign-in | The app exchanges the code (PKCE) and checks the ID token and the `ceramics` group on every request; values from `/config/cognito/staff/*` |
| Email | An outbox in the table, sent by a mailer from the table's stream; failures shown, retried and alarmed |
| Deploy | SAM; a hand-deployed bootstrap stack with tag-conditioned roles; stage then prod on every merge, each with a smoke test |
| The scheduled close | EventBridge Scheduler, daily at 03:17 Austin time |

A later choice that changes one of these needs a new decision record.
[Decision 0008](decisions/0008-the-form-caps-received-emails-per-day-and-per-recipient.md)
(proposed) adds to the form's rate limit a daily cap on received emails, kept as a studio
setting, and a limit per recipient address, with an alarm on the mailer's send volume;
[harden-outgoing-email](../.implementation_plans/harden-outgoing-email/README.md) plans
them.
