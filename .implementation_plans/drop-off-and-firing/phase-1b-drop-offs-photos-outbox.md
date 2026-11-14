---
phase_id: 1b
title: "The domain: drop-offs, photos, the outbox and closing"
epic: 1
implements: [2, 5, 7]
depends_on: [1a]
domain: [app]
estimated_size: L
---

# Phase 1b: The domain: drop-offs, photos, the outbox and closing

> **Status:** [x] Complete — 2026-11-13 on branch feat/drop-off-and-firing-phase-1

Part of phase 1, split into 1a to 1d by `/prep` (see
[phase 1a](phase-1a-domain-core-and-studio.md)). The conventions in phase 1a's
**app: conventions** apply here unchanged.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): "Treat everything the public form sends as hostile",
  the rules on personal details and logging.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): the
  outbox, photos re-encoded on submit, the 7-day backups after a close.
- This plan's [README](README.md#domain-model) and
  [phase 1a](phase-1a-domain-core-and-studio.md): the errors, message keys, IDs, limits
  and `Studio` this phase uses.
- Stories #2 (the form's fields and limits), #5 (rejection), #7 (closing), and epic #1's
  **Decided** list (the 14-day window counts from the ready email; Austin time).

## Goal

A drop-off, its photos' types, its email outbox entries and its close exist as plain
Python, with every #2, #5 and #7 rule they carry in one place: every field the public
form sends checked at once, rejection and its same-day undo, the email outbox's states,
and the close that deletes the personal details. Tested with no AWS and no fakes.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `domain/photos.py` | `PhotoRef`, `PhotoSize`, `UploadSlot`, `PresignedPost`, `CheckedPhoto`, `PhotoRefusal` |
| `domain/dropoff.py` | `Contact`, `DropOffDetails`, `DropOff`, `DropOffState`, `Rejection`; `new_drop_off`, `reject`, `undo_rejection` |
| `domain/email.py` | `Email`, `EmailKind`, `EmailStatus`; `new_email`, `claim`, `mark_sent`, `mark_failed`, `mark_cancelled`, `retry`, `needs_attention` |
| `domain/closing.py` | `is_closable`, `close` |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/domain/test_dropoff.py`, `test_email.py`, `test_closing.py` | The rules |

## Files to modify

- `tests/domain/builders.py`: add `details(**overrides)` (the keyword arguments of
  `DropOffDetails.create`, valid by default: "Test Person", an address built from parts
  on `example.org`, a phone number built from digit groups) and
  `a_drop_off(number=1, state=WAITING, ...)`.

## Implementation details

### `domain/photos.py`

```python
class PhotoSize(StrEnum):
    FULL = "full"
    THUMB = "thumb"


@dataclass(frozen=True, slots=True)
class PhotoRef:  # a kept photo; the adapter maps it to dropoffs/AC-n/<index>[-thumb].jpg
    drop_off_id: DropOffId
    index: int  # 1..6


@dataclass(frozen=True, slots=True)
class PresignedPost:  # what the browser posts to; opaque to the domain
    url: str
    fields: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class UploadSlot:
    slot_id: str  # is_slot_id's shape: exactly 22 of [A-Za-z0-9_-]; the only handle the form sends back
    post: PresignedPost
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CheckedPhoto:  # what the inspector returns: re-encoded JPEGs without EXIF
    full: bytes
    thumb: bytes


class PhotoRefusal(StrEnum):
    NOT_IMAGE = "not_image"
    TOO_LARGE = "too_large"
    TOO_MANY_PIXELS = "too_many_pixels"
    MISSING = "missing"
```

`CheckedPhoto` and `PresignedPost` define no `__repr__` that prints their bytes or
fields (`field(repr=False)`), so a photo's contents never reach a log by accident.

### `domain/dropoff.py`

```python
class DropOffState(StrEnum):
    WAITING = "waiting"
    IN_LOAD = "in_load"
    FIRED = "fired"
    REJECTED = "rejected"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Contact:
    name: str
    email: str
    phone: str  # digits only, as typed digits; shown formatted by the page


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: ItemId
    message: str | None  # None once closed, or when none was written
    by: str  # staff username
    at: datetime


@dataclass(frozen=True, slots=True)
class DropOffDetails:
    contact: Contact
    pieces: int
    firing_type: ItemId
    glaze_type: ItemId | None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        email: str,
        phone: str,
        pieces: str,
        firing_type: str,
        glaze_type: str | None,
        photo_count: int,
        studio: Studio,
    ) -> "DropOffDetails":
        """Check every field at once; raise InvalidDetails with every field's key, or return."""


