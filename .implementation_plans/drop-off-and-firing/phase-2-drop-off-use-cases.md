---
phase_id: 2
title: "Use cases: drop off, waiting list, reject"
epic: 1
implements: [2, 3, 5]
depends_on: [1]
domain: [app]
estimated_size: L
---

# Phase 2: Use cases: drop off, waiting list, reject

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): "Treat everything the public form sends as hostile",
  the logging rules, "Send email only from an address at `asmbly.org`".
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md):
  photos re-encoded on submit, the rate limit under a keyed hash, the outbox.
- This plan's [README](README.md#domain-model) and
  [phase 1](phase-1-domain-model.md): the entities, ports, fakes and message keys this
  phase calls. A name that differs from phase 1 is a mistake here.
- Story #2 (the form's criteria), #3 (the waiting list and search), #5 (rejection),
  and epic #1's **Decided** list (rejection email follows the Kiln Ops template, a
  rejected piece resubmitted gets a new ID).
- The design's email board (epic #1's design comment): the received and needs-attention
  emails' sections and wording.
- Patterns: AsmblyMCPs `src/mcp_core/logging.py` (fixed field names, IDs only) and
  `src/servers/ceramics/mail.py` (what it never logs).
- Jinja2's documentation on autoescaping (`select_autoescape`) and on
  `Environment(undefined=StrictUndefined)`.

## Goal

