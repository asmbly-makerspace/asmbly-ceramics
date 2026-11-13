---
phase_id: 1d
title: The ports and their in-memory fakes
epic: 1
implements: [2, 4]
depends_on: [1c]
domain: [app]
estimated_size: L
---

# Phase 1d: The ports and their in-memory fakes

> **Status:** [ ] Pending

Part of phase 1, split into 1a to 1d by `/prep` (see
[phase 1a](phase-1a-domain-core-and-studio.md)). The conventions in phase 1a's
**app: conventions** apply here unchanged; a module under `ports/` imports only the
standard library, `asmbly_ceramics.domain` and `asmbly_ceramics.ports`, which phase
1a's import test already checks.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): AWS behind ports; the rules on logging AWS errors by
  code.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): one
  table, one transaction per change with a version check on each item, IDs from a
  counter, the rate limit in the table, the outbox.
- This plan's [README](README.md#ports): the ports table. A name here that differs from
  it is a mistake in this document (the README's methods are summaries; the signatures
  here are the contract).
- Phases [1a](phase-1a-domain-core-and-studio.md), [1b](phase-1b-drop-offs-photos-outbox.md)
  and [1c](phase-1c-loads-waiting-search.md): the entities the ports carry.
- Patterns, not imports: the facilities repository's
  `functions/classes/class_photo_upload_api/dynamodb_class_list_cache.py` and
  `tests/fake_class_list_cache.py` (one port, one module owning boto3, an in-memory fake
  the tests use); AsmblyMCPs `src/mcp_core/logging.py` (fixed field names, no personal
  data).

## Goal

Every port the app will use exists as a `typing.Protocol`, each with an in-memory fake
that behaves as its contract says, failures included, so that phases 2 and 3 test every
use case against the fakes. Nothing imports boto3, Starlette or Jinja2. No runtime
dependency is added.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `ports/__init__.py` | Empty |
| `ports/errors.py` | `Unavailable` and its subclasses `RecordsUnavailable`, `IdsUnavailable`, `PhotosUnavailable`, `SignInUnavailable`, `SecretsUnavailable`; `SecretMissing` |
| `ports/records.py` | `Records`, `Put`, `Update`, `Change`, `Item`, `Submission`, `Conflict` |
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
| `tests/adapters/__init__.py`, `tests/adapters/test_memory.py` | Each fake keeps its port's contract, failures included |

## Files to modify

- `src/asmbly_ceramics/__init__.py`: nothing but its docstring, which says where the
  domain, the ports and the fakes are.

## Implementation details

### Ports

Each in `ports/`, a `typing.Protocol`. Port errors are not `DomainError`s: they say
something outside failed, and their text is fixed and safe.

**`ports/errors.py`**: the errors every port shares, in one module so each port imports
them from one place:

```python
class Unavailable(Exception):
    """AWS or the network failed. Safe to show as "try again"; holds the provider's
    error code only, never its message."""

    def __init__(self, code: str) -> None: ...  # .code; the message is f"unavailable: {code}"


class RecordsUnavailable(Unavailable): ...  # Records, and RateLimiter (its counts are in the table)


class IdsUnavailable(Unavailable): ...  # IdNumbers


class PhotosUnavailable(Unavailable): ...  # PhotoStore


class SignInUnavailable(Unavailable): ...  # StaffTokens: the pool's keys or token endpoint can't be reached


class SecretsUnavailable(Unavailable): ...  # Secrets


class SecretMissing(Exception):  # Secrets: the parameter doesn't exist (a setup error, at start)
    def __init__(self, name: str) -> None: ...  # names the parameter, never a value
```

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
    item: DropOff | Load | Email | Studio  # replace; refused unless the stored version
    # equals item.version (the stored copy becomes version + 1)


Change = Put | Update


class Conflict(Exception):
    """Someone else changed one of these first. Nothing was written."""

    def __init__(self, ids: Sequence[str] = ()) -> None: ...  # .ids: the drop-off or load IDs, when known


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

The contract, which the fake keeps and phase 4's adapter matches:

- **Keys.** A drop-off by its ID; a load by its ID; the studio is one item; an email by
  (`drop_off_id`, `kind`, `occasion`); a submission by `token_hash`; a `SettingChange` by
  its `at` and a random suffix the adapter adds (so two at the same instant both land).
- **`Put`** stores the item with `version + 1` (an entity created at version 0 is
  stored, and read back, at version 1); refused with `Conflict` when the key exists.
  `Put` of a `Studio` happens once (the starting values); every later change is an
  `Update`.
- **`Update`** stores the item with `version + 1`; refused with `Conflict` unless an
  item with that key is stored at exactly `item.version`. A `SettingChange` or a
  `Submission` is never updated (the type says so).
