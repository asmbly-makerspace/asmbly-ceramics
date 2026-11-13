---
phase_id: 1a
title: "The domain's core: errors, IDs, limits and the studio"
epic: 1
implements: [6]
depends_on: []
domain: [app]
estimated_size: L
---

# Phase 1a: The domain's core: errors, IDs, limits and the studio

> **Status:** [x] Complete — 2026-11-13 on branch feat/drop-off-and-firing-phase-1

Phase 1 (the domain model, ports and fakes) was split into 1a to 1d by `/prep` on
2026-11-13: its estimate was near 2,000 changed lines, well over L. Together, 1a to 1d
build exactly what phase 1 planned, with prep's corrections folded in. "Phase 1" in the
other phase documents means all four.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the planned shape, the rules on personal details and
  logging.
- [docs/architecture.md](../../docs/architecture.md): the domain as the stories describe
  it.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): why
  one table, one transaction per change, a load of at most 48, the outbox.
- This plan's [README](README.md#domain-model): the entities, states, rules table and
  ports table. A name here that differs from the README is a mistake in this document.
- Story #6 (settings) and epic #1's **Decided** list (starting reasons, pickup hours
  text, the sending address at `asmbly.org`).
- Patterns, not imports: AsmblyMCPs `src/mcp_core/errors.py` (an error whose message is
  safe to show, and everything else hidden).

## Goal

