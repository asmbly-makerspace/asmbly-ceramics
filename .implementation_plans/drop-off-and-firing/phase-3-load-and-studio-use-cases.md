---
phase_id: 3
title: "Use cases: loads, settings, close, counts"
epic: 1
implements: [4, 6, 7]
depends_on: [2b, 2d]
domain: [app]
estimated_size: L
---

# Phase 3: Use cases: loads, settings, close, counts

> **Status:** [x] Complete — 2026-11-13 on branch feat/drop-off-and-firing-phases-2-4

## Required reading

- [CLAUDE.md](../../CLAUDE.md): email only from the console's `asmbly.org` address and
  only to the person who dropped off or the signed-in staff member; keep personal
  details no longer than #7 says.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): the
  outbox, at-least-once delivery from the stream, the 48-drop-off load, the daily close.
- This plan's [README](README.md#domain-model), phase 1 ([1b](phase-1b-drop-offs-photos-outbox.md), [1c](phase-1c-loads-waiting-search.md),
  [1d](phase-1d-ports-and-fakes.md)) (the
  load, email, studio and closing rules, the ports and fakes) and
  phase 2 ([2a](phase-2a-logging-studio-and-form-reads.md): `log_event`, `CurrentStudio`,
  the test `world` fixture; [2c](phase-2c-email-composer.md): `Composer`, `outgoing` (from `ports/composer.py`);
  [2d](phase-2d-waiting-list-and-rejection.md): `FindDropOffs`, and the undone-rejection
  rule `RetryEmail` and `SendPendingEmail` keep). A name that differs from those is a mistake
  here.
- Story #4 (loads, the ready email, retry, the alarm), #6 (settings, test email,
  history), #7 (closing, counts), and epic #1's **Decided** list (the 14-day window
  counts from the ready email; staff pick a load's firing type by hand; weekly counts
  Monday to Sunday, Austin time; retry from the load and the drop-off).
- AWS: "Using AWS Lambda with Amazon DynamoDB" (`/lambda/latest/dg/with-ddb.html`):
  stream records are processed at least once, so duplicates happen. That is why
  `SendPendingEmail` claims before it sends.

## Goal

Every use case behind the console's second half and the two background jobs exists,
tested against the fakes: starting, changing, filling, emptying, firing and marking a
load fired (all its ready emails queued in the same commit); sending a queued email
once, with failures recorded by code and logged for the alarm; retrying a failed email;
the studio's settings and lists with their history and a test email; the daily close
that deletes personal details and photos; and the weekly counts.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `domain/counts.py` | `Week`, `week_containing`, `WeekCounts`, `count_week` |
| `use_cases/loads.py` | `StartLoad`, `ChangeLoad`, `AddToLoad`, `RemoveFromLoad`, `StartFiring`, `MarkFired`, `ViewLoad`, `LoadView`, `ListLoads` |
| `use_cases/emails.py` | `SendPendingEmail`, `RetryEmail` |
| `use_cases/settings.py` | `ViewStudio`, `ChangeEmailSettings`, `SendTestEmail`, `AddCatalogItem`, `RetireCatalogItem`, `RestoreCatalogItem`, `DeleteCatalogItem` |
| `use_cases/close.py` | `CloseFinished`, `CloseReport` |
| `use_cases/counts.py` | `WeeklyCounts` |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/domain/test_counts.py` | The week's bounds and the counting |
| `tests/use_cases/test_loads.py`, `test_emails.py`, `test_settings.py`, `test_close.py`, `test_counts.py`, `test_flow_logs.py` | The use cases |

## Files to modify

- `src/asmbly_ceramics/domain/errors.py`: add `NoStaffEmail` ("Your sign-in has no
  email address, so a test email can't be sent.") and `TestEmailFailed` ("The test email
  didn't send ({code}). Nothing was saved.", with `.code`).
- `src/asmbly_ceramics/domain/email.py`: `Email` gains `pickup_window_days: int | None =
  None`, the window a sent ready email gave; `mark_sent(email, at, *, pickup_window_days:
  int | None = None)` requires it (1 or more) for a ready email and refuses it for the
  other kinds (`ValueError`, a bug), so every sent ready email keeps the window the close
  counts from. `tests/domain/test_email.py`: both rules. Phase 4's DynamoDB conversion
  stores the field (its `/prep` adds it).
- `src/asmbly_ceramics/ports/mailer.py`: `REFUSED_CODES`, the codes a `Mailer` raises
  `SendFailed` with only when the provider answered that it did not take the message
  (SES's error responses: `MessageRejected`, `ThrottlingException`, `Throttling`,
  `TooManyRequestsException`, `LimitExceededException`, `SendingPausedException`,
  `AccountSuspendedException`, `MailFromDomainNotVerifiedException`,
  `NotFoundException`, `BadRequestException`, and the adapter's own
  `MessageTooLarge`). Any other code (a network error, a lost response, `unknown`) may
  have been sent.
- `src/asmbly_ceramics/use_cases/reject.py` and `tests/use_cases/test_reject.py`:
  `UndoRejection` reports a `FAILED` rejected email as `MAY_HAVE_GONE` when
  `emails.may_have_gone(email)` (below: a code not in `NOT_SENT_CODES`, or more than one
  attempt); the existing "failed means never
  went" test keeps a refused code, and new tests cover `unexpected` and an unlisted code.
- `tests/adapters/test_memory.py`: only if a `mark_sent` call there needs the new
  keyword.
- `tests/use_cases/conftest.py`: build this phase's use cases in the `world` fixture.
- `use_cases/emails.py` and `use_cases/settings.py` import `Composer`, `ComposedEmail`
  and `outgoing` from `asmbly_ceramics.ports.composer`, never from `mail/`: The use cases import only the domain, the ports and each other (`tests/domain/test_imports.py`, phase 2a), so they never import `mail/` or Jinja2. `ComposedEmail`, the `Composer` Protocol, `outgoing` and `cid` live in `ports/composer.py` (decided in phase 2a's review, like "AWS behind ports": the use cases depend on an interface, the templates are its one implementation); `mail/compose.py` holds `JinjaComposer`, which satisfies `Composer`.

No dependency changes: Jinja2 came with phase 2.

## Implementation details

### app: `domain/counts.py` (#7)

```python
@dataclass(frozen=True, slots=True)
class Week:
    monday: date  # Austin date

    def sunday(self) -> date: ...
    def utc_bounds(
        self,
    ) -> tuple[datetime, datetime]: ...  # [Monday 00:00, next Monday 00:00) in STUDIO_TZ, as UTC


