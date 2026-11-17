# Harden outgoing email: implementation plan

**Created:** 2026-11-17

## Overview

The app sends three kinds of email from the studio's `asmbly.org` address through an
outbox (decision 0002). Four issues found in earlier reviews say where that path can
still go wrong:

- **#22, and #21's part 2 (a lost claim response):** the mailer claims an email with one
  commit before it sends. If that commit raises `CommitOutcomeUnknown` (a timeout, a
  lost answer) and landed anyway, the stream's retry finds the email `sending` and does
  nothing, so it waits about 15 minutes for staff to press "Try sending again".
- **#30:** nothing caps how many "We received your drop-off" emails one environment's
  form can queue in a day. Someone rotating devices, networks and addresses could make
  many, all from the `asmbly.org` identity that AsmblyMCPs owns and other projects share.
- **#18:** nothing limits how often the form emails one address, so a third party can be
  sent many emails from the studio.

This plan fixes the claim (phase 1), adds a daily cap on received emails kept as a studio
setting, with an alarm on the mailer's send volume (phase 2), and adds a limit per
recipient address under a keyed hash (phase 3). The defaults were set for this run on
17 November 2026: 300 received emails per environment per day, and 3 drop-offs per
recipient per day.
[Decision 0008](../../docs/decisions/0008-the-form-caps-received-emails-per-day-and-per-recipient.md)
(proposed, written with this plan) records the choices for #30 and #18 and the ones that
lost.

What was found on 17 November 2026, before planning, from the code (no AWS read was
needed: the template and the code answer every question here, and this run has no AWS
access):

- `SendPendingEmail` (`use_cases/emails.py`) lets `CommitOutcomeUnknown` on the claim go
  up; `entry/mailer.py` then reports the record for Lambda to retry and logs
  `mailer_crashed` at ERROR. The DynamoDB adapter raises `CommitOutcomeUnknown` for a
  botocore error after its retries, `TransactionInProgressException`,
  `InternalServerError`, or any error after a retry.
- The form's limits (`domain/limits.py`: `DEVICE_LIMIT` 10 and `ADDRESS_LIMIT` 30 in
  10 minutes) go through the `RateLimiter` port, a rolling window on one
  `RATE#<key>` item per key that keeps at most `limit` hits and fails closed, counted
  under a `KeyHasher` HMAC with the form's `hash-key`. The form role may already read and
  put any `RATE#*` item. `SubmitDropOff` already holds the limiter, the hasher and the
  studio, so no wiring changes.
- The template already has an alarm topic with the maintainers' confirmed subscription,
  four metric filters on the app's JSON lines, and seven alarms; the bootstrap's
  execution role already creates filters and `asmbly-ceramics-*` alarms.

## Domain model

What this plan adds, without reworking the model:

- **Email (outbox)**: one new rule, `holds_claim(stored, claimed)` in `domain/email.py`:
  an email re-read by key is this call's claim when it is sending with the same
  `claimed_at` and `attempts`. `SendPendingEmail` re-reads after a claim whose outcome is
  unknown and sends only when the stored email holds its claim; a pending one is raised
  for the stream to retry; one held by anything else is left alone. No state or
  transition changes.
