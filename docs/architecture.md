# Architecture

This page says what the app must do (from epic #1's stories), the shape its code must
have, what it needs from other repositories, and what is still to be decided. What is
decided and why is in
[decision 0001](decisions/0001-the-ceramics-studio-has-its-own-repository.md).

## Today

Nothing is built. There is no app, nothing in AWS, and no deploy. How it will be
built is planned in
[.implementation_plans/drop-off-and-firing/](../.implementation_plans/drop-off-and-firing/README.md). The studio takes
drop-offs through a ClickUp form until #8 switches it over.

## What the stories ask for

| Part | Who uses it | Stories |
| --- | --- | --- |
| **Drop-off form**: public, no sign-in, phone-friendly, reached by the studio's QR code; shows the new ID (`AC-1`, `AC-2`, …) at once | Anyone dropping off | #2 |
| **Staff console**: the waiting list, search, loads, rejections, settings and their history, weekly counts | Ceramics staff (the `ceramics` staff group) | #3, #4, #5, #6, #7 |
| **Emails**: received, ready for pickup (after firing), needs attention (rejected); each with the drop-off's photos in the email, from the sending address set in the console | The person who dropped off | #2, #4, #5, #6 |
| **Photo storage**: 1 to 6 photos per drop-off, private in S3, seen only through the console | Ceramics staff | #2, #3 |
| **Closing**: once the pickup window has passed, a drop-off closes and its personal details and photos are deleted | Nobody sees it run | #7 |
| **Kiln schedule**: planned loads for the next 4 weeks, public, no personal details | Anyone | #9 (Could) |

### The domain, as the stories describe it

- A **drop-off** has an ID, the person's name, email and phone, a number of pieces
  (1 to 50), a firing type (bisque or glaze), a glaze type (glaze only), and 1 to 6
  photos. It is *waiting*, then in a load, *fired*, or *rejected* (with a reason and an
  optional message; undoable the same day), and finally *closed*, which keeps the ID,
  dates, firing type, pieces, load and reason and deletes everything personal. A drop-off
  still waiting after 60 days shows as overdue.
- A **load** is a kiln, a firing type and a date. It goes *loading → firing → fired*;
  drop-offs are added and removed only while it is loading, and a fired load and its
  drop-offs can't change. Every fired drop-off belongs to exactly one load. With #9, a
  load can be planned ahead with a date.
- **Kilns** (Athena, Helios and Vulcan today), **firing types**, **glaze types**,
  **rejection reasons**, the **pickup window and hours** and the **sending address**
  are settings, edited in the console with a history of who changed what. Anything a
  drop-off or load has used is retired, not deleted.

## Planned shape

[CLAUDE.md](../CLAUDE.md#planned-shape-not-built-yet) has the rules; in short:

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
| AsmblyMCPs | Sending rights on the `asmbly.org` email domain, whose SES identity its `mcp-bootstrap` stack owns, or the domain moved to shared infrastructure | #2, #4, #5, #6 |
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
