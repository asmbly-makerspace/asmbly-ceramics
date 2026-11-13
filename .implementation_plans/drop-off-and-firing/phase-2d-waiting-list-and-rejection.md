---
phase_id: 2d
title: "Use cases: the waiting list, search, one drop-off and rejection"
epic: 1
implements: [3, 5]
depends_on: [2a, 2c]
domain: [app]
estimated_size: L
---

# Phase 2d: Use cases: the waiting list, search, one drop-off and rejection

> **Status:** [ ] Pending

Part of phase 2, split into 2a to 2d by `/prep` (see
[phase 2a](phase-2a-logging-studio-and-form-reads.md)). The logging rules,
`CurrentStudio` and the `world` fixture from 2a, and the `Composer` from
[2c](phase-2c-email-composer.md), apply here unchanged.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the logging rules; "escape it wherever it is shown or
  put in an email".
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): the
  outbox, one transaction per change with a version check.
- [Phase 2a](phase-2a-logging-studio-and-form-reads.md),
  [phase 2c](phase-2c-email-composer.md), and phase 1
  ([1b](phase-1b-drop-offs-photos-outbox.md): `reject`, `undo_rejection`,
  `rejection_occasion`, `is_still_rejected`, `mark_cancelled`, `needs_attention`;
  [1c](phase-1c-loads-waiting-search.md): `parse_query`, `matches`, `waiting_order`,
  `totals`, `days_waiting`, `is_overdue`; [1d](phase-1d-ports-and-fakes.md): `Records`).
- Story #3 (the waiting list and search), #5 (rejection), and epic #1's **Decided** list
  (a rejected piece resubmitted gets a new ID).

## Goal

Every use case behind the first half of the console exists, tested against phase 1's
fakes and 2c's composer: the waiting list with its totals and filter, search by ID or
part of a name, one drop-off's page with its emails, and rejecting with a preview and a
same-day undo that cancels the rejection email if it hasn't gone.

## Files to create

| Path | What |
| --- | --- |
| `src/asmbly_ceramics/use_cases/waiting.py` | `WaitingRow`, `WaitingView`, `WaitingList`, `FindDropOffs` |
| `src/asmbly_ceramics/use_cases/view_drop_off.py` | `DropOffView`, `ViewDropOff` |
| `src/asmbly_ceramics/use_cases/reject.py` | `RejectRequest`, `PreviewRejection`, `RejectDropOff`, `UndoRequest`, `Undone`, `UndoRejection` |
| `tests/use_cases/test_waiting.py`, `test_view_drop_off.py`, `test_reject.py`, `test_no_personal_details_logged.py` | The use cases |

## Files to modify

- `tests/use_cases/conftest.py`: build this phase's use cases (and a `JinjaComposer`
  from `mail.compose`: tests may import it) in the `world` fixture.
