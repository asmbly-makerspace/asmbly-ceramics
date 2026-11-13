---
phase_id: 1
title: The domain model, ports and fakes
epic: 1
implements: [2, 4, 5, 6, 7]
depends_on: []
domain: [app]
estimated_size: L
---

# Phase 1: The domain model, ports and fakes

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the planned shape, the rules on personal details and
  logging.
- [docs/architecture.md](../../docs/architecture.md): the domain as the stories describe
  it.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): why
  one table, one transaction per change, a load of at most 48, the outbox.
- This plan's [README](README.md#domain-model): the entities, states, rules table and
  ports table. This phase builds exactly those; a name here that differs from the
  README is a mistake in this document.
- Stories #2 (the form's fields and limits), #4 (loads), #5 (rejection), #6 (settings),
  #7 (closing, overdue), and epic #1's **Decided** list (starting reasons, pickup hours
  text, 14-day window from the ready email, search forms, Austin time).
- Patterns, not imports:
  - AsmblyMCPs `src/mcp_core/errors.py`: an error whose message is safe to show, and
    everything else hidden.
  - AsmblyMCPs `src/mcp_core/logging.py`: fixed field names, no personal data.
  - The facilities repository's `functions/classes/class_photo_upload_api/dynamodb_class_list_cache.py`
    and `tests/fake_class_list_cache.py`: one port, one module owning boto3, an
    in-memory fake the tests use.

## Goal

The whole domain of epic #1 (drop-offs, loads, the studio's settings and lists, the
email outbox, IDs, photos' limits, search, the waiting list, closing) exists as plain,
typed Python with every rule the stories state in one place and tested with no AWS and
no fakes. Every port the app will use exists as a `Protocol`, each with an in-memory
fake that behaves as its contract says, failures included, so that phases 2 and 3 test
every use case against the fakes. Nothing imports boto3, Starlette or Jinja2. No
runtime dependency is added.

Weekly counts (`domain/counts.py`) join in phase 3 with the use case that needs them,
to keep this phase under L.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `domain/__init__.py` | Empty |
| `domain/errors.py` | `DomainError` and its subclasses, each with a safe message |
| `domain/ids.py` | `DropOffId`, `LoadId`, `ItemId`; parsing and formatting |
| `domain/limits.py` | The fixed numbers the stories state, as named constants |
| `domain/photos.py` | `PhotoRef`, `PhotoSize`, `UploadSlot`, `PresignedPost`, `CheckedPhoto`, `PhotoRefusal` |
| `domain/dropoff.py` | `Contact`, `DropOffDetails`, `DropOff`, `DropOffState`, `Rejection`; `reject`, `undo_rejection` |
| `domain/load.py` | `Load`, `LoadStatus`, `FireResult`; `start_load`, `add_to_load`, `remove_from_load`, `start_firing`, `fire` |
| `domain/email.py` | `Email`, `EmailKind`, `EmailStatus`; `new_email`, `claim`, `mark_sent`, `mark_failed`, `mark_cancelled`, `retry`, `needs_attention` |
| `domain/studio.py` | `Studio`, `CatalogItem`, `CatalogList`, `ItemStatus`, `SettingChange`; `starting_studio`, `check_sending_address`, `change_email_settings`, `add_item`, `retire_item`, `restore_item`, `delete_item` |
| `domain/search.py` | `Query`, `parse_query`, `matches` |
| `domain/waiting.py` | `WaitingTotals`, `waiting_order`, `totals`, `is_overdue` |
| `domain/closing.py` | `is_closable`, `close` |
| `ports/__init__.py` | Empty |
| `ports/records.py` | `Records`, `Put`, `Update`, `Change`, `Submission`, `Conflict` |
| `ports/ids.py` | `IdNumbers` |
| `ports/photos.py` | `PhotoStore`, `UploadMissing` |
| `ports/images.py` | `PhotoInspector`, `PhotoRefused` |
| `ports/mailer.py` | `Mailer`, `OutgoingEmail`, `InlineImage`, `SendFailed` |
| `ports/staff.py` | `StaffTokens`, `StaffMember`, `NotSignedIn`, `NotAllowed` |
| `ports/rate_limit.py` | `RateLimiter` |
| `ports/clock.py` | `Clock` |
| `ports/secrets.py` | `Secrets`, `SecretName` |
| `adapters/__init__.py`, `adapters/memory/__init__.py` | Empty |
| `adapters/memory/records.py` | `MemoryRecords` |
| `adapters/memory/ids.py` | `MemoryIdNumbers` |
| `adapters/memory/photos.py` | `MemoryPhotoStore` |
| `adapters/memory/images.py` | `MemoryPhotoInspector` |
| `adapters/memory/mailer.py` | `MemoryMailer` |
| `adapters/memory/staff_tokens.py` | `MemoryStaffTokens` |
| `adapters/memory/rate_limit.py` | `MemoryRateLimiter` |
| `adapters/memory/clock.py` | `FixedClock` |
| `adapters/memory/secrets.py` | `MemorySecrets` |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/domain/__init__.py` | Empty |
| `tests/domain/builders.py` | Made-up test data built in code: `a_studio()`, `details(**overrides)`, `a_drop_off(...)`, `a_load(...)`. Names like "Test Person"; addresses built from parts on `example.org`; never a literal address or phone number in the file |
| `tests/domain/test_ids.py`, `test_dropoff.py`, `test_load.py`, `test_email.py`, `test_studio.py`, `test_search.py`, `test_waiting.py`, `test_closing.py` | The rules |
| `tests/adapters/__init__.py`, `tests/adapters/test_memory.py` | Each fake keeps its port's contract, failures included |

## Files to modify

- `src/asmbly_ceramics/__init__.py`: nothing but its docstring, which says where the
  domain, the ports and the fakes are.
- `tests/test_package.py`: unchanged unless it lists modules.

## Implementation details

### app: conventions

- Every entity is a `@dataclass(frozen=True, slots=True)`. A change returns a new value
  (`dataclasses.replace`) with the same `version`; the `Records` adapter writes
  `version + 1` and checks the old one. Entities created here start at `version=0`.
- Datetimes are timezone-aware (UTC in storage); the studio's day is
  `limits.STUDIO_TZ`. ruff's `DTZ` rules already forbid naive datetimes.
- Every domain function that refuses raises a `DomainError` subclass. Its `message` is
  safe to show to staff and to log: it names IDs, states and setting names, never a
  person's name, email, phone or message.
- No module under `domain/` or `ports/` imports anything outside the standard library
  and `asmbly_ceramics.domain`. A test (`test_the_domain_imports_only_the_standard_library`)
  walks the modules' imports and fails otherwise.

### `domain/errors.py`

```python
class DomainError(Exception):
    """A refusal whose message is safe to show to staff and to log."""
    def __init__(self, message: str) -> None: ...
    @property
    def message(self) -> str: ...