The pieces every other domain module stands on exist as plain, typed Python: the
domain's errors with safe messages, the IDs, the fixed numbers the stories state, and
the studio's settings and lists with every #6 rule. A test fails if anything under
`domain/` or `ports/` imports more than it may. Nothing imports boto3, Starlette or
Jinja2. No runtime dependency is added.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `domain/__init__.py` | Empty |
| `domain/errors.py` | `DomainError` and its subclasses, each with a safe message |
| `domain/ids.py` | `DropOffId`, `LoadId`, `ItemId`; parsing and formatting; `new_item_id` |
| `domain/limits.py` | The fixed numbers the stories state, as named constants |
| `domain/studio.py` | `Studio`, `CatalogItem`, `CatalogList`, `ItemStatus`, `SettingChange`; `starting_studio`, `check_sending_address`, `change_email_settings`, `add_item`, `retire_item`, `restore_item`, `delete_item`; and `is_valid_email`, the address check `DropOffDetails.create` (phase 1b) shares |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/domain/__init__.py` | Empty |
| `tests/domain/builders.py` | Made-up test data built in code, starting with `a_studio()` (phases 1b and 1c add `details`, `a_drop_off`, `a_load`). Addresses built from parts on `example.org` or `asmbly.org`; never a literal address or phone number in the file (`tests/repo/test_personal_data.py` would fail) |
| `tests/domain/test_imports.py` | `test_the_domain_imports_only_the_standard_library` |
| `tests/domain/test_ids.py`, `tests/domain/test_studio.py` | The rules |

## Files to modify

- `tests/test_package.py`: unchanged (it lists no modules).

## Implementation details

### app: conventions (for all of phase 1)

- Every entity is a `@dataclass(frozen=True, slots=True)`. A change returns a new value
  (`dataclasses.replace`) with the same `version`; the `Records` adapter writes
  `version + 1` and checks the old one. Entities created here start at `version=0`.
- Datetimes are timezone-aware (UTC in storage); the studio's day is
  `limits.STUDIO_TZ`. ruff's `DTZ` rules already forbid naive datetimes.
- Every domain function that refuses raises a `DomainError` subclass. Its `message` is
  safe to show to staff and to log: it names IDs, states and setting names, never a
  person's name, email, phone or message. A function given an impossible input (a bug in
  the caller, not a refusal) raises `ValueError`.
- Numbers typed by a person (pieces, the pickup window) are ASCII digits only
  (`re.fullmatch(r"[0-9]+", ...)` after stripping), never `str.isdigit()`, which accepts
  other scripts' digits and superscripts.
- **Imports.** A module under `domain/` imports only the standard library and
  `asmbly_ceramics.domain`. A module under `ports/` (phase 1d) imports only the standard
  library, `asmbly_ceramics.domain` and `asmbly_ceramics.ports`.
  `test_the_domain_imports_only_the_standard_library` parses each module's imports with
  `ast` (no import of the module needed) and fails otherwise; it walks `ports/` too
  once that folder exists, so phase 1d needs no change to it. The standard library is
  `sys.stdlib_module_names`.

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

Each subclass's constructor takes what its message names (IDs, states, item names, the
field) and builds the message; nothing else. Item names (kiln names, reasons) are studio
data, not personal details, and may appear in messages. `InvalidDetails` never holds a
field's value, only its key.

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
    number: int  # >= 1; ValueError otherwise

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

`parse` accepts exactly `AC-` (or `L-`) and ASCII digits without a leading zero.
`new_item_id` lowercases, turns every run of other characters into one `-`, trims `-`,
cuts to 40, and adds `-2`, `-3`, … when the slug is taken (within 40 characters); a name
with no letter or digit becomes `item`. Issuing numbers is the `IdNumbers` port's
contract (phase 1d), not the domain's.

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
`zoneinfo` finds the zone in the system's data here; phase 4 adds `tzdata` for Lambda.

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


def is_valid_email(address: str) -> bool: ...
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

- `is_valid_email` (shared with phase 1b's `DropOffDetails.create`): at most
  `EMAIL_MAX`; exactly one `@`; a non-empty local part without spaces or control
  characters; a domain with a dot whose labels are non-empty `[A-Za-z0-9-]` not starting
  or ending with `-`. No DNS lookup.
- `check_sending_address` (#6): stripped, the domain lowercased; `is_valid_email`, and a
  domain exactly `SENDING_DOMAIN`; otherwise `SendingAddressOutsideAsmbly`. A subdomain
  is refused. Returns the normalized address.
- `starting_studio`: the values epic #1 decided: kilns Athena, Helios, Vulcan; firing
  types Bisque and Glaze (`needs_glaze_type` on Glaze only); glaze types "House dip
  glaze" and "Commercial glaze"; reasons "Has glaze issues", "Needs more time to dry"
  and "Other" (`needs_message`); `pickup_window_days=14`; the pickup hours text from
  epic #1's **Decided** (members during Asmbly open hours, 7 days a week, 5am–2am;
  class students during the Steward on Duty (SOD) shifts, per the events calendar on
  asmbly.org). The sending address is the argument, which composition takes from the
  `INITIAL_SENDING_ADDRESS` value (phase 7); it is checked like any other. The change
  recorded is `SettingChange(at, "system", "Starting settings")`. No address is written
  in the code.
- `change_email_settings`: `check_sending_address`; window a whole number from
  `PICKUP_WINDOW_MIN` to `PICKUP_WINDOW_MAX` (`InvalidSetting("pickup_window_days", ...)`);
  hours text stripped, 1 to `HOURS_TEXT_MAX` characters
  (`InvalidSetting("pickup_hours_text", ...)`). One `SettingChange` per value that
  changed: "Sending address: A → B", "Pickup window: 10 → 14 days", "Changed the pickup
  hours text". No change, no record (and the studio returned unchanged).
- `add_item`: name stripped, 1 to `ITEM_NAME_MAX` (`InvalidSetting("name", ...)`);
  `DuplicateItem` for a name already in that list, case-insensitively, retired ones
  included; the ID from `new_item_id`. `needs_glaze_type` on any list but firing types,
  or `needs_message` on any list but reasons, is a `ValueError` (a bug). Records "Added
  kiln Helios".
- `retire_item` / `restore_item`: flip the status (`UnknownItem` for an unknown ID;
  retiring a retired item or restoring an active one, as a double click would, is
  `InvalidSetting("status", "Vulcan is already retired.")`). Retiring the **last active item of any list** is refused
  (`InvalidSetting`), so the form and the console always have one to pick: a studio with
  no active glaze type could never accept a Glaze drop-off. Records "Retired kiln
  Vulcan" / "Restored kiln Vulcan".
- `delete_item` (#6): `UnknownItem`; `ItemInUse` when `used` (the caller asks
  `Records.is_item_used`, phase 1d); deleting the last active item of a list is refused
  like retiring it. Records "Deleted kiln Helios".

## Tests

`tests/domain/` (no fakes, no AWS):

- `test_the_domain_imports_only_the_standard_library`: every module under `domain/`
  imports only the standard library and `asmbly_ceramics.domain`, and every module
  under `ports/` (once it exists) only those and `asmbly_ceramics.ports`. A second case
  feeds it a made-up module source importing `boto3` and shows it is caught.
- `test_drop_off_id_formats_and_parses`: `AC-1`, `AC-12`; `parse` refuses `AC-0`, `AC-`,
  `ac-12x`, `AC-012`; the same for `LoadId` with `L-4`.
- `test_new_item_id_makes_a_unique_slug`.
- `test_every_domain_error_message_is_safe`: each error class, built with IDs and item
  names, has a message naming only those.
- `test_sending_address_must_be_at_asmbly_org` (parametrized: another domain, a
  subdomain, no `@`, two `@`, upper case domain accepted and lowercased).
- `test_starting_studio_has_the_decided_values` and `..._records_system_as_the_author`.
- `test_change_email_settings_records_one_change_per_value` and `..._records_nothing_when_unchanged`;
  `test_pickup_window_below_1_refused`; `test_pickup_window_above_90_refused`;
  `test_pickup_window_not_a_whole_number_refused` (`2.5`, `ten`, a non-ASCII digit);
  `test_hours_text_over_2000_refused`; `test_hours_text_empty_refused`.
- `test_used_item_can_be_retired_not_deleted`; `test_unused_item_can_be_deleted`;
  `test_retired_item_cannot_be_picked`; `test_duplicate_name_refused_case_insensitively`;
  `test_the_last_active_item_of_each_list_cannot_be_retired_or_deleted` (parametrized
  over the four lists); `test_restore_makes_an_item_pickable_again`.

## Acceptance criteria

1. #6's rules are functions in `domain/studio.py`, each refusal tested: the sending
   address must be exactly at `asmbly.org` (a subdomain is refused); an item in use can
   be retired, not deleted; every change returns the `SettingChange` the history
   records, with the staff username and the time.
2. `starting_studio` holds the values epic #1 decided, recorded as made by `system`.
3. `DropOffId` formats and parses `AC-n` and nothing else.
4. Nothing under `src/asmbly_ceramics/domain/` imports boto3, botocore, Starlette,
   Jinja2 or Pillow (the import test).

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

Built on 2026-11-13. What phases 1b to 1d can rely on:

- `asmbly_ceramics.domain.errors`: `DomainError` (`.message`) and the 23 subclasses
  above, each constructor taking only what its message names. Signatures that the
  sketch left open: `NotFound(id: DropOffId | LoadId)`, `NotWaiting(drop_off_id, state)`,
  `LoadNotLoading(load_id, status)`, `LoadFull(load_id, capacity)`,
  `WrongLoadStatus(load_id, status, expected)`,
  `FiringTypeMismatch(drop_off_id, drop_off_firing_type, load_firing_type)` (pass the
  items' names), `MessageTooLong(limit)`, `SendingAddressOutsideAsmbly(domain)`,
  `InvalidSetting(field, message)`, `UnknownItem(kind)`, `ItemRetired(name)`,
  `ItemInUse(name)`, `DuplicateItem(kind, name)`. `InvalidDetails(errors)` needs at
  least one field and holds a read-only copy of the message keys. `ItemInUse` says "used
  by a drop-off or a load", since either makes an item used. pep8-naming's N818 ("Error"
  suffix) is off in `errors.py` only, with a file-level comment, to keep the plan's names.
- `asmbly_ceramics.domain.ids`: `DropOffId`, `LoadId` (ordered; `number` from 1, else
  `ValueError`; `parse` raises `ValueError`), `ItemId`, `ITEM_ID_MAX`, `new_item_id`.
- `asmbly_ceramics.domain.limits`: every constant listed above, unchanged.
- `asmbly_ceramics.domain.studio`: everything listed above, plus `SYSTEM` ("system").
  The starting pickup hours text is private to the module; read it from
  `starting_studio(...)`. `is_valid_email` takes ASCII only, the local part being
  RFC 5322's dot-atom of at most 64 characters and each domain label at most 63
  (SES takes addresses in 7-bit ASCII), so phase 1b's form refuses
  an address SES would refuse later. Every change function raises `ValueError` for an
  empty `by` or a naive `at`. Kind words in messages: kiln, firing type, glaze type,
  reason.
- `tests/domain/builders.py`: `a_studio()`, `an_address(local, domain="example.org")`,
  `a_sending_address(local="ceramics")`, `NOW` and `STAFF` (`kiln-tech`).
- `tests/domain/test_imports.py` already walks `ports/` with its allowed imports; phase
  1d needs no change to it.

A `SettingChange.what` can hold the studio's sending address; it is studio data shown in
the console's history, but a later phase shouldn't log it.