def week_containing(day: date) -> Week: ...


@dataclass(frozen=True, slots=True)
class WeekCounts:
    week: Week
    drop_offs: Mapping[ItemId, int]  # created this week, per firing type
    pieces: Mapping[ItemId, int]  # per firing type
    loads: Mapping[ItemId, int]  # fired this week (fired_at), per kiln
    rejections: Mapping[ItemId, int]  # rejected this week (rejection.at), per reason


def count_week(
    week: Week, created: Iterable[DropOff], fired_loads: Iterable[Load], rejected: Iterable[DropOff]
) -> WeekCounts: ...
```

A closed drop-off still counts: it keeps its dates, firing type, pieces and reason. An
undone rejection has no rejection and doesn't count.

### app: loads (`use_cases/loads.py`) (#4)

```python
class StartLoad:
    def __init__(self, records: Records, ids: IdNumbers, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, kiln: ItemId, firing_type: ItemId, on: date | None, staff: StaffMember) -> Load:
        ...
        # on defaults to today, Austin; commit Put(load); log event=load_started, load_id, user


class ChangeLoad:  # "Change kiln, firing or date", only while loading; firing type only while empty (FiringTypeLocked)
    def __call__(
        self, load_id: LoadId, kiln: ItemId, firing_type: ItemId, on: date, version: int, staff: StaffMember
    ) -> Load: ...


class AddToLoad:
    def __init__(self, records: Records) -> None: ...
    def __call__(
        self, load_id: LoadId, drop_off_id: DropOffId, *, confirmed: bool, staff: StaffMember
    ) -> Load: ...


class RemoveFromLoad:
    def __call__(self, load_id: LoadId, drop_off_id: DropOffId, staff: StaffMember) -> Load: ...


class StartFiring:
    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load: ...


class MarkFired:
    def __init__(self, records: Records, clock: Clock) -> None: ...
    def __call__(self, load_id: LoadId, version: int, staff: StaffMember) -> Load: ...


@dataclass(frozen=True, slots=True)
class LoadView:
    load: Load
    kiln: str
    firing_type: str
    members: tuple[DropOff, ...]  # in the order added
    total_drop_offs: int
    total_pieces: int
    emails: Mapping[DropOffId, Email]  # the ready email of each member, once fired
    sent: int  # "11 of 12 emails sent"
    needing_attention: tuple[Email, ...]  # failed, or sending for too long
    waiting: tuple[WaitingRow, ...]  # waiting drop-offs, filtered to the load's firing type unless all=True


class ViewLoad:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, load_id: LoadId, *, all_firing_types: bool = False) -> LoadView: ...


class ListLoads:
    def __call__(
        self,
    ) -> tuple[list[Load], list[Load]]: ...  # (loading or firing, fired in the last 8 weeks newest first)