FieldErrors = Mapping[str, str]          # field name -> message key (see below)

class InvalidDetails(DomainError):       # "The drop-off has errors." + .errors: FieldErrors
class NotFound(DomainError):             # "AC-12 doesn't exist." / "Load L-4 doesn't exist."
class NotWaiting(DomainError):           # "AC-12 isn't waiting: it is fired."
class AlreadyInLoad(DomainError):        # "AC-12 is already in load L-4."
class NotInLoad(DomainError):            # "AC-12 isn't in load L-4."
class LoadNotLoading(DomainError):       # "Load L-4 is firing: nothing can be added or removed."
class LoadFull(DomainError):             # "Load L-4 already holds 48 drop-offs."
class EmptyLoad(DomainError):            # "Load L-4 is empty: add a drop-off before firing."
class WrongLoadStatus(DomainError):      # "Load L-4 is loading, not firing."
class AlreadyFired(DomainError):         # "Load L-4 is already fired; nothing was sent again."
class FiringTypeMismatch(DomainError):   # "AC-61 is bisque. This load is glaze." (.drop_off_id)
class MessageRequired(DomainError):      # "This reason needs a message."
class MessageTooLong(DomainError):       # "The message is longer than 1,000 characters."
class NotRejected(DomainError):          # "AC-12 isn't rejected."
class UndoTooLate(DomainError):          # "AC-12 was rejected on an earlier day; undo works only the same day."
class SendingAddressOutsideAsmbly(DomainError)  # "Use an address at asmbly.org."
class InvalidSetting(DomainError):       # .field and a message: "Enter a number of days from 1 to 90."
class UnknownItem(DomainError):          # "That kiln doesn't exist."
class ItemRetired(DomainError):          # "Vulcan is retired and can't be picked."
class ItemInUse(DomainError):            # "Helios is used by a load: retire it instead."
class DuplicateItem(DomainError):        # "There is already a kiln called Helios."
class EmailNotRetryable(DomainError):    # "That email isn't failed."
class TooManySubmissions(DomainError):   # "Too many drop-offs from this device. Try again later."
```

Item names (kiln names, reasons) are studio data, not personal details, and may appear
in messages.

**Message keys** for `InvalidDetails.errors`. The web phases map each to the text shown
next to the field; the keys are the contract:

| Field | Keys |
| --- | --- |
| `name` | `name.required`, `name.too_long` |
| `email` | `email.required`, `email.invalid` |
| `phone` | `phone.required`, `phone.invalid` |
| `pieces` | `pieces.invalid` (not a whole number from 1 to 50) |
| `firing_type` | `firing_type.required`, `firing_type.unknown` |
| `glaze_type` | `glaze_type.required`, `glaze_type.unknown`, `glaze_type.not_allowed` |
| `photos` | `photos.count`, `photos.missing` |
| `photo.<n>` (n from 1) | `photo.not_image`, `photo.too_large`, `photo.too_many_pixels`, `photo.missing` |
| `form` | `form.expired` (the submission token is missing or malformed: the page was too old) |

### `domain/ids.py`

```python
@dataclass(frozen=True, slots=True, order=True)
class DropOffId:
    number: int  # >= 1

    def __str__(self) -> str: ...  # "AC-12"
    @classmethod
    def parse(cls, text: str) -> "DropOffId": ...  # "AC-12" only; ValueError otherwise


