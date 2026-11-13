---
phase_id: 2a
title: "Use cases: logging, keyed hashes, the studio and the form's reads"
epic: 1
implements: [2]
depends_on: [1d]
domain: [app]
estimated_size: L
---

# Phase 2a: Use cases: logging, keyed hashes, the studio and the form's reads

> **Status:** [x] Complete — 2026-11-13 on branch feat/drop-off-and-firing-phases-2-4

Phase 2 (the use cases behind the drop-off form and the first half of the console) was
split into 2a to 2d by `/prep` on 2026-11-13: its estimate was about 2,500 changed lines,
well over L. Together, 2a to 2d build exactly what phase 2 planned, with prep's
corrections folded in. "Phase 2" in the other phase documents means all four.

| Sub-phase | What |
| --- | --- |
| 2a (this one) | `log_event`, `KeyHasher`, `CurrentStudio`, `ViewStudioChoices`, `ReceivedSummary`, `RequestUploadSlots`, the test `world` fixture |
| [2b](phase-2b-submit-drop-off.md) | `SubmitDropOff` |
| [2c](phase-2c-email-composer.md) | The email composer and its templates (Jinja2) |
| [2d](phase-2d-waiting-list-and-rejection.md) | `WaitingList`, `FindDropOffs`, `ViewDropOff`, `PreviewRejection`, `RejectDropOff`, `UndoRejection` |

## Required reading

- [CLAUDE.md](../../CLAUDE.md): "Treat everything the public form sends as hostile",
  the logging rules.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): the
  rate limit under a keyed hash; the form never reads a drop-off item.
- This plan's [README](README.md#domain-model) and
  phase 1 ([1a](phase-1a-domain-core-and-studio.md), [1b](phase-1b-drop-offs-photos-outbox.md),
  [1c](phase-1c-loads-waiting-search.md), [1d](phase-1d-ports-and-fakes.md)): the
  entities, ports, fakes and message keys this phase calls. A name that differs from
  phase 1 is a mistake here.
- Story #2 (the form's criteria: the ID page, the rate limit).
- Patterns: AsmblyMCPs `src/mcp_core/logging.py` (fixed field names, IDs only).

## Goal