```

- **Reads before a change are strongly consistent** (`records.load`, `records.drop_off`),
  and every change is one commit of `Update`s with the versions read, so two staff
  acting at once can't both win: the loser gets `Conflict`, and the page asks them to
  reload.
- `AddToLoad`: reads the load and the drop-off (`NotFound` for either);
  `add_to_load(load, drop_off, confirmed=confirmed)`; commit `Update(load)`,
  `Update(drop_off)`. `FiringTypeMismatch` passes up for the page to ask "Add anyway?";
  the page calls again with `confirmed=True`. `NotWaiting` and `AlreadyInLoad` pass up
  with their reason ("AC-88 isn't waiting: it is fired."). Typed or scanned IDs are
  parsed by the page with `parse_query` (its `query.id`, or nothing to add when it is
  `None`); a name search uses `FindDropOffs(...,
  waiting_only=True)` from phase 2 and then adds by ID. Logs `event=added_to_load`,
  `load_id`, `drop_off_id`, `user`.
- `RemoveFromLoad`: the reverse; the drop-off is back in the waiting list. Logs
  `event=removed_from_load`.
- `ChangeLoad`: reads the load (`NotFound`), `change_load(load, kiln, firing_type, on,
  studio)`, and commits `Update(load)` with the version the page read. Its outcomes:
  - a new kiln, or a new date, is allowed while the load is loading, with or without
    drop-offs in it; members are kept;
  - a new firing type is allowed only while the load is empty; once it has drop-offs,
    `FiringTypeLocked` passes up ("Load L-4 has drop-offs in it: remove them before
    changing its firing type.") and nothing is committed;
  - a retired or unknown kiln or firing type it changes to raises the studio's error;
  - a load that is firing or fired raises `LoadNotLoading` and nothing is committed.
  Logs `event=load_changed`, `load_id`, `user`.
- `StartFiring`: `start_firing`; commit `Update(load)`. Logs `event=load_firing`.
- `MarkFired`: reads the load and every member drop-off (strongly consistent, one by
  one; at most 48), `fire(load, members, now)`, and commits `Update(load)`, an
  `Update` for each drop-off and a `Put` of each ready email: at most 97 changes, within
  the port's 100. `AlreadyFired` passes up and nothing is queued: firing again sends
  nothing. A ready email that already exists for a drop-off would make the commit fail
  with `Conflict`; that can't happen for a drop-off fired once, and the test shows the
  commit holds exactly one ready email each. Logs `event=load_fired`, `load_id`,
  `count` (drop-offs), `user`.
- `ViewLoad` shows each member's ID, name, pieces and thumbnail (the page fetches the
  thumbnail), the totals, and once fired, how many ready emails are sent and which need
  attention. Past loads stay viewable with their contents (#4).

### app: sending and retrying email (`use_cases/emails.py`) (#4, #2, #5)

```python
class SendPendingEmail:
    def __init__(
        self,
        records: Records,
        photos: PhotoStore,
        mailer: Mailer,
        clock: Clock,
        studio: CurrentStudio,
        composer: Composer,
    ) -> None: ...
    def __call__(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str) -> EmailStatus | None: ...


class RetryEmail:
    def __init__(self, records: Records, clock: Clock) -> None: ...
    def __call__(
        self, drop_off_id: DropOffId, kind: EmailKind, occasion: str, staff: StaffMember
    ) -> Email: ...
```

`SendPendingEmail` is what the mailer function (phase 7) calls for each stream record
whose new image has `status = pending`. In order:

1. `records.email(...)` (strongly consistent). Missing, or not `PENDING`: return `None`
   (a duplicate delivery; nothing happens).
2. **Claim**: commit `Update(claim(email, now))`. `Conflict` means another invocation
   claimed it: return `None`. Only the claimer sends, so a duplicate stream record
   never sends twice.
3. Read the drop-off. If it is `CLOSED`, or the email is `REJECTED` and
   `not is_still_rejected(drop_off, email.occasion)` (`domain.email`: the one check,
   comparing `rejection_occasion(drop_off.rejection.at)`, UTC to the microsecond, so a
   time read back in another offset or precision still matches; the rejection was
   undone, or undone and rejected again), commit `mark_cancelled` and log
   `event=email_cancelled`. Nothing is sent.
4. Read the current studio (#6: every email after a change uses the new settings) and
   each photo's full-size copy (`photos.read(ref, PhotoSize.FULL)`). A missing photo
   fails the email with code `photo_missing`.
5. Compose with `Composer` (`received`, `ready` with `sent_at=now`, or `rejected`),
   with `cid` image sources, and `outgoing(..., to=drop_off.contact.email,
   sending_address=studio.sending_address, photos=...)`. The recipient is always the
   drop-off's own email: no other address is possible here.
6. `mailer.send(...)`. On success commit `mark_sent(email, now)` and log
   `event=email_sent`, `kind`, `drop_off_id`. For a ready email, `sent_at` is when the
   pickup window starts (#7). The ready email's record keeps the pickup window it was
   composed with (`studio.pickup_window_days` at send, committed with `mark_sent`), so
   the close counts from the same window the email's date came from (phase 2c's
   review). Read the photos (step 4) by the same drop-off key as the recipient;
   `outgoing` refuses a ref naming another drop-off or a repeated index.
7. On `SendFailed(code)` commit `mark_failed(email, code)` and log, at ERROR:
   `event=email_failed`, `kind`, `drop_off_id`, `error_code`. On any other exception,
   the same with `reason=unexpected` and the exception's class name as `error_code`
   (`KeyError`: `error_code`'s log shape takes it; never the exception's text; the
   email stores `mark_failed(email, "unexpected")`), and return instead of raising, so
   the stream doesn't retry a send that may have half-happened.

   Because such a send may have reached the person, phase 2d's `UndoRejection` must not
   keep telling staff it never went. **Decided (prep):** a failure is known not to
   have gone only when its code is in `NOT_SENT_CODES` = `ports.mailer.REFUSED_CODES`
   plus this module's pre-send codes, which are stored when the failure happened before
   `mailer.send` was called: `photo_missing` (`UploadMissing` reading a photo),
   `photos_unavailable` (`PhotosUnavailable`), `compose_failed` (the `Composer` or
   `outgoing` raised `ValueError`), `drop_off_missing`, and `records_unavailable` (the
   drop-off or the studio couldn't be read after the claim). `was_not_sent(code)` is
   that check, and `may_have_gone(email)` adds that an email tried more than once may
   have gone on an earlier attempt. `UndoRejection` gives `NOT_SENT` for a `FAILED`
   email only when `may_have_gone` is false, and `MAY_HAVE_GONE` otherwise (`unexpected`, `unknown`, a timeout,
   any code not listed): an allowlist, so a new code fails safe toward "contact the
   person" (phase 2d's review, #5).
   An unexpected exception raised before `mailer.send` is still stored as
   `unexpected`. That is cautious, because it may come from inside the send.

   A successful send whose `mark_sent` commit then fails is never marked failed. The
   use case logs `event=email_unrecorded` at ERROR with `kind`, `drop_off_id` and
   `error_code`, and returns `SENDING` (see below).

**The log line phase 7's alarm counts** is exactly:
`{"level": "ERROR", "event": "email_failed", "kind": "<received|ready|rejected>", "drop_off_id": "AC-12", "error_code": "<code>"}`
(plus the formatter's own fields). Its metric filter is `{ $.event = "email_failed" }`.
Decided: a log line and a metric filter, not a `Metrics` port, so no new port and no
CloudWatch right in the mailer.

If the commit after a successful send fails, the email stays `SENDING`; after
`STALE_SENDING_AFTER` it shows as needing attention and can be retried, which may send
it twice. That is accepted: a duplicate email is better than a lost one, and the case
needs DynamoDB to fail between two calls.

`RetryEmail` (#4: "Try sending again" on the load's page and the drop-off's page):
`retry(email, now)` (failed, or stuck sending) and commit `Update`. The stream then
delivers it to `SendPendingEmail` again. It goes only to that drop-off: the key names
it. Logs `event=email_retried`, `kind`, `drop_off_id`, `user`. When it is sent, the
failure clears because the item's status is `SENT`.

### app: settings (`use_cases/settings.py`) (#6)

```python
@dataclass(frozen=True, slots=True)
class StudioView:
    studio: Studio
    history: tuple[SettingChange, ...]
    used: Mapping[tuple[CatalogList, ItemId], bool]  # which items can only be retired
    older: str | None  # the next page's cursor (Records.history's HistoryPage.older); None at the end