- **`commit`** is all or nothing: one refused change writes none. More than 100
  changes, or two changes on the same key, raise `ValueError` before anything is
  written (a bug: the domain's 48-drop-off limit keeps a fire at 97).
- **Ranges** are half-open, `start <= value < end`: `drop_offs_created_between` on
  `created_at`, `drop_offs_rejected_between` on `rejection.at`, `loads_between` on
  `date`.
- **Order.** `drop_offs_*` by `created_at` then ID; `loads_*` by `date` then ID;
  `emails_for` and `emails_in` by `created_at`; `history` newest first, at most `limit`,
  strictly before `before` when given.
- **`is_item_used`**: a kiln by any load; a firing type by any drop-off or load; a glaze
  type by any drop-off; a reason by any drop-off's rejection (closed ones included).

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
    def __init__(self, kind: PhotoRefusal) -> None: ...  # .kind


class PhotoInspector(Protocol):
    def inspect(self, data: bytes) -> CheckedPhoto: ...  # PhotoRefused


@dataclass(frozen=True, slots=True)
class InlineImage:
    content_id: str  # "photo-1"
    filename: str  # "AC-12-1.jpg"
    data: bytes  # repr=False
    content_type: str = "image/jpeg"


@dataclass(frozen=True, slots=True)
class OutgoingEmail:  # every field but the IDs is repr=False: it holds the person's address and name
    from_address: str
    from_name: str  # "Asmbly Ceramics"
    reply_to: str
    to: str
    subject: str
    html: str
    text: str
    inline: tuple[InlineImage, ...] = ()


class SendFailed(Exception):
    def __init__(self, code: str) -> None: ...  # .code: the provider's error code, never its message


class Mailer(Protocol):
    def send(self, message: OutgoingEmail) -> None: ...


@dataclass(frozen=True, slots=True)
class StaffMember:
    username: str
    email: str | None  # from the verified token, for the test email only; never logged; repr=False


class NotSignedIn(Exception): ...  # no token, bad signature, wrong issuer/client/use, expired


class NotAllowed(Exception):  # a valid token without the ceramics group
    def __init__(self, username: str) -> None: ...  # .username


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
    ) -> bool: ...  # counts this hit, allowed or not; False when over the limit; RecordsUnavailable


class Clock(Protocol):
    def now(self) -> datetime: ...  # aware, UTC


class SecretName(StrEnum):
    HASH_KEY = "hash-key"  # keyed hashes for rate limits and submission tokens (form)
    FORM_KEY = "form-key"  # signs the public form's __Host-received cookie (form only)
    SESSION_KEY = "session-key"  # signs the console's sign-in state and CSRF tokens (console only)


class Secrets(Protocol):
    def get(self, name: SecretName) -> bytes: ...  # SecretMissing, SecretsUnavailable
```

### The fakes

Thin: a dict and the contract's checks, enough to test every outcome. Each fake has a
way to fail on purpose. None logs or prints.

| Fake | State | Contract it keeps | Failure switch |
| --- | --- | --- | --- |
| `MemoryRecords` | dicts keyed as the contract above | every rule in the contract above; stores and returns copies (frozen, so the same objects) | `fail_next_commit_with: Exception \| None` (e.g. `Conflict()` or `RecordsUnavailable("ThrottlingException")`), cleared after it fires, nothing written; `commits: list[Sequence[Change]]` of the commits that succeeded, for assertions |
| `MemoryIdNumbers` | two counters | increasing, never repeats | `skip(n)` to show gaps are fine; `fail_with: Exception \| None` |
| `MemoryPhotoStore` | uploads and kept photos by key | `upload_slots` returns `count` slots with 22+ character random IDs, a fake URL and `expires_at = now + UPLOAD_SLOT_LIFETIME`; `read_upload` raises `UploadMissing` for an unknown slot or data over `PHOTO_MAX_BYTES`; `keep` returns refs 1..n; `read` raises `UploadMissing` when gone; `delete_drop_off` idempotent and removes both sizes | `put_upload(slot_id, data)` to simulate the browser's upload; `fail_with: Exception \| None` |
| `MemoryPhotoInspector` | none | returns `CheckedPhoto(full=data, thumb=data[:16])` | refuses data starting with `b"NOT-IMAGE"`, `b"TOO-LARGE"`, `b"TOO-MANY-PIXELS"` with the matching `PhotoRefusal` |
| `MemoryMailer` | `sent: list[OutgoingEmail]` | stores the message | `fail_with: str \| None` raises `SendFailed(code)` and stores nothing |
| `MemoryStaffTokens` | `members: dict[str, StaffMember]` (token → a member of `ceramics`); `outsiders: dict[str, str]` (token → username, signed in but not in the group); `codes: dict[str, str]` (code → token) | `verify`: a member's token returns it; an outsider's raises `NotAllowed(username)`; anything else `NotSignedIn`. `exchange` returns the code's token or raises `NotSignedIn`. `sign_in_url` and `sign_out_url` return an `https://sign-in.example.org/...` URL with the arguments as query parameters | `fail_with: Exception \| None` (e.g. `SignInUnavailable("timeout")`) |
| `MemoryRateLimiter` | hit times per key | counts every hit, allowed or not, in a window `(now - limit.window, now]`; returns whether the count, this hit included, is at most `limit.limit` | `fail_with: Exception \| None` (`RecordsUnavailable`: the limiter fails closed) |
| `FixedClock` | an aware UTC time | `now()`; a naive time given to it is a `ValueError` | `advance(timedelta)` |
| `MemorySecrets` | fixed bytes per name, 32 by default | `get` | `SecretMissing` for a name removed with `remove(name)` |