The conventions every later use case stands on exist and are tested against phase 1's
fakes: the one logging function and its fixed field names, keyed hashes of the raw
values the public form sends, the studio read (seeded the first time), and the three
reads behind the public form: the choices it offers, the upload slots it asks for, and
the ID page's summary. The `world` test fixture that 2b and 2d extend exists.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `use_cases/__init__.py` | Empty |
| `use_cases/log.py` | `log_event`, `LOG_FIELDS`: the only way use cases log |
| `use_cases/keys.py` | `KeyHasher`: keyed hashes of device cookies, addresses and submission tokens; `is_form_token` |
| `use_cases/studio.py` | `CurrentStudio`: reads the studio, seeding the starting values the first time; `StudioChoices`, `ViewStudioChoices` |
| `use_cases/received.py` | `ReceivedView`, `received_view`, `SubmissionNotFound`, `ReceivedSummary`: the ID page's summary |
| `use_cases/uploads.py` | `SlotRequest`, `RequestUploadSlots` |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/use_cases/__init__.py` | Empty |
| `tests/use_cases/conftest.py` | A `world` fixture: every fake from phase 1, a `FixedClock`, a `KeyHasher` over `MemorySecrets`, a `CurrentStudio` over an address on `asmbly.org` built in code, and this phase's use cases built on them (2b and 2d add theirs) |
| `tests/use_cases/test_log.py`, `test_keys.py`, `test_studio.py`, `test_received.py`, `test_uploads.py` | This phase's use cases |

## Files to modify

- `src/asmbly_ceramics/adapters/memory/records.py`: add a read log, `reads: list[str]`,
  appended with the method's name (`"drop_off"`, `"submission"`, `"studio"`, …) by every
  read method, so a test can prove which items a use case read (prep: phase 2's
  `test_received_summary_reads_only_the_submission` relied on a counter the fake didn't
  have). `commit` doesn't append. Every public read method appends its own name once
  per call, whichever helpers it uses: `drop_off`, `load`, `studio`, `email`,
  `submission`, `drop_offs_in`, `drop_offs_created_between`,
  `drop_offs_rejected_between`, `loads_in`, `loads_between`, `emails_for`, `emails_in`,
  `history`, `is_item_used` (once, though it reads two kinds). The name is appended
  before `fail_reads_with` raises, so a failed read is logged too.
- `tests/adapters/test_memory.py`: `test_records_logs_each_read_by_method_name`.
- `src/asmbly_ceramics/adapters/memory/photos.py`: `slot_count()`, the slots issued, so
  a test can prove a refusal issued none. `src/asmbly_ceramics/adapters/memory/secrets.py`:
  `set(name, value)` beside `remove`. Both added in build (review).
- `.implementation_plans/drop-off-and-firing/phase-2b-submit-drop-off.md`: step 2
  counts the address only when the device is allowed (review).
- `src/asmbly_ceramics/domain/photos.py`: `PHOTO_COUNT_KEY` and `is_photo_count`, the
  one photo-count check that `domain/dropoff.py` (`DropOffDetails`) and
  `RequestUploadSlots` both use; `tests/domain/test_photos.py` tests it. Added in review.
- `src/asmbly_ceramics/domain/ids.py`: `is_drop_off_id`, `is_load_id` and `is_item_id`,
  the shapes `log.py` checks with; `new_item_id` always gives a slug with a letter
  (`06` gives `item-06`). `tests/domain/test_ids.py` tests them. Added in review.
- `src/asmbly_ceramics/domain/errors.py`: `TooManySubmissions` says "Too many drop-offs
  from here in the last few minutes. Try again later.", naming neither limit, since the
  address limit raises it too; `tests/domain/test_errors.py` and phase 1a's document
  follow. Changed in review.
- `tests/domain/test_imports.py`: the import check walks `use_cases/` too (the domain,
  the ports and the use cases only; no adapter, AWS library or web framework). Added in
  build; phase 4 extends the same check to `mail/` and `web/`.

No dependency changes.

## Implementation details

### app: logging (`use_cases/log.py`)

```python
LOG_FIELDS = frozenset(
    {
        "event",
        "drop_off_id",
        "load_id",
        "user",
        "kind",
        "outcome",
        "reason",
        "error_code",
        "count",
        "fields",
        "list",
        "item",
    }
)

logger = logging.getLogger("asmbly_ceramics")


def log_event(event: str, *, level: int = logging.INFO, **fields: str | int) -> None:
    """Log one event with fixed field names. Unknown names raise ValueError (a bug)."""
```

- Every use case logs through `log_event`, with `extra=fields` (and `event` in the
  extra too). The record's message is the event name alone, never a formatted value.
  Phase 7 formats these as JSON lines; the field names are a contract with its metric
  filters and alarms.
- What may go in each field: `drop_off_id` (`AC-12`), `load_id` (`L-4`), `user` (a
  staff username), `kind` (an email kind), `outcome`, `reason` (a fixed word or an item
  ID), `error_code` (a provider's error code as `ports.errors.error_code` keeps it, or a
  fixed code), `count`
  (a number), `fields` (field *names* that were refused, comma-joined, never their
  values), `list` and `item` (a catalog list and item ID). Never a name, email, phone,
  message, photo, token, cookie or address.
- Decided in review: as a backstop, each field has its own shape, and a value without it
  is logged as `invalid` rather than raising, so a caller's mistake can't put an address
  or a sentence in a log and doesn't fail a request. The shapes are listed in the
  hand-off (`asmbly_ceramics.use_cases.log`) and in `log.py`'s docstring; IDs and slugs
  are checked by `domain.ids`, error codes start from `domain.email.is_error_code`.

### app: keyed hashes (`use_cases/keys.py`)

```python
class KeyHasher:
    def __init__(self, secrets: Secrets) -> None: ...  # reads SecretName.HASH_KEY once, lazily
    def device(self, cookie: str) -> str: ...  # "device#" + hex HMAC-SHA256
    def address(self, source_address: str) -> str: ...  # "address#" + hex HMAC-SHA256
    def slots_device(self, cookie: str) -> str: ...  # "slots-device#" + ...
    def slots_address(self, source_address: str) -> str: ...  # "slots-address#" + ...
    def submission(self, token: str) -> str: ...  # "submission#" + ...