@dataclass(frozen=True, slots=True, order=True)
class LoadId:
    number: int

    def __str__(self) -> str: ...  # "L-4"
    @classmethod
    def parse(cls, text: str) -> "LoadId": ...


ItemId = NewType("ItemId", str)  # a slug, 1-40 of [a-z0-9-], made by new_item_id(name, existing)


def new_item_id(name: str, existing: Collection[ItemId]) -> ItemId: ...
```

Issuing numbers is the `IdNumbers` port's contract (below), not the domain's.

### `domain/limits.py`

```python
PIECES_MIN, PIECES_MAX = 1, 50
PHOTOS_MIN, PHOTOS_MAX = 1, 6
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_FULL_LONG_SIDE = 2048  # pixels, the copy kept and emailed
PHOTO_THUMB_LONG_SIDE = 320
NAME_MAX = 100
EMAIL_MAX = 254
PHONE_DIGITS_MIN, PHONE_DIGITS_MAX = 10, 15
MESSAGE_MAX = 1000
HOURS_TEXT_MAX = 2000
PICKUP_WINDOW_MIN, PICKUP_WINDOW_MAX = 1, 90  # days
ITEM_NAME_MAX = 60


@dataclass(frozen=True, slots=True)
class RateLimit:
    limit: int
    window: timedelta


DEVICE_LIMIT = RateLimit(limit=10, window=timedelta(minutes=10))
ADDRESS_LIMIT = RateLimit(limit=30, window=timedelta(minutes=10))
SLOT_DEVICE_LIMIT = RateLimit(limit=20, window=timedelta(minutes=10))  # requests for upload slots
SLOT_ADDRESS_LIMIT = RateLimit(limit=60, window=timedelta(minutes=10))
UPLOAD_SLOT_LIFETIME = timedelta(minutes=15)
SUBMISSION_LIFETIME = timedelta(days=1)
OVERDUE_AFTER = timedelta(days=60)
LOAD_CAPACITY = 48
STALE_SENDING_AFTER = timedelta(minutes=15)
STUDIO_TZ = ZoneInfo("America/Chicago")
SENDING_DOMAIN = "asmbly.org"
```

These are the stories' rules, not settings (README, "The rules, each in one place").

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
    slot_id: str  # random, URL-safe, 22+ characters; the only handle the form sends back
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
        studio: "Studio",
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

The checks in `DropOffDetails.create`, every one on the server (the page's own checks
are a convenience):

- `name`: control characters removed, then stripped; empty is `name.required`; over
  `NAME_MAX` is `name.too_long`.
- `email`: stripped, at most `EMAIL_MAX`; one `@`, a non-empty local part without
  spaces or control characters, a domain with a dot and labels of `[A-Za-z0-9-]`;
  otherwise `email.invalid`. No DNS lookup.
- `phone`: the digits in what was typed, allowing spaces, `+`, `-`, `.`, `(` and `)`
  and nothing else; 10 to 15 digits; stored as the digits.
- `pieces`: a whole number written in digits, 1 to 50.
- `firing_type`: an active item of the studio's firing types.
- `glaze_type`: required and active when the firing type `needs_glaze_type`; refused
  (`glaze_type.not_allowed`) when it doesn't.
- `photo_count`: 1 to 6, otherwise `photos.count`.

`reject` (#5): only from `WAITING` (else `NotWaiting`); the reason must be an active
reason (`UnknownItem`, `ItemRetired`); the message is stripped, `None` when empty;
`MessageRequired` when the reason `needs_message` and there is none; `MessageTooLong`
over `MESSAGE_MAX`. `undo_rejection`: only from `REJECTED` (`NotRejected`), and only
when `at` and the rejection's `at` fall on the same date in `STUDIO_TZ`
(`UndoTooLate`); returns the drop-off `WAITING` with `rejection=None`.

### `domain/load.py`

```python
class LoadStatus(StrEnum):
    LOADING = "loading"
    FIRING = "firing"
    FIRED = "fired"


@dataclass(frozen=True, slots=True)
class Load:
    id: LoadId
    kiln: ItemId
    firing_type: ItemId
    date: date
    status: LoadStatus
    members: tuple[DropOffId, ...]
    started_by: str
    started_at: datetime
    fired_at: datetime | None = None
    version: int = 0