@dataclass(frozen=True, slots=True)
class DropOff:
    id: DropOffId
    contact: Contact | None
    pieces: int
    firing_type: ItemId
    glaze_type: ItemId | None
    photos: tuple[PhotoRef, ...]
    created_at: datetime
    state: DropOffState
    load_id: LoadId | None = None
    rejection: Rejection | None = None
    fired_at: datetime | None = None
    closed_at: datetime | None = None
    version: int = 0


def new_drop_off(
    id: DropOffId, details: DropOffDetails, photos: Sequence[PhotoRef], at: datetime
) -> DropOff: ...
def reject(drop_off: DropOff, reason: CatalogItem, message: str | None, by: str, at: datetime) -> DropOff: ...
def undo_rejection(drop_off: DropOff, at: datetime) -> DropOff: ...
```

`Contact` and `Rejection` mark `name`, `email`, `phone` and `message` `repr=False`, so
printing a drop-off (a failing assertion, a traceback's locals) shows no personal
detail.

The checks in `DropOffDetails.create`, every one on the server (the page's own checks
are a convenience). Each field is checked; the errors are gathered and raised together
as one `InvalidDetails`:

- `name`: control characters (Unicode category `C*`, which includes CR and LF) removed,
  then stripped; empty is `name.required`; over `NAME_MAX` is `name.too_long`.
- `email`: stripped; empty is `email.required`; otherwise `is_valid_email` (phase 1a)
  or `email.invalid`. No DNS lookup.
- `phone`: stripped; empty is `phone.required`; the digits in what was typed, allowing
  ASCII digits, spaces, `+`, `-`, `.`, `(` and `)` and nothing else; 10 to 15 digits;
  stored as the digits; otherwise `phone.invalid`.
- `pieces`: stripped, ASCII digits only, 1 to 50; otherwise `pieces.invalid`.
- `firing_type`: empty is `firing_type.required`; it must be an active item of the
  studio's firing types (`firing_type.unknown` for an unknown or retired one).
- `glaze_type`: when the firing type `needs_glaze_type`, required
  (`glaze_type.required`) and an active glaze type (`glaze_type.unknown`); when it
  doesn't, a non-empty value is refused (`glaze_type.not_allowed`) and an empty one is
  `None`. When the firing type itself is refused, the glaze type is checked only for
  being a known active glaze type if given.
- `photo_count`: 1 to 6, otherwise `photos.count`.

`new_drop_off` makes a `WAITING` drop-off at version 0. `photos` must be 1 to 6 refs
for this ID, indexes 1..n (else `ValueError`: a bug).

`reject` (#5): only from `WAITING` (else `NotWaiting`, naming the state); the reason is
the `CatalogItem` the caller looked up with `studio.item(CatalogList.REASONS, id)`,
which raises `UnknownItem`; a retired reason is refused here with `ItemRetired`; the
message is stripped, `None` when empty; `MessageRequired` when the reason
`needs_message` and there is none; `MessageTooLong` over `MESSAGE_MAX`. Returns the
drop-off `REJECTED` with `Rejection(reason.id, message, by, at)`.

`undo_rejection`: only from `REJECTED` (`NotRejected`), and only when `at` and the
rejection's `at` fall on the same date in `STUDIO_TZ` (`UndoTooLate`); returns the
drop-off `WAITING` with `rejection=None`.

### `domain/email.py`

```python
class EmailKind(StrEnum):
    RECEIVED = "received"
    READY = "ready"
    REJECTED = "rejected"


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Email:
    drop_off_id: DropOffId
    kind: EmailKind
    occasion: str  # "" for received and ready; rejection_occasion(rejection.at) for rejected
    status: EmailStatus
    created_at: datetime
    attempts: int = 0
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    error_code: str | None = None
    version: int = 0