```

- Decided: the use cases receive the raw cookie, address and token from the page and
  hash them here, so that no raw value reaches `Records`, `RateLimiter` or a log. The
  key is the `hash-key` secret (phase 7 sets it in Parameter Store per environment).
  Each method's prefix goes into the HMAC's input as well as the output, so one raw
  value hashed for two purposes gives two unrelated digests.
- The key must be at least 32 bytes (`HASH_KEY_MIN_BYTES`); a shorter one (an empty or
  placeholder parameter) raises `ValueError("hash-key is too short")`, is not cached,
  and fails the first request instead of giving weak hashes (prep).
- `address` normalizes before hashing (prep: one IPv6 caller could otherwise rotate
  addresses inside its /64 and get past the only limit that needs no cookie): the value
  is parsed with `ipaddress`; an IPv4-mapped IPv6 address hashes as its IPv4 address;
  any other IPv6 address hashes as its /64 network (`2001:db8:1:2::/64`); an IPv4
  address hashes as itself; text that isn't an address (it never should be: API
  Gateway sets it) hashes as given. `slots_address` normalizes the same way.
- `SecretMissing` and `SecretsUnavailable` from `Secrets.get` go up unchanged (the page
  says "try again"); a failed read isn't cached, so the next call tries again.
- Decided (phase 1d's hand-off asked): the outputs stay `str`, not `NewType`s, because
  the ports take `str`; the prefix on every output and
  `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter` (2b) are the
  guard. Revisit if a port starts taking a hash type.

### app: the studio (`use_cases/studio.py`)

```python
class CurrentStudio:
    def __init__(
        self, records: Records, clock: Clock, initial_sending_address: str, *, seed: bool = True
    ) -> None: ...
    def __call__(self) -> Studio: ...


class StudioNotSeeded(Exception):  # read-only and no studio stored yet: a setup error
    def __init__(self) -> None: ...
```

- The constructor runs `check_sending_address` on `initial_sending_address` (prep), so a
  wrong `INITIAL_SENDING_ADDRESS` fails composition at start, not a stranger's first
  form load. With `seed=False` (phase 7's mailer, whose role can't write the studio) a
  missing studio raises `StudioNotSeeded` instead of seeding.

Reads `records.studio()` (strongly consistent). When there is none, builds
`starting_studio(initial_sending_address, now)` and commits `Put(studio)` and
`Put(change)`; on `Conflict` (another request seeded it first) reads again and returns
what it finds; if that read still finds none, raises `RecordsUnavailable("StudioMissing")`
(the page says "try again"). Logs `event=studio_seeded` once, only after its own
commit lands. Composition (phase 7) passes the
`INITIAL_SENDING_ADDRESS` value; tests pass an address built in code on `asmbly.org`.

```python
@dataclass(frozen=True, slots=True)
class StudioChoices:
    firing_types: tuple[CatalogItem, ...]  # active only, in the studio's order; each says needs_glaze_type
    glaze_types: tuple[CatalogItem, ...]  # active only


class ViewStudioChoices:  # what the form offers
    def __init__(self, studio: CurrentStudio) -> None: ...
    def __call__(self) -> StudioChoices: ...
```

### app: the ID page's summary (`use_cases/received.py`)

```python
@dataclass(frozen=True, slots=True)
class ReceivedView:
    id: DropOffId
    pieces: int
    firing_type: str  # the item's name
    glaze_type: str | None
    created_at: datetime  # shown in Austin time


def received_view(submission: Submission) -> ReceivedView: ...  # the summary the Submission item carries


class SubmissionNotFound(DomainError):  # "That page has expired." (fixed text, no value)
    def __init__(self) -> None: ...


class ReceivedSummary:  # the ID page after Submit
    def __init__(self, records: Records, clock: Clock) -> None: ...
    def __call__(self, token_hash: str) -> ReceivedView: ...  # SubmissionNotFound; never a contact detail