@dataclass(frozen=True, slots=True)
class FireResult:
    load: Load
    drop_offs: tuple[DropOff, ...]
    emails: tuple[Email, ...]


def start_load(
    id: LoadId, kiln: ItemId, firing_type: ItemId, on: date, by: str, at: datetime, studio: Studio
) -> Load: ...
def change_load(load: Load, kiln: ItemId, firing_type: ItemId, on: date, studio: Studio) -> Load: ...
def add_to_load(load: Load, drop_off: DropOff, *, confirmed: bool) -> tuple[Load, DropOff]: ...
def remove_from_load(load: Load, drop_off: DropOff) -> tuple[Load, DropOff]: ...
def start_firing(load: Load) -> Load: ...
def fire(load: Load, members: Sequence[DropOff], at: datetime) -> FireResult: ...
```

- `start_load`, `change_load` (#4): kiln and firing type must be active items; only
  while `LOADING`.
- `add_to_load`: `LoadNotLoading` unless `LOADING`; `AlreadyInLoad` when the drop-off
  is `IN_LOAD` (naming its load); `NotWaiting` for any other state (naming it);
  `LoadFull` at `LOAD_CAPACITY`; `FiringTypeMismatch` when the firing types differ and
  `confirmed` is false. Returns the load with the ID appended and the drop-off
  `IN_LOAD` with `load_id`.
- `remove_from_load`: `LoadNotLoading`, `NotInLoad`; the drop-off goes back to
  `WAITING`, `load_id=None`.
- `start_firing`: `WrongLoadStatus` unless `LOADING`; `EmptyLoad` with no members.
- `fire`: `AlreadyFired` when `FIRED` (nothing else happens: firing again sends
  nothing); `WrongLoadStatus` when `LOADING`; `members` must be exactly the load's
  members, each `IN_LOAD` in this load (else `ValueError`: a bug, not a refusal).
  Returns the load `FIRED` with `fired_at`, each drop-off `FIRED` with `fired_at`, and
  one `new_email(id, READY, at)` each. The use case commits all of it at once.

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
    occasion: str  # "" for received and ready; the rejection's at, ISO, for rejected
    status: EmailStatus
    created_at: datetime
    attempts: int = 0
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    error_code: str | None = None
    version: int = 0


def new_email(drop_off_id: DropOffId, kind: EmailKind, at: datetime, occasion: str = "") -> Email: ...
def claim(email: Email, at: datetime) -> Email: ...  # PENDING -> SENDING, attempts + 1
def mark_sent(email: Email, at: datetime) -> Email: ...  # SENDING -> SENT
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

The key (`drop_off_id`, `kind`, `occasion`) is what makes the outbox safe: the
`Records` port refuses a second `Put` of the same key, so a received or ready email is
queued once, and a new rejection after an undo queues a new email.

### `domain/studio.py`

```python
class CatalogList(StrEnum):
    KILNS = "kilns"
    FIRING_TYPES = "firing_types"
    GLAZE_TYPES = "glaze_types"
    REASONS = "reasons"


class ItemStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: ItemId
    name: str
    status: ItemStatus = ItemStatus.ACTIVE
    needs_glaze_type: bool = False  # firing types only
    needs_message: bool = False  # reasons only


@dataclass(frozen=True, slots=True)
class Studio:
    sending_address: str
    pickup_window_days: int
    pickup_hours_text: str
    kilns: tuple[CatalogItem, ...]
    firing_types: tuple[CatalogItem, ...]
    glaze_types: tuple[CatalogItem, ...]
    reasons: tuple[CatalogItem, ...]
    version: int = 0

    def items(self, which: CatalogList) -> tuple[CatalogItem, ...]: ...
    def item(self, which: CatalogList, id: ItemId) -> CatalogItem: ...  # UnknownItem
    def active_item(self, which: CatalogList, id: ItemId) -> CatalogItem: ...  # UnknownItem, ItemRetired


@dataclass(frozen=True, slots=True)
class SettingChange:
    at: datetime
    by: str  # staff username, or "system" for the starting values
    what: str  # "Pickup window: 10 → 14 days", "Added kiln Helios", "Changed the pickup hours text"