- **Studio (settings as data, #6)**: one new setting, `received_emails_per_day`
  (`STARTING_RECEIVED_EMAILS_PER_DAY = 300`; 1 to 2,000), changed with the other email
  settings (`change_email_settings`, with a history line) and read when a drop-off is
  submitted. A studio stored before it reads 300.
- **The form's limits** (rules in `domain/limits.py`, counted through the existing
  `RateLimiter` port, rolling windows, failing closed):
  - the existing device and source-address limits, unchanged, before any field is read;
  - **new:** `RECIPIENT_LIMIT` (3 in 24 hours) per recipient, counted under
    `KeyHasher.recipient`, an HMAC of `normalized_recipient(address)` (a domain function:
    case, plus tags and Gmail's dots folded) with the purpose prefix `recipient#`;
  - **new:** the daily cap, `RateLimit(studio.received_emails_per_day, 24 hours)` under the
    fixed, non-personal key `received-emails`.
  The two new ones are counted only once every field and photo has passed, the recipient
  first and the cap only when the recipient is allowed. Either refuses with one new
  domain error, `DropOffNotTaken`, whose one fixed sentence names no cap, limit, count,
  address or hash.
- **Ports:** none new, none changed in shape. `RateLimiter`'s docstring allows a fixed,
  non-personal key beside a keyed hash. No adapter or fake changes.
- **Entry points:** the public `POST /drop-off` answers `DropOffNotTaken` with 429 and
  its sentence; the console's settings page gains one field; the mailer's handler is
  unchanged.
- **Infrastructure:** one metric filter (`email_sent` → `EmailsSent`) and one alarm
  (`asmbly-ceramics-<env>-email-volume`, 100 in an hour) in `infra/app.yaml`.
- **Room to grow.** The kiln schedule (#9) is a public page that sends no email and
  takes no submission, so neither the limits nor the cap touch it. A glaze log would be
  staff-only, behind the console's sign-in. Any later public form that queues email
  goes through `DropOffNotTaken`'s pattern: a rule or setting counted through
  `RateLimiter`, refused with one fixed sentence.

## Stories

The issues are not labeled `story` and are not sub-issues of epic #1, so the phase
documents carry no `epic:` or `implements:` (a `/prep` check of them would refuse them as
another epic's); this table is what decides the closing keywords.

| Story | Title | Phases |
| --- | --- | --- |
| #22 | Outbox claim whose commit outcome is unknown waits for a manual retry | 1 |
| #21 | Follow-ups from phase 3 (part 2 only: a lost claim response) | 1 (Refs only: parts 1 and 3 stay open) |
| #30 | Cap the received emails the form can queue, per environment | 2 |
| #18 | Public form: consider a rate limit per recipient address | 3 |

The pull request that lands phase 1 says `Closes #22` and `Refs #21`; phase 2's says
`Closes #30`; phase 3's says `Closes #18`. One pull request landing all three says
`Closes #22`, `Closes #30`, `Closes #18` and `Refs #21`. Nothing here closes #21.

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| [1](phase-1-outbox-claim-recovery.md) | The mailer: a claim whose outcome is unknown | app | S | [~] In progress |
| [2](phase-2-daily-cap-and-send-alarm.md) | The form: a daily cap on received emails, and an alarm on the send volume | app, web, infra, docs | L | [~] In progress |
| [3](phase-3-per-recipient-limit.md) | The form: a limit per recipient address | app, web, docs | M | [~] In progress |

## Dependencies

- Nothing outside this repository: no other plan, no work in asmbly-staff-login,
  AsmblyMCPs or the facilities repository, no by-hand AWS step. `drop-off-and-firing` and
  `firing-records-and-notes` built everything this plan changes.
- Phase 3 depends on phase 2 (`DropOffNotTaken`, its 429 branch, and the submit's step 4b
  that phase 3 puts its check before). Phase 1 depends on nothing.

## Parallelism

- **1 and 2: parallel-safe.** Phase 1 changes `domain/email.py`, `use_cases/emails.py`,
  `tests/domain/test_email.py`, `tests/use_cases/test_emails.py` and
  `tests/entry/test_mailer.py`; phase 2 touches none of them, and phase 1 touches none of
  phase 2's files (`domain/errors.py`, `domain/limits.py`, `domain/studio.py`, `keys.py`,
  `use_cases/limits.py`, `submit.py`, `settings.py`, the pages, `infra/app.yaml`). Both
  add a line to `docs/architecture.md`, a trivial conflict.
- **1 and 3: parallel-safe** for the same reason (phase 3 waits for 2 anyway).
- **2 and 3: sequential** by their dependency; they share `domain/limits.py`,
  `use_cases/limits.py`, `use_cases/submit.py`, `tests/use_cases/test_submit.py` and
  `tests/web/test_submit.py`.

## Admin actions

| When | Who | What | Why a template can't |
| --- | --- | --- | --- |
| After the merge | The maintainer, or whoever talks to ceramics staff | Tell staff about Settings › Emails › "Received emails a day, at most" (300; no need to change it), that one email address can make at most three drop-offs a day, and that someone the form turns away is asked to see staff: take that drop-off by hand and tell the maintainers | Telling people |
| After the merge | The maintainer | Confirm the stage checks in phases 2 and 3 (the cap set to 1 refuses the second drop-off; the logged-errors alarm email arrives; the cap set back to 300; the fourth drop-off to one address refused), then set phase 2's tracker row to `[x]` | A check by a person on the live stage |

No AWS or GitHub step: the new alarm notifies the existing alarm topic, whose email
subscription is confirmed; no parameter, secret, right or bootstrap change.
**Infrastructure clearance:** phase 2 adds one metric filter and one alarm to
`infra/app.yaml`, named from `ProjectSlug` and `AppEnv`, the alarm with the five tags,
created by the deploy under the bootstrap's existing rights (`logs:PutMetricFilter`,
`cloudwatch:PutMetricAlarm` and `TagResource` on `asmbly-ceramics-*` alarms). The new
table items (`RATE#received-emails`, `RATE#recipient#…`) fall under the form role's
existing `RATE#*` right and expire by TTL.

## Rollout

Every phase reaches the live app through the normal merge and deploy (stage, its smoke
test, prod, its smoke test); none needs a by-hand step.

1. **Phase 1** changes the mailer's code only. Check: on stage, a drop-off's received
   email arrives once. Undo: revert.
2. **Phase 2** writes the studio's new attribute on its next save (it reads 300 until
   then), one `RATE#received-emails` item per environment, and creates the metric filter
   and the alarm. Check: the stage steps in the phase (cap 1 refuses the second drop-off
   with the friendly sentence, the logged-errors alarm email arrives, cap back to 300;
   `describe-alarms` shows `asmbly-ceramics-stage-email-volume`). Undo: revert;
   CloudFormation deletes the filter and alarm, the `RATE#` item expires, and the reverted
   code's first settings save drops the attribute (it reads 300 again when re-applied).