```

`ReceivedView` has no field for a name, email, phone or photo, so the public ID page
can't show one. `ReceivedSummary` reads only the `Submission` item
(`records.submission(token_hash)`, strongly consistent), which carries the summary
(phase 1); the form function never reads a drop-off item, and phase 7's form role
can't. The web layer calls it with the submission hash from its own signed cookie
(phase 6). An unknown submission, or one whose `expires_at` has passed (`now >= expires_at`; the table's TTL
deletes late, so the use case checks it against the clock), raises
`SubmissionNotFound`. (Prep: phase 2 said `NotFound`, but `domain.errors.NotFound`
takes a drop-off or load ID, which an unknown submission doesn't have, and its message
would name it.)

### app: `RequestUploadSlots` (`use_cases/uploads.py`)

```python
@dataclass(frozen=True, slots=True)
class SlotRequest:
    count: int  # 1..PHOTOS_MAX
    device: str  # the device cookie
    source_address: str


class RequestUploadSlots:
    def __init__(self, photos: PhotoStore, limiter: RateLimiter, hasher: KeyHasher, clock: Clock) -> None: ...
    def __call__(self, request: SlotRequest) -> list[UploadSlot]: ...
```

- A count that isn't an `int` (a `bool` included) or is outside `PHOTOS_MIN` to
  `PHOTOS_MAX` raises `InvalidDetails({"photos": "photos.count"})`, before the limiter
  is hit.
- The device value must have the token shape (`is_form_token`, below); an empty or
  malformed one raises `InvalidDetails({"form": "form.expired"})` before the limiter is
  hit, so cookieless callers never share one `device#` bucket (prep). The page sets the
  cookie when it serves the form (phase 6), so only a caller that never loaded the form
  meets this; the page's answer is to reload.
