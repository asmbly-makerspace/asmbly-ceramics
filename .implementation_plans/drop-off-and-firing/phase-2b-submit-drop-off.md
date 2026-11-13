---
phase_id: 2b
title: "Use cases: submit a drop-off"
epic: 1
implements: [2]
depends_on: [2a]
domain: [app]
estimated_size: L
---

# Phase 2b: Use cases: submit a drop-off

> **Status:** [ ] Pending

Part of phase 2, split into 2a to 2d by `/prep` (see
[phase 2a](phase-2a-logging-studio-and-form-reads.md)). The logging rules, `KeyHasher`,
`CurrentStudio`, `received_view` and the `world` fixture from 2a apply here unchanged.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): "Treat everything the public form sends as hostile",
  "Keep photos private", the logging rules.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md):
  photos re-encoded on submit, the rate limit under a keyed hash, the outbox.
- [Phase 2a](phase-2a-logging-studio-and-form-reads.md) and
  [phase 1d](phase-1d-ports-and-fakes.md) (the `PhotoStore` contract: `keep` all or
  nothing, `discard_uploads`, `delete_drop_off` after a failed commit), and
  [phase 1b](phase-1b-drop-offs-photos-outbox.md) (`DropOffDetails.create`, its message
  keys, `new_drop_off`, `new_email`, `is_slot_id`).
- Story #2 (the form's criteria) and epic #1's **Decided** list (a rejected piece
  resubmitted gets a new ID).

## Goal

`SubmitDropOff` exists and is tested against phase 1's fakes: the token checked and a
repeated submit answered with the same ID, the rate limit, every field and photo
checked with every problem reported at once, the ID issued, the photos kept, the
drop-off, its received email and its submission stored together, the kept photos
deleted when that commit fails, and the raw uploads used up once it lands.

## Files to create

| Path | What |
| --- | --- |
| `src/asmbly_ceramics/use_cases/submit.py` | `SubmitRequest`, `Submitted`, `SubmitDropOff` |
| `tests/use_cases/test_submit.py` | The use case |

## Files to modify

- `tests/use_cases/conftest.py`: build `SubmitDropOff` in the `world` fixture, and a
  helper that uploads made-up photo bytes into fresh slots through
  `MemoryPhotoStore.put_upload`.

No dependency changes.

## Implementation details

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
    view: ReceivedView  # from the Submission item: no contact details
    token_hash: str  # what the web layer signs into __Host-received
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

`SubmitRequest`'s `name`, `email`, `phone`, `submission_token`, `device` and
`source_address` are `field(repr=False)`, so a traceback or a log of the request shows
none of them.

In order:

1. **The token.** It and the device value must each pass 2a's `is_form_token` (22 to
   64 of `[A-Za-z0-9_-]`; the form puts a fresh token in each page it serves and sets
   the device cookie); otherwise `InvalidDetails({"form": "form.expired"})`, before
   anything is counted, so cookieless callers never share one `device#` bucket. Hash it; if `records.submission(hash)`
   exists and hasn't expired, return `Submitted(received_view(it), hash,
   repeated=True)`, read from the submission item alone: a refresh or a double tap
   makes no second drop-off and counts nothing.
2. **The rate limit** (#2). `limiter.hit(hasher.device(...), DEVICE_LIMIT, now)`, then,
   only when the device is allowed, `limiter.hit(hasher.address(...), ADDRESS_LIMIT,
   now)`; either false raises `TooManySubmissions`. Every attempt that reaches this step
   counts against its device, refused or not; a device already over its limit isn't
   counted against the address, so one phone retrying can't fill the bucket the
   studio's wifi shares (2a's order for upload slots, decided in 2a's review). `RecordsUnavailable` goes up: the limit fails closed.
3. **The fields.** First the slots, before any photo read: each slot ID must pass
   `domain.photos.is_slot_id` (exactly 22 of `[A-Za-z0-9_-]`, the one shape
   `upload_slots` gives and the photo stores check) and there must be at most
   `PHOTOS_MAX` distinct ones; otherwise `InvalidDetails({"photos": "photos.count"})` at
   once, reading nothing. Then `DropOffDetails.create(..., photo_count=len(distinct
   slots), studio=self._studio())`, whose photo-count check is
   `domain.photos.is_photo_count` with the key `PHOTO_COUNT_KEY` (`photos.count`), the
   one check `RequestUploadSlots` uses too (2a's review): 2b writes no 1-to-6 check of
   its own, and uses `PHOTO_COUNT_KEY` for the at-most-`PHOTOS_MAX` slots refusal. A
   duplicated slot ID counts once; the distinct slots keep their first order.
4. **The photos.** For each distinct slot, in order (`<n>` from 1), `photos.read_upload(slot)`
   then `inspector.inspect(data)`. `UploadMissing` gives `photo.<n>: photo.missing`;
   `PhotoRefused(kind)` gives `photo.<n>: photo.<kind>` (`not_image`, `too_large`,
   `too_many_pixels`). Steps 3 and 4 both run (unless step 3 refused the slots), so the
   page shows every problem at once, then raise one `InvalidDetails`. Before raising
   one with a `photo.missing`, read `records.submission(hash)` again: a double tap's
   other request may have committed and used the uploads up meanwhile, and then this
   one returns that submission with `repeated=True` instead (prep). Nothing is
   stored: refused uploads stay under `uploads/` and expire with the bucket's lifecycle
   rule. Each upload's bytes are dropped once inspected (up to 6 × 10 MB; phase 7 sizes
   the form function's memory for one 10 MB decode).
5. **The ID.** `ids.next_drop_off_id()`.
6. **Keep the photos.** `photos.keep(id, checked)` returns the refs. `keep` never
   overwrites (phase 1d): `PhotosAlreadyKept` means photos are already under that
   number (a counter that went backwards), so take `ids.next_drop_off_id()` once more
   and keep again, at most 3 tries in all, then raise the last `PhotosAlreadyKept`.
7. **Commit** `Put(new_drop_off(...))`, `Put(new_email(id, EmailKind.RECEIVED, now))`
   and `Put(Submission(hash, id, pieces, firing type name, glaze type name, now, now +
   SUBMISSION_LIFETIME))` together, and return `Submitted(received_view(submission),
   hash, repeated=False)`. **On any commit failure**, the kept photos have no record and
   the close (#7) would never delete them, so `photos.delete_drop_off(id)` comes first
   (the number is skipped, which the ID contract allows), then:
   - `Conflict` and `records.submission(hash)` now exists (the same token committed in a
     race): return the stored submission's view with `repeated=True`, and go on to
     step 8;
   - `Conflict` with no stored submission (the drop-off's key was taken: a counter that
     went backwards), take the next ID and go back to step 6, within the same 3 tries;
   - `RecordsUnavailable`, or any other exception: re-raise it after the delete (the
     page says "try again"; the uploads are untouched, so the same submit can be sent
     again).
   If `delete_drop_off` itself raises, log `event=photos_not_deleted` with
   `drop_off_id` and `error_code` and re-raise the commit's error: the photos are left
   to the cleanup backstop phases 4 and 7 add (phase 1d's hand-off). `keep` itself is
   all or nothing (phase 1d), so a `keep` that raised needs no cleanup here.
8. **Use the uploads up.** Once the commit has succeeded, or the race above found the
   stored submission, `photos.discard_uploads(distinct slots)` (phase 1d): the raw
   uploads, EXIF included, are deleted at once instead of waiting a day for the
   lifecycle rule, and a slot can never make a second drop-off. It runs only after a
   commit, so a refused or failed submit can be sent again with the same uploads. If
   it raises `PhotosUnavailable`, the drop-off stands: log `event=uploads_not_discarded`
   with `drop_off_id` and `error_code`, and return as usual. The lifecycle rule removes
   the uploads within a day; until then a second submit from them would read them
   again (a narrow case, accepted).

Logs: `event=drop_off_submitted`, `drop_off_id`, `count` (photos); on refusal
`event=drop_off_refused`, `reason` (`invalid_details`, `device_limit`, `address_limit`, `form_expired`: the
same words 2a's `upload_slots_refused` logs for the two limits),
`fields` (the refused field names, sorted, comma-joined). Never a value.

## Tests

`tests/use_cases/test_submit.py` (against the fakes, asserting on what was stored and
sent, not only on return values):

- `test_submit_stores_the_drop_off_its_received_email_and_the_submission_together`: one
  commit with three `Put`s; the drop-off is `WAITING` with photo refs 1..n.
- `test_submit_issues_increasing_ids` and `test_two_submissions_in_a_row_get_their_own_ids` (#2).
- `test_the_same_token_twice_returns_the_same_id_and_stores_nothing_more` (no second
  commit, no second limiter hit).
- `test_a_race_on_the_same_token_returns_the_first_and_deletes_the_kept_photos` (the
  fake's `fail_next_commit_with=Conflict()` and a submission written in between).
- `test_a_taken_drop_off_key_takes_the_next_number` (`Conflict` with no submission).
- `test_a_failed_commit_deletes_the_kept_photos_and_raises` (parametrized over
  `RecordsUnavailable("InternalServerError")` and a `RuntimeError`, through
  `fail_next_commit_with`: the error is raised, `kept_count(id)` is 0, and the uploads
  are not discarded) and `test_a_failed_cleanup_logs_and_raises_the_commit_error`.
- `test_submit_discards_the_uploads_once_committed` (the fake's `upload_count()` is 0
  and `read_upload` of each slot raises `UploadMissing`) and
  `test_a_slot_cannot_make_a_second_drop_off` (a new token with the same slots gets
  `photo.<n>: photo.missing`).
- `test_a_refused_submit_keeps_the_uploads_for_a_retry` (nothing discarded) and
  `test_a_failed_discard_still_returns_the_drop_off`.
- `test_photos_already_kept_takes_the_next_number` and
  `test_photos_already_kept_three_times_raises`.
- `test_each_bad_field_is_refused_and_nothing_is_stored` (parametrized over phase 1b's
  keys; no commit, no ID, no kept photo).
- `test_a_photo_that_isnt_an_image_is_refused_next_to_it` (`photo.2: photo.not_image`),
  `test_a_photo_over_10_mb_is_refused` (`photo.too_large`),
  `test_a_photo_with_too_many_pixels_is_refused` (`photo.too_many_pixels`),
  `test_a_missing_upload_is_refused`.
- `test_field_and_photo_errors_are_reported_together`.
- `test_an_expired_or_missing_token_is_refused` (21 and 65 characters, a `/`, empty).
- `test_the_eleventh_submission_from_a_device_in_10_minutes_is_refused` and
  `test_it_is_allowed_again_after_10_minutes` (`FixedClock.advance`) (#2).
- `test_the_thirty_first_from_one_address_is_refused_across_devices`.
- `test_submit_fails_closed_when_the_limiter_is_unavailable`.
- `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter` (the fake
  limiter's `keys_hit` holds only `device#`/`address#` hashes; no stored item holds the
  raw token, cookie or address).