def check_sending_address(address: str) -> str: ...
def starting_studio(sending_address: str, at: datetime) -> tuple[Studio, SettingChange]: ...
def change_email_settings(
    studio: Studio,
    *,
    sending_address: str,
    pickup_window_days: str,
    pickup_hours_text: str,
    by: str,
    at: datetime,
) -> tuple[Studio, list[SettingChange]]: ...
def add_item(
    studio: Studio,
    which: CatalogList,
    name: str,
    by: str,
    at: datetime,
    *,
    needs_glaze_type: bool = False,
    needs_message: bool = False,
) -> tuple[Studio, SettingChange]: ...
def retire_item(
    studio: Studio, which: CatalogList, id: ItemId, by: str, at: datetime
) -> tuple[Studio, SettingChange]: ...
def restore_item(
    studio: Studio, which: CatalogList, id: ItemId, by: str, at: datetime
) -> tuple[Studio, SettingChange]: ...
def delete_item(
    studio: Studio, which: CatalogList, id: ItemId, *, used: bool, by: str, at: datetime
) -> tuple[Studio, SettingChange]: ...
```

- `check_sending_address` (#6): stripped, lowercased domain; a valid address (the same
  check as a drop-off's email) whose domain is exactly `SENDING_DOMAIN`; otherwise
  `SendingAddressOutsideAsmbly`. A subdomain is refused.
- `starting_studio`: the values epic #1 decided: kilns Athena, Helios, Vulcan; firing
  types Bisque and Glaze (`needs_glaze_type` on Glaze only); glaze types "House dip
  glaze" and "Commercial glaze"; reasons "Has glaze issues", "Needs more time to dry"
  and "Other" (`needs_message`); `pickup_window_days=14`; the pickup hours text from
  epic #1's **Decided** (members during Asmbly open hours, 7 days a week, 5am–2am;
  class students during the Steward on Duty shifts, per the events calendar on
  asmbly.org). The sending address is the argument, which composition takes from the
  `INITIAL_SENDING_ADDRESS` value (phase 7); it is checked like any other. The change
  recorded is `SettingChange(at, "system", "Starting settings")`. No address is written
  in the code.
- `change_email_settings`: `check_sending_address`; window a whole number from
  `PICKUP_WINDOW_MIN` to `PICKUP_WINDOW_MAX` (`InvalidSetting("pickup_window_days", ...)`); hours text stripped, 1 to
  `HOURS_TEXT_MAX` characters. One `SettingChange` per value that changed:
  "Sending address: A → B", "Pickup window: 10 → 14 days", "Changed the pickup hours
  text". No change, no record.
- `add_item`: name stripped, 1 to `ITEM_NAME_MAX`; `DuplicateItem` for a name already
  in that list, case-insensitively, retired ones included.
- `retire_item` / `restore_item`: flip the status; retiring the last active firing
  type, kiln or reason is refused (`InvalidSetting`), so the form and the console always
  have one to pick.
- `delete_item` (#6): `ItemInUse` when `used`; the caller asks `Records.is_item_used`.

### `domain/search.py` (#3)

```python
@dataclass(frozen=True, slots=True)
class Query:
    number: int | None  # from "AC-12", "ac12", "ac 12", "12"
    text: str  # casefolded, stripped; "" when the query is a number


def parse_query(raw: str) -> Query: ...
def matches(drop_off: DropOff, query: Query) -> bool: ...  # by number, or the name contains the text
```

A closed drop-off has no name and matches by number only. A query of more than 100
characters is cut to 100.

### `domain/waiting.py` (#3, #7)

```python
@dataclass(frozen=True, slots=True)
class WaitingTotals:
    drop_offs: Mapping[ItemId, int]  # per firing type
    pieces: Mapping[ItemId, int]  # per firing type
    pieces_by_glaze: Mapping[ItemId, int]  # per glaze type
    overdue: int


def waiting_order(
    drop_offs: Iterable[DropOff],
) -> list[DropOff]: ...  # WAITING only, oldest created_at first, then by ID
def totals(drop_offs: Iterable[DropOff], now: datetime) -> WaitingTotals: ...
def is_overdue(drop_off: DropOff, now: datetime) -> bool: ...  # WAITING and now - created_at >= OVERDUE_AFTER
```

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
  not closable: the console shows the failed email instead (phase 9). `WAITING` is
  never closable (overdue instead).
- `close`: from `FIRED` or `REJECTED` only (`ValueError` otherwise: a bug); returns
  `CLOSED` with `contact=None`, `photos=()`, the rejection's `message=None`, and
  `closed_at`. The ID, dates, firing type, glaze type, pieces, load and reason stay.

### Ports

Each in `ports/`, a `typing.Protocol`. Port errors are not `DomainError`s: they say
something outside failed, and their text is fixed and safe.

**`ports/records.py`**:

```python
@dataclass(frozen=True, slots=True)
class Submission:  # one per form submission token, so a refresh makes no second drop-off
    token_hash: str
    drop_off_id: DropOffId
    # The ID page's summary, so the public form never reads a drop-off item.
    # No name, email, phone, message or photo: ever.
    pieces: int
    firing_type: str  # the item's name when submitted
    glaze_type: str | None
    created_at: datetime
    expires_at: datetime  # SUBMISSION_LIFETIME; the adapter sets TTL from it


Item = DropOff | Load | Email | Studio | SettingChange | Submission


@dataclass(frozen=True, slots=True)
class Put:
    item: Item  # create; refused if the key exists (expect_absent is always true)


