# Architecture

This page says what the app must do (from epic #1's stories), the shape its code must
have, what it needs from other repositories, and what is still to be decided. What is
decided and why is in
[decision 0001](decisions/0001-the-ceramics-studio-has-its-own-repository.md).

## Today

Nothing is built. There is no app, nothing in AWS, and no deploy. The studio takes
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

`/plan-tech` decides these for epic #1, and each lands in a decision record, not here:

- The web framework, and whether pages are rendered on the server or by a script in
  the browser.
- The hosting (for example Lambda behind an HTTP API, or a container) and the addresses
  of the form and the console.
- The data store, and how an ID is issued so that no two drop-offs share one (#2).
- How photos get to S3 (through the app, or uploaded straight to S3 with a short-lived
  link), how staff see them, and how they go into an email within SES's size limit.
- How the form's rate limit (10 per device in 10 minutes) is enforced.
- How staff sign-in is checked: the token's issuer, audience and group, and where the
  app reads the staff sign-in's values.
- The deploy: the tool (SAM, CloudFormation or another), the deploy role and its tag
  conditions, the stacks and their `Component` tags, whether there is a stage
  environment, and the smoke test.
- How the scheduled close (#7) runs.