def new_email(drop_off_id: DropOffId, kind: EmailKind, at: datetime, occasion: str = "") -> Email: ...
def claim(email: Email, at: datetime) -> Email: ...  # PENDING -> SENDING, attempts + 1, claimed_at
def mark_sent(email: Email, at: datetime) -> Email: ...  # SENDING -> SENT, sent_at
def mark_failed(
    email: Email, code: str
) -> Email: ...  # SENDING -> FAILED; code is an error code, at most 64 of [A-Za-z0-9_.-]
def mark_cancelled(email: Email) -> Email: ...  # PENDING|SENDING -> CANCELLED
def retry(
    email: Email, at: datetime
) -> Email: ...  # FAILED, or stale SENDING -> PENDING; EmailNotRetryable otherwise
def needs_attention(
    email: Email, now: datetime
) -> bool: ...  # FAILED, or SENDING for longer than STALE_SENDING_AFTER
```

- A move from a status the comment doesn't allow is a `ValueError` (a bug: the use
  case reads the email first), except `retry`, which staff ask for, and raises
  `EmailNotRetryable`.
- `new_email`: `occasion` must be `""` for `RECEIVED` and `READY`, and for `REJECTED`
  exactly what `rejection_occasion` gives (else `ValueError`).
- `rejection_occasion(rejected_at)`: the one format of a rejected email's occasion, the
  time in UTC to the microsecond (`2026-11-13T21:04:05.000000+00:00`), so the same
  instant gives the same key whatever offset or precision a caller or the table holds
  it in. `is_still_rejected(drop_off, occasion)` is the one check that a drop-off is
  still rejected by that rejection (not undone, or undone and rejected again). Every
  caller uses these two; none formats a time itself.
- `mark_failed`: a code with any other character, or longer than 64, is a `ValueError`,
  so AWS's message text can never be stored in its place.
- `retry` clears `error_code` and `claimed_at`; a stale `SENDING` is one claimed longer
  ago than `STALE_SENDING_AFTER`. A stale send may in fact have gone out; retrying it
  can send a second copy, which is accepted (decision 0002: at-least-once).

The key (`drop_off_id`, `kind`, `occasion`) is what makes the outbox safe: the
`Records` port (phase 1d) refuses a second `Put` of the same key, so a received or
ready email is queued once, and a new rejection after an undo queues a new email.

### `domain/closing.py` (#7)

```python
def is_closable(
    drop_off: DropOff, ready_sent_at: datetime | None, pickup_window_days: int, now: datetime
) -> bool: ...
def close(drop_off: DropOff, at: datetime) -> DropOff: ...
```

- `is_closable`: `FIRED` and `ready_sent_at` is set and `ready_sent_at + window <= now`
  (the window counts from the ready email, epic #1); or `REJECTED` and
  `rejection.at + window <= now`. A fired drop-off whose ready email was never sent is
  not closable: the console shows the failed email instead (phase 9). `WAITING`,
  `IN_LOAD` and `CLOSED` are never closable (a waiting one shows as overdue instead).
- `close`: from `FIRED` or `REJECTED` only (`ValueError` otherwise: a bug); returns
  `CLOSED` with `contact=None`, `photos=()`, the rejection's `message=None`, and
  `closed_at`. The ID, dates, firing type, glaze type, pieces, load and reason stay.

## Tests

`tests/domain/` (no fakes, no AWS):

- `test_details_accept_a_valid_bisque_and_a_valid_glaze_drop_off`.
- `test_each_field_refusal_has_its_key` (parametrized over the message-key table: empty
  name, a name of only control characters, name over 100, missing or malformed email
  (no `@`, two `@`, a space, a CR or LF), phone with letters or 9 digits or 16, pieces
  `0`, `51`, `2.5`, `two`, a non-ASCII digit, unknown or retired firing type, glaze
  missing for Glaze, glaze given for Bisque, unknown or retired glaze type, 0 and 7
  photos).
- `test_control_characters_are_removed_from_the_name`.
- `test_several_bad_fields_are_reported_together`: one `InvalidDetails` with every key.
- `test_a_refusal_message_holds_no_personal_detail`: the message, keys and `repr` of
  every refusal above contain none of the made-up name, email or phone.
- `test_a_drop_off_repr_holds_no_personal_detail`.
- `test_reject_needs_a_message_for_other`, `test_reject_refuses_a_message_over_1000`,
  `test_reject_only_from_waiting` (each other state), `test_reject_refuses_a_retired_reason`,
  `test_reject_stores_an_empty_message_as_none`.
- `test_undo_on_the_same_austin_day` and `test_undo_refused_the_next_austin_day` (a
  rejection at 23:30 Austin time undone at 00:10 is refused, though the same UTC day);
  `test_undo_only_from_rejected`.
- `test_email_moves_pending_sending_sent` and `..._failed_with_its_code`;
  `test_retry_only_failed_or_stuck` (renamed in phase 3); `test_needs_attention_after_15_minutes_sending`;
  `test_an_error_code_with_other_characters_is_refused`; `test_cancel_from_pending_or_sending_only`.
- `test_fired_closes_after_the_window_from_the_ready_email`;
  `test_fired_without_a_sent_ready_email_never_closes`;
  `test_rejected_closes_after_the_window_from_the_rejection`;
  `test_waiting_never_closes`;
  `test_close_deletes_contact_message_and_photos_and_keeps_the_rest`;
  `test_close_refuses_a_waiting_drop_off`.

## Acceptance criteria

1. `DropOffDetails.create` with a bad email, phone, missing field, wrong pieces, wrong
   glaze type or wrong photo count raises `InvalidDetails` whose `errors` has each bad
   field's key, all at once, and no message, key or `repr` holds the person's details
   (#2).
2. `reject` needs a message for a reason that needs one, refuses one over 1,000
   characters, and works only on a waiting drop-off; `undo_rejection` the next Austin
   day raises `UndoTooLate` (#5).
3. The outbox's moves are functions in `domain/email.py`; a failure stores an error
   code only.
4. `close` returns a drop-off with no contact, no photos and no message, and keeps its
   ID, dates, firing type, pieces, load and reason; `is_closable` counts the window from
   the ready email for a fired drop-off and from the rejection for a rejected one (#7).

## Verification

```bash
uv run pytest tests/domain
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