Every use case behind the drop-off form and the first half of the console exists,
tested against phase 1's fakes: asking for upload slots, submitting a drop-off (rate
limit, every field and photo checked, the ID issued, the photos kept, the drop-off and
its received email stored together, a repeated submit answered with the same ID), the
waiting list with its totals, search, one drop-off's page, and rejecting with a preview
and a same-day undo. The three emails are composed from templates with everything
escaped, ready for the mailer in phase 3. The logging conventions every later phase
uses are fixed here.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `use_cases/__init__.py` | Empty |
| `use_cases/log.py` | `log_event`, `LOG_FIELDS`: the only way use cases log |
| `use_cases/keys.py` | `KeyHasher`: keyed hashes of device cookies, addresses and submission tokens |
| `use_cases/studio.py` | `CurrentStudio`: reads the studio, seeding the starting values the first time; `ViewStudioChoices` |
| `use_cases/received.py` | `ReceivedSummary`, `ReceivedView`: the ID page's summary |
| `use_cases/uploads.py` | `RequestUploadSlots` |
| `use_cases/submit.py` | `SubmitDropOff`, `SubmitRequest`, `Submitted` |
| `use_cases/waiting.py` | `WaitingList`, `WaitingView`, `WaitingRow`, `FindDropOffs` |
| `use_cases/view_drop_off.py` | `ViewDropOff`, `DropOffView` |
| `use_cases/reject.py` | `PreviewRejection`, `RejectDropOff`, `UndoRejection` |
| `mail/__init__.py` | Empty |
| `mail/compose.py` | `Composer` and `ComposedEmail` |
| `mail/templates/_layout.html` | The shared email frame: purple band with the Asmbly name, the ceramics bar, the footer |
| `mail/templates/received.html`, `received.txt` | "We received your drop-off" |
| `mail/templates/ready.html`, `ready.txt` | "Your pieces are ready for pickup" (used from phase 3) |
| `mail/templates/rejected.html`, `rejected.txt` | "Your drop-off needs attention" |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/use_cases/__init__.py` | Empty |
| `tests/use_cases/conftest.py` | A `world` fixture: every fake from phase 1, a `FixedClock`, a `KeyHasher` over `MemorySecrets`, the studio seeded, and the use cases built on them |
| `tests/use_cases/test_submit.py`, `test_uploads.py`, `test_waiting.py`, `test_view_drop_off.py`, `test_reject.py`, `test_studio.py`, `test_log.py` | The use cases |
| `tests/mail/__init__.py`, `tests/mail/test_compose.py` | The composer |

## Files to modify

- `pyproject.toml` and `uv.lock`: `uv add jinja2` (runtime). Never edit `uv.lock` by
  hand.
- `pyproject.toml`: `[tool.uv.build-backend]` or the package data setting `uv_build`
  needs so that `mail/templates/*` ship with the package (check uv's documentation for
  the current key; a test below fails if the templates are missing from an installed
  package).

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

- Every use case logs through `log_event`, with `extra=fields`. Phase 7 formats these
  as JSON lines; the field names are a contract with its metric filters and alarms.
- What may go in each field: `drop_off_id` (`AC-12`), `load_id` (`L-4`), `user` (a
  staff username), `kind` (an email kind), `outcome`, `reason` and `error_code` (fixed
  words or a provider's error code), `count` (a number), `fields` (field *names* that
  were refused, comma-joined, never their values), `list` and `item` (a catalog list
  and item ID). Never a name, email, phone, message, photo, token, cookie or address.
- `tests/use_cases/test_log.py` checks that an unknown field raises, and the end-to-end
  log test below checks no personal detail is ever logged.

### app: keyed hashes (`use_cases/keys.py`)

```python
class KeyHasher:
    def __init__(self, secrets: Secrets) -> None: ...  # reads SecretName.HASH_KEY once, lazily
    def device(self, cookie: str) -> str: ...  # "device#" + hex HMAC-SHA256
    def address(self, source_address: str) -> str: ...  # "address#" + hex HMAC-SHA256
    def slots_device(self, cookie: str) -> str: ...  # "slots-device#" + ...
    def slots_address(self, source_address: str) -> str: ...
    def submission(self, token: str) -> str: ...  # "submission#" + ...
```

Decided: the use cases receive the raw cookie, address and token from the page and
hash them here, so that no raw value reaches `Records`, `RateLimiter` or a log. The
key is the `hash-key` secret (phase 7 sets it in Parameter Store per environment).

### app: the studio (`use_cases/studio.py`)

```python
class CurrentStudio:
    def __init__(self, records: Records, clock: Clock, initial_sending_address: str) -> None: ...
    def __call__(self) -> Studio: ...
```

Reads `records.studio()` (strongly consistent). When there is none, builds
`starting_studio(initial_sending_address, now)` and commits `Put(studio)` and
`Put(change)`; on `Conflict` (another request seeded it first) reads again. Logs
`event=studio_seeded` once. Composition (phase 7) passes the `INITIAL_SENDING_ADDRESS`
value; tests pass an address built in code on `asmbly.org`.

### app: `ViewStudioChoices` and `ReceivedSummary`

```python
@dataclass(frozen=True, slots=True)
class StudioChoices:
    firing_types: tuple[CatalogItem, ...]  # active only, in the studio's order; each says needs_glaze_type
    glaze_types: tuple[CatalogItem, ...]  # active only


class ViewStudioChoices:  # use_cases/studio.py: what the form offers
    def __init__(self, studio: CurrentStudio) -> None: ...
    def __call__(self) -> StudioChoices: ...


@dataclass(frozen=True, slots=True)
class ReceivedView:
    id: DropOffId
    pieces: int
    firing_type: str  # the item's name
    glaze_type: str | None
    created_at: datetime  # shown in Austin time


class ReceivedSummary:  # use_cases/received.py: the ID page after Submit
    def __init__(self, records: Records, studio: CurrentStudio) -> None: ...
    def __call__(self, id: DropOffId) -> ReceivedView: ...  # NotFound; never a contact detail
```

`ReceivedView` has no field for a name, email, phone or photo, so the public ID page
can't show one. The web layer only calls it with the ID from its own signed cookie
(phase 6).

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

- A count outside 1 to 6 raises `InvalidDetails({"photos": "photos.count"})`.
- Counts against `SLOT_DEVICE_LIMIT` and `SLOT_ADDRESS_LIMIT` (phase 1), so nobody can
  ask for unlimited upload links; over either raises `TooManySubmissions`. These limits
  are looser than the submission limit, because a person may change photos before
  submitting.
- Returns `photos.upload_slots(count, now)`. Logs `event=upload_slots`, `count`.

### app: `SubmitDropOff` (`use_cases/submit.py`)

```python
@dataclass(frozen=True, slots=True)
class SubmitRequest:
    name: str
    email: str
    phone: str
    pieces: str
    firing_type: str
    glaze_type: str | None
    upload_slots: tuple[str, ...]
    submission_token: str
    device: str
    source_address: str


@dataclass(frozen=True, slots=True)
class Submitted:
    drop_off: DropOff
    repeated: bool  # True when this token had already made the drop-off


class SubmitDropOff:
    def __init__(
        self,
        records: Records,
        ids: IdNumbers,
        photos: PhotoStore,
        inspector: PhotoInspector,
        limiter: RateLimiter,
        hasher: KeyHasher,
        clock: Clock,
        studio: CurrentStudio,
    ) -> None: ...
    def __call__(self, request: SubmitRequest) -> Submitted: ...
```

In order:

1. **The token.** It must be 22 to 64 URL-safe characters (the form puts a fresh one in
   each page it serves); otherwise `InvalidDetails({"form": "form.expired"})`. Hash it;
   if `records.submission(hash)` exists, return `Submitted(that drop-off,
   repeated=True)`: a refresh or a double tap makes no second drop-off and counts
   nothing.
2. **The rate limit** (#2). `limiter.hit(hasher.device(...), DEVICE_LIMIT, now)` and
   the same for the address with `ADDRESS_LIMIT`; either false raises
   `TooManySubmissions`. Every attempt that reaches this step counts, refused or not.
3. **The fields.** `DropOffDetails.create(..., photo_count=len(set(upload_slots)),
   studio=CurrentStudio())`. A duplicated slot ID counts once.
4. **The photos.** For each slot, in order, `photos.read_upload(slot)` then
   `inspector.inspect(data)`. `UploadMissing` gives `photo.<n>: photo.missing`;
   `PhotoRefused(kind)` gives `photo.<n>: photo.<kind>`. Steps 3 and 4 both run, so the
   page shows every problem at once, then raise one `InvalidDetails`. Nothing is
   stored: refused uploads stay under `uploads/` and expire with the bucket's
   lifecycle rule.
5. **The ID.** `ids.next_drop_off_id()`.
6. **Keep the photos.** `photos.keep(id, checked)` returns the refs.
7. **Commit** `Put(drop_off)`, `Put(new_email(id, RECEIVED, now))`,
   `Put(Submission(hash, id, now + SUBMISSION_LIFETIME))` together. On `Conflict` (the
   same token committed in a race), `photos.delete_drop_off(id)` (the number is
   skipped, which the ID contract allows) and return the stored submission's drop-off
   with `repeated=True`.

Logs: `event=drop_off_submitted`, `drop_off_id`, `count` (photos); on refusal
`event=drop_off_refused`, `reason` (`invalid_details`, `rate_limited`, `form_expired`),
`fields` (the refused field names). Never a value.

Memory: up to 6 uploads of 10 MB are read one at a time and dropped once inspected;
phase 7 sizes the form function's memory for one 10 MB decode.

### app: the waiting list and search (`use_cases/waiting.py`)

```python
@dataclass(frozen=True, slots=True)
class WaitingRow:
    drop_off: DropOff
    days_waiting: int  # whole Austin days since created_at
    overdue: bool
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
  applied to the rows only. Overdue rows are marked (#7).
- `FindDropOffs` (#3): `parse_query`. A number reads `records.drop_off(DropOffId(n))`
  (any state, closed included, so staff can look up an old slip). Text searches
  waiting, in-load, fired and rejected drop-offs with `matches`, oldest first, at most
  50 rows. `waiting_only=True` is what the load page's search uses (phase 9).
- Neither logs: reads aren't logged, and a search's text may be a name.

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

`can_undo_rejection` is `REJECTED` and the same Austin day (the same rule as
`undo_rejection`, by calling it on a copy and catching `UndoTooLate`, so the rule stays
in one place).

### app: rejecting (`use_cases/reject.py`) (#5)

```python
@dataclass(frozen=True, slots=True)
class RejectRequest:
    drop_off_id: DropOffId
    reason: ItemId
    message: str
    version: int  # the version the staff member saw
    staff: StaffMember


class PreviewRejection:
    def __init__(
        self, records: Records, photos: PhotoStore, clock: Clock, studio: CurrentStudio, composer: Composer
    ) -> None: ...
    def __call__(self, request: RejectRequest, image_src: Callable[[PhotoRef], str]) -> ComposedEmail: ...


class RejectDropOff:
    def __init__(self, records: Records, clock: Clock, studio: CurrentStudio) -> None: ...
    def __call__(self, request: RejectRequest) -> DropOff: ...


class UndoRejection:
    def __init__(self, records: Records, clock: Clock) -> None: ...
    def __call__(self, drop_off_id: DropOffId, version: int, staff: StaffMember) -> DropOff: ...
```

- `PreviewRejection`: applies `reject` to the stored drop-off without saving (so every
  refusal shows before sending), then composes the rejected email with the current
  studio. `image_src` lets the console point the preview's images at its own photo
  addresses; the email that is sent uses `cid:` references instead. The preview and
  the sent email come from the same template and the same settings, which is what "see
  the email exactly as it will go out" needs; if staff change a setting between preview
  and send, the email uses the new one (#6: every email after a change uses it).
- `RejectDropOff`: `NotFound`; `Conflict` when `version` isn't the stored one (someone
  else changed it: the page says to reload); `reject(...)`; commit
  `Update(drop_off)` and `Put(new_email(id, REJECTED, now, occasion=rejection.at.isoformat()))`.
  The drop-off leaves the waiting list and can't join a load, because its state is
  `REJECTED` (the domain refuses it in `add_to_load`). Logs `event=drop_off_rejected`,
  `drop_off_id`, `user`, `reason` (the reason's item ID).
- `UndoRejection`: `undo_rejection(...)`; if the rejection's email is still `PENDING`,
  `mark_cancelled` it in the same commit (an email already sent can't be unsent; staff
  contact the person, #5). Sends nothing. Logs `event=rejection_undone`, `drop_off_id`,
  `user`.

### app: the composer (`mail/compose.py`)

```python
@dataclass(frozen=True, slots=True)
class ComposedEmail:
    subject: str
    html: str
    text: str


class Composer:
    def __init__(self) -> None:
        ...  # Environment(PackageLoader("asmbly_ceramics.mail"), autoescape=select_autoescape(["html"]),
        #             undefined=StrictUndefined); .txt templates render with autoescape off

    def received(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...
    def ready(
        self, drop_off: DropOff, studio: Studio, sent_at: datetime, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...
    def rejected(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...
    def test(self, studio: Studio) -> ComposedEmail: ...  # phase 3's test email


def outgoing(
    composed: ComposedEmail, *, to: str, sending_address: str, photos: Sequence[tuple[PhotoRef, bytes]]
) -> OutgoingEmail:
    ...
    # from_name "Asmbly Ceramics", reply_to = sending_address, inline images "photo-<index>" / "AC-12-<index>.jpg"


def cid(ref: PhotoRef) -> str: ...  # "cid:photo-<index>"
```

Content, following the design's email board and epic #1's **Decided** list (the Kiln
Ops templates, with the ID, the reason and the staff message added):

| Email | Subject | Body |
| --- | --- | --- |
| received | `We received your drop-off (AC-12)` | "Hi {name}, thanks for dropping off. Here's your ID:", the ID large, "Make sure each piece has a slip with this ID and your name.", pieces, firing (and glaze type), dropped off (Austin time, "Fri Nov 13, 10:42 AM"), the photos, "We'll email you again when it's fired and ready for pickup." |
| ready | `Ready for pickup (AC-12)` | "Your pieces from drop-off AC-12 have exited the kiln and are ready for pickup!", "Pick up by {sent_at + window, Austin date}. You have {window} days to collect them; after that, they may be subject to disposal.", "Pickup hours" and the hours text, "If you have any questions, reach out to our Kiln Ops team at {sending address}.", "~ Kiln Ops", the photos |
| rejected | `Your drop-off needs attention (AC-12)` | "One or more of your pieces from drop-off AC-12 has been rejected from kiln firing due to:", the reason, the staff message under "From Kiln Ops" when there is one, "Please make adjustments and resubmit for firing with the drop-off form; you'll get a new ID. If you have questions, please reach out to the kiln lead at {sending address}.", the pickup hours, "~ Kiln Ops", the photos |

- Every email's footer: "Asmbly Makerspace · 9701 Dessau Rd, Suite 304, Austin, TX
  78754. Reply to this email to reach ceramics staff."
- The subject holds the ID only, never a name, so nothing a person typed reaches a
  header.
- Everything typed (the name, the message, the hours text, item names) is escaped in
  the HTML by autoescape; the hours text and the message keep their line breaks
  (escaped first, then each line a paragraph). No link is built from typed text. No
  link to a kiln schedule (#9 is out of scope).
- The plain-text part says the same, without photos.
- The HTML uses inline styles only (email clients drop `<style>`) in the design's
  colours, and `<img src="{{ image_src(ref) }}" alt="Photo {n} of AC-12">`.
- The Asmbly logo is text in the band, not an image, in this phase; phase 6 may replace
  `_layout.html`'s band with the shared brand partial (the README's parallelism table).

## Tests

- `test_studio_choices_list_only_active_items`; `test_received_view_has_no_contact_fields`
  (the dataclass's fields are exactly the ones above); `test_received_summary_of_an_unknown_id_raises_not_found`.

`tests/use_cases/` (against the fakes, asserting on what was stored and sent, not only
on return values):

- `test_submit_stores_the_drop_off_its_received_email_and_the_submission_together`: one
  commit with three `Put`s; the drop-off is `WAITING` with photo refs 1..n.
- `test_submit_issues_increasing_ids` and `test_two_submissions_in_a_row_get_their_own_ids` (#2).
- `test_the_same_token_twice_returns_the_same_id_and_stores_nothing_more`.
- `test_a_race_on_the_same_token_returns_the_first_and_deletes_the_kept_photos` (the
  fake's `fail_next_commit_with=Conflict()` and a submission written in between).
- `test_each_bad_field_is_refused_and_nothing_is_stored` (parametrized over phase 1's
  keys; no commit, no ID, no kept photo).
- `test_a_photo_that_isnt_an_image_is_refused_next_to_it` (`photo.2: photo.not_image`),
  `test_a_photo_over_10_mb_is_refused` (`photo.too_large`), `test_a_missing_upload_is_refused`.
- `test_field_and_photo_errors_are_reported_together`.
- `test_an_expired_or_missing_token_is_refused`.
- `test_the_eleventh_submission_from_a_device_in_10_minutes_is_refused` and
  `test_it_is_allowed_again_after_10_minutes` (`FixedClock.advance`) (#2).
- `test_the_thirty_first_from_one_address_is_refused_across_devices`.
- `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter`.
- `test_upload_slots_count_must_be_1_to_6` and `test_upload_slot_requests_are_limited`.
- `test_the_studio_is_seeded_once_with_the_starting_values` and
  `test_a_seeding_race_reads_the_winner`.
- `test_waiting_is_oldest_first_with_bisque_and_glaze_totals_in_pieces` (#3).
- `test_the_filter_narrows_rows_not_totals`; `test_overdue_rows_are_marked`.
- `test_find_by_every_id_form` (`AC-12`, `ac12`, `12`) and `test_find_by_part_of_a_name` (#3).
- `test_find_by_number_finds_a_closed_drop_off`; `test_find_returns_at_most_50`.
- `test_view_drop_off_lists_its_emails_and_those_needing_attention`; `test_view_unknown_id_is_not_found`.
- `test_preview_shows_the_email_with_reason_and_message_and_saves_nothing` (#5).
- `test_preview_refuses_other_without_a_message` and `..._over_1000_characters`.
- `test_reject_stores_the_rejection_and_queues_one_email` (#5).
- `test_a_rejected_drop_off_leaves_the_waiting_list`.
- `test_reject_with_a_stale_version_is_a_conflict_and_stores_nothing`.
- `test_undo_the_same_day_returns_it_to_waiting_and_sends_nothing` (#5).
- `test_undo_cancels_the_rejection_email_if_still_pending`.
- `test_undo_the_next_day_is_refused`.
- `test_unknown_log_field_raises`.
- `test_nothing_logged_holds_personal_details`: runs submit (accepted and refused),
  find by name, preview, reject and undo with made-up details built in code (a name
  like "Test Person", an address built from parts on `example.org`, a phone built from
  digits), captures every log record with `caplog`, and asserts that none of the
  name, address, phone, message or token appears in any record's message or extra
  fields.

`tests/mail/test_compose.py`:

- `test_each_email_has_its_subject_with_the_id`.
- `test_markup_in_the_name_message_and_hours_is_escaped` (`<script>` and `<img onerror>`
  come out as text).
- `test_the_text_part_has_no_markup`.
- `test_inline_images_match_the_cid_references`.
- `test_ready_gives_the_pickup_date_from_when_it_is_sent` (the window from the studio,
  Austin date).
- `test_rejected_includes_the_reason_and_the_message_and_omits_an_empty_message`.
- `test_there_is_no_link_to_a_kiln_schedule`.
- `test_from_name_and_reply_to_are_set_by_outgoing`.
- `test_the_templates_ship_with_the_package` (loads each template through the package
  loader).

## Acceptance criteria

1. `SubmitDropOff` with valid details and 1 to 6 accepted photos commits the drop-off,
   its received email and its submission in one commit and returns `AC-n` with n one
   more than the last issued (#2).
2. Any refused field or photo raises one `InvalidDetails` naming every bad field and
   photo, and nothing is committed, kept or numbered (#2).
3. The same submission token twice returns the same drop-off and commits nothing more.
4. The 11th submission from one device within 10 minutes raises `TooManySubmissions`
   (#2).
5. No raw device cookie, address or token is passed to `Records`, `RateLimiter` or a
   log.
6. `WaitingList` returns waiting drop-offs oldest first, with bisque and glaze totals in
   pieces (#3); `FindDropOffs` finds by `AC-12`, `ac12`, `12` and part of a name (#3).
7. `PreviewRejection` returns the email as the template renders it and stores nothing;
   `RejectDropOff` stores the rejection and queues exactly one rejected email (#5).
8. `UndoRejection` the same Austin day returns the drop-off to waiting and queues
   nothing; the next day it is refused (#5).
9. Every composed email escapes what people typed, names the ID in its subject, and
   says nothing of a kiln schedule.
10. No log record from these use cases holds a name, email, phone, message or token.

## Verification

```bash
uv run pytest tests/use_cases tests/mail
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

- `log_event` and `LOG_FIELDS`: the only logging use cases do, with the field names
  phase 7's metric filters match.
- `KeyHasher` and the `hash-key` secret; `CurrentStudio` and the seeding from the
  initial sending address.
- `ViewStudioChoices` (`StudioChoices`), `ReceivedSummary` (`ReceivedView`),
  `RequestUploadSlots`, `SubmitDropOff` (`SubmitRequest`, `Submitted`), `WaitingList`,
  `FindDropOffs`, `ViewDropOff`, `PreviewRejection`, `RejectDropOff`, `UndoRejection`,
  with the errors each raises.
- `Composer` (`received`, `ready`, `rejected`, `test`), `outgoing` and `cid`: phase 3's
  mailer composes with them; the console's preview passes its own `image_src`.