### What is logged

Nothing in phase 1 logs: the domain is pure and the fakes are silent. Phase 2 sets the
logging conventions for use cases.

## Tests

`tests/adapters/test_memory.py`:

- `test_records_put_stores_version_one_and_refuses_an_existing_key`;
  `test_records_update_refuses_a_stale_version`; `test_records_update_of_a_missing_item_conflicts`;
  `test_records_commit_is_all_or_nothing`; `test_records_refuses_more_than_100_changes`;
  `test_records_refuses_two_changes_on_one_key`;
  `test_records_failure_switch_raises_and_writes_nothing`.
- `test_records_email_key_includes_the_occasion` (a second ready email for one drop-off
  conflicts; a rejected email for a new rejection doesn't).
- `test_records_lists_filter_and_sort` (states, statuses, half-open ranges, history newest
  first with `limit` and `before`); `test_records_is_item_used_for_each_list`.
- `test_ids_never_repeat`; `test_ids_skip_leaves_a_gap`.
- `test_photo_store_slots_expire_after_15_minutes`; `test_photo_store_read_upload_of_an_unknown_slot_raises`;
  `test_photo_store_refuses_an_upload_over_10_mb`; `test_photo_store_keep_then_read_both_sizes`;
  `test_photo_store_delete_is_idempotent`.
- `test_inspector_refuses_each_marker`; `test_mailer_failure_raises_send_failed_with_the_code`;
  `test_an_outgoing_email_repr_holds_no_address`.
- `test_staff_tokens_not_allowed_and_not_signed_in`; `test_staff_tokens_exchange`.
- `test_rate_limiter_allows_10_then_refuses_within_the_window_and_allows_after`.
- `test_clock_advances_and_refuses_a_naive_time`; `test_secrets_get_and_missing`.
- `test_each_fake_satisfies_its_port`: each fake assigned to a variable typed as its
  port, so mypy checks the fake keeps the protocol's signatures.

## Acceptance criteria

1. Every port in the README's ports table exists as a `Protocol` with a fake under
   `adapters/memory/` that passes its contract tests, failures included.
2. `MemoryIdNumbers` never repeats a number (#2: no two drop-offs share an ID), and
   `MemoryRateLimiter` refuses the 11th hit within 10 minutes under `DEVICE_LIMIT` (#2).
3. `MemoryRecords` refuses a second `Put` of the same email key, so firing a load again
   can never queue a second ready email (#4), and refuses a stale `Update` with
   `Conflict`, writing nothing.
4. Nothing under `src/asmbly_ceramics/ports/` imports boto3, botocore, Starlette,
   Jinja2 or Pillow (phase 1a's import test).

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

What the next phases can rely on, as planned:

- The entities, states and functions of phases 1a to 1c, under `asmbly_ceramics.domain`.
- The ports under `asmbly_ceramics.ports`, with these exact names: `Records.commit`
  with `Put`/`Update`/`Conflict`, the reads listed, `IdNumbers`, `PhotoStore`
  (`upload_slots`, `read_upload`, `keep`, `read`, `delete_drop_off`, `UploadMissing`),
  `PhotoInspector.inspect`/`PhotoRefused`, `Mailer.send`/`OutgoingEmail`/`InlineImage`/`SendFailed`,
  `StaffTokens`/`StaffMember`/`NotSignedIn`/`NotAllowed`, `RateLimiter.hit`, `Clock`,
  `Secrets`/`SecretName`, and the `Unavailable` family and `SecretMissing` in
  `asmbly_ceramics.ports.errors`.
- The fakes under `asmbly_ceramics.adapters.memory`, with their failure switches, and
  the builders in `tests/domain/builders.py`.
- The message keys for field errors (phase 1a).
- Phase 4's adapter section names some reads differently (`failed_emails`,
  `settings_history`, `get_drop_off`); the names here are the contract, and phase 4's
  `/prep` corrects its document.