The coverage floor (90) holds with the new code. Nothing to see in production.

## Rollout

Nothing reaches AWS.

## Admin actions

None.

## Hand-off

Built on 2026-11-13. What phases 1c and later can rely on:

- `asmbly_ceramics.domain.photos`: `PhotoSize`, `PhotoRef(drop_off_id, index)` (index 1
  to 6, else `ValueError`; ordered), `PresignedPost(url, fields)`,
  `UploadSlot(slot_id, post, expires_at)`, `CheckedPhoto(full, thumb)` and
  `PhotoRefusal` (`photo.<value>` is its message key). `PresignedPost` and
  `CheckedPhoto` print none of their fields in a `repr`, and `UploadSlot` leaves out its
  `slot_id` (a bearer handle); `tests/domain/test_photos.py` checks this.
- `asmbly_ceramics.domain.dropoff`: `DropOffState` (with `.label`, the state as words
  for messages: `in load`), `Contact`, `Rejection`, `DropOffDetails.create(...)`,
  `DropOff`, `new_drop_off`, `reject`, `undo_rejection`, as sketched. `Contact`'s fields
  and `Rejection.message` are `repr=False`. `reject` turns CRLF and CR in the message
  into LF, then removes every other control character (Unicode Cc but LF and tab),
  before stripping it. `DropOffDetails.create` removes control and format characters
  (Unicode C*) and the line and paragraph separators (U+2028, U+2029) from the name, and
  refuses a `photo_count` that isn't an `int` (a `bool` or a `float`). `NotWaiting` is given `state.label`, never form text.
  `DropOffDetails.create` checks pieces with at most three ASCII digits before `int()`.
- `asmbly_ceramics.domain.email`: `EmailKind`, `EmailStatus`, `Email`, `ERROR_CODE_MAX`
  (64), `new_email`, `claim`, `mark_sent`, `mark_failed`, `mark_cancelled`, `retry`,
  `needs_attention`, as sketched. A `ValueError` for a disallowed move names the
  drop-off, the kind and the status only. `retry` records no time: the entry goes back
  to `PENDING` with `claimed_at` cleared; a "retried at" field, if the console needs one,
  is for a later phase to add.
- Added in the whole-branch review: `domain.email.rejection_occasion`,
  `is_rejection_occasion` and `is_still_rejected` (above; phase 2's `RejectDropOff` and
  `UndoRejection` and phase 3's `SendPendingEmail` use them), and
  `domain.photos.is_slot_id` with `SLOT_ID_LENGTH` (exactly 22 of `[A-Za-z0-9_-]`, the
  one slot-ID shape phase 2's `SubmitDropOff`, the memory fake and phase 4's
  `S3PhotoStore` all check).
- `asmbly_ceramics.domain.closing`: `is_closable(drop_off, ready_sent_at,
  pickup_window_days, now)` (`ValueError` for a window under 1 day) and
  `close(drop_off, at)`. The caller still deletes the photos themselves
  (`PhotoStore.delete_drop_off`, phase 1d).
- Every function in these modules that takes a time (`new_drop_off`, `reject`,
  `undo_rejection`, `new_email`, `claim`, `mark_sent`, `retry`, `needs_attention`,
  `is_closable`, for `now` and a given `ready_sent_at`, and `close`) raises `ValueError`
  for a naive one, whatever the entry's status. The records themselves (`DropOff`,
  `Email`, `UploadSlot`) don't check their fields' times.
- `tests/domain/builders.py`: `details(**overrides)` (typed by `DetailsArgs`),
  `photo_refs(id, count=2)`, `a_drop_off(number=1, state=WAITING, *, at=NOW, load=1,
  reason="other")`, and the made-up person `TEST_NAME`, `TEST_EMAIL`, `TEST_PHONE`,
  `TEST_PHONE_DIGITS`, `TEST_MESSAGE`, for checks that none of them leaks.

For phase 4's prep: phase 4's sketch of `UploadSlot(id, url, fields, expires_at)`,
`UploadSlotId`, `CheckedPhoto(full, thumbnail, width, height)` and the refusal kinds
`unsupported_type`/`not_an_image` differ from the names here; the names here are the
contract.

For phase 4's and phase 6's prep: `phase-6-drop-off-form.md` (line 347) uses the refusal
kind `not_an_image` where `PhotoRefusal` has `not_image`, and phase 4's `unsupported_type`
(a HEIC or GIF file) has no `PhotoRefusal` member and no `photo.*` message key. Prep for
those phases settles one name for each and adds the missing member and key here.
