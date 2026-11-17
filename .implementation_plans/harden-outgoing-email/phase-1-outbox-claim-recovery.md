---
phase_id: 1
title: "The mailer: a claim whose outcome is unknown"
depends_on: []
domain: [app]
estimated_size: S
---

# Phase 1: The mailer: a claim whose outcome is unknown

> **Status:** [~] In progress

Finishes #22. Finishes #21's part 2 (a lost claim response); #21 stays open for its parts
1 and 3, which this plan doesn't touch.

## Required reading

- [README](README.md): the Domain model and Parallelism (this phase shares no code file
  with phases 2 and 3 and may run beside them; only `docs/architecture.md` is common).
- Issues #22 and #21 (part 2 only).
- `src/asmbly_ceramics/use_cases/emails.py`: `SendPendingEmail.__call__` (the claim) and
  `_fail` (how a failure is logged by code, then stored).
- `src/asmbly_ceramics/domain/email.py`: `claim`, `stuck_since`, `needs_attention`.
- `src/asmbly_ceramics/ports/records.py`: `CommitOutcomeUnknown` and the `commit`
  contract; `src/asmbly_ceramics/adapters/aws/records.py`'s module docstring (what leaves
  a transaction's outcome open, and that botocore retries with the same
  `ClientRequestToken`).
- `src/asmbly_ceramics/entry/mailer.py`: an exception from `SendPendingEmail` reports the
  record in `batchItemFailures` and logs `mailer_crashed`.
- The closest pattern: `SubmitDropOff._landed_anyway` in `use_cases/submit.py` (re-read
  after a commit whose outcome is open) and `TimedOutRecords` in
  `tests/use_cases/test_submit.py` (a fake whose commit lands and then raises).
- AWS: [TransactWriteItems](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html)
  (idempotency with `ClientRequestToken`; `TransactionInProgressException`).

## Goal

When the mailer's claim commit raises `CommitOutcomeUnknown`, `SendPendingEmail` re-reads
the email by its key and:

- if the stored email holds **this** claim (sending, the same `claimed_at` and
  `attempts`), it goes on to send it, once, in the same call;
- if it is still pending, it raises the `CommitOutcomeUnknown` as today, so the stream
  tries the record again and nothing has been sent;