@dataclass(frozen=True, slots=True)
class Update:
    item: Item  # replace; refused unless the stored version equals item.version
    # (the stored copy becomes version + 1)


Change = Put | Update


class Conflict(Exception):
    """Someone else changed one of these first. Nothing was written."""


class Unavailable(Exception):
    """AWS or the network failed. Safe to show as "try again"; holds the provider's
    error code only, never its message."""

    def __init__(self, code: str) -> None: ...


class RecordsUnavailable(Unavailable): ...  # Records


class IdsUnavailable(Unavailable): ...  # IdNumbers


class PhotosUnavailable(Unavailable): ...  # PhotoStore


class SignInUnavailable(Unavailable): ...  # StaffTokens: the pool's keys or token endpoint can't be reached


class SecretsUnavailable(Unavailable): ...  # Secrets


class SecretMissing(Exception): ...  # Secrets: the parameter doesn't exist (a setup error, at start)


class Records(Protocol):
    def commit(self, changes: Sequence[Change]) -> None: ...  # all or nothing; Conflict; at most 100 changes
    # strongly consistent reads (used right before a commit):
    def drop_off(self, id: DropOffId) -> DropOff | None: ...
    def load(self, id: LoadId) -> Load | None: ...
    def studio(self) -> Studio | None: ...
    def email(self, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email | None: ...
    def submission(self, token_hash: str) -> Submission | None: ...
    # lists (eventually consistent is fine: a stale list can't cause a wrong write,
    # because every write checks versions):
    def drop_offs_in(self, states: Collection[DropOffState]) -> list[DropOff]: ...
    def drop_offs_created_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def drop_offs_rejected_between(self, start: datetime, end: datetime) -> list[DropOff]: ...
    def loads_in(self, statuses: Collection[LoadStatus]) -> list[Load]: ...
    def loads_between(self, start: date, end: date) -> list[Load]: ...
    def emails_for(self, drop_off_id: DropOffId) -> list[Email]: ...
    def emails_in(self, statuses: Collection[EmailStatus]) -> list[Email]: ...
    def history(self, limit: int, before: datetime | None = None) -> list[SettingChange]: ...  # newest first
    def is_item_used(self, which: CatalogList, id: ItemId) -> bool: ...
```

`Put` of a `SettingChange` is keyed by its time and a random suffix the adapter adds;
`Put` of a `Studio` happens once (the starting values), every later change is an
`Update`.

**The others:**

```python
class IdNumbers(Protocol):
    def next_drop_off_id(
        self,
    ) -> DropOffId: ...  # never the same number twice, even under concurrency; gaps allowed
    def next_load_id(self) -> LoadId: ...


class UploadMissing(Exception): ...  # no upload for that slot (never sent, expired, wrong size)


class PhotoStore(Protocol):
    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]: ...
    def read_upload(self, slot_id: str) -> bytes: ...  # UploadMissing; never more than PHOTO_MAX_BYTES
    def keep(self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]: ...
    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes: ...  # UploadMissing when gone
    def delete_drop_off(self, drop_off_id: DropOffId) -> None: ...  # idempotent


class PhotoRefused(Exception):
    def __init__(self, kind: PhotoRefusal) -> None: ...


class PhotoInspector(Protocol):
    def inspect(self, data: bytes) -> CheckedPhoto: ...  # PhotoRefused


@dataclass(frozen=True, slots=True)
class InlineImage:
    content_id: str  # "photo-1"
    filename: str  # "AC-12-1.jpg"
    data: bytes
    content_type: str = "image/jpeg"


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    from_address: str
    from_name: str  # "Asmbly Ceramics"
    reply_to: str
    to: str
    subject: str
    html: str
    text: str
    inline: tuple[InlineImage, ...] = ()


class SendFailed(Exception):
    def __init__(self, code: str) -> None: ...  # the provider's error code, never its message


class Mailer(Protocol):
    def send(self, message: OutgoingEmail) -> None: ...


@dataclass(frozen=True, slots=True)
class StaffMember:
    username: str
    email: str | None  # from the verified token, for the test email only; never logged


class NotSignedIn(Exception): ...  # no token, bad signature, wrong issuer/client/use, expired


class NotAllowed(Exception):  # a valid token without the ceramics group
    def __init__(self, username: str) -> None: ...


