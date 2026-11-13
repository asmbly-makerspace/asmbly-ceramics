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

> **Status:** [x] Complete — 2026-11-13 on branch feat/drop-off-and-firing-phase-1

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
| `ports/clock.py` | `Clock`: the time behind the 10-minute device limit and the drop-off's times (#2) |
| `ports/secrets.py` | `Secrets`, `SecretName`: the keys that hash a device for the 10-submission limit (#2) |
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

    # A code that isn't 1 to 64 of [A-Za-z0-9_.-] (domain.email's ERROR_CODE shape) is
    # stored as "unknown", so text an adapter passes by mistake never reaches a log.


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
    token_hash: str  # repr=False: a keyed hash of the form's token, a lookup handle
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
    def history(self, limit: int, before: str | None = None) -> HistoryPage: ...  # opaque cursor
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
- **`Update`** replaces the whole item (phase 4: a transactional `Put` of the whole
  item under a version condition) and stores it with `version + 1`; refused with
  `Conflict` unless an item with that key is stored at exactly `item.version`. A `SettingChange` or a
  `Submission` is never updated (the type says so).
- **`commit`** is all or nothing: one refused change writes none. More than 100
  changes, or two changes on the same key, raise `ValueError` before anything is
  written (a bug: the domain's 48-drop-off limit keeps a fire at 97;
  `test_firing_a_full_load_fits_in_one_commit` pins `2 * LOAD_CAPACITY + 1 <=
  MAX_CHANGES`). `commit` returns nothing: a caller that needs a stored item afterwards
  reads it again (an entity is stored at `item.version + 1`).
- **Ranges** are half-open, `start <= value < end`: `drop_offs_created_between` on
  `created_at`, `drop_offs_rejected_between` on `rejection.at`, `loads_between` on
  `date`.
- **Order.** `drop_offs_*` by `created_at` then ID; `loads_*` by `date` then ID;
  `emails_for` and `emails_in` by `created_at`; `history` newest first, at most `limit`.
- **History pages by an opaque cursor** (changed in the whole-branch review): `history`
  returns `HistoryPage(changes, older)`, and `older`, passed back as `before`, resumes
  just after the page's last change; it is `None` exactly when nothing older exists. A
  cursor of a time alone skipped changes: one `change_email_settings` writes up to
  three changes with the same `at`, and `history(2)` then `history(2, before=at)` lost
  the third. Changes at one instant come in their key's suffix order. A cursor
  `history` never gave is `BadCursor` (a port error). The fake's cursor is
  `<at ISO>#<suffix>`, like phase 4's sort key after `HISTORY#`; callers treat it as
  opaque (`test_history_pages_never_split_or_skip_changes_at_one_instant`,
  `test_history_refuses_a_cursor_it_never_gave`).
- **`is_item_used`**: a kiln by any load; a firing type by any drop-off or load; a glaze
  type by any drop-off; a reason by any drop-off's rejection (closed ones included).

**The others:**

```python
class IdNumbers(Protocol):
    def next_drop_off_id(
        self,
    ) -> DropOffId: ...  # never the same number twice, even under concurrency; gaps allowed
    def next_load_id(self) -> LoadId: ...


class UploadMissing(Exception): ...  # no upload for that slot (never sent, expired, wrong size, discarded)


class PhotosAlreadyKept(Exception): ...  # keep found photos for that drop-off; nothing overwritten


class PhotoStore(Protocol):  # every method: PhotosUnavailable(code)
    def upload_slots(self, count: int, now: datetime) -> list[UploadSlot]: ...  # 1 to 6, else ValueError
    def read_upload(self, slot_id: str) -> bytes: ...  # UploadMissing; <= PHOTO_MAX_BYTES
    def discard_uploads(self, slot_ids: Sequence[str]) -> None: ...  # uses the slots up; idempotent
    def keep(
        self, drop_off_id: DropOffId, photos: Sequence[CheckedPhoto]
    ) -> tuple[PhotoRef, ...]: ...  # 1 to 6, else ValueError; never overwrites: PhotosAlreadyKept;
    # all or nothing: when it raises, nothing is left under the drop-off's number
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
    def __init__(self, code: str) -> None: ...  # .code: the provider's error code, never its message;

    # normalized as Unavailable's code is ("unknown" when it isn't a code)


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
    # The ID token; NotSignedIn (unknown or used code, wrong verifier or redirect URI;
    # one exchange per code); SignInUnavailable.
    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str: ...
    def sign_out_url(self, *, redirect_uri: str) -> str: ...


class RateLimiter(Protocol):
    # Counts this hit, allowed or not; False when over the limit in the rolling window
    # (now - limit.window, now]; key is a keyed hash; RecordsUnavailable (fails closed).
    def hit(self, key: str, limit: RateLimit, now: datetime) -> bool: ...


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
way to fail on purpose. None logs or prints. Every method that takes a time (`now`,
a range's `start` and `end`, `before`) raises `ValueError` for a naive one, as the
domain does; so does `FixedClock`.

| Fake | State | Contract it keeps | Failure switch |
| --- | --- | --- | --- |
| `MemoryRecords` | dicts keyed as the contract above | every rule in the contract above; stores and returns copies (frozen, so the same objects) | `fail_next_commit_with: Exception \| None` (e.g. `Conflict()` or `RecordsUnavailable("ThrottlingException")`), cleared after it fires, nothing written; `commits: list[Sequence[Change]]` of the commits that succeeded, for assertions |
| `MemoryIdNumbers` | two counters | increasing, never repeats | `skip(n)` (n at least 1) to show gaps are fine; `fail_with: Exception \| None` |
| `MemoryPhotoStore` | uploads and kept photos by key | `upload_slots` returns `count` slots with random IDs of `is_slot_id`'s shape (exactly 22 of `[A-Za-z0-9_-]`), a fake URL and `expires_at = now + UPLOAD_SLOT_LIFETIME`; `read_upload` raises `UploadMissing` for an unknown slot, one of another shape, one with no upload, or one discarded; `discard_uploads` drops the uploads and uses the slots up, ignoring an ID of another shape; `keep` stores only the `CheckedPhoto`s' bytes, refuses a count outside 1 to 6 with `ValueError`, raises `PhotosAlreadyKept` when the drop-off already has photos, and returns refs 1..n; `read` raises `UploadMissing` when gone; `delete_drop_off` idempotent and removes both sizes | `put_upload(slot_id, data)` to simulate the browser's upload: `ValueError` for a slot it didn't issue; empty data or data over `PHOTO_MAX_BYTES` is not kept (S3's 1-byte-to-10-MB condition refuses it), so `read_upload` raises `UploadMissing`; `read_uploads` (slots asked for, in order), `upload_count()`; `fail_with: Exception \| None` |
| `MemoryPhotoInspector` | none | returns `CheckedPhoto(full=data, thumb=data[:16])` | refuses data starting with `b"NOT-IMAGE"`, `b"TOO-LARGE"`, `b"TOO-MANY-PIXELS"` with the matching `PhotoRefusal` |
| `MemoryMailer` | `sent: list[OutgoingEmail]` | stores the message; a `from_address` not at `SENDING_DOMAIN` is a `ValueError` and nothing is stored (the adapter refuses it the same way) | `fail_with: str \| None` raises `SendFailed(code)` and stores nothing |
| `MemoryStaffTokens` | `members: dict[str, StaffMember]` (token → a member of `ceramics`); `outsiders: dict[str, str]` (token → username, signed in but not in the group); codes issued by `approve(code, token)`, each tied to the last `sign_in_url`'s challenge and redirect URI | `verify`: a member's token returns it; an outsider's raises `NotAllowed(username)`; anything else `NotSignedIn`. `exchange` pops the code (one try) and returns its token only when `s256(code_verifier)` is the challenge and the redirect URI is the same; otherwise `NotSignedIn`. `sign_in_url` and `sign_out_url` return an `https://sign-in.example.org/...` URL with the arguments as query parameters | `fail_with: Exception \| None` (e.g. `SignInUnavailable("timeout")`) |
| `MemoryRateLimiter` | the latest `limit.limit` hit times per key | counts every hit, allowed or not, in a rolling window `(now - limit.window, now]`; returns whether the count, this hit included, is at most `limit.limit` | `keys_hit` (every key counted); `fail_with: Exception \| None` (`RecordsUnavailable`: the limiter fails closed) |
| `FixedClock` | an aware UTC time | `now()`; a naive time given to it is a `ValueError` | `advance(timedelta)` |
| `MemorySecrets` | fixed bytes per name, 32 by default | `get` | `SecretMissing` for a name removed with `remove(name)` |

### What is logged

Nothing in phase 1 logs: the domain is pure and the fakes are silent. Phase 2 sets the
logging conventions for use cases.

Prep (2026-11-13) added: the mailer fake's `asmbly.org` check, the naive-time rule, the
code normalization, `Submission.token_hash`'s `repr=False`, and what the photo fake
keeps. The phase is estimated at about 1,100 changed lines, as 1a to 1c were; it isn't
split again, because a port without its fake and contract tests can't be checked.

## Tests

`tests/adapters/test_memory.py`:

- `test_records_put_stores_version_one_and_refuses_an_existing_key`;
  `test_records_update_refuses_a_stale_version`; `test_records_update_of_a_missing_item_conflicts`;
  `test_records_commit_is_all_or_nothing`; `test_records_refuses_more_than_100_changes`;
  `test_records_refuses_two_changes_on_one_key`;
  `test_records_empty_commit_is_a_no_op_and_not_recorded`;
  `test_conflict_refuses_one_string_for_its_ids`;
  `test_records_failure_switch_raises_and_writes_nothing`;
  `test_firing_a_full_load_fits_in_one_commit`;
  `test_commit_returns_nothing_and_a_re_read_shows_the_stored_version`.
- `test_records_email_key_includes_the_occasion` (a second ready email for one drop-off
  conflicts; a rejected email for a new rejection doesn't).
- `test_records_lists_filter_and_sort` (states, statuses, half-open ranges, history newest
  first with `limit` and the `older` cursor); `test_records_is_item_used_for_each_list`;
  `test_history_pages_never_split_or_skip_changes_at_one_instant`;
  `test_history_refuses_a_cursor_it_never_gave`.
- `test_ids_never_repeat`; `test_ids_skip_leaves_a_gap`.
- `test_photo_store_slots_expire_after_15_minutes`; `test_photo_store_read_upload_of_an_unknown_slot_raises`;
  `test_photo_store_refuses_an_upload_over_10_mb`; `test_photo_store_keep_then_read_both_sizes`;
  `test_photo_store_delete_is_idempotent`; `test_photo_store_refuses_an_empty_upload`;
  `test_photo_store_records_each_read_upload`; `test_photo_store_discard_uses_the_slots_up`;
  `test_photo_store_keep_never_overwrites`; `test_photo_store_ignores_a_slot_id_of_another_shape`;
  `test_photo_store_keep_that_fails_leaves_nothing`.
- `test_inspector_refuses_each_marker`; `test_mailer_failure_raises_send_failed_with_the_code`;
  `test_an_outgoing_email_repr_holds_no_address`; `test_mailer_refuses_a_from_outside_asmbly_org`;
  `test_reprs_hold_no_bytes_token_or_address` (`InlineImage`, `StaffMember`, `Submission`).
- `test_port_errors_keep_a_code_never_a_message` (`Unavailable`, `SendFailed`,
  `SecretMissing`); `test_every_port_error_has_safe_text` (one of each port error class).
- `test_fakes_refuse_a_naive_time` (photo slots, rate limiter, records' ranges, and a
  `history` cursor with a naive time, which is `BadCursor`).
- `test_staff_tokens_not_allowed_and_not_signed_in`; `test_s256_is_the_pkce_challenge`;
  `test_staff_tokens_exchange_returns_the_token_once`;
  `test_staff_tokens_exchange_refuses_a_wrong_verifier_or_redirect`;
  `test_staff_tokens_urls_and_failures`.
- `test_rate_limiter_allows_10_then_refuses_within_the_window_and_allows_after`;
  `test_rate_limiter_window_is_rolling_across_a_fixed_boundary`;
  `test_rate_limiter_shows_the_keys_it_counted`.
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

Built on 2026-11-13. What phases 2 and later can rely on:

- The entities, states and functions of phases 1a to 1c, under `asmbly_ceramics.domain`,
  and `domain.email.is_error_code(code)` (1 to 64 of `[A-Za-z0-9_.-]`), which
  `mark_failed` and the port errors share.
- `asmbly_ceramics.ports`, with the names and signatures above: `records` (`Records`,
  `Put`, `Update`, `Change`, `Item`, `Submission`, `Conflict`, `HistoryPage`,
  `BadCursor`, `MAX_CHANGES = 100`),
  `ids.IdNumbers`, `photos` (`PhotoStore`, `UploadMissing`, `PhotosAlreadyKept`), `images` (`PhotoInspector`,
  `PhotoRefused`), `mailer` (`Mailer`, `OutgoingEmail`, `InlineImage`, `SendFailed`,
  `is_sending_address`), `staff` (`StaffTokens`, `StaffMember`, `NotSignedIn`,
  `NotAllowed`), `rate_limit.RateLimiter`, `clock.Clock`, `secrets` (`Secrets`,
  `SecretName`), and `errors` (`PortError`, the base of every port error; `Unavailable`
  and its five subclasses; `SecretMissing`; `error_code`).
- `Unavailable(code)` and `SendFailed(code)` keep a code with `is_error_code`'s shape and
  store any other text as `unknown`, so an adapter that passes AWS's message by mistake
  leaks nothing. `Conflict.ids` names the drop-offs and loads refused (an email's or a
  submission's drop-off), once each, in order.
- `is_sending_address(address)` is true only for an address exactly as
  `check_sending_address` returns it (at `asmbly.org`, domain lowercase, no spaces).
  `MemoryMailer.send` raises `ValueError` otherwise, before its failure switch; phase
  4's SES adapter does the same.
- `OutgoingEmail` prints no field in its `repr`; `InlineImage.data`,
  `StaffMember.email` and `Submission.token_hash` are `repr=False`.
- The fakes under `asmbly_ceramics.adapters.memory`, each with `fail_with`
  (`MemoryMailer`'s is an error code), except `MemoryRecords`, which has
  `fail_next_commit_with` (cleared once it fires), `fail_reads_with` (added for the use
  cases' "records unavailable" tests: every read raises it while set) and `commits`.
  `MemoryPhotoStore` has `put_upload(slot_id, data)` (`ValueError` for a slot it didn't
  issue; empty or over 10 MB is not kept), `kept_count(drop_off_id)`, `upload_count()`
  and `read_uploads` (every slot `read_upload` was asked for); it ignores a slot's
  expiry, which S3's lifecycle enforces in phase 4. `upload_slots` and `keep` take 1 to
  6 (`ValueError` otherwise). `MemoryIdNumbers.skip(n)` skips both counters.
  `MemorySecrets.remove(name)`; `FixedClock.advance(by)`; `MemoryStaffTokens` has
  `members`, `outsiders` and `approve(code, token)` (after a `sign_in_url`), and
  `adapters.memory.staff_tokens.s256(verifier)` gives the challenge;
  `MemoryRateLimiter.keys_hit` lists the keys counted. `history(limit)` refuses a limit under 1. The
  fakes refuse a naive time with `ValueError`, and log and print nothing.
- Decided in the 1d review (each in the port's docstring, kept by its fake and tested):
  - `RateLimiter.hit` counts in a **rolling** window `(now - window, now]`, refused
    hits included, and fails closed; `key` is always a keyed hash, never a raw
    address or cookie value. Phase 4's DynamoDB design was changed from fixed floored
    windows to match (one item per key with at most `limit` hit times, a versioned
    put); phase 7's form role gets `GetItem`/`PutItem` on `RATE#*`.
  - `PhotoStore.discard_uploads(slot_ids)` uses slots up; phase 2's `SubmitDropOff`
    calls it after the commit (step 8). `keep` leaves the uploads alone and never
    overwrites: `PhotosAlreadyKept(drop_off_id)`, which phase 2 handles by taking the
    next number.
  - `Records.commit([])` is a no-op: nothing sent, nothing recorded in `commits`.
  - `StaffTokens.exchange` refuses a wrong verifier or redirect URI, and a code is good
    for one exchange (the fake pops it on any try).
  - `Conflict(ids)` refuses a bare `str`; `SecretMissing(name)` keeps only a name with
    an error code's shape (else `unknown`); `MemoryIdNumbers.skip(n)` refuses n < 1.
  - `tests/domain/test_imports.py` also checks `adapters/memory/` (standard library,
    domain and ports only).
- For later phases (from the 1d review, not built here):
  - Phase 2: make the `KeyHasher`'s outputs `NewType`s (e.g. `RateKey`,
    `SubmissionHash`) if the ports start taking them, so a raw value can't be passed
    where a hash is expected; today the ports take `str`.
  - Phase 4: `S3PhotoStore.read_upload` and `discard_uploads` check
    `domain.photos.is_slot_id` (exactly 22 of `[A-Za-z0-9_-]`, `token_urlsafe(16)`'s
    shape) before any S3 call, as the memory fake now does (written into phase 4's
    photo store section). There is one shape: phase 2 checks the same function.
  - When entry points arrive (phases 6 and 8): a `tests/repo/` test that nothing under
    `entry/` or `web/` imports `asmbly_ceramics.adapters.memory`, so a fake can never
    serve production.
- The marker bytes `NOT_IMAGE`, `TOO_LARGE`, `TOO_MANY_PIXELS` in
  `adapters.memory.images`.
- The builders in `tests/domain/builders.py`; the made-up `Submission` and
  `OutgoingEmail` builders are local to `tests/adapters/test_memory.py`.
- Phase 4's adapter section names some reads differently (`failed_emails`,
  `settings_history`, `get_drop_off`) and some photo types differently (see phase 1b's
  hand-off); the names here and in phase 1b are the contract, and phase 4's `/prep`
  corrects its document.

From the whole-branch review (after 1a to 1d were built):

- **`Records.history` changed shape**: `history(limit, before: str | None) ->
  HistoryPage(changes, older)`, with `BadCursor` for a cursor it never gave (see the
  contract above). Phase 3's `ViewStudio`, phase 4's adapter and phase 9's history page
  take the cursor as opaque text.
- **`Update` means replace.** The contract's `Update` is a transactional `Put` of the
  whole item under `version = :expected` (phase 4's `commit`), not an `UpdateItem`. Phase
  7 grants the mailer's role `dynamodb:UpdateItem` only (`MarkEmails`), so every mailer
  commit (`claim`, `mark_sent`, `mark_failed`, `mark_cancelled`) would be refused.
  **Phase 7's `/prep` must reconcile**: either grant the mailer `dynamodb:PutItem` on
  `EMAIL#*` (and correct the line "no `PutItem`" in its verification), or have phase 4's
  adapter send an `Update` of an `Email` as an `UpdateItem` that sets every attribute
  under the same version condition. Phase 4's `/prep` checks the same for any other role
  that commits an `Update`.
- **`commit` returns nothing**; callers re-read (contract above).
- **`PhotoStore.keep` is all or nothing**, and a caller whose commit fails in any way
  after `keep` (`Conflict`, `RecordsUnavailable`, anything else) calls
  `delete_drop_off(id)` before it returns or raises (the port's docstring; phase 2's
  step 7). Today phase 7 gives the form's role only `s3:PutObject` on `dropoffs/*`, so it
  can't make that call. **Phases 4 and 7 must give a cleanup path**: `s3:DeleteObject`
  on `dropoffs/*` for the form's role (it adds little, since `PutObject` there can
  already overwrite a photo), and a backstop for a cleanup that itself fails (a sweep
  in the daily close for `dropoffs/AC-n/` prefixes with no drop-off record, or another
  rule phase 4 designs), so no photo outlives the close (#7).
- **Phases 3 and 4 `/prep` must settle the use-count port shape** (review finding 5,
  not changed here): phase 9's lists show each item's use count ("Used by 212 loads"),
  but `Records.is_item_used` returns a bool, and phase 4's table has no index that
  counts uses. Prep decides between a `use_counts(which)` read (and the index or scan
  behind it) and showing used/unused only, and updates this port, its fake and phase 9.
- **Only a retired item can be deleted** (`domain.studio.delete_item`, phase 1a's
  hand-off), so `is_item_used` is read only once nothing new can name the item; no
  `Check` change to `commit` was needed.
