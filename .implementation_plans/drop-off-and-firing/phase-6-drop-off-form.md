---
phase_id: 6
title: The drop-off form
epic: 1
implements: [2]
depends_on: [2]
domain: [web]
estimated_size: L
---

# Phase 6: The drop-off form

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): "Treat everything the public form sends as hostile", the
  photo rules, and what is never logged.
- [The plan's README](README.md): the domain model, the ports, and the security section.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md):
  server-rendered Starlette pages, photos straight to S3, the rate limit.
- [Phase 2](phase-2-drop-off-use-cases.md): `RequestUploadSlots` and `SubmitDropOff`,
  their requests, results and errors, which this phase only calls.
- Story #2's acceptance criteria, and the design's "Drop-off form" and "Your ID, on
  screen" screens (epic #1's design comment).
- The closest existing page: the facilities repository's kiln drop-off viewer
  (`functions/ceramics/kiln_dropoff_recent_entries_viewer/page.html`) for the ceramics
  tokens and the header band, and `layers/common/python/common/brand.py` for the brand
  tokens and the inline logo; `layers/common/python/common/csp.py` for the fixed CSP
  frame. Copy the ideas and values, not the code: nothing here imports from that
  repository.
- Starlette's documentation for `Starlette`, `Route`, `Mount`, `StaticFiles`,
  `Jinja2Templates` and `TestClient`; Jinja2's on autoescape.
- AWS: "Creating an HTML Form (Using AWS Signature Version 4)"
  (`/AmazonS3/latest/developerguide/sigv4-HTTPPOSTForms.html`) for the order of the
  POST's fields (the file last) and `success_action_status`; "Elements of a CORS
  configuration" (`/AmazonS3/latest/userguide/ManageCorsUsing.html`) for the rule
  phase 7 adds.
- WebKit bug 267277 and 292350 (what an iPhone sends under an `accept` list): the
  reason for the list below, at medium confidence.
- AWS: API Gateway's documentation on the request headers an HTTP API sends to its
  integration, for `X-Forwarded-For`: the rate limit relies on API Gateway appending the
  real client address as the header's last value and keeping whatever the caller sent in
  front of it. **To confirm in `/prep`** against that page before this phase is built.

## Goal

Someone at the studio scans the QR code (later, #8), fills in the form on their phone,
adds 1 to 6 photos from the camera or the library, taps Submit, and sees their new ID
(`AC-12`) in large type with a short summary. Every field is checked on the server; a
refused field shows its message next to it and nothing is saved; an 11th drop-off from
one device within 10 minutes is refused. A refresh after Submit makes no second
drop-off. The page shows nothing about anyone else. All of it runs in tests against the
in-memory fakes; phase 7 deploys it.

## Files to create

| Path | What |
| --- | --- |
| `src/asmbly_ceramics/web/__init__.py` | Empty package marker |
| `src/asmbly_ceramics/web/app.py` | `WebServices`, `WebSettings`, `create_app()`: routes, templates, static files, the security middleware, error handlers |
| `src/asmbly_ceramics/web/public.py` | The public endpoints: the form, upload slots, submit, received, health |
| `src/asmbly_ceramics/web/security.py` | Security headers and CSP, the same-origin check, signed cookies, the device cookie |
| `src/asmbly_ceramics/web/brand.py` | The brand and ceramics tokens and the inline logo and icon, used by the templates and the email partials |
| `src/asmbly_ceramics/web/errors.py` | `PageError` and the handlers that turn a refusal into a page without details |
| `src/asmbly_ceramics/web/fields.py` | Reading the posted form into the use case's request, and mapping `FieldErrors` to messages |
| `src/asmbly_ceramics/web/local.py` | `app`: the form on the in-memory fakes, for a person to try on their machine; never deployed |
| `src/asmbly_ceramics/web/templates/base.html` | The page shell: purple band with the white logo, the ceramics band, `<main>`, the footer |
| `src/asmbly_ceramics/web/templates/form.html` | The drop-off form |
| `src/asmbly_ceramics/web/templates/received.html` | The ID page |
| `src/asmbly_ceramics/web/templates/error.html` | Errors and "try again later" |
| `src/asmbly_ceramics/web/templates/partials/field.html` | A labelled field with its hint and error message |
| `src/asmbly_ceramics/web/templates/partials/logo.svg` | The Asmbly logo, `fill: currentColor` |
| `src/asmbly_ceramics/web/templates/partials/ceramics-icon.svg` | The ceramics icon |
| `src/asmbly_ceramics/web/static/app.css` | All styles; tokens in `:root`, nothing inline |
| `src/asmbly_ceramics/web/static/upload.js` | The photo upload and the glaze field's show and hide |
| `tests/web/__init__.py` | Package marker |
| `tests/web/conftest.py` | `client` and `services` fixtures on the fakes, made-up details built in code |
| `tests/web/test_form.py` | The form page and the device cookie |
| `tests/web/test_submit.py` | Submit: each field, photos, repeats, the received page |
| `tests/web/test_uploads.py` | Upload slots: counts, origin, rate limit |
| `tests/web/test_security.py` | Headers on every response, CSP, same-origin checks, escaping |
| `tests/web/test_style.py` | Tokens only in `:root`, tap targets, the contrast pairs |
| `tests/web/test_logging.py` | Nothing personal in any log line of a whole drop-off |

## Files to modify

| Path | What changes |
| --- | --- |
| `pyproject.toml`, `uv.lock` | `uv add starlette python-multipart` and `uv add jinja2` if phase 2 hasn't already; `uv add --dev httpx` for `TestClient`. Never edit `uv.lock` by hand. |
| `src/asmbly_ceramics/mail/templates/` | Phase 2's email templates use `web/brand.py`'s tokens and logo partial for the email header, so the emails and the pages match (one source) |
| `tests/repo/test_personal_data.py` | Nothing to change; the templates' example text uses no address or number (checked by this test) |

## Implementation details

### web

#### The app and its services

```python
@dataclass(frozen=True)
class WebSettings:
    site_url: str  # "https://ceramics.asmbly.org"; its scheme and host are the only allowed Origin
    photo_upload_origin: str  # "https://<bucket>.s3.us-east-2.amazonaws.com", for connect-src
    version: str  # shown by /health
    cookie_key: bytes  # signs __Host-received; the form key (SecretName.FORM_KEY) from Secrets (phase 7)


@dataclass(frozen=True)
class WebServices:
    view_studio_choices: (
        ViewStudioChoices  # phase 2: active firing types (with needs_glaze_type) and glaze types
    )
    request_upload_slots: RequestUploadSlots  # phase 2
    submit_drop_off: SubmitDropOff  # phase 2
    received_summary: ReceivedSummary  # phase 2: the ID page's summary, no contact details


def create_app(services: WebServices, settings: WebSettings) -> Starlette: ...
```

`create_app` mounts `/static` (`StaticFiles`, `Cache-Control: public, max-age=3600`
there only), registers the routes below, a middleware that adds the headers from
`security.py` to every response (errors and 404s included), and handlers for
`PageError`, `HTTPException` and any other exception (a 500 page "Something went wrong.
Nothing was saved; please try again." and one log line `page_crashed` with the
exception's class and the route, never its text). Phase 8 adds the console routes to
the same app factory; nothing here assumes there are none.

`ViewStudioChoices` and `ReceivedSummary` are phase 2's (`use_cases/studio.py`,
`use_cases/received.py`).

#### Routes

| Method and path | Who | Calls | Returns |
| --- | --- | --- | --- |
| `GET /` | anyone | `view_studio_choices` | the form; sets `__Host-device` if absent |
| `POST /drop-off/uploads` | anyone, same origin, with a submission token | `request_upload_slots` | JSON `{"slots": [{"id", "url", "fields"}]}` |
| `POST /drop-off` | anyone, same origin | `submit_drop_off` | 303 to `/drop-off/received`, or the form with its errors (400) |
| `GET /drop-off/received` | the device that just submitted | `received_summary` | the ID page, or 303 to `/` |
| `GET /health` | anyone | none | `{"status": "ok", "version": "<version>"}` |

Anything else under the public app is a 404 page. Methods not listed get 405.

#### `GET /`: the form

- Sets `__Host-device` when the request has none: 32 random bytes,
  `secrets.token_urlsafe(32)`, `Path=/; Secure; HttpOnly; SameSite=Lax;
  Max-Age=31536000`. The value is only ever used hashed (phase 2's rate limit key).
- Renders `form.html` with a fresh submission token (`secrets.token_urlsafe(24)`) in a
  hidden field, and the active firing types and glaze types from `view_studio_choices`
  (data, not code: whatever staff set in the console, #6).
- Fields, in order, each with a `<label>`, server-side check and message:

| Field | Input | Server check (phase 2's `DropOffDetails.create`, shown here as the page maps it) | Message next to the field |
| --- | --- | --- | --- |
| `name` | `type=text autocomplete=name maxlength=100` | 1 to 100 characters after trimming, no control characters | "Enter your name." |
| `email` | `type=email inputmode=email autocomplete=email maxlength=254` | at most 254 characters, one `@`, a non-empty local part, a domain with a dot and no spaces, no control characters | "Enter an email address, like the one you check most." |
| `phone` | `type=tel inputmode=tel autocomplete=tel maxlength=20` | 7 to 20 characters of digits, spaces and `+ ( ) - .`, with 10 to 15 digits | "Enter a phone number with its area code." |
| `pieces` | `type=number inputmode=numeric min=1 max=50 value=1`, with − and + buttons of 44 px | a whole number from 1 to 50 | "Enter how many pieces, from 1 to 50." |
| `firing_type` | radio buttons, one per active firing type | an active firing type's ID | "Choose bisque or glaze." (the names come from the list, not the code) |
| `glaze_type` | radio buttons, one per active glaze type, in a fieldset shown only when the chosen firing type needs one | required and active when the firing type needs one; refused when it doesn't | "Choose the glaze you used." / not shown otherwise |
| `photos` | `type=file accept="image/jpeg,image/png,image/webp" multiple` | 1 to 6 slot IDs from `POST /drop-off/uploads` (random, so only the browser that asked knows them), each holding an upload the inspector accepts (below) | "Add 1 to 6 photos." / "Photo 3 isn't a photo we can read. Use a JPEG or PNG photo." / "Photo 2 is over 10 MB." |
| `submission` | hidden | a token from `GET /` (24 to 64 URL-safe characters) | the page is shown again with "Something went wrong. Please submit again." |

  The messages above are the plan's wording; the email message must not contain an
  example address (the repository's personal-data test fails on one). The firing and
  glaze checks use the lists as they are when the drop-off is submitted.
- No `capture` attribute, so a phone offers both the camera and the library.
- The `accept` list is deliberately specific: under it, an iPhone converts HEIC photos
  to JPEG before upload (WebKit bug 292350); under `image/*` it may send HEIC, which
  Pillow can't read. A HEIC file that still arrives is refused by the inspector with the
  "isn't a photo we can read" message.
- Without JavaScript, a `<noscript>` banner says "This form needs JavaScript to upload
  photos." and the Submit button stays, so the server's "Add 1 to 6 photos." explains
  the refusal if someone submits anyway.

#### `upload.js`

A plain script (no build step, no library), loaded with `<script src="/static/upload.js"
defer>`; no inline script anywhere.

1. Shows the glaze fieldset only for a firing type whose radio has
   `data-needs-glaze="true"`; without the script the fieldset is always shown and the
   server enforces the rule.
2. On Submit: stops the default submit, checks the number of files (1 to 6) and each
   size (≤ 10 MB) for the person's convenience, showing the same messages as the server
   next to the photo field.
3. Calls `POST /drop-off/uploads` with `{"count": n, "submission": token}` and
   `Content-Type: application/json`, `credentials: "same-origin"`.
4. Posts each file to its slot's `url` as `FormData`: every entry of `fields` first, then
   `file` last (S3 requires the file to be the last field), two at a time, showing
   "Uploading photo 2 of 4…". A non-2xx answer from S3 shows "Photo 2 couldn't be
   uploaded. Check it is under 10 MB and try again." and stops.
5. Puts the slot IDs in hidden `slot` inputs, in the person's order, and submits the
   form normally (a real form POST, so the server's page is what the person sees).

#### `POST /drop-off/uploads`

- Same-origin check (below), then the body: JSON only, at most 1 KB, `count` an integer
  from 1 to 6 and `submission` a well-formed token. Anything else: 400
  `{"error": "bad_request"}`.
- Calls `request_upload_slots(SlotRequest(count, device, source_address))`, where
  `device` is the `__Host-device` cookie (a request without one gets 400: the form page
  always sets it) and `source_address` is `security.client_address(request)` (below).
- Rate limited (phase 2's `TooManySubmissions`): 429 `{"error": "rate_limited"}`, which the
  script shows as "Too many drop-offs from this device. Try again later."
- Returns `{"slots": [{"id", "url", "fields"}]}`; the slot's fields are the presigned
  POST's, already limited by phase 2 and 4 to 1 byte to 10 MB and `image/` types for
  15 minutes.

#### `POST /drop-off`

- Same-origin check, then reads at most 16 KB of `application/x-www-form-urlencoded`
  (larger: 413 page). `fields.py` turns it into phase 2's `SubmitRequest(name,
  email, phone, pieces, firing_type, glaze_type, upload_slots, submission_token, device,
  source_address)`, `source_address` from `security.client_address(request)`,
  keeping each value a string; the domain does the checking.
- Outcomes:

| From `submit_drop_off` | The page |
| --- | --- |
| `Submitted(view, repeated)`, new or the same one as before for this submission token | 303 to `/drop-off/received`, setting `__Host-received` |
| `InvalidDetails(errors)` | 400, the form again with each message next to its field, the person's values kept (escaped), photos to choose again, a summary at the top linking to each field ("There are 2 problems with your drop-off.") |
| `TooManySubmissions` | 429, `error.html`: "Too many drop-offs from this device. Try again later." |
| `RecordsUnavailable`, `PhotosUnavailable` or another port's `Unavailable` | 503 page: "Something went wrong on our side. Nothing was saved; please try again." |
| anything else | 500 page, nothing saved (the use case writes everything in one transaction or nothing) |

- `__Host-received`: `<submission token hash>.<expiry>.<hmac>`, HMAC-SHA256 with the
  form key, expiry 30 minutes, `Path=/; Secure; HttpOnly; SameSite=Lax`. It holds the
  submission's keyed hash only: no ID, nothing personal.

#### `GET /drop-off/received`

- Reads and checks `__Host-received` (signature, expiry, a well-formed hash). Missing,
  bad or expired: 303 to `/`.
- Calls `received_summary(token_hash)`, which reads only the `Submission` item (phase 2):
  the ID, pieces, the firing type's and glaze type's names, when. No name, email, phone
  or photo, and the form function never reads a drop-off item.
- Shows the ID in monospace bold in `--ceramics-shade` at 2.5 rem, "Write this ID and
  your name on a slip for each piece.", the summary, "We've emailed you a copy with your
  photos.", and a link "Drop off another piece" to `/`. No link to the kiln schedule
  (#9 is not in this plan).

#### The client's address (`security.py`)

`client_address(request) -> str`: the **last** comma-separated value of the
`X-Forwarded-For` header, trimmed. API Gateway's HTTP API appends the address it saw to
whatever the caller sent, so only the last value can be trusted; anything earlier is the
caller's own text. A missing or empty header answers 400. uvicorn runs without
`--proxy-headers` (phase 7), so Starlette's `request.client` is the Web Adapter's
loopback and is never used.

#### Same-origin check (`security.py`)

`require_same_origin(request)`: the `Origin` header must equal `settings.site_url`'s
origin exactly; if `Origin` is absent, `Sec-Fetch-Site` must be `same-origin`; otherwise
403 page "This form can only be sent from the drop-off page." This, with SameSite
cookies and the per-page submission token, is the form's protection against
cross-site posts.

#### Security headers (`security.py`, one helper for every response)

```
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self';
  img-src 'self' blob: data:; font-src 'self'; connect-src 'self' <photo_upload_origin>;
  form-action 'self'; base-uri 'none'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Cache-Control: no-store            (static files: public, max-age=3600)
Referrer-Policy: no-referrer
Strict-Transport-Security: max-age=31536000
```

`csp(settings)` builds the policy from a fixed frame (as the facilities repository's
`csp.py` does): `default-src 'none'` first and `base-uri`, `form-action`,
`frame-ancestors` last; a source holding `;`, `,`, a space, CR or LF raises. No page
uses inline script, inline style or `style=` attributes; `img-src blob:` lets the form
preview the chosen photos.

#### Branding (`brand.py`, `app.css`)

From the facilities repository's `brand.py` and the kiln page, values copied:

- Brand colours: `--asmbly-purple #292D6A`, `--asmbly-white #F2F4EF`,
  `--midnight-black #171d1a`, `--ceramics #b34a9a`, `--lasers #D33E43`.
- Derived: `--ceramics-shade #944180`, `--ceramics-shade-60 #753867`,
  `--ceramics-40 #d9b0cd`, `--ceramics-20 #e5d2de`, `--ceramics-10 #ece3e6`,
  `--lasers-shade #ad373b`, `--lasers-20 #ecd0cd`, `--asmbly-purple-20 #caccd4`,
  `--asmbly-purple-40 #a2a4ba`.
- Type: `--font-body` (Roboto, system-ui, …), `--font-heading` ("Helvetica Neue",
  "Segoe UI", Roboto, …), `--font-mono` (ui-monospace, …); no font files are fetched.
  Sizes `1rem`, `1.75rem`, `1.25rem`, `0.875rem`; line height 1.5.
- Space `--space-1` to `--space-6` (0.25 to 2 rem), `--tap-target 2.75rem` (44 px),
  `--focus-width 3px`.
- Roles: page `--asmbly-white` on `--midnight-black` text; IDs and primary buttons
  `--ceramics-shade`; hover `--ceramics-shade-60`; errors with an edge in
  `--lasers-shade` on `--lasers-20` and a "✕" glyph, so they don't rely on colour.

The header: a purple band with the white logo (inline SVG, `fill: currentColor`,
`aria-label="Asmbly Makerspace"`), then the ceramics band (ceramics colour, the white
ceramics icon, "Drop off for firing" as the h1; white on ceramics is 4.35:1, so only
large text and the icon sit on it). One column, `max-width: 34rem`, 16 px side gutter,
no horizontal scroll at 320 px. The email templates (phase 2) take the same tokens from
`brand.py`.

#### Logging

One line per outcome, from the page: `drop_off_page` with `outcome` (`shown`,
`submitted`, `refused`, `rate_limited`, `expired`, `bad_request`) and, when there is
one, `drop_off_id` (`AC-12`) and the refused field names (`fields: ["email", "photos"]`,
the names only). Never a value the person typed, a cookie, a token, an address or an IP.

#### Phones

`<meta name="viewport" content="width=device-width, initial-scale=1">`; inputs at 16 px
or more so iOS doesn't zoom; the right keyboard for email, phone and pieces; the photo
field opens the camera or the library; previews as 96 px thumbnails with a "Remove"
button each; Submit is full width at the bottom. Readable in sunlight: body text
contrast at least 7:1 on the page background.

## Tests

`tests/web/` uses `TestClient(create_app(services, settings))` with phase 1's fakes and
phase 2's use cases; made-up details are built in code (for example
`"tester" + "@" + "example.org"`), never written whole in a file.

- `test_form.py`
  - `test_the_form_lists_the_active_firing_and_glaze_types`: the names come from the
    fake studio; a retired one isn't offered.
  - `test_the_form_sets_a_device_cookie_once`: first visit sets `__Host-device` with
    `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`; a second visit with it sets none.
  - `test_each_page_load_has_a_new_submission_token`.
  - `test_the_photo_field_accepts_only_jpeg_png_and_webp_and_doesnt_force_the_camera`.
  - `test_the_form_says_it_needs_javascript_for_photos` (the `<noscript>` text).
- `test_submit.py`
  - `test_a_valid_drop_off_is_stored_and_redirects_to_its_id`: 303 to
    `/drop-off/received`; the fake records hold one drop-off with its photos; the
    outbox holds one `received` email.
  - `test_each_missing_or_bad_field_shows_its_message_and_saves_nothing`, parametrized
    over name (empty, 101 characters, a control character), email (no `@`, 255
    characters, a space), phone (6 digits, 16 digits, letters), pieces (0, 51, "two"),
    firing type (empty, unknown, retired), glaze type (missing for glaze, given for
    bisque, retired): each answers 400 with the message next to the field and the fake
    records unchanged.
  - `test_no_photos_and_seven_photos_are_refused`.
  - `test_a_file_that_isnt_an_image_is_refused_next_to_the_photo_field` (the fake
    inspector refuses kind `not_an_image`).
  - `test_a_photo_over_10_mb_is_refused` (the fake photo store holds 10 MB + 1 byte for
    the slot).
  - `test_a_malformed_or_seventh_slot_is_refused_before_any_read`: a slot ID that isn't
    22 to 64 URL-safe characters, or a seventh distinct slot, answers 400 next to the
    photos and the fake photo store records no read.
  - `test_the_eleventh_drop_off_from_one_device_in_ten_minutes_is_refused` (429, the
    message, nothing saved); `test_the_device_can_drop_off_again_after_ten_minutes` (the
    fake clock moves on).
  - `test_the_thirty_first_from_one_address_is_refused_even_with_new_cookies`.
  - `test_submitting_the_same_page_twice_gives_the_same_id`: the same submission token
    posted twice gives one drop-off and the same ID on both received pages.
  - `test_the_received_page_shows_the_id_and_no_contact_details`: the ID is there; the
    made-up name, email and phone are nowhere in the HTML.
  - `test_the_received_page_without_its_cookie_goes_back_to_the_form`, and with a
    tampered or expired cookie.
  - `test_values_are_kept_and_escaped_when_the_form_is_shown_again`: a name of
    `<script>alert(1)</script>` comes back as `&lt;script&gt;…`.
  - `test_an_oversized_body_is_refused` (16 KB + 1).
- `test_uploads.py`
  - `test_upload_slots_are_issued_for_one_to_six_photos`; `0`, `7`, `"3"` and a missing
    token get 400.
  - `test_upload_slots_need_the_device_cookie`.
  - `test_upload_slots_are_rate_limited` (429 after the limit).
  - `test_spoofed_forwarded_for_does_not_change_the_rate_key`: a request with
    `X-Forwarded-For: 1.2.3.4, <real>` counts against `<real>`; a request without the
    header gets 400.
  - `test_upload_slots_fail_closed_when_the_limiter_is_unavailable` (the fake records
    raise `RecordsUnavailable`: 503, no slot issued).
- `test_security.py`
  - `test_every_response_has_the_security_headers`: `/`, `/health`, a 404, a 400, the
    received page, a 500 from a use case that raises.
  - `test_the_csp_allows_only_the_photo_bucket_to_be_contacted`.
  - `test_a_post_from_another_origin_is_refused` (both POST routes, 403, nothing
    saved); `test_a_post_without_origin_needs_same_origin_fetch_metadata`.
  - `test_no_page_has_inline_script_or_style`: every rendered page's HTML has no
    `<script>` without `src`, no `<style>` and no `style=`.
  - `test_the_health_check_names_the_version`.
- `test_style.py`
  - `test_colours_and_sizes_are_only_tokens` (outside `:root`, `app.css` uses `var(...)`
    only), `test_buttons_and_inputs_are_at_least_44px`,
    `test_text_colour_pairs_meet_wcag_aa` (each pair the page uses, computed).
- `test_logging.py`
  - `test_a_whole_drop_off_logs_nothing_personal`: with `caplog` on every logger, a
    submit with made-up details, a refused submit and a rate-limited one: no log record
    holds the name, email, phone, the device cookie, the submission token or an IP.

## Acceptance criteria

1. `GET /` on a phone-width viewport shows the Asmbly logo, the ceramics band and the
   form with no horizontal scroll (#2: "opens the form on a phone, with no sign-in; it
   shows the Asmbly logo and the ceramics colours").
2. The form asks for name, email, phone, pieces (1–50), firing type, glaze type only for
   a firing type that needs one, and 1 to 6 photos from the camera or the library (#2).
3. A valid submit stores one drop-off and one `received` email in the outbox, and the
   next page shows its `AC-n` ID in large type (#2).
4. Each invalid or missing field answers 400 with its message next to the field, and the
   fake records are unchanged (#2).
5. A file that isn't a JPEG, PNG or WebP image, or a photo over 10 MB, is refused next to
   the photo field and nothing is stored (#2).
6. Two submissions in a row from one person (two page loads) get two IDs; the same page
   submitted twice gets one ID (#2).
7. The 11th submission from one device within 10 minutes answers 429 with "Too many
   drop-offs from this device. Try again later." and stores nothing (#2).
8. The received page shows no name, email, phone or photo, and without its signed cookie
   sends the browser back to the form.
9. Every response carries the CSP, `nosniff`, `no-store`, `no-referrer` and HSTS
   headers, and no page has inline script or style.
10. A POST from another origin is refused with 403 and stores nothing.
11. No log line from a whole drop-off holds a name, email, phone, cookie, token or IP.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest tests/web
uv run pytest --cov
```

To try the form on your machine, on the fakes (no AWS, nothing sent):

```bash
uv run uvicorn asmbly_ceramics.web.local:app --reload
```

`local.py` builds the app on the in-memory fakes with a fake photo store that accepts
the browser's POSTs at `/local-uploads/<slot>` (served by the same app, local only) and
prints nothing personal. Open it at `http://127.0.0.1:8000/` in a phone-sized window.

After phase 7's deploy (it's that phase's check, written here so the form is tested
where people use it): open `https://ceramics-stage.asmbly.org/` on an iPhone and on an
Android phone, submit with made-up details, a mailbox you own and two photos, one taken
with the camera then. Expect the ID page, the "We received your drop-off" email with
both photos, and in the stage table the photos stored as JPEG; an iPhone photo arriving
as JPEG answers the HEIC question (record the iOS version in the hand-off).

## Rollout

Nothing reaches AWS. Phase 7 deploys this form.

## Admin actions

None.

## Hand-off

Filled in when the phase is done. It will say: `create_app(services, settings)` and the
`WebServices` and `WebSettings` fields as built; the public routes; the cookie names
(`__Host-device`, `__Host-received`); `security.py`'s helpers (`security_headers`,
`csp`, `require_same_origin`, `sign`, `verify`) for the console to reuse; the base
template's blocks; the S3 CORS rule phase 7 must add (AllowedOrigins the site's
address, AllowedMethods `POST`, AllowedHeaders `*`, MaxAgeSeconds 3000); and the
results of the phone tests once phase 7 has run them.