class ViewStudio:
    def __call__(self, before: str | None = None, limit: int = 20) -> StudioView: ...  # newest first


class ChangeEmailSettings:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(
        self,
        *,
        sending_address: str,
        pickup_window_days: str,
        pickup_hours_text: str,
        version: int,
        staff: StaffMember,
    ) -> Studio: ...


class SendTestEmail:
    def __init__(self, mailer: Mailer, studio: CurrentStudio, composer: Composer) -> None: ...
    def __call__(self, *, sending_address: str, staff: StaffMember) -> None: ...


class AddCatalogItem:
    def __call__(
        self,
        which: CatalogList,
        name: str,
        *,
        needs_glaze_type: bool,
        needs_message: bool,
        version: int,
        staff: StaffMember,
    ) -> Studio: ...


class RetireCatalogItem:
    def __call__(self, which: CatalogList, id: ItemId, version: int, staff: StaffMember) -> Studio: ...


class RestoreCatalogItem: ...  # same signature


class DeleteCatalogItem: ...  # same signature; asks records.is_item_used first
```

- Each change: read the studio, check the `version` the page showed (`Conflict`
  otherwise), apply the domain function, commit `Update(studio)` and a `Put` of each
  `SettingChange(by=staff.username)`. Logs `event=settings_changed`, `user`, and for
  lists `list` and `item` (item IDs, not names).
- `ChangeEmailSettings`: `check_sending_address` refuses an address outside
  `asmbly.org` with `SendingAddressOutsideAsmbly` (#6).
- `SendTestEmail` (#6: "sends from the new address to the signed-in staff member before
  it is saved"): `check_sending_address(sending_address)`; `NoStaffEmail` when
  `staff.email` is `None`; composes `Composer.test(studio)` and sends it with
  `outgoing(..., to=staff.email, sending_address=<the new address>)`. It doesn't save
  anything and isn't queued: it is sent now, and `SendFailed(code)` becomes
  `TestEmailFailed(code)` for the page. The recipient is only ever the signed-in staff
  member's own address from their verified token. Logs `event=test_email`, `user`,
  `outcome` (`sent` or `failed`), `error_code`.
- `DeleteCatalogItem`: the domain refuses an active item (`InvalidSetting("status",
  "Retire Kiln Four before deleting it.")`): only a retired item can be deleted, so it
  asks `records.is_item_used(...)` only once retiring has stopped new use. Then
  `ItemInUse` when used (#6: anything a drop-off or load has used stays retired).
  **Accepted race (review round 1):** a `SubmitDropOff`, `RejectDropOff`, `StartLoad` or
  `ChangeLoad` that read the studio before the retire, and commits after the delete, can
  still name the deleted item, because no commit checks the studio's version. Closing it
  needs a condition on the studio's version in those commits, which is a change to the
  `Records` port, its fake and phase 4's adapter. It is left as a follow-up (#21).
- `ViewStudio(before)`: `before` is the opaque cursor from the previous page's
  `older`; `BadCursor` (a hand-edited address) passes up to the page, which shows the
  first page. Changes saved at one instant are never split or skipped across pages.

### app: closing (`use_cases/close.py`) (#7)

```python
@dataclass(frozen=True, slots=True)
class CloseReport:
    closed: tuple[DropOffId, ...]
    failed: int