- if anything else holds it (another call's claim, sent, failed, cancelled), it returns
  `None`, as a lost race does today;
- if the re-read fails, it raises the original `CommitOutcomeUnknown`, nothing sent.

So a claim that landed but whose answer was lost (#21 part 2, #22) no longer waits about
15 minutes for "Try sending again". The one case left is a claim that lands only after
the re-read found it pending; the stream's retry then finds it sending and does nothing,
and staff see it as stuck after `STALE_SENDING_AFTER`, as today. That case already logs
`mailer_crashed` at ERROR (the `logged-errors` alarm), and now `email_claim_unknown`
says which drop-off.

## Files to create

None.

## Files to modify

- `src/asmbly_ceramics/domain/email.py`: `holds_claim`.
- `src/asmbly_ceramics/use_cases/emails.py`: the claim's `CommitOutcomeUnknown` branch,
  `_after_unknown_claim`, the module docstring.
- `tests/domain/test_email.py`: `holds_claim`'s cases.
- `tests/use_cases/test_emails.py`: the use case's outcomes, with a fake in the module.
- `tests/entry/test_mailer.py`: a claim that landed behind an unknown outcome isn't
  retried by Lambda.
- `docs/architecture.md`: one bullet under "What the domain code settles".

## Implementation details

### app

**The domain** (`domain/email.py`), plain Python:

```python
def holds_claim(stored: Email | None, claimed: Email) -> bool:
    """Whether `stored` (re-read by key) is the claim `claimed` made: sending, with the same
    `claimed_at` and `attempts`. False for None, for any other status, and for another
    call's claim (another `claimed_at`, or an attempt counted since)."""
```

`claimed` is what `claim(email, now)` returned, so its `claimed_at` is this call's `now`
(an aware time to the microsecond) and its `attempts` the counted attempt. The version is
not compared: the stored one is what the next `Update` must carry, so the use case goes
on with `stored`, not `claimed`.

**The use case** (`use_cases/emails.py`, `SendPendingEmail.__call__`):

```python
claimed = claim(email, now)
try:
    self._records.commit([Update(claimed)])
except Conflict:
    return None
except CommitOutcomeUnknown as unknown:
    stored = self._after_unknown_claim(claimed, unknown)  # raises `unknown`, or None
    if stored is None:
        return None
    claimed = stored  # holds this claim, at the version `Records` stored
else:
    claimed = replace(claimed, version=claimed.version + 1)
try:
    return self._send(claimed, now)
except Exception as error:
    ...  # unchanged
```

`_after_unknown_claim(self, claimed: Email, unknown: CommitOutcomeUnknown) -> Email | None`:

1. `stored = self._records.email(claimed.drop_off_id, claimed.kind, claimed.occasion)`;
   on `Unavailable` (any port error), log
   `email_claim_unknown` (WARNING, `kind`, `drop_off_id`, `outcome="unreadable"`,
   `error_code=unknown.code`) and `raise unknown from None`: nothing was sent and the
   stream retries.
2. `holds_claim(stored, claimed)`: log `email_claim_unknown` (WARNING,
   `outcome="held"`, `error_code=unknown.code`) and return `stored`.
3. `stored` is pending (or `None`, which can't happen for an email the call just read,
   and is treated the same): log `email_claim_unknown` (WARNING, `outcome="not_held"`)
   and `raise unknown from None`.
4. Anything else: log `email_claim_unknown` (WARNING, `outcome="taken"`) and return
   `None`; another call holds it, or it is finished.

`kind`, `drop_off_id`, `outcome` and `error_code` already have shapes in
`use_cases/log.py`; no new field. Nothing logged holds an address or a message.

A plain `RecordsUnavailable` (not `CommitOutcomeUnknown`) on the claim is unchanged: it
means nothing was written, and it goes up so the stream retries.

**Ports, adapters, fakes:** unchanged. `MemoryRecords.fail_next_commit_with` raises
*before* writing, so the tests use their own subclass that writes and then raises.

**Wiring:** unchanged (`composition.build_mailer`).

### web, infra, ci

None. Nothing reaches AWS but the mailer's code.

### docs

`docs/architecture.md`, "What the domain code settles": "The mailer re-reads an email
whose claim's outcome is unknown and sends it when the stored email holds that claim
(`holds_claim`); a claim that lands only after the re-read waits for staff, as a stuck
email."

## Tests

`tests/domain/test_email.py`:

- `test_holds_claim_when_the_stored_email_is_this_claim`: `claim(pending, NOW)` stored at
  version + 1 is held.
- `test_holds_claim_is_false_for_a_pending_email`, `..._for_none`,
  `..._for_another_calls_claim` (another `claimed_at`), `..._for_a_later_attempt` (one
  more attempt counted), `..._for_a_sent_failed_or_cancelled_email` (parametrized).

`tests/use_cases/test_emails.py`, with a module fake
`UnknownClaimRecords(MemoryRecords)` that, for a commit holding one email `Update` whose
status is sending, writes it (`lands=True`) or not, optionally makes reads fail after,
and raises `CommitOutcomeUnknown("ReadTimeoutError")`; every other commit passes through:

- `test_a_claim_that_landed_behind_an_unknown_outcome_is_sent_once`: returns `SENT`; one
  message, to the drop-off's own address; the stored email is sent with `attempts == 1`;
  one `email_claim_unknown` line with `outcome == "held"`, `drop_off_id == "AC-1"` and no
  address in any log record.
- `test_a_claim_that_didnt_land_raises_so_the_stream_retries`: raises
  `CommitOutcomeUnknown`; nothing sent; the email is still pending with `attempts == 0`;
  `outcome == "not_held"`. A second call (the stream's retry, ordinary records) sends it
  once.
- `test_a_claim_whose_reread_fails_raises_and_sends_nothing`: raises the original
  `CommitOutcomeUnknown` (its `code` is `ReadTimeoutError`), nothing sent,
  `outcome == "unreadable"`.
- `test_a_claim_another_call_took_meanwhile_returns_none`: the fake stores another claim
  (another `claimed_at`) instead of this one; returns `None`, nothing sent,
  `outcome == "taken"`.
- `test_a_claim_that_landed_and_then_fails_to_send_is_marked_failed`: held, then the
  mailer refuses (`world.mailer` set to fail): the stored email is failed with the
  refusal's code at the version after the claim (proves the use case went on with the
  stored version, not `claimed.version + 1` blindly).
- `test_a_plain_records_failure_on_the_claim_still_raises` (regression of today's
  behavior): `RecordsUnavailable` raised by the claim goes up and no re-read happens
  (`records.reads` holds only the first `email` read).

The world is rebuilt on the module fake before the drop-off is made: `world.submit` with
`rebuilt(world, records=fake)` from `tests/use_cases/test_submit.py`, and `world.send_email`
as a new `SendPendingEmail` on the same fake and the world's other fakes; the fake is armed
only after `dropped_off`. `conftest.py` isn't changed.

`tests/entry/test_mailer.py`:

- `test_a_claim_that_landed_behind_an_unknown_outcome_isnt_retried`: the handler, built on
  the fakes with that fake, returns no `batchItemFailures` and logs no `mailer_crashed`.

## Acceptance criteria

1. A claim commit that lands and raises `CommitOutcomeUnknown` sends the email in the same
   call, once, and stores it sent (#22's suggested fix; #21 part 2).
2. A claim commit that doesn't land and raises `CommitOutcomeUnknown` sends nothing and
   raises, so Lambda retries the record; the retry sends it once.
3. If the re-read fails, nothing is sent and the original error goes up.
4. If another call holds the email, nothing is sent and the call returns `None`.
5. Every outcome logs `email_claim_unknown` with the drop-off's ID, the kind and an
   outcome word, never an address; `_send`'s logging is unchanged.
6. `holds_claim` is the one rule, in `domain/email.py`, tested without fakes.

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .` passes.
- [ ] `uv run mypy` passes, with type hints on `holds_claim` and `_after_unknown_claim`.
- [ ] `uv run pytest --cov` passes and the coverage floor holds.
- [ ] `domain/` and `use_cases/` import nothing from `boto3`, `botocore`, `starlette` or
      `jinja2` (the existing grep test).
- [ ] No log record in the new tests holds `TEST_EMAIL` or the photos' bytes
      (`tests/use_cases/test_no_personal_details_logged.py` style assertion in each test).

After the merge: nothing to see unless a claim times out. On stage, drop off with a
made-up name to the tester's own inbox; the received email arrives there once, and the mailer's log shows
`email_sent` for that ID and no `email_claim_unknown`. With phase 3's limit live (the
phases merge together), this spends one of that inbox's three drop-offs a day (#18), so
phase 3's check uses another inbox, or waits 24 hours.

## Rollout

Code only: the mailer function's new version, deployed by the merge (stage, its smoke
test, prod, its smoke test). No new resource, right or stored attribute. Check: on
stage, a drop-off's received email arrives once. Undo: revert the pull request.

## Admin actions

None.

## Hand-off

Built on branch `feat/harden-outgoing-email`; stays `[~] In progress` until the merge's
deploy and the stage check under Rollout (a received email arrives once), confirmed by
the maintainer, who then sets this phase's tracker row to `[x] Complete`.

- `domain.email.holds_claim(stored, claimed) -> bool`: the one rule for "this re-read
  email is my claim" (sending, same `claimed_at` and `attempts`; the version isn't
  compared).
- `SendPendingEmail._after_unknown_claim(claimed, unknown) -> Email | None`: logs
  `email_claim_unknown` (WARNING; `kind`, `drop_off_id`, `error_code`, `outcome` one of
  `held`, `not_held`, `unreadable`, `taken`). No port, fake, adapter, wiring or template
  changed; nothing for phases 2 and 3 to rely on.
- `tests/use_cases/test_emails.py::UnknownClaimRecords` and `on_unknown_claims(world)`:
  a `MemoryRecords` whose armed claim lands (or not, or something else lands instead)
  and then raises `CommitOutcomeUnknown`; `tests/entry/test_mailer.py` reuses it.
- Deferred, as the plan says: a claim that lands only after the re-read still waits for
  staff as a stuck email.
