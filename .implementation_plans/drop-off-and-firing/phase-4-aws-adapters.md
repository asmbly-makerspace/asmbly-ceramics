---
phase_id: 4
title: The AWS adapters
epic: 1
implements: [2]
depends_on: [1]
domain: [app]
estimated_size: L
---

# Phase 4: The AWS adapters

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the rules on logging, personal details, photos and
  email.
- [The plan's README](README.md): the domain model, the ports table, and the Security
  section.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): the
  data store, photos, email and sign-in choices this phase implements.
- [Phase 1](phase-1-domain-model.md): the ports (`src/asmbly_ceramics/ports/`) and their
  contracts, and the in-memory fakes whose behavior each adapter must match.
- The closest existing code: AsmblyMCPs' `src/mcp_core/auth.py` (PyJWT with a JWKS
  client, keys cached, RS256 pinned, a 503 when keys can't be fetched),
  `src/mcp_core/secrets.py` (SSM with a 5-minute cache) and
  `src/servers/ceramics/mail.py` (SES v2 `send_email`, errors by code, `from None`). The
  facilities repository's `common/aws.py` (`_error_summary`: class name and AWS error
  code only) and `class_photo_upload_api/lambda_function.py` (`aud` checked with
  `hmac.compare_digest`).
- AWS's documentation, read for this plan on 13 November 2026 (all under
  `https://docs.aws.amazon.com`):
  - DynamoDB: "UpdateItem" `/amazondynamodb/latest/APIReference/API_UpdateItem.html`
    (`ADD`, `UPDATED_NEW`); "Working with items and attributes"
    `/amazondynamodb/latest/developerguide/WorkingWithItems.html` (an atomic counter
    isn't idempotent); "DynamoDB condition expression CLI example"
    `/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html`
    (`attribute_not_exists`); "TransactWriteItems"
    `/amazondynamodb/latest/APIReference/API_TransactWriteItems.html` (100 actions,
    4 MB, no two actions on one item, `CancellationReasons` in request order,
    `ClientRequestToken` for 10 minutes); "Using time to live (TTL)"
    `/amazondynamodb/latest/developerguide/TTL.html` and "Working with expired items"
    `/amazondynamodb/latest/developerguide/ttl-expired-items.html` (deleted "typically
    within a few days"; readers must filter); "DynamoDB read consistency"
    `/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html` (GSI reads
    are eventually consistent).
  - Lambda and the stream: "Using event filtering with a DynamoDB event source"
    `/lambda/latest/dg/with-ddb-filtering.html` ("DynamoDB event source mappings only
    support filtering on the dynamodb key", so not on `eventName`).
  - S3: "POST Policy" `/AmazonS3/latest/developerguide/sigv4-HTTPPOSTConstructPolicy.html`;
    "Creating an HTML Form (Using AWS Signature Version 4)"
    `/AmazonS3/latest/developerguide/sigv4-HTTPPOSTForms.html` (`success_action_status`,
    `x-amz-security-token`); "Download and upload objects with presigned URLs"
    `/AmazonS3/latest/userguide/using-presigned-url.html` (a link signed with role
    credentials expires with the role session); boto3's `generate_presigned_post`
    `/boto3/latest/reference/services/s3/client/generate_presigned_post.html`.
  - SES v2: "SendEmail" `/ses/latest/APIReference-V2/API_SendEmail.html` (its errors);
    "Attachment" `/ses/latest/APIReference-V2/API_Attachment.html` (`INLINE`,
    `ContentId`, `FileName` required); "Service quotas in Amazon SES"
    `/ses/latest/dg/quotas.html` (40 MB per message through the v2 API, after base64);
    "Errors related to the sending quotas" `/ses/latest/dg/manage-sending-quotas-errors.html`
    (`ThrottlingException`).
  - Cognito: "The redirect and authorization endpoint"
    `/cognito/latest/developerguide/authorization-endpoint.html`; "The token endpoint"
    `/cognito/latest/developerguide/token-endpoint.html`; "The managed login sign-out
    endpoint: /logout" `/cognito/latest/developerguide/logout-endpoint.html`;
    "Verifying JSON web tokens"
    `/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html`
    (`aud` on an ID token, `token_use`); "Adding groups to a user pool"
    `/cognito/latest/developerguide/cognito-user-pools-user-groups.html`
    (`cognito:groups` in the ID token); "Understanding the identity (ID) token"
    `/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html`
    (`cognito:username`).
  - Pillow, from its source on GitHub (its documentation host didn't load):
    `src/PIL/Image.py` (`MAX_IMAGE_PIXELS`, `DecompressionBombWarning` above it,
    `DecompressionBombError` above twice it; `Image.open(fp, formats=...)`),
    `src/PIL/ImageOps.py` (`exif_transpose`), and the JPEG writer (EXIF is written only
    when `exif=` is passed to `save`). Pillow 13.0.0 has cp314 manylinux wheels for
    aarch64 and x86_64 (PyPI).

## Goal

Every port phase 1 defines has an adapter the deployed app will use: DynamoDB for
records, ID numbers and the rate limit; S3 for photos; Pillow for checking and
re-encoding photos; SES v2 for email; PyJWT and the staff pool's token endpoint for
sign-in; SSM Parameter Store for secrets; the system clock. Each adapter behaves as its
port's contract says, including its failures, and is tested against `botocore`'s
`Stubber` (or, for PyJWT and the token endpoint, a stubbed key set and transport), with
no network and no AWS. Nothing logged or raised holds a person's details, a token or
AWS's error message. Nothing is wired into a running app yet: phase 7's composition
root does that.

## Files to create

- `src/asmbly_ceramics/adapters/aws/__init__.py`
- `src/asmbly_ceramics/adapters/aws/errors.py`: `aws_error_code(exc) -> str` and
  `log_aws_error(logger, operation, exc)`, the only way any adapter reports an AWS
  failure.
- `src/asmbly_ceramics/adapters/aws/keys.py`: the table's key design (one function per
  item kind) and the item ↔ domain conversions.
- `src/asmbly_ceramics/adapters/aws/records.py`: `DynamoDbRecords` (`Records`).
- `src/asmbly_ceramics/adapters/aws/ids.py`: `DynamoDbIdNumbers` (`IdNumbers`).
- `src/asmbly_ceramics/adapters/aws/rate_limit.py`: `DynamoDbRateLimiter`
  (`RateLimiter`).
- `src/asmbly_ceramics/adapters/aws/photos.py`: `S3PhotoStore` (`PhotoStore`).
- `src/asmbly_ceramics/adapters/aws/mailer.py`: `SesMailer` (`Mailer`).
- `src/asmbly_ceramics/adapters/aws/staff_tokens.py`: `CognitoStaffTokens`
  (`StaffTokens`).
- `src/asmbly_ceramics/adapters/aws/secrets.py`: `SsmSecrets` (`Secrets`).
- `src/asmbly_ceramics/adapters/images.py`: `PillowPhotoInspector` (`PhotoInspector`).
- `src/asmbly_ceramics/adapters/clock.py`: `SystemClock` (`Clock`).
- `tests/adapters/__init__.py`, `tests/adapters/aws/__init__.py`
- `tests/adapters/aws/conftest.py`: `stubbed(client)` fixture; a `caplog`-based
  `assert_no_personal_details(records)` helper (shared with phase 1's
  `tests/personal_data.py` if phase 1 created one: reuse it, don't copy it).
- `tests/adapters/aws/test_keys.py`, `test_records.py`, `test_ids.py`,
  `test_rate_limit.py`, `test_photos.py`, `test_mailer.py`, `test_staff_tokens.py`,
  `test_secrets.py`
- `tests/adapters/test_images.py`, `tests/adapters/test_clock.py`
- `tests/adapters/contract/`: one module per port that runs the same contract tests
  against the in-memory fake and against the AWS adapter on its stub (see Tests).

## Files to modify

- `pyproject.toml` and `uv.lock`, through uv only:
  `uv add boto3 pillow "pyjwt[crypto]"` and
  `uv add --dev "boto3-stubs[dynamodb,s3,sesv2,ssm]"`. No hand edits to `uv.lock`.
- `pyproject.toml` `[tool.mypy]`: nothing new is expected (Pillow and PyJWT ship
  types; boto3 is typed through the stubs). If mypy needs an override for a
  third-party module, it is per module and says why.

## Implementation details

### app: shared rules for every adapter

- **Boundaries.** Only modules under `adapters/` import `boto3`, `botocore`, `PIL` or
  `jwt`. A test (`test_only_adapters_import_aws_libraries`, phase 1's import check
  extended) walks `src/asmbly_ceramics/` and fails if `domain/`, `ports/`,
  `use_cases/`, `mail/` or `web/` imports any of them.
- **Clients are passed in.** Each adapter takes its boto3 client in its constructor
  (`DynamoDbRecords(client: DynamoDBClient, table: str)`), so tests pass a stubbed
  client and phase 7 passes real ones. Nothing creates a client at import.
- **Errors.** Every `botocore.exceptions.ClientError` is turned into the port's own
  error with `raise PortError(...) from None`, after
  `log_aws_error(logger, "<operation>", exc)` logs one line with the operation and
  `exc.response["Error"]["Code"]`, never `str(exc)` or the message (AWS's text can
  quote what was sent). `BotoCoreError` (a network failure) logs its class name only.
- **What is logged.** Drop-off IDs, load IDs, email kinds, counts, error codes. Never a
  name, an email address, a phone number, a rejection message, a photo's bytes, an
  object key's random part, a token, a code verifier, or a hashed rate-limit key.

### app: the table's key design (`adapters/aws/keys.py`)

One table, `asmbly-ceramics-<env>-records`, string keys `PK` and `SK`, two global
secondary indexes with string keys. Every item has `kind` and `version` (a number, 1 on
create, +1 on every update).

| Item | `PK` | `SK` | `GSI1PK` / `GSI1SK` | `GSI2PK` / `GSI2SK` | `ttl` |
| --- | --- | --- | --- | --- | --- |
| Drop-off | `DROPOFF#AC-12` | `META` | `DROPOFF#<state>` / `<created_at ISO>#AC-12` | — | — |
| Load | `LOAD#L-4` | `META` | `LOAD#<status>` / `<date>#L-4` | `LOADDATE` / `<date>#L-4` | — |
| Studio settings and lists | `STUDIO` | `CURRENT` | — | — | — |
| Settings history entry | `STUDIO` | `HISTORY#<at ISO>#<n>` | — | — | — |
| Email (outbox) | `EMAIL#AC-12` | `<kind>` or `rejected#<rejected_at ISO>` | — | `EMAIL#<status>` / `<created_at ISO>#AC-12#<kind>` | — |
| ID counters | `COUNTER#dropoff`, `COUNTER#load` | `META` | — | — | — |
| Rate-limit count | `RATE#<hmac hex>#<window start ISO>` | `META` | — | — | window end + 1 day |
| Submission token | `SUBMISSION#<token>` | `META` | — | — | created + 1 day |

- `<state>` and `<status>` are the domain enums' values (`waiting`, `in_load`, `fired`,
  `rejected`, `closed`; `loading`, `firing`, `fired`; `pending`, `sending`, `sent`,
  `failed`), so the waiting list is a `Query` on `GSI1PK = DROPOFF#waiting` in
  `GSI1SK` order (oldest first), the drop-offs to close are `DROPOFF#fired` and
  `DROPOFF#rejected`, and failed emails are `GSI2PK = EMAIL#failed`.
- Timestamps are ISO 8601 in UTC with a `Z`, so they sort as strings. Dates (a load's
  date) are `YYYY-MM-DD` in Austin time, as the domain gives them.
- A `SubmissionToken` item maps a form's one-time token to the drop-off it made
  (phase 2), so a refresh after Submit finds the same ID.
- Every item has a top-level `type` string: `drop_off`, `load`, `studio`, `history`,
  `email`, `counter`, `rate` or `submission`.
- The stream (phase 7 turns it on) uses `NEW_IMAGE`. An email item's `type` and `status`
  attributes are top-level strings, so phase 7's filter
  `{"dynamodb": {"NewImage": {"type": {"S": ["email"]}, "status": {"S": ["pending"]}}}}`
  matches both a new
  email and one set back to `pending` by "Try sending again". A filter on `eventName`
  isn't possible (with-ddb-filtering.html).
- Personal fields on a drop-off are top-level attributes `contact_name`,
  `contact_email`, `contact_phone`, and `rejection_message`, so closing removes them
  with one `REMOVE` and the item keeps the rest (#7).
- `keys.py` holds `to_item(entity) -> dict[str, AttributeValue]` and
  `from_item(item) -> entity` for each kind, using boto3's `TypeSerializer` and
  `TypeDeserializer`. Numbers come back as `Decimal`; the converters turn them into
  `int`.

### app: `DynamoDbRecords` (`Records`)

```python
class DynamoDbRecords:
    def __init__(self, client: DynamoDBClient, table: str, clock: Clock) -> None: ...
```

- **Reads by key** (`get_drop_off`, `get_load`, `get_studio`, `get_email`, and the
  submission token lookup) use `GetItem` with `ConsistentRead=True`, so a page read
  right after a change sees it.
- **List queries** (`waiting_drop_offs`, `drop_offs_to_close`, `loads_by_status`,
  `loads_between`, `failed_emails`, `emails_for(drop_off_id)`, `settings_history`,
  `drop_offs_created_between` for weekly counts) use `Query`, paginated with
  `LastEvaluatedKey` until done. Queries on `GSI1` and `GSI2` are eventually consistent.
  That is acceptable where it's used, and phase 2's and 3's use cases already re-check
  by key before they change anything:
  - the waiting list, the failed emails and the weekly counts may lag a change by
    under a second; the next page load shows it;
  - `AddToLoad`, `RejectDropOff` and `CloseFinished` read each drop-off by key
    (consistent) and commit with a version check, so a stale list can never cause a
    wrong change; it can only cause a `Conflict` the page reports ("AC-12 changed;
    reload").
  - `emails_for` and `settings_history` query the base table (`PK`), so they are
    consistent.
- **`commit(changes: Sequence[Change]) -> None`.** Phase 1 defines `Change` as a put of
  a new item or an update of an existing one with its expected version. The adapter
  sends one `TransactWriteItems`:
  - a new item → `Put` with `ConditionExpression="attribute_not_exists(PK)"`;
  - an existing item → `Put` of the whole new item with
    `ConditionExpression="version = :expected"` and `version` set to expected + 1;
  - a closing drop-off → `Update` with `REMOVE contact_name, contact_email,
    contact_phone, rejection_message` and the new state, under the same version
    condition (so a removed attribute isn't left behind by a whole-item put);
  - more than 100 changes, or two changes on the same key, raise `ValueError` before
    any call: the domain's limit of 48 drop-offs per load keeps a fire at 97 items at
    most, and a test pins that;
  - `ClientRequestToken` is a hash of the changes, so a retry by boto3 inside 10
    minutes is idempotent.
- **Errors.** `TransactionCanceledException` whose `CancellationReasons` hold
  `ConditionalCheckFailed` → `Conflict(ids)` naming the drop-off or load IDs whose
  condition failed (from the reasons' order, which matches the request's).
  `TransactionConflict` (another transaction in flight) → `Conflict` as well.
  `ProvisionedThroughputExceededException`, `ThrottlingException`,
  `InternalServerError`, and network errors → `RecordsUnavailable(code)`. Anything
  else → `RecordsUnavailable(code)` after logging the code.
- **Rights it needs** (phase 7): `dynamodb:GetItem`, `dynamodb:Query`,
  `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:ConditionCheckItem` (the
  transaction's actions are authorized per item action) on the table and on
  `table/<name>/index/*`. Phase 7 narrows the form's role to the keys it may write with
  `dynamodb:LeadingKeys`.

### app: `DynamoDbIdNumbers` (`IdNumbers`)

- `next_drop_off_id() -> DropOffId`: `UpdateItem` on `PK=COUNTER#dropoff, SK=META`,
  `UpdateExpression="ADD next_number :one"`, `ReturnValues="UPDATED_NEW"`; returns
  `DropOffId(n)`. The first call creates the item and returns 1 (`AC-1`).
- `next_load_id() -> LoadId`: the same on `COUNTER#load`.
- The counter is not idempotent (WorkingWithItems.html): if the call is retried after
  DynamoDB applied it, a number is skipped. That is acceptable: #2 says IDs are
  numbered upwards and never shared, not that there are no gaps. Uniqueness doesn't
  rest on the counter alone: the drop-off is then written with
  `attribute_not_exists(PK)` in `commit`, so even a counter reset can't overwrite a
  drop-off; it raises `Conflict`, and `SubmitDropOff` (phase 2) asks for the next
  number once more.
- Errors → `IdsUnavailable(code)`.
- Rights: `dynamodb:UpdateItem` on the table, keys `COUNTER#*`.

### app: `DynamoDbRateLimiter` (`RateLimiter`)

```python
def hit(self, key: RateKey, window: timedelta, limit: int) -> bool: ...
```

- `RateKey` (phase 1) is already the HMAC-SHA256 hex of the cookie or the address
  (the use case hashes with the key from `Secrets`); the adapter never sees the raw
  value.
- The window starts at `now` floored to the window's length (fixed windows of 10
  minutes). `UpdateItem` on `PK=RATE#<key>#<window start>`,
  `ADD hits :one SET #ttl = if_not_exists(#ttl, :expires)`, `ReturnValues=UPDATED_NEW`;
  returns `hits <= limit`. `:expires` is the window's end plus a day, as epoch seconds.
- A fixed window allows up to twice the limit across a window boundary; phase 1's
  `domain/limits.py` states the limit as "at most 10 in each 10-minute window", which
  #2's "more than 10 within 10 minutes are refused" is checked against in phase 2.
- Expired items still exist until TTL removes them; the key includes the window start,
  so an old item is never read again.
- Errors: the limiter fails open for a throttle or outage (`hit` returns `True` and
  logs the code at WARNING), because refusing every drop-off when DynamoDB hiccups is
  worse than letting a burst through; the decision is logged so phase 7's alarm on
  `level=ERROR` doesn't miss a long outage (it logs at ERROR after 3 consecutive
  failures in one container).
- Rights: `dynamodb:UpdateItem` on keys `RATE#*`.

### app: `S3PhotoStore` (`PhotoStore`)

```python
class S3PhotoStore:
    def __init__(self, client: S3Client, bucket: str, clock: Clock) -> None: ...
    def upload_slots(self, count: int) -> list[UploadSlot]: ...
    def read_upload(self, slot: UploadSlotId) -> bytes: ...
    def keep(self, drop_off: DropOffId, photos: Sequence[CheckedPhoto]) -> tuple[PhotoRef, ...]: ...
    def read(self, ref: PhotoRef, size: PhotoSize) -> bytes: ...
    def delete_drop_off(self, drop_off: DropOffId) -> None: ...
```

- **`upload_slots(count)`** (1 to 6, refused otherwise): for each slot, a random id
  (`secrets.token_urlsafe(16)`) and key `uploads/<id>/0`, and
  `generate_presigned_post(Bucket, Key=key, Fields={"success_action_status": "204"},
  Conditions=[{"key": key}, ["content-length-range", 1, 10485760],
  ["starts-with", "$Content-Type", "image/"], {"success_action_status": "204"}],
  ExpiresIn=900)`. Returns `UploadSlot(id, url, fields, expires_at)`. With the Lambda
  role's credentials the `fields` include `x-amz-security-token`, and the link stops
  working when the role session ends even if that is sooner than 15 minutes
  (using-presigned-url.html); the form (phase 6) asks for new slots if an upload is
  refused as expired. A field set in `Fields` needs its own condition, so
  `success_action_status` is in both (boto3 page).
- **What S3 answers to a file over 10 MB** is not stated on the POST pages (the error
  list has `EntityTooLarge`, 400, without tying it to `content-length-range`). The
  adapter doesn't depend on it: the form treats any non-2xx answer to an upload as
  "that photo couldn't be uploaded", and `read_upload` refuses anything over 10 MB
  again. Phase 7's verification records the real answer.
- **`read_upload(slot)`**: `GetObject` on `uploads/<id>/0` with
  `Range="bytes=0-10485760"` (10 MB + 1 byte). If `ContentLength` from the response's
  `ContentRange` total is over 10485760, raise `UploadMissing` (phase 1's contract: never more than `PHOTO_MAX_BYTES`); `NoSuchKey` →
  `UploadMissing(slot)` (never uploaded, or already used); other codes →
  `PhotosUnavailable(code)`. The `Content-Type` the browser sent is ignored: the
  inspector decides the type.
- **`keep(drop_off, photos)`**: for photo `k` (1 to 6), `PutObject` of the full JPEG to
  `dropoffs/AC-n/<k>.jpg` and the thumbnail to `dropoffs/AC-n/<k>-thumb.jpg`,
  `ContentType="image/jpeg"`, `IfNoneMatch="*"` so an existing photo is never
  overwritten. **To confirm in /prep** against S3's "conditional writes" page
  (`/AmazonS3/latest/userguide/conditional-writes.html`) that `If-None-Match: *` on
  `PutObject` is supported in us-east-2 and returns `PreconditionFailed` (412) when
  the key exists; if it isn't, drop the condition (the key holds a new, never-reused
  ID). Then `DeleteObject` on each upload. Returns the refs. A failure part-way
  deletes what it wrote under `dropoffs/AC-n/` and raises `PhotosUnavailable(code)`;
  `SubmitDropOff` then stores nothing (phase 2).
- **`read(ref, size)`**: `GetObject` on the full or thumbnail key; `NoSuchKey` →
  `UploadMissing` (phase 1's contract for a kept photo that is gone).
- **`delete_drop_off(id)`**: `ListObjectsV2` with `Prefix="dropoffs/AC-n/"`, then
  `DeleteObjects` in one call (at most 12 keys); a per-key error in the response's
  `Errors` → `PhotosUnavailable(code)` so `CloseFinished` retries tomorrow. Deleting
  what's already gone succeeds.
- Object keys never hold a name or anything typed; the upload id is random and not
  logged.
- Rights: `s3:PutObject` on `uploads/*` (signed into the POST: the role that signs
  must hold it), `s3:GetObject` and `s3:DeleteObject` on `uploads/*`, `s3:PutObject` on
  `dropoffs/*` (form); `s3:GetObject` on `dropoffs/*` (console, mailer);
  `s3:ListBucket` with `s3:prefix` `dropoffs/*` and `s3:DeleteObject` on `dropoffs/*`
  (close). Phase 7 splits them by role.

### app: `PillowPhotoInspector` (`PhotoInspector`)

```python
class PillowPhotoInspector:
    def inspect(self, data: bytes) -> CheckedPhoto: ...  # or raises PhotoRefused(kind)
```

- Over 10485760 bytes → `PhotoRefused("too_large")` before opening.
- `Image.open(BytesIO(data), formats=["JPEG", "PNG", "WEBP"])` inside
  `warnings.catch_warnings()` with `simplefilter("error", Image.DecompressionBombWarning)`,
  so an image over `MAX_IMAGE_PIXELS` (left at Pillow's default, about 89.5 million
  pixels) is refused, not just warned about. `UnidentifiedImageError` → if the bytes
  start like HEIF/HEIC (`ftypheic`, `ftypheix`, `ftypmif1` at offset 4) →
  `PhotoRefused("unsupported_type")`, else `PhotoRefused("not_an_image")`.
  `DecompressionBombWarning` or `DecompressionBombError` → `PhotoRefused("too_many_pixels")`.
- `image.verify()`, then open again (verify leaves the image unusable), `image.load()`
  (a truncated file raises here → `not_an_image`).
- `ImageOps.exif_transpose(image)` so the photo is upright, then `convert("RGB")`
  (drops alpha onto white for PNG and WebP).
- Full size: a copy resized with `thumbnail((2048, 2048), Image.Resampling.LANCZOS)`
  (only ever smaller), saved as JPEG, `quality=85`, `optimize=True`, no `exif=` and no
  `icc_profile=`, so EXIF (location included) and other metadata are not written.
  Thumbnail: the same at 320 px, `quality=80`.
- Returns `CheckedPhoto(full: bytes, thumbnail: bytes, width, height)`. The refusal
  kinds are phase 1's `PhotoRefusal` enum; their messages to the person are the
  domain's (phase 2 shows them next to the photo field).
- Pillow runs in the Lambda's memory; phase 7 sizes the form function for six 10 MB
  photos decoded one at a time (each is freed before the next).
- No rights.

### app: `SesMailer` (`Mailer`)

```python
class SesMailer:
    def __init__(self, client: SESV2Client, display_name: str = "Asmbly Ceramics") -> None: ...
    def send(self, message: OutgoingEmail) -> None: ...  # raises SendFailed(code)
```

- `OutgoingEmail` (phase 1) holds `sender` (the console's sending address, already
  checked to be at `asmbly.org` by the domain), `to` (one address), `subject`,
  `html`, `text`, and `inline_photos: tuple[InlinePhoto(content_id, filename, data), ...]`.
- The call: `send_email(FromEmailAddress=formataddr((display_name, sender)),
  Destination={"ToAddresses": [to]}, ReplyToAddresses=[sender],
  Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body":
  {"Html": {...}, "Text": {...}}, "Attachments": [{"FileName": "AC-12-1.jpg",
  "RawContent": data, "ContentDisposition": "INLINE", "ContentId": "ac-12-1",
  "ContentType": "image/jpeg", "ContentTransferEncoding": "BASE64"}, ...]}})`.
  `formataddr` from `email.utils` quotes the display name.
- Size: six re-encoded photos (each well under 1 MB at 2048 px, quality 85) plus the
  body stay far below SES's 40 MB per message through the v2 API (quotas.html). The
  adapter still refuses a message whose attachments total over 30 MB with
  `SendFailed("MessageTooLarge")` rather than sending it.
- Errors, by `Error.Code` (API_SendEmail.html and manage-sending-quotas-errors.html):
  `TooManyRequestsException`, `ThrottlingException`, `LimitExceededException`,
  `SendingPausedException`, `AccountSuspendedException`, `MessageRejected`,
  `MailFromDomainNotVerifiedException`, `NotFoundException`, `BadRequestException`,
  and any other code → `SendFailed(code)`. `SendFailed.retryable` is true for the two
  throttling codes and network errors, which the mailer (phase 3) leaves `pending` to
  try again; the rest mark the email `failed`.
- Never logged: the recipient, the subject, the body, the attachments, the message
  text of AWS's error. Logged: the drop-off ID and email kind (the caller passes them
  for logging as `log_context`), the code.
- Rights: `ses:SendEmail` on `arn:aws:ses:<region>:<account>:identity/asmbly.org`, with
  `ses:FromAddress` like `*@asmbly.org` (phase 5's boundary, phase 7's roles).

### app: `CognitoStaffTokens` (`StaffTokens`)

```python
class CognitoStaffTokens:
    def __init__(
        self,
        issuer: str,
        sign_in_url: str,
        client_id: str,
        jwks: PyJWKClient | None = None,
        transport: TokenTransport | None = None,
    ) -> None: ...
    def verify(self, id_token: str) -> StaffMember: ...
    def sign_in_url(self, state: str, code_challenge: str, redirect_uri: str) -> str: ...
    def sign_out_url(self, logout_uri: str) -> str: ...
    def exchange(self, code: str, code_verifier: str, redirect_uri: str) -> str: ...  # returns the ID token
```

- **Keys.** `PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_jwk_set=True,
  lifespan=3600, cache_keys=False, timeout=5)`, created once per container. A failure
  to fetch keys → `SignInUnavailable` (the web layer answers 503 "Sign-in isn't
  working right now", phase 8), never `NotSignedIn`.
- **`verify`.** `jwt.decode(token, key, algorithms=["RS256"], issuer=issuer,
  audience=client_id, options={"require": ["exp", "iss", "aud", "token_use"]},
  leeway=30)`; then `hmac.compare_digest(claims["aud"], client_id)` (PyJWT already
  checks `aud`; this is the facilities repository's belt and braces, kept because the
  comparison is the security boundary), `claims["token_use"] == "id"`. Any
  `jwt.PyJWTError` (bad signature, expired, wrong issuer or audience, missing claim) →
  `NotSignedIn(reason)` with a short fixed reason (`expired`, `invalid`). Then
  `"ceramics" in claims.get("cognito:groups", [])`, with a missing or non-list claim
  treated as no groups → `NotAllowed(username)`. `username = claims["cognito:username"]`;
  `email = claims["email"]` only when `claims.get("email_verified") is True`, else
  `None` (phase 3's test email then says the account has no verified address).
  Returns `StaffMember(username, email)`.
- **The group name** `ceramics` is the staff pool's group (asmbly-staff-login#4),
  a constant in `domain/staff.py` (phase 1), not a setting.
- **`sign_in_url`** builds `f"{sign_in_url}/oauth2/authorize?"` +
  `urlencode({"response_type": "code", "client_id": ..., "redirect_uri": ...,
  "scope": "openid", "state": ..., "code_challenge": ..., "code_challenge_method": "S256"})`
  (authorization-endpoint.html). `sign_in_url` is asmbly-staff-login's
  `/config/cognito/staff/sign-in-url` value, which includes `https://` and no path.
- **`sign_out_url`**: `f"{sign_in_url}/logout?"` + `urlencode({"client_id": ...,
  "logout_uri": ...})` (logout-endpoint.html).
- **`exchange`**: `POST f"{sign_in_url}/oauth2/token"` with
  `Content-Type: application/x-www-form-urlencoded` and body `grant_type=authorization_code`,
  `client_id`, `code`, `redirect_uri`, `code_verifier` (a public client: no secret,
  token-endpoint.html), through `urllib.request` with a 5-second timeout (no new HTTP
  dependency). The transport is a small `TokenTransport` protocol so tests stub it. A
  non-200 answer → `NotSignedIn`, logging the OAuth `error` field only
  (`invalid_grant`, …); the ID token is then `verify`'d before it is returned.
- Never logged: a token, a code, a verifier, the state, the email claim. Logged:
  the username on success, the fixed reason on failure.
- No AWS rights: the keys and the token endpoint are public HTTPS. The issuer, sign-in
  address and client ID come from `/config/cognito/staff/*` at deploy time (phase 7
  and 8).

### app: `SsmSecrets` (`Secrets`)

- `get(name) -> bytes`: `GetParameter(Name=f"/asmbly-ceramics/{env}/{name}",
  WithDecryption=True)`, base64-decoded, cached in the process for 5 minutes.
  `ParameterNotFound` → `SecretMissing(name)`, whose message names the parameter (not
  its value) so a missing by-hand step shows clearly in the logs; other codes →
  `SecretsUnavailable(code)`. The value is never logged.
- The names phase 7 uses: `hash-key` (the rate limit's HMAC key) and `session-key`
  (the console's session and CSRF signing key, phase 8).
- Rights: `ssm:GetParameter` on `parameter/asmbly-ceramics/<env>/*`, and `kms:Decrypt`
  through SSM (the AWS-managed key).

### app: `SystemClock` (`Clock`)

- `now() -> datetime`: `datetime.now(UTC)`. The domain converts to
  `America/Chicago` where a rule needs the Austin day. `tzdata` is added with
  `uv add tzdata` if phase 1 didn't add it (Lambda's image has no system zone data
  guaranteed for `zoneinfo`).

## Tests

No test opens a network connection; a `conftest.py` fixture sets
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` to dummy values and `AWS_DEFAULT_REGION`
to `us-east-2`, and builds each client with `botocore.stub.Stubber` active. Personal
details in tests are made up and built in code (`"Test " + "Person"`, an
`example.org` address assembled from parts), as the repository's personal-data test
requires.

**Contract tests** (`tests/adapters/contract/`), parametrized over the fake and the
adapter-on-stub, so the fake can't drift from the adapter:

- `test_records_commit_new_item_then_conflict_on_second_put`
- `test_records_update_with_stale_version_raises_conflict_naming_the_id`
- `test_records_waiting_list_is_oldest_first`
- `test_ids_never_repeat_and_start_at_one`
- `test_photo_store_keep_then_read_then_delete`
- `test_rate_limiter_allows_limit_then_refuses_in_the_same_window`
- `test_mailer_records_what_was_sent` (fake) / `..._sends_one_call` (adapter)

**Records and keys**

- `test_keys_round_trip_every_item_kind`: each entity → item → entity is equal.
- `test_drop_off_item_puts_personal_details_in_their_own_attributes`
- `test_email_item_status_is_a_top_level_string_for_the_stream_filter`
- `test_get_uses_consistent_reads`
- `test_commit_new_uses_attribute_not_exists`
- `test_commit_update_checks_and_bumps_version`
- `test_commit_close_removes_personal_attributes`
- `test_commit_refuses_more_than_100_changes_before_calling_aws`
- `test_commit_refuses_two_changes_on_one_key`
- `test_a_fire_of_48_drop_offs_fits_one_transaction` (97 items)
- `test_transaction_cancelled_maps_reasons_to_the_ids_that_conflicted`
- `test_throttling_becomes_records_unavailable_and_logs_the_code_only`
- `test_queries_follow_last_evaluated_key`

**IDs**

- `test_next_drop_off_id_adds_one_and_formats_ac_n`
- `test_next_load_id_uses_its_own_counter`
- `test_counter_failure_raises_ids_unavailable`

**Rate limit**

- `test_hit_counts_in_a_fixed_window_and_sets_ttl_once`
- `test_eleventh_hit_in_a_window_is_refused`
- `test_new_window_starts_counting_again`
- `test_outage_fails_open_and_logs_warning_then_error`

**Photos**

- `test_upload_slots_sign_exact_key_size_and_type_conditions`
- `test_upload_slots_refuses_zero_or_more_than_six`
- `test_read_upload_refuses_more_than_10_mb`
- `test_read_upload_missing_object_is_upload_missing`
- `test_keep_writes_full_and_thumbnail_with_if_none_match_then_deletes_uploads`
- `test_keep_failure_cleans_up_what_it_wrote`
- `test_delete_drop_off_lists_and_deletes_in_one_call`
- `test_delete_drop_off_with_nothing_left_succeeds`
- `test_no_object_key_or_upload_id_is_logged`

**Images** (images built in memory with Pillow; none committed)

- `test_jpeg_png_and_webp_are_accepted_and_returned_as_jpeg`
- `test_gps_exif_is_gone_after_inspection`: a JPEG made with a GPS IFD in its EXIF;
  the result's EXIF is empty.
- `test_rotated_photo_is_turned_upright` (EXIF orientation 6)
- `test_full_size_is_at_most_2048_and_thumbnail_320`
- `test_text_file_is_not_an_image`
- `test_heic_signature_is_unsupported_type`
- `test_gif_is_unsupported_type` (opened by Pillow only if allowed; `formats=` refuses)
- `test_truncated_jpeg_is_not_an_image`
- `test_decompression_bomb_is_refused` (a small PNG header claiming more pixels than
  `MAX_IMAGE_PIXELS`, or `MAX_IMAGE_PIXELS` lowered inside the test)
- `test_over_10_mb_is_refused_before_opening`

**Mailer**

- `test_send_builds_simple_content_with_inline_attachments`: one `send_email` call
  with `Html`, `Text`, `INLINE` attachments, `ContentId`s matching the HTML's `cid:`.
- `test_from_has_display_name_and_reply_to_is_the_sender`
- `test_each_ses_error_code_becomes_send_failed_with_that_code` (parametrized over the
  ten codes)
- `test_throttling_is_retryable_and_message_rejected_is_not`
- `test_oversized_message_is_refused_before_calling_ses`
- `test_nothing_logged_holds_the_address_subject_or_body`

**Staff tokens** (an RSA key generated in the test; the key set served by a stub
`PyJWKClient`)

- `test_valid_id_token_in_ceramics_returns_username_and_verified_email`
- `test_unverified_email_is_none`
- `test_expired_token_is_not_signed_in`
- `test_wrong_issuer_audience_or_signature_is_not_signed_in` (parametrized)
- `test_access_token_is_refused` (`token_use=access`)
- `test_hs256_token_is_refused` (algorithm confusion)
- `test_signed_in_without_ceramics_group_is_not_allowed`
- `test_missing_groups_claim_is_not_allowed`
- `test_keys_unavailable_is_sign_in_unavailable_not_not_signed_in`
- `test_sign_in_url_has_pkce_state_and_openid`
- `test_sign_out_url_has_client_and_logout_uri`
- `test_exchange_posts_code_and_verifier_and_verifies_the_result`
- `test_exchange_error_reports_only_the_oauth_error_code`
- `test_no_token_code_or_verifier_is_logged`

**Secrets and clock**

- `test_secret_is_read_with_decryption_and_cached`
- `test_missing_parameter_names_it_without_a_value`
- `test_clock_is_utc_aware`

**Across adapters**

- `test_only_adapters_import_aws_libraries`
- `test_adapters_never_log_an_aws_error_message`: each adapter is made to fail with a
  `ClientError` whose message holds a made-up email address; the captured logs and the
  raised error's text don't contain it.

## Acceptance criteria

1. `DynamoDbRecords.commit` of a drop-off whose `PK` exists raises `Conflict` naming
   the drop-off's ID and writes nothing (#2: no two drop-offs share an ID).
2. `DynamoDbIdNumbers.next_drop_off_id` returns `AC-1` on an empty table and a higher
   number on every later call (#2).
3. `S3PhotoStore.upload_slots` signs a POST whose policy allows exactly one key, 1 byte
   to 10485760 bytes, a `Content-Type` starting `image/`, for 900 seconds (#2: 10 MB).
4. `read_upload` refuses an object of 10485761 bytes with `UploadMissing` (#2).
5. `PillowPhotoInspector.inspect` refuses a text file as `not_an_image`, a HEIC file as
   `unsupported_type`, and returns a JPEG with no EXIF for a JPEG that had GPS data
   (#2; photos keep no location).
6. `SesMailer.send` sends one message from the given sender at `asmbly.org` with
   Reply-To set, the photos as `INLINE` attachments, and maps every SES error to
   `SendFailed(code)` without logging the recipient, subject or body (#2, #4).
7. `CognitoStaffTokens.verify` returns a `StaffMember` only for an RS256 ID token from
   the staff pool's issuer, for this app's client, unexpired, with `ceramics` in
   `cognito:groups`; raises `NotAllowed` for a valid token without the group and
   `NotSignedIn` for every other failure; raises `SignInUnavailable` when the keys
   can't be fetched.
8. No adapter logs or raises a person's name, email address or phone number, a token,
   or AWS's error message; each adapter's test proves it.
9. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
   `uv run pytest --cov` pass, with coverage at or above the floor.

## Verification

```bash
uv run pytest tests/adapters -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

Nothing to see in production: no adapter is wired into a running app until phase 7.
Phase 7's smoke test and its first drop-off exercise every adapter except
`CognitoStaffTokens` (phase 8).

## Rollout

Nothing reaches AWS.

## Admin actions

None.

## Hand-off

Phase 7 can rely on:

- Adapters, each taking a boto3 client (or, for tokens, plain values) in its
  constructor: `DynamoDbRecords(client, table, clock)`,
  `DynamoDbIdNumbers(client, table)`, `DynamoDbRateLimiter(client, table, clock)`,
  `S3PhotoStore(client, bucket, clock)`, `PillowPhotoInspector()`,
  `SesMailer(client)`, `SsmSecrets(client, env)`, `SystemClock()`, and (phase 8)
  `CognitoStaffTokens(issuer, sign_in_url, client_id)`.
- The table's key design and indexes above: `PK`, `SK` (strings), `GSI1` on
  `GSI1PK`/`GSI1SK`, `GSI2` on `GSI2PK`/`GSI2SK`, TTL attribute `ttl`, a stream with
  `NEW_IMAGE`, and the email items' top-level `status` for the filter
  `{"dynamodb": {"NewImage": {"type": {"S": ["email"]}, "status": {"S": ["pending"]}}}}`.
- The bucket layout: `uploads/<random>/0` (expire after a day) and
  `dropoffs/AC-n/<k>.jpg`, `dropoffs/AC-n/<k>-thumb.jpg`.
- The SSM parameter names `/asmbly-ceramics/<env>/hash-key` and
  `/asmbly-ceramics/<env>/session-key`.
- The rights per adapter, listed under each adapter above, for phase 7 to split by
  function role:

  | Adapter | Actions | Resources |
  | --- | --- | --- |
  | `DynamoDbRecords` | `dynamodb:GetItem`, `Query`, `PutItem`, `UpdateItem`, `ConditionCheckItem` | the table and `index/*` |
  | `DynamoDbIdNumbers` | `dynamodb:UpdateItem` | the table, keys `COUNTER#*` |
  | `DynamoDbRateLimiter` | `dynamodb:UpdateItem` | the table, keys `RATE#*` |
  | `S3PhotoStore` | `s3:PutObject`, `GetObject`, `DeleteObject` on `uploads/*`; `PutObject` on `dropoffs/*` (form); `GetObject` on `dropoffs/*` (console, mailer); `ListBucket` (prefix `dropoffs/`), `DeleteObject` on `dropoffs/*` (close) | the photo bucket |
  | `SesMailer` | `ses:SendEmail` | `identity/asmbly.org`, `ses:FromAddress` like `*@asmbly.org` |
  | `SsmSecrets` | `ssm:GetParameter`; `kms:Decrypt` via SSM | `parameter/asmbly-ceramics/<env>/*` |
  | `CognitoStaffTokens`, `PillowPhotoInspector`, `SystemClock` | none | — |