class CloseFinished:
    def __init__(self, records: Records, photos: PhotoStore, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self) -> CloseReport: ...
```

1. `records.drop_offs_in({FIRED, REJECTED})`; the studio's current pickup window.
2. For each: the ready email's `sent_at` when fired (`records.email(id, READY)`);
   `is_due_to_close(...)` (its private `_is_closable` since the third review), which compares now with `pickup_deadline` (phase 2c's review):
   the start of the Austin day after the pickup-by day the email named, so the close
   never deletes on that day. For a fired drop-off the window passed is the one kept
   with its sent ready email (below), never the studio's current window: staff
   shortening it afterwards must not delete details before an emailed date. A fired
   drop-off whose ready email never sent is skipped; the
   console's load and drop-off pages show its failed email (phase 9), and it closes
   once the email is sent and the window has passed.
3. For each closable one: first `photos.delete_drop_off(id)` (idempotent), then commit
   `Update(close(drop_off, now))` with the version read. Photos first, so a failure
   between the two leaves a drop-off that the next run closes again, never a closed
   drop-off whose photos remain. A `Conflict` or any other failure for one drop-off is
   logged (`event=close_failed`, `drop_off_id`, `error_code` or `reason`) and the run
   goes on to the next.
4. Logs `event=drop_off_closed`, `drop_off_id` for each, then one `event=close_run`
   with `count` (how many closed); failures are logged per drop-off (step 3).

Running it twice in a row closes nothing the second time. What closing keeps and
deletes is `domain.closing.close`'s rule (phase 1). The rate-limit counts and submission
items hold only keyed hashes and an ID, and expire on their own (TTL, phase 4).

### app: counts (`use_cases/counts.py`) (#7)

```python
@dataclass(frozen=True, slots=True)
class CountsView:
    counts: WeekCounts
    names: Mapping[
        tuple[CatalogList, ItemId], str
    ]  # item names, retired ones included (IDs are unique per list)
    overdue: tuple[WaitingRow, ...]  # waiting 60 days or more, oldest first (listed first on the page)


class WeeklyCounts:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(
        self, day: date | None = None
    ) -> CountsView: ...  # the week containing day; this week by default