- `test_a_malformed_or_seventh_slot_is_refused_before_any_read` (a slot ID of 21 or 23
  characters, or with `/` or `.`, fails `is_slot_id`; the fake photo store's
  `read_uploads` is empty).
- `test_a_duplicated_slot_counts_once`.
- `test_a_double_tap_that_lost_the_uploads_returns_the_winner` (the submission written
  between the photo reads, through a fake photo store wrapper).
- `test_a_missing_or_malformed_device_is_refused_before_counting`.
- `test_the_request_repr_holds_no_personal_detail`.
- `test_nothing_logged_by_submit_holds_personal_details`: runs submit accepted, refused
  for a field, refused by the limit, and failed at commit, with made-up details built in
  code (`tests/domain/builders.py`'s `TEST_NAME`, `TEST_EMAIL`, `TEST_PHONE`), captures
  every log record with `caplog`, and asserts that none of the name, address, phone,
  token, cookie or source address appears in any record's message or extra fields.

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
6. A commit that fails after the photos are kept deletes them before the error goes
   up; a committed drop-off uses its uploads up.
7. No log record from `SubmitDropOff` holds a name, email, phone or token.

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

- `SubmitDropOff` (`SubmitRequest`, `Submitted`), with the errors it raises:
  `InvalidDetails` (field keys, `photo.<n>` keys, `form.expired`),
  `TooManySubmissions`, `RecordsUnavailable`, `IdsUnavailable`, `PhotosUnavailable`,
  `PhotosAlreadyKept` (after 3 tries), `SecretsUnavailable`.
- The `world` fixture builds it, with a helper to upload made-up photos.
- For phase 6: when `Submitted.repeated` is true, the page says the drop-off was
  already received as `AC-n` (a restored form sent again gets the first ID, not a new
  drop-off); the device cookie and the token both have `is_form_token`'s shape.