- `use_cases/reject.py` imports `Composer` and `ComposedEmail` from
  `asmbly_ceramics.ports.composer`, never from `mail/`: The use cases import only the domain, the ports and each other (`tests/domain/test_imports.py`, phase 2a), so they never import `mail/` or Jinja2. `ComposedEmail`, the `Composer` Protocol, `outgoing` and `cid` live in `ports/composer.py` (decided in phase 2a's review, like "AWS behind ports": the use cases depend on an interface, the templates are its one implementation); `mail/compose.py` holds `JinjaComposer`, which satisfies `Composer`.

No dependency changes.

## Implementation details

### app: the waiting list and search (`use_cases/waiting.py`)

```python
@dataclass(frozen=True, slots=True)
class WaitingRow:
    drop_off: DropOff
    days_waiting: int  # domain.waiting.days_waiting
    overdue: bool  # domain.waiting.is_overdue
    firing_type: str  # the item's name
    glaze_type: str | None


@dataclass(frozen=True, slots=True)
class WaitingView:
    rows: tuple[WaitingRow, ...]
    totals: WaitingTotals
    firing_types: tuple[CatalogItem, ...]  # for the filter


class WaitingList:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, firing_type: ItemId | None = None) -> WaitingView: ...


class FindDropOffs:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, raw_query: str, *, waiting_only: bool = False) -> list[WaitingRow]: ...
```

- `WaitingList` (#3): `records.drop_offs_in({WAITING})`, `waiting_order`, `totals`
  over all waiting drop-offs (the totals ignore the filter), the filter by firing type
  applied to the rows only. Overdue rows are marked (#7). `firing_types` is the
  studio's active firing types plus any retired one that a waiting drop-off still has,
  in the studio's order, so every row can be filtered to. An unknown filter ID gives no
  rows, not an error.
- `FindDropOffs` (#3): `parse_query`. An ID reads `records.drop_off(query.id)`
  (any state, closed included, so staff can look up an old slip; with
  `waiting_only=True`, only when it is waiting). Text searches waiting, in-load, fired
  and rejected drop-offs (`waiting_only=True`: waiting only) with `matches`, oldest
  first, at most 50 rows (`SEARCH_MAX`, a named constant in `use_cases/waiting.py`). An
  empty query gives no rows. `waiting_only=True` is what the load page's search uses
  (phase 9).
- For a row whose drop-off isn't waiting, `days_waiting` is still the domain's count
  and `overdue` is `False` (`is_overdue` says so).
- Neither logs: reads aren't logged, and a search's text may be a name. (Phase 8 must
  keep the query out of access logs and the address bar: a POST, or a GET whose query
  API Gateway's access log omits. Noted for phase 8's prep.)

### app: one drop-off (`use_cases/view_drop_off.py`)

```python
@dataclass(frozen=True, slots=True)
class DropOffView:
    drop_off: DropOff
    firing_type: str
    glaze_type: str | None
    load: Load | None
    emails: tuple[Email, ...]
    emails_needing_attention: tuple[Email, ...]
    can_undo_rejection: bool
    reasons: tuple[CatalogItem, ...]  # active ones, for the reject form


class ViewDropOff:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, id: DropOffId) -> DropOffView: ...  # NotFound
```

- `emails` is `records.emails_for(id)`. `emails_needing_attention` is those with
  `needs_attention(email, now)`, except a rejected email whose rejection was undone
  (`not is_still_rejected(drop_off, email.occasion)`): it is history, not something to
  retry.
- `can_undo_rejection` is `REJECTED` and the same Austin day (the same rule as
  `undo_rejection`, by calling it on the drop-off and catching `UndoTooLate`, so the
  rule stays in one place).

### app: rejecting (`use_cases/reject.py`) (#5)

```python
@dataclass(frozen=True, slots=True)
class RejectRequest:
    drop_off_id: DropOffId
    reason: ItemId
    message: str = field(repr=False)
    version: int  # the version the staff member saw
    staff: StaffMember


class PreviewRejection:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio, composer: Composer) -> None: ...
    def __call__(self, request: RejectRequest, image_src: Callable[[PhotoRef], str]) -> ComposedEmail: ...


class RejectDropOff:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, request: RejectRequest) -> DropOff: ...


@dataclass(frozen=True, slots=True)
class UndoRequest:
    drop_off_id: DropOffId
    version: int
    staff: StaffMember


@dataclass(frozen=True, slots=True)
class Undone:
    drop_off: DropOff
    email_cancelled: bool  # False: the rejection email may already have gone; staff contact the person (#5)


class UndoRejection:
    def __init__(self, records: Records, clock: Clock) -> None: ...
    def __call__(self, request: UndoRequest) -> Undone: ...
```

(`message` and the `StaffMember`'s email stay out of the `repr`; prep dropped phase 2's
`photos` argument from `PreviewRejection`, which never reads a photo: `image_src` is
how the console points at them.)

- **The reason.** `studio.item(CatalogList.REASONS, request.reason)`; an unknown ID is
  `UnknownItem`, a retired one `ItemRetired` (from `reject`). An empty message is
  `None`.
- `PreviewRejection`: `NotFound`; `Conflict` when `version` isn't the stored one;
  applies `reject` to the stored drop-off without saving (so every refusal shows before
  sending: `NotWaiting`, `MessageRequired`, `MessageTooLong`, `ItemRetired`), then
  composes the rejected email with the current studio. `image_src` lets the console
  point the preview's images at its own photo addresses; the email that is sent uses
  `cid:` references instead. The preview and the sent email come from the same
  template and the same settings, which is what "see the email exactly as it will go
  out" needs; if staff change a setting between preview and send, the email uses the
  new one (#6: every email after a change uses it). Logs nothing.
- `RejectDropOff`: `NotFound`; `Conflict` when `version` isn't the stored one (someone
  else changed it: the page says to reload); `reject(...)`; commit
  `Update(drop_off)` and `Put(new_email(id, EmailKind.REJECTED, now,
  occasion=rejection_occasion(rejection.at)))` (`domain.email`: UTC to the microsecond,
  the one format; no caller formats the time itself). Returns the drop-off as read back
  after the commit. The drop-off leaves the waiting list and can't join a load, because
  its state is `REJECTED` (the domain refuses it in `add_to_load`). Logs
  `event=drop_off_rejected`, `drop_off_id`, `user`, `reason` (the reason's item ID).
- `UndoRejection`: `NotFound`; `Conflict` on a stale `version`; take the occasion
  `rejection_occasion(drop_off.rejection.at)` before the undo clears the rejection;
  `undo_rejection(...)` (`NotRejected`, `UndoTooLate`); read the email by
  `records.email(id, EmailKind.REJECTED, occasion)`. If it is `PENDING` or `SENDING`,
  `mark_cancelled` it in the same commit as `Update(drop_off)` and return
  `email_cancelled=True`; a `SENDING` one may be mid-send, and a mailer whose
  `mark_sent` then meets the new version loses its commit, which phase 3's
  `SendPendingEmail` handles by re-reading and checking `is_still_rejected` before it
  sends. If it is `SENT` or `FAILED` (or missing), only the drop-off changes and
  `email_cancelled=False`: an email already sent can't be unsent, so staff contact the
  person (#5). A `FAILED` one stays `FAILED` (the domain cancels only `PENDING` and
  `SENDING`) and `ViewDropOff` no longer lists it as needing attention; phase 3's
  `RetryEmail` must refuse a rejected email that `is_still_rejected` says is stale
  (noted for phase 3's prep). Sends nothing. Logs `event=rejection_undone`,
  `drop_off_id`, `user`, `outcome` (`email_cancelled` or `email_not_cancelled`).

## Tests

`tests/use_cases/` (against the fakes, asserting on what was stored, not only on return
values):

- `test_waiting_is_oldest_first_with_bisque_and_glaze_totals_in_pieces` (#3).
- `test_the_filter_narrows_rows_not_totals`; `test_overdue_rows_are_marked`;
  `test_the_filter_offers_a_retired_type_that_still_has_waiting_rows`.
- `test_find_by_every_id_form` (`AC-12`, `ac12`, `12`) and `test_find_by_part_of_a_name` (#3).
- `test_find_by_number_finds_a_closed_drop_off`; `test_find_returns_at_most_50`;
  `test_find_waiting_only_skips_other_states`; `test_an_empty_query_finds_nothing`.
- `test_view_drop_off_lists_its_emails_and_those_needing_attention`;
  `test_view_unknown_id_is_not_found`;
  `test_an_undone_rejections_failed_email_does_not_need_attention`.
- `test_preview_shows_the_email_with_reason_and_message_and_saves_nothing` (#5).
- `test_preview_refuses_other_without_a_message` and `..._over_1000_characters`.
- `test_reject_stores_the_rejection_and_queues_one_email` (#5).
- `test_reject_with_an_unknown_or_retired_reason_is_refused`.
- `test_a_rejected_drop_off_leaves_the_waiting_list`.
- `test_reject_with_a_stale_version_is_a_conflict_and_stores_nothing`.
- `test_undo_the_same_day_returns_it_to_waiting_and_sends_nothing` (#5).
- `test_undo_cancels_the_rejection_email_if_still_pending` and
  `..._if_sending` (the drop-off as read back from the fake with its rejection time in
  another offset still finds the email: the key is `rejection_occasion`'s).
- `test_undo_after_the_email_was_sent_says_so` (`email_cancelled` is `False`).
- `test_undo_the_next_day_is_refused`.
- `test_the_request_repr_holds_no_message`.
- `test_no_personal_details_logged.py`, `test_nothing_logged_holds_personal_details`:
  runs submit (accepted and refused), the waiting list, find by name, view, preview,
  reject and undo with made-up details built in code (`tests/domain/builders.py`'s
  `TEST_NAME`, `TEST_EMAIL`, `TEST_PHONE`, `TEST_MESSAGE`), captures every log record
  with `caplog`, and asserts that none of the name, address, phone, message or token
  appears in any record's message or extra fields.

## Acceptance criteria

1. `WaitingList` returns waiting drop-offs oldest first, with bisque and glaze totals in
   pieces (#3); `FindDropOffs` finds by `AC-12`, `ac12`, `12` and part of a name (#3).
2. `PreviewRejection` returns the email as the template renders it and stores nothing;
   `RejectDropOff` stores the rejection and queues exactly one rejected email (#5).
3. `UndoRejection` the same Austin day returns the drop-off to waiting, cancels the
   rejection email if it hasn't gone, says whether it did, and queues nothing; the next
   day it is refused (#5).
4. No log record from these use cases holds a name, email, phone, message or token.

## Verification

```bash
uv run pytest tests/use_cases
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

Filled in when the phase is done.

What the next phase can rely on, as planned:

- `WaitingList` (`WaitingView`, `WaitingRow`), `FindDropOffs`, `ViewDropOff`
  (`DropOffView`), `PreviewRejection`, `RejectDropOff` (`RejectRequest`),
  `UndoRejection` (`UndoRequest`, `Undone`), with the errors each raises.
- For phase 3: `RetryEmail` refuses a rejected email whose rejection was undone, and
  `SendPendingEmail` checks `is_still_rejected` before sending one.
- For phase 8: search text stays out of access logs and the address bar; the undo
  page tells staff when the rejection email had already gone.