```

Uses `records.drop_offs_created_between`, `records.loads_in({FIRED})` filtered to
loads whose `fired_at` falls in the week, `records.drop_offs_rejected_between`, and the
waiting list's overdue rows (`WaitingList`'s rows with `overdue`). **Decided (prep):**
the week is not read with `loads_between`, which goes by the load's `date`. A load dated
Sunday and fired overnight into Monday counts in the week it was fired.

### Prep notes for the build (from this phase's audit)

- `RetryEmail` reads the drop-off too. An email that `is_history` (the drop-off is
  closed, or the rejection was undone) is refused with `EmailNotRetryable`. A retry of
  an email that is already `PENDING` and not stuck (a double click) returns it unchanged
  and commits nothing; one stuck pending is written again (review round 1). Tests: `test_retry_refuses_a_closed_drop_offs_email`,
  `test_retry_of_a_pending_email_changes_nothing`.
- In `SendPendingEmail` the catch-all starts only after a successful claim. Before
  that, `RecordsUnavailable` and any other error are raised, so the stream retries and
  nothing has been sent. `email_failed` is logged before the `mark_failed` commit, so
  the alarm counts it even if that commit fails.
- `MarkFired`, `StartFiring` and `ChangeLoad` let the domain's status refusal
  (`AlreadyFired`, `LoadNotLoading`, `WrongLoadStatus`) win over a stale version. A
  second click on "Fired" gets `AlreadyFired`, not `Conflict`.
- `CloseFinished`: on a `Conflict` it reads the drop-off again. One already `CLOSED`
  (by an overlapping run) isn't a failure. `close_failed` is logged at ERROR.
- `SendTestEmail` passes `check_sending_address`'s normalized result to `outgoing`. A
  `ValueError` from `outgoing` (the token's address isn't an address) becomes
  `TestEmailFailed("bad_recipient")`.
- `ChangeEmailSettings` with nothing changed commits and logs nothing, and returns the
  studio as stored.
- `test_flow_logs` also asserts that no record carries `exc_info`.
- `WeekCounts.pieces` counts the pieces of drop-offs created that week, beside
  `drop_offs`. `ListLoads` lists fired loads by `fired_at` within the last 8 weeks
  (`loads_in({FIRED})`), not by `date`.
- **Decided (prep):** a rejected drop-off closes by the rejection's time whatever its
  rejected email's status. #7's retention rule bounds how long the details are kept,
  and staff see the failed email on the drop-off's page throughout the window. This
  differs from a fired drop-off, which waits for its ready email because the window
  counts from that email. It is an open question for the maintainer (#20).
- Phase 7 keeps the mailer function's timeout well under `STALE_SENDING_AFTER` (15
  minutes), so a retry of a stuck email can't overlap a live send. Phase 9's close
  handler calls `CloseFinished()` with no arguments: the use case reads the clock.

## Tests

`tests/domain/test_counts.py`:

- `test_a_week_runs_monday_to_sunday_austin_time` (Sunday 23:30 Austin is in the week;
  Monday 00:10 Austin is the next, though both are Monday in UTC).
- `test_counts_by_firing_type_kiln_and_reason`; `test_closed_drop_offs_still_count`;
  `test_an_undone_rejection_doesnt_count`.

`tests/use_cases/test_loads.py` (#4):

- `test_start_load_defaults_to_today_in_austin`; `test_start_load_refuses_a_retired_kiln`.
- `test_add_by_id_moves_it_from_waiting_into_the_load`.
- `test_add_refuses_a_drop_off_that_isnt_waiting_with_the_reason`;
  `test_add_refuses_one_already_in_another_load_naming_it`.
- `test_a_different_firing_type_asks_then_adds_when_confirmed`.
- `test_remove_puts_it_back_in_the_waiting_list`.
- `test_change_load_changes_kiln_and_date_with_drop_offs_in_it`.
- `test_change_load_refuses_a_new_firing_type_once_it_has_drop_offs` (`FiringTypeLocked`,
  nothing committed); `test_change_load_changes_the_firing_type_of_an_empty_load`.
- `test_change_load_refuses_a_load_that_isnt_loading` (`LoadNotLoading` once firing or
  fired, nothing committed).
- `test_nothing_can_be_added_or_removed_once_firing`.
- `test_mark_fired_marks_every_member_and_queues_one_ready_email_each_in_one_commit`.
- `test_marking_fired_again_queues_nothing`.
- `test_two_staff_adding_at_once_one_gets_a_conflict` (the fake's version check).
- `test_a_fired_load_and_its_drop_offs_cant_change`.
- `test_view_load_counts_drop_offs_pieces_and_sent_emails_and_lists_failures`.
- `test_view_load_waiting_list_defaults_to_the_load_firing_type`.
- `test_past_loads_are_listed_with_their_contents`.

`tests/use_cases/test_emails.py`:

- `test_a_pending_email_is_sent_once_to_the_drop_offs_own_address`.
- `test_a_duplicate_delivery_sends_nothing` (call twice; `MemoryMailer.sent` has one).
- `test_a_claim_lost_to_another_invocation_sends_nothing`.
- `test_the_email_uses_the_settings_in_force_when_sent` (change the sending address,
  then send).
- `test_a_ready_email_records_sent_at_for_the_pickup_window`.
- `test_a_failure_records_the_code_and_logs_email_failed` (the exact field names above).
- `test_an_unexpected_error_is_recorded_without_its_text_and_not_raised`.
- `test_a_missing_photo_fails_the_email_with_photo_missing`.
- `test_an_undone_rejections_email_is_cancelled_not_sent`;
  `test_a_rejection_read_back_in_another_offset_is_still_sent` (the stored rejection's
  time in Austin time, the email's occasion from `rejection_occasion`: sent, not
  cancelled).
- `test_a_closed_drop_offs_email_is_cancelled`.
- `test_retry_requeues_only_that_email_and_a_send_clears_the_failure` (#4).
- `test_retry_refuses_a_sent_email`.

`tests/use_cases/test_settings.py` (#6):

- `test_an_address_outside_asmbly_org_is_refused`.
- `test_the_test_email_goes_from_the_new_address_to_the_signed_in_staff_member_and_saves_nothing`.
- `test_a_test_email_without_a_staff_email_is_refused`.
- `test_a_failed_test_email_reports_the_code`.
- `test_every_change_records_who_and_when` and `test_history_pages_newest_first`;
  `test_history_pages_keep_the_changes_of_one_save_together` (an email-settings save
  that changes all three values, paged 2 at a time, shows all three once).
- `test_a_used_kiln_can_be_retired_not_deleted`; `test_an_active_item_must_be_retired_before_it_is_deleted`;
  `test_a_retired_unused_item_can_be_deleted`.
- `test_the_history_holds_no_sending_address` (the change reads "Changed the sending
  address").
- `test_a_stale_version_is_a_conflict`.
- `test_a_new_firing_type_needing_a_glaze_type_is_offered_by_the_form` (the next
  submission accepts it).

`tests/use_cases/test_close.py` (#7):

- `test_a_fired_drop_off_closes_once_the_window_has_passed_since_the_ready_email`
  (not one second before the end of the Austin pick-up-by day, at the next run).
- `test_a_shorter_window_set_after_the_ready_email_doesnt_close_early` (the close uses
  the window kept with the sent email).
- `test_a_rejected_drop_off_closes_once_the_window_has_passed_since_the_rejection`.
- `test_closing_deletes_name_email_phone_message_and_photos_and_keeps_the_rest`
  (asserts on the stored item and on `MemoryPhotoStore`).
- `test_a_fired_drop_off_whose_ready_email_failed_doesnt_close`.
- `test_a_waiting_drop_off_never_closes`.
- `test_photos_are_deleted_before_the_record_is_closed` and
  `test_a_failed_commit_leaves_it_for_the_next_run`.
- `test_running_twice_closes_nothing_the_second_time`.
- `test_one_failure_doesnt_stop_the_run`.

`tests/use_cases/test_counts.py` (#7):

- `test_this_weeks_counts_by_firing_type_kiln_and_reason`;
  `test_overdue_drop_offs_are_listed_oldest_first`.

`tests/use_cases/test_reject.py` (#5, added):

- `test_undo_after_an_unexpected_failure_says_it_may_have_gone`;
  `test_undo_after_an_unlisted_failure_code_says_it_may_have_gone`; the existing
  refused-code test keeps `NOT_SENT`.

`tests/use_cases/test_flow_logs.py` (next to phase 2's
`test_no_personal_details_logged.py`, which covers the form and rejection alone):

- `test_a_whole_flow_logs_no_personal_details`: with made-up details built in code
  (a name like "Test Person", an address built from parts on `example.org`, a phone
  built from digits, a rejection message), runs submit, reject, undo, start a load, add,
  start firing, mark fired, send each pending email (one failing), retry, a settings
  change, a test email, and the close after the window; captures every record with
  `caplog` and asserts none holds the name, address, phone, message or a token, in its
  message or its extra fields.

## Acceptance criteria

1. `AddToLoad` with a drop-off already in another load raises `AlreadyInLoad` naming
   both IDs and commits nothing (#4).
2. `AddToLoad` with a different firing type raises `FiringTypeMismatch` unless
   `confirmed=True` (#4).
3. After `StartFiring`, `AddToLoad`, `RemoveFromLoad` and `ChangeLoad` raise
   `LoadNotLoading` (#4). `ChangeLoad` changes the kiln and date of a loading load with
   drop-offs in it, and refuses a new firing type with `FiringTypeLocked` once it has
   any (#4).
4. `MarkFired` commits the load, every member drop-off and one ready email each in a
   single commit; a second `MarkFired` raises `AlreadyFired` and commits nothing (#4).
5. `SendPendingEmail` called twice for one email sends one message, to the drop-off's
   own address, from the studio's current sending address (#4, #6).
6. A failed send leaves the email `failed` with its code, logs `event=email_failed`
   with `kind`, `drop_off_id` and `error_code`, and `RetryEmail` requeues only that
   email (#4).
7. `ChangeEmailSettings` refuses an address outside `asmbly.org`; `SendTestEmail` sends
   from the unsaved address to the signed-in staff member only, and saves nothing (#6).
8. Every settings change commits a `SettingChange` with the staff username and time
   (#6); a used item can be retired, not deleted (#6).
9. `CloseFinished` closes a fired drop-off once the Austin day its ready email named
   as "Pick up by" has ended, counted with the window kept with that email, and a rejected one once it has passed since the rejection;
   the closed record has no name, email, phone, message or photos, and its photos are
   gone from the store (#7).
10. `WeeklyCounts` counts Monday to Sunday, Austin time (#7).
11. No log record from a full flow holds a name, email, phone, message or token.

## Verification

```bash
uv run pytest tests/domain/test_counts.py tests/use_cases
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