- Hashes both values first (a key that can't be read goes up with nothing counted),
  then counts against `SLOT_DEVICE_LIMIT` (`hasher.slots_device`) and, only when the
  device is allowed, `SLOT_ADDRESS_LIMIT` (`hasher.slots_address`); over either raises
  `TooManySubmissions`. Nobody can ask for unlimited upload links: one cookie is capped
  by the device limit, and every new cookie is counted by the address. Decided in
  build (review): a device already over its limit isn't counted against the address,
  because its request is refused either way and counting it would let one phone
  retrying with the same cookie keep the studio's shared address bucket full. 2b's
  submission limit should follow the same order. These limits are looser than
  the submission limit, because a person may change photos before submitting.
- The limiter fails closed: if `limiter.hit` raises `RecordsUnavailable`, no slot is
  issued and the error goes up (the page says "try again").
- Returns `photos.upload_slots(count, now)`. Logs `event=upload_slots`, `count`; on
  refusal `event=upload_slots_refused`, `reason` (`invalid_details`, `form_expired`,
  `device_limit`, `address_limit`, or `limiter_unavailable` with `error_code`, the
  `RecordsUnavailable`'s code, before the error goes up). A refused device is
  `device_limit` (the address isn't counted then).
- Accepted (prep): everyone on the studio's wifi shares one public address, so its
  limits (60 slot requests, 30 submissions in 10 minutes) are shared by a busy class.
  Phase 6 asks for every slot in one request per form, not one per photo picked, to
  keep well inside it. A refused hit counts too (the port's contract), so one person
  rotating device cookies on the studio's wifi can fill the shared address bucket for a
  while: accepted with the shared-wifi risk above (prep). Retrying with one cookie
  can't (above).
- Accepted (prep): a browser with cookies turned off never has a device cookie, so it
  always gets `form.expired`; phase 6's message for it says the form needs cookies, not
  only "reload".
- Accepted (prep): `KeyHasher` keeps the key for the life of a Lambda container, so a
  `hash-key` rotation splits hashes across containers for a while (a refresh after
  Submit on a new container would miss its `Submission`), and any rotation orphans
  every live `Submission` (its ID page expires; in 2b a re-posted token makes a second
  drop-off) as well as resetting the rate-limit counts. Owed by phase 5: its runbook
  says to rotate `hash-key` only when the studio is closed (see the hand-off).

`is_form_token(value: str) -> bool` lives in `use_cases/keys.py`: exactly 22 to 64 of
`[A-Za-z0-9_-]` (`re.fullmatch` with `re.ASCII`, so a trailing newline is refused; a
non-`str` is `False`), the shape of the form's submission token and of the device cookie
(phase 6 makes both with `secrets.token_urlsafe`). 2b checks the submission token and
the device with it.

## Tests

- `tests/use_cases/test_log.py`: `test_unknown_log_field_raises`;
  `test_log_event_puts_the_fields_in_extra_and_only_the_event_in_the_message`.
- `test_keys.py`: `test_is_form_token_takes_22_to_64_url_safe_characters` (21, 65, a trailing newline and a non-ASCII letter refused);
  `test_a_short_key_raises_and_is_not_cached`;
  `test_an_ipv6_address_hashes_by_its_64_network_and_a_mapped_ipv4_as_ipv4`; `test_each_hash_has_its_prefix_and_differs_by_purpose` (the same raw
  value hashed by `device` and `slots_device` gives different digests);
  `test_hashes_hold_no_raw_value`; `test_the_key_is_read_once`;
  `test_a_missing_key_raises_and_is_not_cached`.
- `test_studio.py`: `test_the_studio_is_seeded_once_with_the_starting_values` (two
  calls, one commit, one `studio_seeded` log); `test_a_seeding_race_reads_the_winner`
  (the fake's `fail_next_commit_with=Conflict()` with a studio written in between);
  `test_studio_choices_list_only_active_items`;
  `test_a_wrong_initial_sending_address_fails_at_construction`;
  `test_read_only_studio_raises_studio_not_seeded`;
  `test_a_conflict_with_no_studio_after_it_raises_records_unavailable`;
  `test_a_seeded_studio_that_cant_be_read_back_raises_records_unavailable`;
  `test_studio_logs_hold_no_sending_address` (`caplog`).
- `test_received.py`: `test_received_view_has_no_contact_fields` (the dataclass's
  fields are exactly the five above);
  `test_an_unknown_submission_raises_submission_not_found`;
  `test_an_expired_submission_raises_submission_not_found` (at exactly `expires_at` too);
  `test_received_summary_reads_only_the_submission` (the fake's `reads` is exactly
  `["submission"]`).
- `test_uploads.py`: `test_upload_slots_count_must_be_1_to_6` (0, 7, `True`);
  `test_upload_slot_requests_are_limited` (the 21st from a device and the 61st from an
  address within 10 minutes raise `TooManySubmissions`);
  `test_upload_slots_fail_closed_when_the_limiter_is_unavailable` (no slot issued; logged as
  `limiter_unavailable` with the code);
  `test_a_value_that_isnt_a_submission_hash_is_not_looked_up` (in `test_received.py`);
  `test_a_value_that_isnt_an_id_or_a_word_is_logged_as_invalid` (in `test_log.py`);
  `test_upload_slot_refusals_log_which_limit_and_no_raw_value` (`caplog`: no device
  cookie or address in any record);
  `test_a_device_over_its_limit_doesnt_count_against_the_address`;
  `test_upload_slots_fail_closed_when_the_hash_key_cant_be_read`;
  `test_upload_slot_keys_are_hashes` (`keys_hit` holds only `slots-device#` and
  `slots-address#` keys); `test_a_missing_or_malformed_device_is_refused_before_counting`.

## Acceptance criteria

1. `log_event` refuses a field outside `LOG_FIELDS`, and puts no value in a record's
   message.
2. `KeyHasher` turns every raw cookie, address and token into a prefixed keyed hash,
   counts an IPv6 address by its /64, and refuses a key under 32 bytes.
3. `CurrentStudio` seeds the studio once, and a seeding race returns the winner's.
4. `ViewStudioChoices` offers only active firing and glaze types (#2's form choices).
5. `ReceivedSummary` reads only the submission, returns no contact detail, and raises
   `SubmissionNotFound` for an unknown or expired one (#2: the ID on screen).
6. `RequestUploadSlots` issues 1 to 6 slots, is rate limited per device and per
   address, and issues nothing when the limiter can't be reached (#2's limits).

## Verification

```bash
uv run pytest tests/use_cases tests/adapters
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

Built on 2026-11-13. What phases 2b, 2d, 3 and later can rely on:

- `asmbly_ceramics.use_cases.log`: `log_event(event, *, level=logging.INFO, **fields)`
  and `LOG_FIELDS`. The event is a snake_case word (`ValueError` otherwise) and is the
  record's whole message; the fields go in `extra` with `event`; an unknown field name
  raises `ValueError`, a value that isn't a `str` or `int` (a `bool` included) raises
  `TypeError`. Logger `asmbly_ceramics`. Callers pass fixed words, IDs, usernames and
  `ports.errors.error_code` codes only. As a backstop each field has its own shape
  (review): `drop_off_id` and `load_id` checked by `domain.ids`'s
  `is_drop_off_id` and `is_load_id`, `count` an `int` only, `kind`, `outcome` and `list`
  a lowercase snake_case word, `reason` such a word or an item ID, `item` an item ID
  (`domain.ids.is_item_id`: a slug always holds a letter, and `new_item_id` gives a name
  without one an `item-` prefix, so `06` is `item-06`), `error_code` `is_error_code`'s
  shape that is either 1 to 3 digits (`404`) or holds a letter, has no `-` and is under
  64 characters (`photo_missing`, `EC2ThrottledException`, `KeyError`), `fields` comma-joined field names (`photo.2` allowed), `user` a
  handle of at most 40 with a letter; a value without its field's shape is logged as
  `invalid`. So a phone number, an IP address, a `#` hash or a 64-character digest never
  fits; a one-word name, or a token as a `user`, still can, which is why callers pass
  only the listed values.
- `asmbly_ceramics.use_cases.keys`: `is_form_token(value)` (22 to 64 of
  `[A-Za-z0-9_-]`, `fullmatch`, ASCII); `is_submission_hash(value)` (`SUBMISSION_PREFIX`,
  `submission#`, and 64 lowercase hex: the one check of that shape); `KeyHasher(secrets)` with `device`,
  `address`, `slots_device`, `slots_address`, `submission`, each returning
  `"<prefix>#" + 64 hex` (the prefix is in the HMAC's input too). The `hash-key` is read
  once, on first use; `SecretMissing` and `SecretsUnavailable` go up and aren't cached;
  a key under `HASH_KEY_MIN_BYTES` (32) raises `ValueError("hash-key is too short")`.
  Addresses: IPv4 as itself, an IPv4-mapped IPv6 as its IPv4, other IPv6 by its /64,
  other text as given.
- `asmbly_ceramics.use_cases.studio`: `CurrentStudio(records, clock,
  initial_sending_address, *, seed=True)` (the address is checked with
  `check_sending_address` at construction); calling it returns the stored studio,
  seeding `starting_studio` once (one commit of `Put(studio)`, `Put(change)`, one
  `studio_seeded` log); on `Conflict` it returns the winner's, or raises
  `RecordsUnavailable("StudioMissing")` if none is there (and after its own commit it
  reads the studio back, raising the same if it can't); `seed=False` raises
  `StudioNotSeeded` instead of seeding. `ViewStudioChoices(studio)()` returns
  `StudioChoices(firing_types, glaze_types)`, active items only, in the studio's order.
- `asmbly_ceramics.use_cases.received`: `ReceivedView(id, pieces, firing_type,
  glaze_type, created_at)`, `received_view(submission)`, `SubmissionNotFound` (a
  `DomainError`, "That page has expired."), `ReceivedSummary(records, clock)(token_hash)`,
  which looks up only an `is_submission_hash` value (anything else is
  `SubmissionNotFound` with nothing read), reads only `records.submission`, and treats
  `now >= expires_at` as expired.
- `asmbly_ceramics.use_cases.uploads`: `SlotRequest(count, device, source_address)`
  (device and address `repr=False`), `RequestUploadSlots(photos, limiter, hasher,
  clock)(request) -> list[UploadSlot]`. Hashes first (`SecretMissing`,
  `SecretsUnavailable` or a short key go up, nothing counted). Refuses a count that isn't
  `domain.photos.is_photo_count` with `InvalidDetails({"photos": PHOTO_COUNT_KEY})`
  (`photos.count`, the same check and key as `DropOffDetails.create`) and a malformed device with
  `InvalidDetails({"form": "form.expired"})` before counting; hits
  `SLOT_DEVICE_LIMIT`, then `SLOT_ADDRESS_LIMIT` only when the device is allowed, and
  raises `TooManySubmissions` if either refuses; `RecordsUnavailable` from the limiter goes up
  (logged `upload_slots_refused`, `reason=limiter_unavailable`, `error_code`), and
  `PhotosUnavailable` from the store goes up. Logs `upload_slots` (`count`) or
  `upload_slots_refused` (`reason`: `invalid_details`, `form_expired`, `device_limit`,
  `address_limit`, `limiter_unavailable`).
- `MemoryPhotoStore.slot_count()` (slots issued) and `MemorySecrets.set(name, value)`,
  added in build for these tests.
- `MemoryRecords.reads`: every read method's name, once per call, failed reads included;
  `commit` doesn't append.
- `tests/use_cases/conftest.py`: the `world` fixture (`World` with every fake,
  `FixedClock(NOW)`, `KeyHasher` over `MemorySecrets`, `studio`, `choices`, `received`,
  `upload_slots`) and the made-up `DEVICE` and `SOURCE_ADDRESS` (TEST-NET-3). 2b and 2d
  add their use cases to `World`.
- `tests/domain/test_imports.py` now walks `use_cases/` (domain, ports and use cases
  only); phase 4 extends it to `mail/` and `web/`.

Owed by later phases (from this phase's prep and review; each phase's `/prep` checks it):

- **2b**: follow the device-first limit order (done in its document); reuse
  `received_view` and the same `now >= expires_at` expiry for a repeated token; pass IDs
  to `log_event` as `str(drop_off.id)` (an `int` `drop_off_id` is logged as `invalid`,
  as is any value without its field's shape); check a photo count only through
  `DropOffDetails.create`, which uses `domain.photos.is_photo_count` (never a third copy
  of the 1-to-6 check); a submission hash's shape only through `keys.is_submission_hash`.
- **2c, 2d and 3**: the use cases never import `mail/` (`tests/domain/test_imports.py`
  allows only the domain, the ports and the use cases). 2c puts `ComposedEmail`, the
  `Composer` Protocol, `outgoing` and `cid` in `ports/composer.py` and `JinjaComposer` in
  `mail/compose.py`; 2d's `PreviewRejection` and phase 3's `SendPendingEmail` and
  `SendTestEmail` import `Composer` from `ports.composer` (written into their documents'
  Files to modify). Chosen over letting `use_cases/` import `mail/`, because it keeps
  "the use cases call interfaces" true for the one non-AWS service too, and the use cases
  then don't depend on Jinja2.
- **Phase 4**: 2a changed `tests/domain/test_imports.py` (it walks `use_cases/`); phase
  4 extends that file, so it starts from 2a's version (README's parallelism table).
- **Phase 5**: the runbook's `hash-key` row says rotating it orphans live submissions
  (ID pages expire, a re-posted token makes a second drop-off) as well as resetting the
  rate-limit counts, so rotate only when the studio is closed.
- **Phase 6**: `POST /drop-off/uploads` maps `InvalidDetails` `form.expired` (a message
  that the form needs cookies, then reload; a request without the device cookie gets
  this, not a 400) and `photos.count`. Both show "try again": `PhotosUnavailable` is
  logged by the page; `RecordsUnavailable` from the limiter is already logged by the use
  case (`upload_slots_refused`, `reason=limiter_unavailable`), so the page doesn't log it
  again (one count per refusal for phase 7's metric). The page shows
  `TooManySubmissions`'s `error.message` and writes no sentence of its own: the domain's
  wording, "Too many drop-offs from here in the last few minutes. Try again later.",
  names neither limit, because the address limits (shared by a whole network) raise it
  too and the exception doesn't say which limit refused (only the log's `reason` does). The submission
  hash passed to `ReceivedSummary` comes only from the signed cookie.
- **Phase 7**: `build_mailer` builds `CurrentStudio(..., seed=False)` (already in its
  document). `ports/secrets.py` says the keys are read at start, but `KeyHasher` reads
  `hash-key` lazily, on the first hash: a missing or short key shows only when a form
  request first needs it. So composition warms it (one `hasher.device(...)` of a fixed
  value at start, failing the start), or the smoke test posts to `/drop-off/uploads`;
  phase 7 picks one.

Done in review: one photo-count check, `domain.photos.is_photo_count` and
`PHOTO_COUNT_KEY`, used by both `RequestUploadSlots` and `DropOffDetails.create`; one
submission-hash shape, `keys.is_submission_hash`. The wording of `TooManySubmissions` is
phase 6's (in its list above).
