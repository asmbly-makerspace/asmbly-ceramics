---
plan: drop-off-and-firing
epic: 1
---

# Drop-offs and firings: implementation plan

**Created:** 2026-11-13

## Overview

The ceramics studio takes about 80 drop-offs and runs about 6 firings a week through a
ClickUp form that can't show an ID and whose emails don't work (epic #1). This plan builds
the app that replaces it: a public, phone-friendly drop-off form that shows the new ID
(`AC-1`, `AC-2`, …) at once; a staff console where the `ceramics` staff group sees what
is waiting, builds and fires kiln loads, rejects drop-offs and manages the studio's
settings; the three emails with photos; the daily close that deletes personal details;
and the switch from ClickUp. It covers stories #2 to #8. The kiln schedule (#9) is left
for a later plan; the model below says where it joins.

The choices `docs/architecture.md` left open (framework, hosting, data store, photos,
rate limit, sign-in, email, deploy, the scheduled close) are made in
[decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md), written
with this plan.

What was found on 13 November 2026, before planning:

- **This repository** holds rules, checks and an empty package; nothing in AWS.
- **AsmblyMCPs** deploys with SAM from a hand-deployed bootstrap stack (an OIDC deploy
  role, a CloudFormation execution role, a permissions boundary), Lambda with the Lambda
  Web Adapter behind an HTTP API, Python 3.14 on arm64. It owns the SES identity for
  `asmbly.org` (in `mcp-bootstrap`, Easy DKIM, production access since October 2026,
  no configuration set). Its roles have no `aws:RequestTag` conditions and its stacks no
  `Owner` or `ManagedBy` tags; this plan adds both.
- **asmbly-staff-login** owns the staff pool, its sign-in page (moving from
  `login.mcp.asmbly.org` to `staff-login.asmbly.org`, its #6) and the
  `/config/cognito/staff/*` values (`issuer`, `sign-in-url`, `auth-domain`,
  `user-pool-id`, `user-pool-arn`, one per client). The existing `ceramics-claude`
  client is the ceramics MCP connector's, not this app's. Access groups (its #4) and the
  app registry that would create this app's client (its #5, `apps/ceramics-staff.yaml`,
  publishing `/config/cognito/staff/ceramics-staff-app-client-id`) are planned, not
  built. Web clients are public, use the code flow with PKCE and `openid` only, and get
  60-minute tokens. There is one pool for stage and prod. Usernames are handles, not
  addresses.
- **The facilities repository** serves the kiln drop-off viewer, a public page listing
  the last day's ClickUp drop-offs by name, which the ClickUp form redirects to. Its
  branding tokens, CSP helper and photo checks are the patterns copied here, by idea not
  by import.
- **DNS**: `ceramics.asmbly.org` and `ceramics-stage.asmbly.org` did not exist.

AWS's documentation was read for every behavior the plan relies on; each phase names its
pages under **Required reading**. Three points are not settled by it and are checked
in a phase's verification instead: S3's answer to a too-large presigned POST, whether
an iPhone converts HEIC to JPEG under the form's `accept` list (WebKit bug reports say
yes), and SES sending for this project from AsmblyMCPs' identity.

## Domain model

All of it is plain Python in `src/asmbly_ceramics/domain/` (phases 1a to 1c; `counts.py`
comes in phase 3 with the use case that needs it): frozen dataclasses
and enums, no AWS library, no web framework, no I/O. A state change is a function that
returns the new value or raises a `DomainError` subclass whose message names the reason
and the IDs ("AC-12 is already in load L-4") and holds no personal detail.

### Entities and their states

- **DropOff**: `id: DropOffId` (`AC-n`), `contact: Contact | None` (name, email,
  phone; `None` once closed), `pieces` (1 to 50), `firing_type: ItemId`,
  `glaze_type: ItemId | None` (required when the firing type needs one, refused
  otherwise), `photos: tuple[PhotoRef, ...]` (1 to 6), `created_at`, `state`,
  `load_id: LoadId | None`, `rejection: Rejection | None` (reason, message up to 1,000
  characters, by, at; the message is `None` once closed), `fired_at`, `closed_at`,
  `version`.

  ```
  waiting ──add_to_load──▶ in_load ──(load fired)──▶ fired ──close──▶ closed
     ▲  │                     │
     │  │◀────remove──────────┘          (only while the load is loading)
     │  └──reject──▶ rejected ──close──▶ closed
     └──undo (same Austin day)──┘
  ```

  *Overdue* is not a state: a drop-off still `waiting` 60 or more whole Austin days
  after the Austin date of its `created_at` (`days_waiting`) is shown as overdue, never
  deleted.
- **Load**: `id: LoadId` (`L-n`), `kiln: ItemId`, `firing_type: ItemId`, `date`
  (today by default), `status`, `members: tuple[DropOffId, ...]`, `started_by`
  (username), `fired_at`, `version`. `loading → firing → fired`; members are added and
  removed only while `loading`; a fired load and its drop-offs never change. At most 48
  members (a fire is one transaction: the load, each drop-off and each email, within
  DynamoDB's 100-item limit).
- **Studio** (the settings, data not code): `sending_address` (must end in
  `@asmbly.org`), `pickup_window_days` (1 or more; 14 to start), `pickup_hours_text`,
  and four lists of `CatalogItem(id, name, status: active | retired)`: kilns, firing
  types (each with `needs_glaze_type`), glaze types, rejection reasons (each with
  `needs_message`). An item any drop-off or load uses can be retired, not deleted, and
  only a retired item can be deleted; a retired item stays on past records and can't be
  picked. Every change appends a
  `SettingChange(at, by, what)` to the history.
- **Email** (the outbox): `(drop_off_id, kind)` with kind `received`, `ready` or
  `rejected`, `status` `pending → sending → sent | failed`, or `cancelled` (from
  `pending` or `sending`, when the drop-off closed or its rejection was undone),
  `attempts`, `error_code`, `sent_at`. One per drop-off and kind (a `rejected` one per
  rejection: its key adds the rejection's time as `rejection_occasion` gives it). The ready email's `sent_at` starts the pickup window.

### The rules, each in one place

| Rule (story) | Where |
| --- | --- |
| Pieces 1–50, 1–6 photos, glaze type exactly when the firing type needs it, required name, email and phone with their formats (#2) | `domain/dropoff.py`, `DropOffDetails.create` |
| Each photo at most 10 MB, a JPEG, PNG or WebP image (#2) | `domain/photos.py` limits; checked by the `PhotoInspector` port |
| No two drop-offs share an ID (#2) | `IdNumbers` port contract; `AC-n` formatting in `domain/ids.py` |
| 10 submissions per device, 30 per address, in 10 minutes (#2) | `domain/limits.py`; counted by the `RateLimiter` port |
| Search: `AC-12`, `ac12`, `12` or part of a name (#3) | `domain/search.py`, `parse_query` and `matches` |
| Waiting oldest first; bisque and glaze totals in pieces (#3); overdue at 60 days waiting, in whole Austin days (#7) | `domain/waiting.py` |
| Add only a waiting drop-off not in a load; a different firing type needs confirming; nothing changes once firing; at most 48 (#4) | `domain/load.py` |
| `loading → firing → fired`; firing again sends nothing (#4) | `domain/load.py`; `Email` keys in `domain/email.py` |
| A message is required for a reason that needs one; at most 1,000 characters; undo the same Austin day only (#5) | `domain/dropoff.py`, `reject` and `undo_rejection` |
| The sending address is at `asmbly.org`; used items are retired, not deleted; every change is recorded (#6) | `domain/studio.py` |
| Close once the pickup window has passed since the ready email (fired) or since the rejection (rejected); delete the details, keep the rest (#7) | `domain/closing.py` |
| Weekly counts Monday to Sunday, Austin time (#7) | `domain/counts.py` |

The fixed numbers above (pieces, photos, sizes, rate limits, 60 days, 1,000 characters,
48, the time zone `America/Chicago`) are rules the stories state, not settings, and live
as named constants in the domain. Everything #6 calls a setting is in `Studio`.

### Ports

Each is a `Protocol` in `src/asmbly_ceramics/ports/`, with an in-memory fake in
`adapters/memory/` (phase 1d) that the use case tests use, and an adapter the app uses
(phase 4). Besides the errors below, a port that can't reach AWS raises its
`Unavailable(code)` subclass (`RecordsUnavailable`, `IdsUnavailable`,
`PhotosUnavailable`, `SignInUnavailable`, `SecretsUnavailable`), which pages show as
"try again".

| Port | Methods (summary) | Adapter | Fake |
| --- | --- | --- | --- |
| `Records` | get and query drop-offs, loads, studio, history, emails, counts; `commit(changes)` applies puts and updates atomically with version checks, raising `Conflict` | `adapters/aws/records.py` (DynamoDB) | `adapters/memory/records.py` |
| `IdNumbers` | `next_drop_off_id()`, `next_load_id()`; never the same number twice | `adapters/aws/ids.py` (DynamoDB `ADD`) | `adapters/memory/ids.py` |
| `PhotoStore` | `upload_slots(count, now)`, `read_upload(slot_id)`, `discard_uploads(slot_ids)`, `keep(drop_off_id, photos)`, `read(ref, size)`, `delete_drop_off(id)` | `adapters/aws/photos.py` (S3) | `adapters/memory/photos.py` |
| `PhotoInspector` | `inspect(data) -> CheckedPhoto` (real type, size, upright, no EXIF, full and thumbnail JPEGs) or `PhotoRefused(kind)` | `adapters/images.py` (Pillow) | `adapters/memory/images.py` |
| `Mailer` | `send(message: OutgoingEmail) -> None`, raising `SendFailed(code)` | `adapters/aws/mailer.py` (SES v2) | `adapters/memory/mailer.py` |
| `StaffTokens` | `verify(token) -> StaffMember(username, email)` or `NotSignedIn`/`NotAllowed`; `sign_in_url(...)`, `exchange(code=, code_verifier=, redirect_uri=)`, `sign_out_url(...)` | `adapters/aws/staff_tokens.py` (PyJWT, the pool's keys, the token endpoint) | `adapters/memory/staff_tokens.py` |
| `RateLimiter` | `hit(key, limit, now) -> bool` | `adapters/aws/rate_limit.py` (DynamoDB, TTL) | `adapters/memory/rate_limit.py` |
| `Clock` | `now() -> datetime` (aware) | `adapters/clock.py` | `adapters/memory/clock.py` |
| `Secrets` | `get(name) -> bytes` | `adapters/aws/secrets.py` (SSM SecureString) | `adapters/memory/secrets.py` |

### Use cases

One module per thing a person does, in `src/asmbly_ceramics/use_cases/`, each a class
whose constructor takes the ports and whose `__call__` takes a typed request. They log
by ID and username only.

- Phase 2: `ViewStudioChoices`, `ReceivedSummary`, `RequestUploadSlots`, `SubmitDropOff`,
  `WaitingList`, `FindDropOffs`,
  `ViewDropOff`, `PreviewRejection`, `RejectDropOff`, `UndoRejection`, and the email
  composer `mail/compose.py` (the three emails, Jinja2 with autoescape).
- Phase 3: `StartLoad`, `ChangeLoad`, `AddToLoad`, `RemoveFromLoad`, `StartFiring`, `MarkFired`,
  `ViewLoad`, `ListLoads`, `SendPendingEmail`, `RetryEmail`, `ViewStudio`,
  `ChangeEmailSettings`, `SendTestEmail`, `AddCatalogItem`, `RetireCatalogItem`,
  `RestoreCatalogItem`, `DeleteCatalogItem`, `CloseFinished`, `WeeklyCounts`.

### Entry points

Pages in `src/asmbly_ceramics/web/` (Starlette, phases 6, 8, 9) and Lambda handlers in
`src/asmbly_ceramics/entry/` (`mailer.py`, `close.py`) only translate a request into a
use case call and its result into a response. `src/asmbly_ceramics/composition.py`
(phase 7) builds the AWS adapters from environment variables; tests build the fakes.

### Where later features join

- **The kiln schedule (#9)**: `Load` gains a `planned` status before `loading` and a
  `planned_for` date; a `PlanLoad` use case; a public page that reads loads through
  `Records` (kiln, firing type, date: no drop-off, no person); the received email gains
  the link. Nothing here changes shape.
- **A glaze log**: a new entity (`GlazeBatch`) with its own use cases and item type in
  the same table, and a console tab; the drop-off model doesn't change.
- **More firing types or kilns**: data, added in the console.

## Stories

| Story | Title | Phases |
| --- | --- | --- |
| #2 | Drop off a piece and get an ID on screen | 1b, 1d, 2, 4, 6, 7 |
| #3 | Ceramics staff sign in and see what's waiting | 1c, 2, 8 |
| #4 | Build a kiln load and fire it | 1c, 1d, 3, 7, 9 |
| #5 | Reject a drop-off with a reason and a message | 1b, 2, 8 |
| #6 | Staff manage the studio's settings in the console | 1a, 3, 9 |
| #7 | Finished drop-offs close and personal details are deleted | 1b, 1c, 3, 9 |
| #8 | The studio switches from ClickUp | 10 |

Only the pull request that lands the last phase in a row says `Closes #N`; earlier ones
say `Refs #N`. #9 (Members see the kiln schedule) is not in this plan.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| [1a](phase-1a-domain-core-and-studio.md) | The domain's core: errors, IDs, limits and the studio | app | L | [x] Complete |
| [1b](phase-1b-drop-offs-photos-outbox.md) | The domain: drop-offs, photos, the outbox and closing | app | L | [x] Complete |
| [1c](phase-1c-loads-waiting-search.md) | The domain: loads, the waiting list and search | app | M | [x] Complete |
| [1d](phase-1d-ports-and-fakes.md) | The ports and their in-memory fakes | app | L | [x] Complete |
| [2](phase-2-drop-off-use-cases.md) | Use cases: drop off, waiting list, reject | app | L | [ ] Pending |
| [3](phase-3-load-and-studio-use-cases.md) | Use cases: loads, settings, close, counts | app | L | [ ] Pending |
| [4](phase-4-aws-adapters.md) | The AWS adapters | app | L | [ ] Pending |
| [5](phase-5-aws-bootstrap.md) | AWS bootstrap: roles, boundary, addresses | infra, docs | M | [ ] Pending |
| [6](phase-6-drop-off-form.md) | The drop-off form | web | L | [ ] Pending |
| [7](phase-7-first-deploy.md) | First deploy: stage and prod | infra, ci | L | [ ] Pending |
| [8](phase-8-console-waiting-and-reject.md) | Console: sign-in, waiting list, rejection | web, infra | L | [ ] Pending |
| [9](phase-9-console-loads-settings-close.md) | Console: loads, settings, counts, the close | web, infra | L | [ ] Pending |
| [10](phase-10-switch-from-clickup.md) | The switch from ClickUp | docs | S | [ ] Pending |

## Dependencies

Between phases (`depends_on`, direct only):

```
1a ──▶ 1b ──▶ 1c ──▶ 1d ──▶ 2 ──▶ 3 ─────────────┐
                      │     └───▶ 6 ──┐           ▼
                      └───▶ 4 ───────▶ 7 ──▶ 8 ──▶ 9 ──▶ 10
                            5 ────────┘
```

- 1b needs 1a; 1c needs 1b; 1d needs 1c; 2 needs 1d; 3 needs 2; 4 needs 1d; 5 needs
  nothing; 6 needs 2; 7 needs 4, 5 and 6; 8 needs 3 and 7; 9 needs 8; 10 needs 9.
- Phase 1 (the domain model, ports and fakes) was split into 1a to 1d by `/prep` on
  2026-11-13, because its estimate was near 2,000 changed lines. "Phase 1" elsewhere in
  this plan means all four.

Outside this repository:

| Needed before | What | Where |
| --- | --- | --- |
| Phase 5 runs | Rights to add records to the `asmbly.org` zone (the maintainer deploys the bootstrap) | By hand; the zone belongs to another project |
| Phase 7 merges | Agreement that asmbly-ceramics' roles may send from the `asmbly.org` identity, From limited to `asmbly.org` | AsmblyMCPs: an issue and a decision record there (the identity is in `mcp-bootstrap`) |
| Phase 8 merges | The `ceramics` group | asmbly-staff-login#4 (plan `access-groups`, phase 1) |
| Phase 8 merges | This app's client and `/config/cognito/staff/ceramics-staff-app-client-id` | asmbly-staff-login#5 (plan `add-an-app`), then the `apps/ceramics-staff.yaml` pull request there |
| Phase 8 is checked | Ceramics staff in the `ceramics` group | asmbly-staff-login#3, Manage users |
| Phase 10 | The kiln drop-off viewer retired and pointed at the new form | The facilities repository (an issue there) |
| Phase 10 | The ClickUp form closed to new drop-offs, its redirect changed | ClickUp, by hand |

## Parallelism

Pairs with no `depends_on` path between them:

| Pair | Verdict | Why |
| --- | --- | --- |
| 5 and 1a to 1d, 2, 3, 4 or 6 | parallel-safe | 5 touches `infra/bootstrap.yaml`, `docs/runbooks/`, `tests/repo/test_bootstrap.py`, `CLAUDE.md`'s checks and `pr-checks.yml`, which none of them touch |
| 3 and 4 | sequential-only | both change `pyproject.toml` and `uv.lock` |
| 3 and 6 | sequential-only | both change `pyproject.toml`, `uv.lock` and `src/asmbly_ceramics/mail/templates/` (6 adds the shared brand partials) |
| 4 and 2 | sequential-only | both change `pyproject.toml` and `uv.lock` |
| 4 and 6 | sequential-only | both change `pyproject.toml` and `uv.lock` |

In practice: 5 can be built while 1a to 4 and 6 are; the others go one at a time.

## Admin actions

| When | Who | What |
| --- | --- | --- |
| Before phase 5 merges | The maintainer | Confirm the addresses `ceramics.asmbly.org` and `ceramics-stage.asmbly.org` |
| After phase 5 merges | The maintainer, with rights to the `asmbly.org` zone | Deploy `asmbly-ceramics-bootstrap` by hand, following `docs/runbooks/aws-bootstrap.md` (phase 5); check the certificates are issued |
| After phase 5 merges | The maintainer | Create the GitHub environments `stage` and `prod` (deployments from `main` only) and their variables: `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `AWS_CFN_EXECUTION_ROLE_ARN`, `SAM_ARTIFACTS_BUCKET`, `WEB_ADAPTER_LAYER_ARN`. No address is a GitHub variable: the repository's Actions logs are public |
| Before phase 7 merges | The maintainer, by hand | For stage and prod, set the SecureStrings `/asmbly-ceramics/<env>/hash-key`, `form-key` and `session-key` (32 random bytes each) and the Strings `/asmbly-ceramics/<env>/alert-email` (the maintainers' address) and `initial-sending-address` (the studio's address at `asmbly.org`), by phase 5's runbook |
| Before phase 7 merges | AsmblyMCPs | Agree the sending right (Dependencies); no change to `mcp-bootstrap` is needed for a same-account sender, but the identity's owner decides |
| After phase 7's first deploy | The maintainer | Confirm the alarm topic's email subscription |
| Before phase 8 merges | asmbly-staff-login | The `ceramics` group and the `ceramics-staff` client (Dependencies), with return URLs `https://ceramics.asmbly.org/console/auth/callback` and `https://ceramics-stage.asmbly.org/console/auth/callback`, sign-out URLs the two addresses' `/console/signed-out`; and the console's address added to the staff invitation |
| Before phase 8 is checked | asmbly-staff-login, Manage users | Put ceramics staff in the `ceramics` group |
| Phase 10 | The maintainer and ceramics staff | Tell staff the switch date beforehand; replace the QR sign; close the ClickUp form; open the facilities issue and see it merged |

## Rollout

1. Phases 1a to 4 and 6 reach no AWS. Phase 5's bootstrap is deployed by hand after its
   merge: check (stack outputs, the certificates issued, the names resolve), undo
   (delete the stack; nothing uses it yet).
2. **Phase 7** is the first deploy. A merge deploys stage, runs the smoke test, then
   deploys prod and runs it again. Check: the smoke test, then the maintainer makes a
   drop-off on stage from a phone with made-up details and a mailbox they own; the ID
   shows, the email arrives with the photos, and a photo's storage address gets 403.
   Undo: a revert pull request (the table and bucket are kept). The form is live on
   prod but its address is not published.
3. **Phase 8** adds the console's first half. Check: ceramics staff sign in on stage,
   see the waiting list, reject and undo a test drop-off; someone outside the group
   sees "not allowed". Undo: revert.
4. **Phase 9** completes the console and turns on the daily close. Check: a stage load
   goes loading, firing, fired with emails; a settings change shows in the history;
   the close function's run is logged. Undo: revert (the schedule is removed with it).
5. **Phase 10**: staff are told the date; on the day, the QR sign and the facilities
   page point to `https://ceramics.asmbly.org/`, and the ClickUp form stops taking
   drop-offs. Check: a drop-off through the QR code. Undo: point the sign back to
   ClickUp; drop-offs already made stay in the app.

## Related work

- asmbly-staff-login#4 and #5 (plans `access-groups`, `add-an-app`): **blocks** phase 8;
  this app is the registry's first web entry (`apps/ceramics-staff.yaml`).
- asmbly-staff-login#6 (the sign-in page moves to `staff-login.asmbly.org`, its open
  pull request #23): **shares** the sign-in address; this app reads it from
  `/config/cognito/staff/sign-in-url` and picks up the new one at its next deploy.
- AsmblyMCPs' SES identity in `mcp-bootstrap` (decisions 0006 and 0015 there): **shares**
  the `asmbly.org` identity and its sending reputation; the right is agreed there
  before phase 7.
- The facilities repository's kiln drop-off viewer (`functions/ceramics/kiln_dropoff_recent_entries_viewer/`):
  **retired by** phase 10, in an issue there.
- AsmblyMCPs#9 (tighten its deploy role): the reason this plan's roles carry tag
  conditions from the start.

## Open questions

- **The Asmbly AWS Tagging Guide.** `CLAUDE.md` names it; neither this repository nor its
  siblings hold it. The plan uses the five keys `CLAUDE.md` lists, with `Component`
  values `App` (the app stacks) and `Bootstrap`, and `Environment=shared` for the
  bootstrap stack, which serves both environments. The maintainer confirms or corrects
  these values before phase 5 merges.
- **A gate on stage's form.** Should stage's form be gated (for example a staff-only
  preview cookie) before phase 7? The plan accepts the risk (Security); say if not.
- **Web sign-in lifetime.** asmbly-staff-login gives web clients 60-minute tokens
  (its add-an-app open question 2), so staff sign in again about hourly at the kiln.
- **Settled in a phase's verification, not by the documentation:** S3's answer to a
  presigned POST over 10 MB (phase 7's smoke test), whether an iPhone sends JPEG under
  the form's `accept` list (phase 6, on a real phone), whether `dynamodb:LeadingKeys`
  is checked per item in a transaction (phase 7, `/prep`), S3 conditional writes
  (`If-None-Match`, phase 4, `/prep`).

## Out of scope

- The kiln schedule (#9): a later plan, on the model above.
- Payments or firing fees, importing ClickUp drop-offs, membership checks, pickup
  tracking or shelf locations, the dip glaze mix log (epic #1).
- The QR sign's short address, contact address and wording (deferred in epic #1).
- HEIC photos sent as HEIC: refused with a message; converting them would need a HEIF
  library.
- A staff email for overdue drop-offs (epic #1: console only).
- AWS WAF: not available on an HTTP API; the rate limit is the app's.

## Security

- **Personal details** (name, email, phone, rejection message) and photos are stored
  only in the table and the bucket of their environment, seen only through the console
  by the `ceramics` group, and deleted by the close (#7): the table's items lose them,
  the photos are deleted from S3. Backups keep them for up to 7 days more (point-in-time
  recovery; decision 0002). Logs, errors, issues, pull requests and test fixtures hold
  drop-off IDs (`AC-12`), load IDs and staff usernames only; AWS errors are logged by
  code. A test in each phase that logs checks this.
- **Photos** never leave the private bucket except through a signed-in console request
  or inside the person's own email. Uploads are presigned POSTs limited to 10 MB and an
  `image/` type for 15 minutes; on submit every photo is decoded, checked and re-encoded
  without EXIF (no location). The bucket blocks all public access and denies non-TLS
  requests.
- **The public form** is hostile input: every field is checked on the server, the
  number and real type and size of photos too, before anything is stored; text is
  escaped wherever it is shown or emailed; submissions are rate-limited per device and
  per address; a repeated submit (a refresh) makes no second drop-off. Pages send a
  strict Content-Security-Policy, `nosniff`, `no-store` and `no-referrer`. The address the
  limit counts is the last `X-Forwarded-For` value (API Gateway's), never one the caller
  can choose; the limit fails closed when the table can't be reached.
- **The forms are findable before the switch.** Both names appear in Certificate
  Transparency logs once phase 5's certificates are issued. Anyone can make a drop-off
  giving any email address, which then gets one "We received your drop-off" email, from
  the studio's address, with the photos the sender uploaded. That is inherent in #2's
  form without sign-in; the per-device and per-address limits bound it, and each email
  goes only to the one address typed. Accepted (decision 0002).
- **The console** checks, on every request, the token's signature, issuer, audience,
  use, expiry and the `ceramics` group; anyone else signed in sees "not allowed".
  Changing requests need a CSRF token and a same-site `Origin`. The session cookie is
  `__Host-`, HttpOnly, Secure and SameSite=Lax.
- **Email** is sent only from the console's sending address, which must be at
  `asmbly.org` (checked in the domain and by `ses:FromAddress` in IAM), only to the
  person who made the drop-off, or to the signed-in staff member for a test.
- **AWS**: every name starts with `asmbly-ceramics-`; every resource carries the five
  tags; the deploy roles are scoped by name and tag and denied every other project's
  resources; the form's role can't read photos or read or list drop-offs, holds only its
  own two keys (`hash-key`, `form-key`; the console's `session-key` is the console's
  alone), and its ID page reads only the submission's summary; a taken-over form
  function could still overwrite a drop-off with a `Put`, which IAM can't prevent
  (accepted in decision 0002); no address is in GitHub or the public Actions logs, and
  the account ID is masked there; no workflow on a pull request gets credentials.