Nothing to see in production.

## Rollout

Nothing reaches AWS.

## Admin actions

None.

## Hand-off

Built on `feat/drop-off-and-firing-phases-2-4` (2026-11-13). What the next phases can rely
on, as built:

- **Constructors** (what phase 7's composition root builds): `StartLoad(records, ids,
  clock, studio)`, `ChangeLoad(records, studio)`, `AddToLoad(records)`,
  `RemoveFromLoad(records)`, `StartFiring(records)`, `MarkFired(records, clock)`,
  `ViewLoad(records, clock, studio)`, `ListLoads(records, clock)`,
  `SendPendingEmail(records, photos, mailer, clock, studio, composer)`,
  `RetryEmail(records, clock)`, `ViewStudio(records, studio)`,
  `ChangeEmailSettings` / `AddCatalogItem` / `RetireCatalogItem` / `RestoreCatalogItem` /
  `DeleteCatalogItem(records, clock, studio)`, `SendTestEmail(mailer, studio, composer)`,
  `CloseFinished(records, photos, clock, studio)`, `WeeklyCounts(records, clock,
  studio)`. Where the plan listed a clock that the use case never reads (`AddToLoad`),
  the use case doesn't take one.
- From the phase's last cold review: `EmailsNeedingAttention(records, clock)` in
  `use_cases/emails.py` is the console-wide list of emails needing attention
  (`needs_acting_on`, oldest first, from `Records.emails_in` over pending, sending and
  failed), as rows of key, status, error code and time only. It keeps a fired drop-off
  whose ready email never went out in sight after its load leaves `ListLoads`; the
  retention rule for such a drop-off stays with #20, before phase 9. `Records.loads_between`
  had no caller and is gone from the port and the fake (phase 4 no longer indexes loads by
  date). `domain.closing.is_closable` is now private (`_is_closable`): callers use
  `is_due_to_close`. `StaffTokens.verify` sets `StaffMember.email` only from a verified
  email claim, which `SendTestEmail` relies on.
- From the cold review: the close's whole rule is `domain.closing.is_due_to_close(drop_off,
  ready_email, studio_window_days, now)`. A sent ready email without its window raises,
  and the close reports it as `close_failed` instead of keeping the details silently.
  The console's "needs attention" check is `domain.email.needs_acting_on`, and phase 9
  calls it too. `use_cases.emails.may_have_gone(email)` is what `UndoRejection` asks: an
  email tried more than once may have gone, because `retry` clears the code.
  `CountsView.names` is keyed by `(CatalogList, ItemId)`.
- From review round 1 (privacy): a `pending` email the stream gave up on (phase 7's
  dead-letter queue) counts as needing attention after `STALE_SENDING_AFTER`, counted
  from `Email.retried_at` or `created_at`. "Try sending again" writes it again so the
  stream redelivers it. Without this, a fired drop-off whose ready email was stuck there
  would keep its details out of every console page's sight. Phase 4 stores `retried_at`
  as well as `pickup_window_days`.
- Follow-ups for the maintainer (review round 1, not done here): closing the
  retire-then-delete race above (a studio-version condition in `Records.commit`), and a
  claim commit whose response is lost, which leaves the email `sending` with no
  `email_failed` line until the console shows it after 15 minutes (phase 4: an
  idempotent commit, or phase 7: an alarm on stuck emails).
- `use_cases/emails.py`: `SendPendingEmail(drop_off_id, kind, occasion) -> EmailStatus
  | None` (`None`: nothing to do). It raises only before the claim, so the stream retries
  only when nothing was sent. `RetryEmail(drop_off_id, kind, occasion, staff)`.
  `was_not_sent(code)`, `NOT_SENT_CODES` and the pre-send codes `photo_missing`,
  `photos_unavailable`, `compose_failed`, `drop_off_missing`, `records_unavailable`,
  plus `unexpected`; `may_have_gone(email)`.
  Log events: `email_sent`, `email_failed` (ERROR: the alarm's line), `email_cancelled`,
  `email_unrecorded` (ERROR: sent, or failed, but the record couldn't be saved), and
  `email_retried`.
- `ports/mailer.py`: `REFUSED_CODES`. Phase 4's `SesMailer` raises `SendFailed` with one
  of these only for SES's error responses, and uses any other code (`unknown`, a
  network error's) when it can't know whether SES took the message.
- `domain/email.py`: `Email.pickup_window_days`, set by `mark_sent` for a ready email.
  Phase 4's item conversion must store it.
- `use_cases/loads.py`: `LoadView`, `RECENT_LOADS` (8 weeks, by `fired_at`).
  `use_cases/settings.py`: `StudioView`, `HISTORY_PAGE` (20), `BAD_RECIPIENT`.
  `use_cases/close.py`: `CloseReport(closed, failed)`. `use_cases/counts.py`:
  `CountsView`. `domain/counts.py`: `Week`, `week_containing`, `WeekCounts`,
  `count_week`.
- Log events for phase 7's metric filters: `load_started`, `load_changed`,
  `added_to_load`, `removed_from_load`, `load_firing`, `load_fired`,
  `settings_changed`, `test_email` (a failure at WARNING), `drop_off_closed`,
  `close_failed` (ERROR), `close_run`.

Decided at this phase's `/prep` and reviews (an unattended run, 2026-11-13), with the
questions left for the maintainer:

- Retention: a fired drop-off whose ready email never sends stays open, and its email
  shows as needing attention (failed, or stuck sending or pending). A rejected
  drop-off closes by the rejection's time whatever its email's status. Both are open
  questions for the maintainer in #20, to settle before phase 9 merges. A limit for
  fired drop-offs touches `domain/closing.py` alone. Making a rejected drop-off wait for
  its email also changes `is_due_to_close`'s signature and `CloseFinished`, which today
  reads no email for a rejected drop-off.
- `ViewStudio.used` stays a bool from `Records.is_item_used`. Phase 9 shows "Used" or
  "Not used yet", its own fallback; no story asks for a count.
- Follow-ups in #21: the retire-then-delete race (a studio-version condition in
  `Records.commit`), a lost claim response, and a repeated "Start load".
- For phase 4's `/prep`: `SendFailed` has no `retryable`, and the mailer marks every
  `SendFailed` `failed` (staff retry it). `SesMailer` uses `REFUSED_CODES` only for SES's
  error responses, and only when it made one attempt: SES's client retries are turned
  off, or a send whose earlier try got no answer is reported as `unknown`, with a
  Stubber test (else a timed-out send that SES took, then a throttled retry, would tell
  an undo `NOT_SENT`). The item conversion stores every `Email` field, including
  `pickup_window_days` and `retried_at`, with a round-trip test asserting each one.
- For phase 7's `/prep`: alarm on `email_unrecorded` as well as `email_failed`, since a
  ready email left `sending` never starts its window.