3. **Phase 3** changes the form's code only and writes `RATE#recipient#…` items. Check:
   on stage, four drop-offs to the tester's own inbox, spelled the ways the limit folds
   (as typed, with a `+` tag if their provider delivers it, in other letter case): the
   fourth is refused, and only three received emails arrive in that inbox. Undo: revert; the items expire by TTL.

Staff are told after the merge (Admin actions). A merge of this plan deploys to prod at
once: the cap and the recipient limit apply to the prod form from then on.

## Related work

- **#21 parts 1 and 3** (the retire-then-delete race; a repeated "Start load"): out of
  scope here, and planned by a separate run. Part 1 changes the `Records` port and
  `use_cases/submit.py`'s commit; phases 2 and 3 also change `submit.py` (step 4b, before
  the commit). Whichever merges second rebases; the changes don't overlap in meaning.
- **#32** (ViewStudio reads every item's use on every render): a separate run, likely in
  `use_cases/settings.py` and `web/console/settings.py`, which phase 2 also changes (one
  more field in the email settings). A textual conflict at most.
- **#20** (an email that never went closes after 30 days) and the emails-needing-attention
  list: unchanged; a claim that lands after phase 1's re-read still shows there as stuck.
- **Decision numbers:** this plan takes 0008. A parallel run that also writes a decision
  record takes the next number when it rebases.

## Out of scope

- #21's parts 1 and 3, and #32 (a separate run).
- A claim token carried from the stream record, to recognize a claim that lands after the
  re-read (the one case phase 1 leaves to staff, as today).
- An alarm on stuck emails (#21 part 2's other suggestion): the re-read removes the case
  it was for; the `logged-errors` alarm already fires on `mailer_crashed`.
- Pausing the form on purpose (a cap of 0), a console view of today's count, and making
  the per-recipient limit a setting (decision 0008's "Revisit if").
- Folding other providers' address aliases beyond plus tags and Gmail's dots.
- Any change to the device and source-address limits, the upload slots' limits, or the
  messages they show.

## Security

- **Personal data:** a new stored value, the keyed hash of a normalized recipient address
  (`RATE#recipient#<64 hex>`), kept until its item's TTL, about two days after the last
  hit; useless without the form's `hash-key`, which only the form reads. The address
  itself is stored nowhere new. No log line, error, page or test fixture holds an
  address, its normalized form, a hash, a count or a setting's value; refusals are logged
  by `reason` only, and test addresses are built in code with `an_address`.
- **The public form:** two new refusals after every field and photo passes, both with
  one fixed, friendly sentence that names no cap, limit, count, address or hash and
  echoes nothing typed (429). Both fail closed. The form role gains no right.
- **Who can open the console:** unchanged. The new settings field is on the existing
  `ceramics`-only page, behind its CSRF check, and is autoescaped.
- **Emails:** fewer can be sent: at most 3 received emails a day to one address and the
  studio's cap per environment. Phase 1 sends a claimed email that would have waited for
  staff; it still sends only from the console's `asmbly.org` address to the drop-off's
  own address, once per claim.
- **AWS:** one metric filter and one tagged alarm per environment, notifying the existing
  topic. No IAM, bootstrap, parameter or secret change.