class StaffTokens(Protocol):
    def verify(self, id_token: str) -> StaffMember: ...
    def sign_in_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str: ...
    def exchange(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> str: ...  # the ID token; NotSignedIn
    def sign_out_url(self, *, redirect_uri: str) -> str: ...


class RateLimiter(Protocol):
    def hit(
        self, key: str, limit: RateLimit, now: datetime
    ) -> bool: ...  # counts this hit; False when over the limit


class Clock(Protocol):
    def now(self) -> datetime: ...  # aware, UTC


class SecretName(StrEnum):
    HASH_KEY = "hash-key"  # keyed hashes for rate limits and submission tokens (form)
    FORM_KEY = "form-key"  # signs the public form's __Host-received cookie (form only)
    SESSION_KEY = "session-key"  # signs the console's sign-in state and CSRF tokens (console only)


class Secrets(Protocol):
    def get(self, name: SecretName) -> bytes: ...
```

### The fakes

Thin: a dict and the contract's checks, enough to test every outcome. Each fake has a
way to fail on purpose.

| Fake | State | Contract it keeps | Failure switch |
| --- | --- | --- | --- |
| `MemoryRecords` | dicts keyed like the table's keys | `Put` refuses an existing key; `Update` refuses a version mismatch; all or nothing; at most 100 changes; stores copies with `version + 1`; lists sorted as the adapter sorts them | `fail_next_commit_with: Exception \| None` (e.g. `Conflict()`); `commits: list[Sequence[Change]]` for assertions |
| `MemoryIdNumbers` | two counters | increasing, never repeats | `skip(n)` to show gaps are fine |
| `MemoryPhotoStore` | uploads and kept photos by key | `read_upload` raises `UploadMissing` for an unknown slot; `keep` returns refs 1..n; `delete_drop_off` idempotent | `put_upload(slot_id, data)` to simulate the browser's upload |
| `MemoryPhotoInspector` | none | returns `CheckedPhoto(full=data, thumb=data[:16])` | refuses data starting with `b"NOT-IMAGE"`, `b"TOO-LARGE"`, `b"TOO-MANY-PIXELS"` with the matching `PhotoRefusal` |
| `MemoryMailer` | `sent: list[OutgoingEmail]` | stores the message | `fail_with: str \| None` raises `SendFailed(code)` |
| `MemoryStaffTokens` | `tokens: dict[str, StaffMember \| None]` | `None` member means `NotAllowed`; unknown token `NotSignedIn`; `sign_in_url` returns a fake URL with the arguments | none needed |
| `MemoryRateLimiter` | hits per key with times | counts hits within the window ending at `now` | none needed |
| `FixedClock` | a time | `now()` | `advance(timedelta)` |
| `MemorySecrets` | fixed bytes per name | `get` | none needed |

### What is logged

Nothing in this phase logs: the domain is pure and the fakes are silent. Phase 2 sets
the logging conventions for use cases.

### Size

About 350 lines of domain, 130 of ports, 170 of fakes, and 300 of tests is near 800.
To stay under L: the fakes hold no logic beyond the contract; the error classes are one
line each; tests are parametrized tables per rule rather than one function per case.
If the build runs over, `domain/waiting.py` and its tests move to phase 2, which uses
them first.

## Tests

`tests/domain/` (no fakes, no AWS):

- `test_the_domain_imports_only_the_standard_library`: every module under `domain/` and
  `ports/` imports only the standard library and `asmbly_ceramics.domain`.
- `test_drop_off_id_formats_and_parses`: `AC-1`, `AC-12`; `parse` refuses `AC-0`,
  `AC-`, `ac-12x`.
- `test_details_accept_a_valid_bisque_and_a_valid_glaze_drop_off`.
- `test_each_field_refusal_has_its_key` (parametrized over the message-key table: empty
  name, name over 100, missing or malformed email, phone with letters or 9 digits or 16,
  pieces `0`, `51`, `2.5`, `two`, unknown or retired firing type, glaze missing for
  Glaze, glaze given for Bisque, retired glaze type, 0 and 7 photos).
- `test_several_bad_fields_are_reported_together`: one `InvalidDetails` with every key.
- `test_a_refusal_message_holds_no_personal_detail`: the message and keys of every
  refusal above contain none of the made-up name, email or phone.
- `test_reject_needs_a_message_for_other`, `test_reject_refuses_a_message_over_1000`,
  `test_reject_only_from_waiting` (each other state), `test_reject_refuses_a_retired_reason`.
- `test_undo_on_the_same_austin_day` and `test_undo_refused_the_next_austin_day` (a
  rejection at 23:30 Austin time undone at 00:10 is refused, though the same UTC day).
- `test_add_to_load_moves_a_waiting_drop_off_in`;
  `test_add_refuses_a_drop_off_in_another_load_naming_it`;
  `test_add_refuses_fired_rejected_and_closed`;
  `test_add_with_a_different_firing_type_needs_confirmation` and `..._added_when_confirmed`;
  `test_a_load_holds_at_most_48`.
- `test_nothing_is_added_or_removed_once_firing` and `..._once_fired`.
- `test_remove_puts_the_drop_off_back_to_waiting`.
- `test_start_firing_refuses_an_empty_load`.
- `test_fire_marks_every_member_fired_and_queues_one_ready_email_each`.
- `test_firing_again_is_refused_and_queues_nothing`.
- `test_email_moves_pending_sending_sent` and `..._failed_with_its_code`;
  `test_retry_only_failed_or_stale_sending`; `test_needs_attention_after_15_minutes_sending`;
  `test_an_error_code_with_other_characters_is_refused`.
- `test_sending_address_must_be_at_asmbly_org` (parametrized: another domain, a
  subdomain, no `@`, upper case domain accepted).
- `test_starting_studio_has_the_decided_values` and `..._records_system_as_the_author`.
- `test_change_email_settings_records_one_change_per_value` and `..._records_nothing_when_unchanged`;
  `test_pickup_window_below_1_refused`; `test_pickup_window_above_90_refused`; `test_hours_text_over_2000_refused`.
- `test_used_item_can_be_retired_not_deleted`; `test_unused_item_can_be_deleted`;
  `test_retired_item_cannot_be_picked`; `test_duplicate_name_refused_case_insensitively`;
  `test_the_last_active_kiln_cannot_be_retired`.
- `test_search_parses_every_id_form` (`AC-12`, `ac12`, `ac 12`, `12`, ` AC-12 `);
  `test_search_matches_any_part_of_the_name_case_insensitively`;
  `test_a_closed_drop_off_matches_by_number_only`.
- `test_waiting_is_oldest_first`; `test_totals_count_pieces_per_firing_type_and_glaze`;
  `test_overdue_at_60_days_not_59`.
- `test_fired_closes_after_the_window_from_the_ready_email`;
  `test_fired_without_a_sent_ready_email_never_closes`;
  `test_rejected_closes_after_the_window_from_the_rejection`;
  `test_waiting_never_closes`;
  `test_close_deletes_contact_message_and_photos_and_keeps_the_rest`.

`tests/adapters/test_memory.py`:

- `test_records_put_refuses_an_existing_key`; `test_records_update_refuses_a_stale_version`;
  `test_records_commit_is_all_or_nothing`; `test_records_refuses_more_than_100_changes`;
  `test_records_failure_switch_raises_and_writes_nothing`.
- `test_ids_never_repeat`.
- `test_photo_store_read_upload_of_an_unknown_slot_raises`; `test_photo_store_delete_is_idempotent`.
- `test_inspector_refuses_each_marker`; `test_mailer_failure_raises_send_failed_with_the_code`;
  `test_staff_tokens_not_allowed_and_not_signed_in`; `test_rate_limiter_allows_10_then_refuses_within_the_window_and_allows_after`.

## Acceptance criteria

1. Every rule in the README's rules table that this phase owns is a function in the
   module the table names, refusing with the error above, and a test shows each
   refusal (#2: fields, pieces, photos count, glaze type; #4: add, remove, firing,
   fired, 48; #5: message, 1,000, same-day undo; #6: address, retire not delete,
   history; #7: closing and overdue).
2. `DropOffDetails.create` with a bad email, phone, missing field or wrong photo count
   raises `InvalidDetails` whose `errors` has each bad field's key, and no message or
   key holds the person's details.
3. `fire` on a fired load raises `AlreadyFired` and returns no email.
4. `add_to_load` with a drop-off already in another load raises `AlreadyInLoad` whose
   message names both IDs.
5. `undo_rejection` the next Austin day raises `UndoTooLate`.
6. `check_sending_address` refuses any address whose domain isn't exactly `asmbly.org`.
7. `close` returns a drop-off with no contact, no photos and no message, and keeps its
   ID, dates, firing type, pieces, load and reason.
8. Every port in the README's ports table exists as a `Protocol` with a fake under
   `adapters/memory/` that passes its contract tests, failures included.
9. Nothing under `src/asmbly_ceramics/domain/` or `src/asmbly_ceramics/ports/` imports
   boto3, botocore, Starlette, Jinja2 or Pillow (the test above).

## Verification

```bash
uv run pytest tests/domain tests/adapters
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

Filled in when the phase is done.

What the next phase can rely on, as planned:

- The entities, states and functions above, under `asmbly_ceramics.domain`.
- The ports under `asmbly_ceramics.ports`, with these exact names: `Records.commit`
  with `Put`/`Update`/`Conflict`, the reads listed, `IdNumbers`, `PhotoStore`
  (`upload_slots`, `read_upload`, `keep`, `read`, `delete_drop_off`, `UploadMissing`),
  `PhotoInspector.inspect`/`PhotoRefused`, `Mailer.send`/`OutgoingEmail`/`InlineImage`/`SendFailed`,
  `StaffTokens`/`StaffMember`/`NotSignedIn`/`NotAllowed`, `RateLimiter.hit`, `Clock`,
  `Secrets`/`SecretName`.
- The fakes under `asmbly_ceramics.adapters.memory`, with their failure switches, and
  the builders in `tests/domain/builders.py`.
- The message keys for field errors (the table above).
