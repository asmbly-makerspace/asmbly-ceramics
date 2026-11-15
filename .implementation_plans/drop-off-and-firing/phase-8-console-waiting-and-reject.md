---
phase_id: 8
title: "Console: sign-in, waiting list, rejection"
epic: 1
implements: [3, 5]
depends_on: [3, 7]
domain: [web, infra]
estimated_size: L
---

# Phase 8: Console: sign-in, waiting list, rejection

> **Status:** [~] In progress

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the rules on personal details, staff access and AWS.
- [The plan's README](README.md): the domain model, ports and use cases this phase calls.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md),
  "Staff sign-in is checked by the app on every request".
- [Phase 3](phase-3-load-and-studio-use-cases.md) (`RetryEmail`) and
  [phase 2d](phase-2d-waiting-list-and-rejection.md) (`WaitingList`, `FindDropOffs`,
  `ViewDropOff`, `PreviewRejection`, `RejectDropOff`, `UndoRejection`).
- [Phase 4](phase-4-aws-adapters.md): `adapters/aws/staff_tokens.py`, the token check
  this phase relies on, and its test keys.
- [Phase 6](phase-6-drop-off-form.md): `web/app.py` (`create_app`, `WebServices`),
  `web/security.py`, `web/templates/base.html` and the brand partials.
- [Phase 7](phase-7-first-deploy.md): `infra/app.yaml`, `composition.py`,
  `scripts/smoke.py`, `.github/workflows/deploy.yml`.
- Stories #3 and #5, and the design's "Waiting to fire", "One drop-off, rejecting" and
  "Not allowed" screens (epic #1's design comment).
- asmbly-staff-login's plan `add-an-app`, phase 3 ("Check the token"): what an app must
  check, and the Parameter Store names.
- AWS's documentation:
  - "The redirect and authorization endpoint"
    (`https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html`):
    `response_type=code`, `client_id`, `redirect_uri`, `state`, `code_challenge`,
    `code_challenge_method=S256`; `state` is returned on the redirect.
  - "The token endpoint" (`.../cognito/latest/developerguide/token-endpoint.html`):
    `grant_type=authorization_code`, `code`, `redirect_uri`, `code_verifier`; a public
    client sends no secret.
  - "The managed login sign-out endpoint: /logout"
    (`.../cognito/latest/developerguide/logout-endpoint.html`): `client_id` and
    `logout_uri`, which must be one of the client's sign-out URLs.
  - "Verifying JSON web tokens"
    (`.../cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html`):
    the JWKS address, `iss`, `aud` on an ID token, `token_use`, `exp`.
  - "Adding groups to a user pool"
    (`.../cognito/latest/developerguide/cognito-user-pools-user-groups.html`):
    `cognito:groups` is in the ID token.
  - "Understanding the identity (ID) token"
    (`.../cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html`):
    `cognito:username`.
  - "Ending user sessions with token revocation"
    (`.../cognito/latest/developerguide/token-revocation.html`): a revoked token still
    verifies locally until it expires, so sign-out clears the cookie and ends the
    managed-login session.
  - "Create AWS Lambda proxy integrations for HTTP APIs in API Gateway"
    (`.../apigateway/latest/developerguide/http-api-develop-integrations-lambda.html`):
    payload format 2.0, the `cookies` array.
  - "AWS::Serverless::Function HttpApi event"
    (`.../serverless-application-model/latest/developerguide/sam-property-function-httpapi.html`):
    `ApiId`, `Method`, `Path`.

## Goal

Ceramics staff in the `ceramics` group sign in through Asmbly's staff sign-in, see every
drop-off waiting to fire (oldest first, with totals, search, thumbnails and days
waiting), open a drop-off with all its photos at full size and its contact details,
reject it with a reason and a message after seeing the email exactly as it will go out,
undo a rejection the same day, see every email needing attention studio-wide and retry
a failed one. Anyone not signed in is sent to
the sign-in and back; anyone signed in but not in the group sees "not allowed". After
this phase #3 is done and #5 is done.

## Files to create

| Path | What |
| --- | --- |
| `src/asmbly_ceramics/web/console/__init__.py` | `console_routes(services: ConsoleServices) -> list[BaseRoute]`, mounted at `/console` by `create_app` |
| `src/asmbly_ceramics/web/console/auth.py` | Sign-in, callback, sign-out, signed-out routes; `require_staff` (the per-request check) |
| `src/asmbly_ceramics/web/console/session.py` | The `__Host-session` and `__Host-signin` cookies: set, read, clear; the signed sign-in state |
| `src/asmbly_ceramics/web/console/csrf.py` | `csrf_token(session_token, key)`, `check_csrf(sent, session_token, key)`, `check_origin(request, site_url)` |
| `src/asmbly_ceramics/web/console/common.py` | `Staff`, `Answer`, `read_form`, `drop_off_id`, `not_found`, `render` |
| `src/asmbly_ceramics/web/console/services.py` | `ConsoleServices` |
| `src/asmbly_ceramics/use_cases/photos.py` | `ViewPhoto` (revision 6) |
| `src/asmbly_ceramics/web/console/waiting.py` | `GET /console` |
| `src/asmbly_ceramics/web/console/dropoffs.py` | The drop-off page, its photos, the rejection preview, reject, undo, retry |
| `src/asmbly_ceramics/web/console/emails.py` | `GET /console/emails`: every email needing attention |
| `src/asmbly_ceramics/web/templates/console/emails.html` | The needs-attention list |
| `src/asmbly_ceramics/web/templates/console/layout.html` | The console's band, "Signed in as", Sign out, the tab row (Waiting (n), Loads, Weekly counts, Settings) |
| `src/asmbly_ceramics/web/templates/console/waiting.html` | The waiting list |
| `src/asmbly_ceramics/web/templates/console/drop_off.html` | One drop-off, with the reject panel and the email statuses |
| `src/asmbly_ceramics/web/templates/console/reject_preview.html` | The rejection email, exactly as it will go out, with Send rejection and Cancel |
| `src/asmbly_ceramics/web/templates/console/not_allowed.html` | The 403 page |
| `src/asmbly_ceramics/web/templates/console/signed_out.html` | The public "You're signed out" page |
| `src/asmbly_ceramics/web/templates/console/signing_out.html` | Sign-out's page, which goes on to the staff sign-out (revision 14) |
| `src/asmbly_ceramics/web/templates/console/message.html` | A message page, with an optional Sign in link |
| `tests/web/console/__init__.py` | |
| `tests/web/console/conftest.py` | A `console_client` fixture: `create_app` over the fakes, with a `StaffTokens` fake that accepts made-up tokens; `signed_in(client, groups=("ceramics",))` |
| `tests/web/console/test_auth.py` | Sign-in, callback, the per-request check, sign-out |
| `tests/web/console/test_csrf.py` | Forged requests |
| `tests/web/console/test_waiting.py` | The waiting list and search |
| `tests/web/console/test_dropoffs.py` | The drop-off page, photos, preview, reject, undo, retry |
| `tests/web/console/test_emails.py` | The needs-attention list |
| `tests/web/console/test_privacy.py` | Nothing personal on public pages or in logs |
| `tests/web/console/test_real_tokens.py` | The same per-request check through phase 4's real verifier, with tokens signed by a test key |

## Files to modify

| Path | Change |
| --- | --- |
| `src/asmbly_ceramics/web/app.py` | `create_app(services, settings, console=None)` adds `console_routes` when `console` is given (the form function's app has none, so `/console` is not served there); `WebServices` is unchanged |
| `src/asmbly_ceramics/composition.py` | `build_console_services() -> (ConsoleServices, WebSettings)` and `console_app()` (the console function's ASGI app) |
| `src/asmbly_ceramics/web/app.py` (`create_from_environment`, from phase 7) | Accepts `APP_ROLE=console` and returns `composition.console_app()`; `entry/run.sh` is unchanged |
| `infra/app.yaml` | `ConsoleFunction`, its role, its log group, the routes and their throttles, the three staff sign-in parameters, `ConsoleLoggedErrorsFilter` and the console in `FunctionErrorsAlarm` |
| `scripts/smoke.py` | Two console checks (below) |
| `tests/repo/test_app_template.py` (from phase 7) | Pins for the console's role and routes |
| `.implementation_plans/drop-off-and-firing/README.md` | Phase 8's status, when the work starts and when it is merged |

## Implementation details

### Prep revisions (15 November 2026)

`/prep` checked this document against the code, and the build and its reviews changed
it further. The sections after this list describe what was built; the list is kept as the
record of what changed from the first draft and why:

1. **Use case calls.** `PreviewRejection(...)(RejectRequest(drop_off_id, reason, message,
   version, staff), image_src)`, `RejectDropOff(...)(RejectRequest(...))` and
   `UndoRejection(...)(UndoRequest(drop_off_id, version, staff))`, with `staff` the
   `StaffMember`. The `version` the staff member saw travels as a hidden field from the
   drop-off page through the preview to Send and Undo, so a change meanwhile is a
   `Conflict` ("AC-12 changed while you were looking."). The use cases log their own
   actions (`drop_off_rejected`, `rejection_undone`, `email_retried`); the console logs
   only its sign-in events.
2. **Undo's message** comes from `Undone.contact_the_person`: "AC-12 is waiting again. No
   email was sent." only when the rejection email never went; otherwise "AC-12 is waiting
   again. The rejection email went, or may have: contact the person directly."
3. **CSRF token.** `StaffMember` has no `sub` or `auth_time`, so `csrf_token(session_token,
   key)` is HMAC-SHA256, under the session key, of `"csrf:" + the session's ID token`:
   bound to the session and new at each sign-in. `check_origin` accepts `Origin` equal to
   the site, or with no `Origin` (or `null`) `Sec-Fetch-Site: same-origin` or a console
   `Referer` of this site.
4. **Session cookie** `Max-Age` is a fixed 3600 seconds (the token's lifetime); an expired
   token in it fails `verify` and is cleared. `NotSignedIn` carries no reason: the adapter
   logs `sign_in_refused` with its fixed reason, and the console logs `auth_rejected`.
   A key-fetch outage is logged by the console as `jwks_unavailable` at ERROR.
5. **Key fetches** are throttled in the adapter: `ThrottledSigningKeys`, `CognitoStaffTokens`'
   default key set, fetches again for an unknown `kid` at most once a minute.
6. **Photos.** A small read-only use case, `use_cases/photos.py` `ViewPhoto(records,
   photos)(id, index, size)`, reads the drop-off's record and `PhotoStore.read(ref, size)`
   (`NotFound` for a closed drop-off, a missing index or a gone photo), instead of the
   whole `ViewDropOff` per thumbnail. A photo request without a valid session answers
   `401` ("Sign in to the console to see this photo."), never the photo and never a
   redirect, so a thumbnail loading after the session ends doesn't overwrite the sign-in
   state; the smoke test's second check expects that `401`. Thumbnails load with
   `loading="lazy"`, and the console function's reserved concurrency is 25 (revision 13),
   so a long waiting list isn't throttled (throttled requests still show in `Api5xxAlarm`).
7. **The preview** shows the composed email in `<iframe sandbox="allow-same-origin"
   srcdoc=...>` (no scripts), and only the preview's response allows inline styles
   (`style-src 'self' 'unsafe-inline'`, `frame-src 'self'`), so the email looks as it will
   go out. The search box and the message carry `autocomplete="off"`.
8. **The drop-off page** offers "Try sending again" for `view.emails_needing_attention`
   and Undo when `view.can_undo_rejection`, as `ViewDropOff` decides; it re-decides
   neither rule. `ConsoleServices` also holds `studio: CurrentStudio`, for the preview's
   From address.
9. **The app factory.** `create_app(services: WebServices | None, settings, console:
   ConsoleServices | None = None)`: the form's routes when `services` is given, the
   console's when `console` is, `/health` and `/static` always. `WebServices` is
   unchanged. The console function's `WebSettings.cookie_key` is the session key.
   `Settings` gains `StaffSignIn.from_environment()` (`STAFF_ISSUER`, `STAFF_SIGN_IN_URL`,
   `STAFF_CLIENT_ID`), and `tests/repo/test_app_template.py`'s variables test covers the
   console's.
10. **The console's role** in `infra/app.yaml`, as phase 7's statements are written (and
    as `tests/repo/test_app_template.py` requires): `ReadRecords` (`dynamodb:GetItem` on
    the table, `LeadingKeys` `DROPOFF#*`, `EMAIL#*`, `LOAD#*`, `STUDIO`),
    `QueryEmailsOfADropOff` (`dynamodb:Query` on the table, `LeadingKeys` `EMAIL#*`),
    `QueryIndexes` (`dynamodb:Query` on `index/*`), `WriteRecords` (`dynamodb:PutItem`,
    `LeadingKeys` `DROPOFF#*`, `EMAIL#*`, `STUDIO`, only inside `TransactWriteItems`,
    `ReturnValues` `NONE`), `ReadKeptPhotos`, `ListKeptPhotos` and `ReadSessionKey`. No
    `dynamodb:TransactWriteItems` statement (not an IAM action).
11. **Alarms.** Phase 7 has no per-function alarm: the console joins the shared ones, a
    `ConsoleLoggedErrorsFilter` feeding `LoggedErrors` and the console in
    `FunctionErrorsAlarm`. No `ConsoleErrorsAlarm`.
12. **Smoke test.** No stack output: check 1 follows two hops, `GET /console` to
    `/console/auth/sign-in?next=%2Fconsole` (the per-request check's redirect), then that to
    the staff sign-in, and checks its shape (an `https` address other than the site's,
    path `/oauth2/authorize`, `client_id`, `code_challenge_method=S256`, `redirect_uri`
    equal to `<site>/console/auth/callback`) and the `__Host-signin` cookie; check 2
    expects `401`. A test runs both checks against the console app as built. Following
    the redirect on to Cognito is left out: its answers belong to asmbly-staff-login and
    aren't documented as a contract here.
13. **Review fixes (15 November 2026).** The console's reserved concurrency is 25 (the
    account has room), with the route throttle on `ANY /console/{proxy+}` bounding it;
    the stage check loads a waiting list of 30 or more rows before prod. The role's
    table `Query` is limited to `EMAIL#*`, the index `Query` is its own statement.
    `DropOffView.can_reject` comes from the domain's `can_be_rejected`. "Waiting (n)" shows
    its count on the waiting page only. The four token cases the Tests list names under
    `test_auth.py` (expired, another client, an access token, other groups only) are
    parametrized in `test_real_tokens.py`, through the real verifier. The router doesn't
    redirect trailing slashes (uvicorn behind the Web Adapter sees plain http).
14. **No form redirect to another site.** Browsers check `form-action 'self'` on each
    redirect of a form submission, so no console POST answers a redirect off-site: a POST
    without a valid session answers a 401 "Your sign-in has ended, so that wasn't saved.
    Sign in and try again." page with a Sign in link, and sign-out answers a 200 page that
    goes on to the staff sign-out by a meta refresh and a Continue link. The rejection
    message's "It has N." is left out (the domain counts the normalised text).
15. **The session is sealed.** `__Host-session` holds `<ID token>.<HMAC-SHA256 under the
    session key>`, checked before the token is verified: changing `session-key` signs
    everyone out, and a token from stage's sign-in (stage and prod share the client) is
    no session on prod. Photos and thumbnails have their own route,
    `GET /console/drop-offs/{id}/photos/{proxy+}`, with their own throttle (burst 100,
    30 a second), so thumbnails can't starve pages. The key set is tried again 5 seconds
    after a cold container's first fetch fails, and a failed refresh keeps the set held.
    The Tests list's `test_photos_without_a_session_redirect_and_never_read_the_store` is
    `test_photos_without_a_session_never_read_the_store` (revision 6: a 401, not a
    redirect).

### web: who may reach what

| Path | Method | Who | Calls |
| --- | --- | --- | --- |
| `/console` | GET | `ceramics` | `WaitingList` |
| `/console/search` | POST | `ceramics`, CSRF | `WaitingList`, `FindDropOffs` |
| `/console/drop-offs/{id}` | GET | `ceramics` | `ViewDropOff` |
| `/console/emails` | GET | `ceramics` | `EmailsNeedingAttention` |
| `/console/drop-offs/{id}/photos/{k}` | GET | `ceramics` (401 without a session) | `ViewPhoto` |
| `/console/drop-offs/{id}/photos/{k}/thumb` | GET | `ceramics` (401 without a session) | `ViewPhoto`, thumbnail |
| `/console/drop-offs/{id}/reject/preview` | POST | `ceramics`, CSRF | `PreviewRejection` |
| `/console/drop-offs/{id}/reject` | POST | `ceramics`, CSRF | `RejectDropOff` |
| `/console/drop-offs/{id}/undo-reject` | POST | `ceramics`, CSRF | `UndoRejection` |
| `/console/drop-offs/{id}/emails/{kind}/retry` | POST | `ceramics`, CSRF | `RetryEmail` |
| `/console/auth/sign-in` | GET | anyone | (starts sign-in) |
| `/console/auth/callback` | GET | anyone holding a valid `__Host-signin` | `StaffTokens.exchange`, `StaffTokens.verify` |
| `/console/sign-out` | POST | anyone whose session verifies, in `ceramics` or not, CSRF; no session or a stale one goes to `/console/signed-out` | (clears the session) |
| `/console/signed-out` | GET | anyone | (static page) |

`{id}` must be `AC-n` (`common.drop_off_id`); anything else is 404 before any use case
runs. `{k}` is 1 to 6; `{kind}` is `received`, `ready` or `rejected`.

### web: the per-request check (`auth.require_staff`)

Every route above except sign-in, callback, sign-out and signed-out goes through
`require_staff(request) -> Staff` (a GET) or `require_staff_post(request) -> (Staff,
form)` (a POST: then this site's origin, then the CSRF token, then the bounded form),
before anything else:

1. No `__Host-session` cookie, a seal that isn't this key's, or `NotSignedIn` from
   `StaffTokens.verify` (phase 4: signature, `iss`, `aud`, `token_use == "id"`, `exp`,
   and the username's shape): a GET is answered `302` to
   `/console/auth/sign-in?next=<the path and query>`; a POST answers a `401` page, "Your
   sign-in has ended, so that wasn't saved. Sign in and try again.", with a Sign in link
   (revision 14: no form redirect off-site). A cookie that was there is cleared, and the
   console logs `auth_rejected` (the adapter logs `sign_in_refused` with its fixed
   reason).
2. `NotAllowed` (a valid token without `ceramics`): `403` with `not_allowed.html`: "You
   don't have access to the ceramics console. Ask the Facilities Manager to add you to
   the ceramics group.", a link to the drop-off form and a "Sign in as someone else"
   button (a POST to `/console/sign-out` with this session's CSRF token). Logged
   `not_allowed`, `user=<username>`.
3. `SignInUnavailable` (the pool's keys can't be fetched and none are held): `503`, "The
   staff sign-in can't be checked right now. Try again in a minute.", logged
   `jwks_unavailable` at ERROR, which `ConsoleLoggedErrorsFilter` counts.
4. A photo (`require_staff_for_photo`) answers 1's case with a `401` page, "Sign in to the
   console to see this photo.", never a redirect and never the photo.

Every console response carries the headers from `web/security.py`
(`Content-Security-Policy` with `form-action 'self'`, `nosniff`, `Cache-Control:
no-store`, `Referrer-Policy: same-origin`).

### web: sign-in and sign-out

- **`GET /console/auth/sign-in?next=...`**: `session.new_sign_in` makes a PKCE verifier
  and a state (32 random bytes each, base64url) and sets `__Host-signin` (HttpOnly,
  Secure, SameSite=Lax, Path=/, Max-Age=600) to `{verifier, state, next, issued_at}`
  signed with HMAC-SHA256 under the session key. `next` is kept only as a console path
  (`safe_next`); otherwise `/console`. Then `302` to `StaffTokens.sign_in_url(state,
  code_challenge, redirect_uri=<site>/console/auth/callback)`.
- **`GET /console/auth/callback?code=...&state=...`**: a missing, tampered or
  ten-minute-old sign-in cookie, an `error=`, or a state that doesn't match
  (`hmac.compare_digest`) answers `400` "Sign-in didn't finish. Try again." with a Sign
  in link (or, already signed in, `303` to `/console`), logged `sign_in_failed`.
  Otherwise `exchange` and `verify`: a member of the group gets `__Host-session` (the
  sealed ID token, Max-Age 3600), `__Host-signin` cleared, `303` to `next`, logged
  `signed_in`; someone outside it gets the 403 page with a link to the staff sign-out and
  no session; an unreachable token endpoint is a 503 logged `sign_in_unavailable`.
- **`POST /console/sign-out`**: no session cookie (its hour has lapsed) or one that no
  longer verifies: `303` to `/console/signed-out`, clearing any stale cookie; there is
  nothing signed in to protect. A session that verifies (in `ceramics` or not), or one
  that can't be checked during a key outage, must carry this site's origin and its CSRF
  token; then the session is cleared and a `200` page goes on to
  `<staff sign-in>/logout?client_id=...&logout_uri=<site>/console/signed-out` by a meta
  refresh and a Continue link. Logged `signed_out`.
- **`GET /console/signed-out`**: "You're signed out of the ceramics console." with a
  Sign in link and a link to the drop-off form. No details.

The ID token is 1 to 2 KB; one that would seal past 4096 characters isn't set (a browser
would drop it) and the callback says sign-in didn't finish. Tokens last 60 minutes and
are not refreshed, so staff sign in again about hourly; the managed-login session
usually makes that one tap. The return addresses are only the two fixed ones built from
`SITE_URL`, never from the request, and the key set is fetched by `ThrottledSigningKeys`
(revisions 5 and 15; a failed refresh, unreachable or an empty or malformed set, keeps
the set held and logs `jwks_refresh_failed` with a code).

### web: forged requests (`csrf.py`)

- `csrf_token(session_token, key)` is HMAC-SHA256 under the session key of `"csrf:" +`
  the session's ID token, base64url: new at each sign-in. Every console form has it as
  the hidden field `csrf`.
- `check_origin(request, site_url)`: `Origin` must equal the site; with no `Origin` (or
  `null`), `Sec-Fetch-Site: same-origin` or a `Referer` of a `/console` page of this
  site. `check_csrf` then compares the field with `hmac.compare_digest`. Either failing
  is `403` "This form has expired. Go back, reload the page and try again.", logged
  `csrf_refused` with `outcome` `missing`, `wrong_token` or `other_origin`.

### web: the waiting list (`GET /console`) and search (`POST /console/search`)

`GET /console` calls `WaitingList(firing_type)`; `POST /console/search` (fields `q` and
`csrf`) calls the same and `FindDropOffs(q)` and renders the same page with the matches,
`200` with no redirect, so the search text (often part of a name) never sits in a URL.
The page shows the heading "Waiting to fire", the search box (`autocomplete="off"`), the
Bisque, Glaze (with the glaze types' split) and Overdue cards from the use case's totals,
a Show filter of chips (`?firing=<item id>`, `aria-current` on the chosen one), and a
table: a lazily loaded 56 px thumbnail, the ID, name, pieces, firing type, glaze type or
"—", and for a waiting row (`WaitingRow.waiting`) its days waiting ("today", "1 day", "n
days", an "overdue" tag at 60), otherwise its state, then Open. Search covers every
state that still has a name (and a closed drop-off by its number), at most 50 rows; no
match says "No drop-offs match that. Check the ID, or try part of the name." `q` is cut
at 100 characters, never refused, and shown back escaped. Under 40rem the table scrolls
sideways and the cards stack.

### web: one drop-off (`GET /console/drop-offs/{id}`)

`ViewDropOff(id)`; an unknown ID is 404 "There's no drop-off AC-999." The page shows the
ID, name, firing type and state, every photo at full size, the details (pieces, firing,
glaze type, dropped off in Austin time, email as a `mailto:` link, phone as a `tel:`
link; a closed drop-off shows none of them), and each email's status with "Try sending
again" for `view.emails_needing_attention`. A waiting drop-off offers "Add to a load"
(`/console/loads`) and "Reject…" (`?reject=1#reject`), which opens the panel on the same
page without a script: a Reason select (the active reasons, "(needs a message)" where
one does), a Message textarea (`maxlength` from the domain's limit,
`autocomplete="off"`), "Preview the email" (a POST with the CSRF token and the version
seen) and Cancel. Undo shows when `view.can_undo_rejection`.

### web: the rejection preview, reject and undo

- **`POST .../reject/preview`** calls `PreviewRejection(RejectRequest(...),
  image_src)`, with each photo at its console thumbnail address. A refusal (`UnknownItem`,
  `ItemRetired`, `MessageRequired`, `MessageTooLong`, `NotWaiting`, `Conflict`) shows
  the drop-off page's panel again with the typed message and the domain error's
  `.message` next to its field. On success `reject_preview.html` shows To, From,
  Subject and the composed HTML in `<iframe sandbox="allow-same-origin" srcdoc=...>`
  (this response alone allows inline styles and `frame-src 'self'`), and a form with the
  reason, message and version hidden, "Send rejection" and Cancel.
- **`POST .../reject`** calls `RejectDropOff(RejectRequest(...))`, which re-checks
  everything and commits the rejection and its outbox email together: `303` to the
  drop-off page with "AC-12 was rejected. The email is on its way."; a refusal shows the
  panel again; an unknown commit outcome is a 503 that says it may have been saved.
- **`POST .../undo-reject`** calls `UndoRejection(UndoRequest(...))`: `303` with the
  message `Undone.contact_the_person` picks (revision 2); `UndoTooLate` on a later Austin
  day.
- **`POST .../emails/{kind}/retry`** (hidden `occasion`, exactly as stored) calls
  `RetryEmail`: `303` with "The email to AC-12 will be sent again." (back to the emails
  list with `back=emails`).

The use cases log their own actions (`drop_off_rejected`, `rejection_undone`,
`email_retried`), by ID and username, never the message.

### web: emails needing attention (`GET /console/emails`)

`EmailsNeedingAttention()` (phase 3): every failed, or stuck pending or sending, email
that isn't history, studio-wide and oldest first. The band shows "Emails need attention
(n)" on every console page whenever n > 0. Each row has the drop-off's ID (a link, or
plain when its record is missing), the email, its state ("Sending failed (code)",
"Stuck sending since …", "Waiting to send since …", from the row's `since`) and "Try
sending again". No name, address or message. Empty: "No email needs attention."

### web: photos

`GET .../photos/{k}` and `.../thumb` answer, after `require_staff_for_photo`, the JPEG
bytes from `ViewPhoto(id, k, size)`, `image/jpeg`, `Cache-Control: no-store`, `nosniff`
and `Content-Disposition: inline; filename="AC-12-k.jpg"` (or `-thumb`). A closed
drop-off, a missing index or a gone photo is 404. Without a valid session it is the 401
page and `PhotoStore` is never read. Photos and thumbnails have their own API route and
throttle (revision 15).

### web: phones and tablets

The console uses the form's layout partials: the band with "Ceramics console", "Signed
in as <username>" and Sign out, then the tab row. Under 40rem the band wraps, the tabs
scroll sideways, the cards stack and the drop-off page puts the details under the
photos. Buttons, chips, tabs, table links and Cancel links are at least 44 px tall
(`--tap-target`).

### web: what is logged

No line per request (uvicorn's access log is off). The console logs only `signed_in`,
`signed_out`, `sign_in_failed`, `sign_in_unavailable`, `auth_rejected`, `not_allowed`,
`csrf_refused` and `jwks_unavailable`, through `log_event`, with `user` the staff
username. No name, email, phone, message, search text, cookie or token is logged; the
reject panel's `Panel.message` and the requests' messages are left out of their reprs.

### app: `composition.build_console_services()`

`build_console_services(settings, staff, clients, staff_tokens) -> (ConsoleServices,
WebSettings)` builds `DynamoDbRecords`, `S3PhotoStore`, `SystemClock`, `SsmSecrets`,
`CurrentStudio` and `CognitoStaffTokens(issuer=, sign_in_origin=, client_id=)` from
`StaffSignIn.from_environment()`, then the use cases, into `web/console/services.py`'s
`ConsoleServices` (`staff_tokens`, `secrets`, `clock`, `studio`, `site_url` with
`callback_url` and `signed_out_url`, `waiting_list`, `find_drop_offs`, `view_drop_off`,
`view_photo`, `preview_rejection`, `reject_drop_off`, `undo_rejection`, `retry_email`,
`emails_needing_attention`). The `WebSettings.cookie_key` is the session key, read at
start. No `Mailer`: rejections go through the outbox. It refuses to start when a
`STAFF_*` variable is empty or the session key can't be read. `console_app()` is the
console function's app.

### infra: `infra/app.yaml`

- Parameters `StaffIssuer`, `StaffSignInUrl` and `StaffClientId`
  (`AWS::SSM::Parameter::Value<String>`, defaults `/config/cognito/staff/issuer`,
  `/config/cognito/staff/sign-in-url` and
  `/config/cognito/staff/ceramics-staff-app-client-id`), resolved at each deploy: a
  missing one fails the change set and changes nothing.
- `ConsoleFunction` (`${ProjectSlug}-${AppEnv}-console`, 1024 MB, 29 s, reserved
  concurrency 25, the Web Adapter layer, `APP_ROLE=console` and the three `STAFF_*`
  variables, no `Events`), its `ConsoleLogGroup` (90 days on prod, 14 on stage), and the
  role statements listed in revision 10: no `ses:SendEmail`, no `UpdateItem`.
- `ConsoleIntegration` (AWS_PROXY, payload 2.0), `ConsoleRoute` (`ANY /console`),
  `ConsoleProxyRoute` (`ANY /console/{proxy+}`), `ConsolePhotosRoute`
  (`GET /console/drop-offs/{id}/photos/{proxy+}`) and `ConsoleInvokePermission`; the
  stage's `RouteSettings` give `ANY /console/{proxy+}` burst 40 and 10 a second, and the
  photos route burst 100 and 30 a second. The console's routes take precedence over the
  form's `$default`.
- No alarm of its own: `ConsoleLoggedErrorsFilter` feeds the shared `LoggedErrors`
  metric, and the console is in `FunctionErrorsAlarm` (revision 11).

### infra: `scripts/smoke.py`

Two checks after the form's, with no credentials (revision 12): `console`, `GET
/console` is a `302` to `/console/auth/sign-in?next=%2Fconsole`, which is a `302` to an
`https` address on another host, path `/oauth2/authorize`, with `client_id`,
`code_challenge_method=S256` and `redirect_uri` `<site>/console/auth/callback`, and sets
`__Host-signin`; `console-photo`, a photo's console address without a session is a
`401` and no image.

## Tests

`tests/web/console/test_auth.py`:

- `test_a_console_page_without_a_session_redirects_to_sign_in_with_next`
- `test_sign_in_sets_a_signed_state_cookie_and_redirects_to_the_authorize_endpoint`:
  `response_type=code`, `scope=openid email`, `code_challenge_method=S256`, the redirect URI.
- `test_callback_with_a_wrong_state_is_refused_and_sets_no_session`
- `test_callback_with_an_old_or_tampered_signin_cookie_is_refused`
- `test_callback_for_a_group_member_sets_the_session_and_returns_to_next`
- `test_callback_for_someone_outside_the_group_shows_not_allowed_and_sets_no_session`
- `test_next_pointing_off_site_is_replaced_by_the_console` (parametrized: `//evil.example`,
  `https://evil.example`, `/\\evil`, `javascript:x`, `/form`)
- `test_a_token_without_groups_is_not_allowed` (expired, another client, an access token and
  other groups only are parametrized in `test_real_tokens.py`, revision 13)
- `test_not_allowed_names_the_facilities_manager_and_links_to_the_form`
- `test_unavailable_signing_keys_answer_503`
- `test_sign_out_clears_the_session_and_goes_to_the_staff_logout`
- `test_sign_out_without_the_csrf_token_is_refused` (also from the not-allowed page)
- `test_sign_out_with_a_stale_session_only_clears_it`
- `test_sign_out_with_no_session_cookie_goes_to_signed_out`
- `test_the_signed_out_page_is_public_and_shows_nothing_personal`

`tests/web/console/test_real_tokens.py` (phase 4's verifier with a test RSA key and a
local JWKS, no network): a valid ID token is accepted; each of wrong `iss`, wrong `aud`,
`token_use=access`, expired, a key not in the JWKS, `alg=none`, and HS256 signed with the
public key is refused.

`tests/web/console/test_csrf.py`:

- `test_a_post_without_the_csrf_field_is_refused_and_changes_nothing`
- `test_a_post_with_another_sessions_csrf_token_is_refused`
- `test_a_post_from_another_origin_is_refused`
- `test_a_post_with_no_origin_and_a_console_referer_is_accepted`

`tests/web/console/test_emails.py`:

- `test_a_failed_ready_email_of_a_fired_drop_off_is_listed_after_its_load_leaves_the_loads_list`
- `test_the_band_links_to_the_list_only_when_an_email_needs_attention`
- `test_each_row_retries_its_own_email` (the form posts the row's ID, kind and occasion;
  a rejected email's `occasion` exactly as stored)
- `test_history_emails_are_not_listed` (a closed drop-off's, an undone rejection's)
- `test_the_list_shows_no_name_address_or_message`
- `test_the_list_needs_the_ceramics_group`

`tests/web/console/test_waiting.py`:

- `test_waiting_drop_offs_are_listed_oldest_first_with_days_waiting`
- `test_bisque_and_glaze_are_totalled_in_pieces_with_glaze_types_split`
- `test_overdue_drop_offs_are_counted_and_tagged_at_60_days`
- `test_search_finds_by_id` (parametrized: `AC-12`, `ac12`, `ac-12`, `12`, ` 12 `)
- `test_search_finds_by_any_part_of_the_name` (case-insensitive)
- `test_a_search_with_no_match_says_so`
- `test_the_firing_filter_shows_one_firing_type`
- `test_markup_in_a_name_is_shown_escaped` (a name of `<script>alert(1)</script>` is
  shown as text, and the response holds no `<script>alert`)
- `test_a_very_long_search_is_cut_not_refused`
- `test_search_is_a_post_and_the_text_never_reaches_a_url` (the search form's `method`
  is `post`; `GET /console?q=<a made-up name>` ignores `q` and shows the plain list; the
  `POST /console/search` response has no `Location` and no link holding the text)
- `test_a_search_without_the_csrf_token_is_refused`

`tests/web/console/test_dropoffs.py`:

- `test_the_drop_off_page_shows_every_photo_and_the_contact_details`
- `test_an_unknown_or_malformed_id_is_404` (`AC-999`, `AC-0`, `ac-12`, `AC-12x`)
- `test_photos_are_served_to_staff_with_private_caching_and_nosniff`
- `test_photos_without_a_session_never_read_the_store` (a 401; the fake `PhotoStore`
  records no read)
- `test_a_closed_drop_off_shows_no_details_and_no_photos`
- `test_other_without_a_message_is_refused_next_to_the_field_and_stores_nothing`
- `test_a_message_of_1001_characters_is_refused`
- `test_a_retired_reason_is_refused`
- `test_the_preview_is_a_post_and_its_message_never_appears_in_a_url` (a GET to the
  preview path is 405; no redirect `Location` holds the message)
- `test_photos_are_served_with_no_store`
- `test_the_preview_is_the_email_that_is_sent`: preview, then reject, then run
  `SendPendingEmail` with the fake `Mailer`; the sent subject and HTML (with `cid:`
  references) equal the preview's, photo addresses aside.
- `test_rejecting_a_drop_off_in_a_load_is_refused`
- `test_a_rejection_records_the_username_and_queues_one_email`
- `test_rejecting_twice_is_refused_and_queues_no_second_email`
- `test_a_conflicting_change_is_reported_and_nothing_is_stored`
- `test_undo_on_the_same_austin_day_puts_it_back_and_sends_nothing`
- `test_undo_the_next_day_is_refused` (the fake clock crosses Austin midnight, not UTC
  midnight)
- `test_retry_requeues_a_failed_email_only`

`tests/web/console/test_privacy.py`:

- `test_no_public_page_shows_contact_details`: with a drop-off whose made-up name, email
  and phone are unique strings, none of them appears in `/`, `/console/signed-out`,
  the not-allowed page, the sign-in redirect, or any error page.
- `test_nothing_logged_holds_a_name_email_phone_message_or_token`: runs sign-in, the
  waiting list with a name search, the drop-off page, a preview, a reject with a message
  and an undo, captures every log record, and checks none holds the made-up details, the
  message, the search text or the token.

`tests/repo/test_app_template.py` additions:

- `test_the_console_reads_only_kept_photos_and_its_session_key`
- `test_the_console_role_cannot_send_email_yet`
- `test_the_console_writes_with_put_item_only` (no `UpdateItem`, `ConditionCheckItem`,
  `DeleteItem` or `Scan`)
- `test_the_console_routes_go_to_the_console_function_only`
- `test_the_staff_sign_in_values_come_from_parameter_store`

## Acceptance criteria

1. A request for any `/console` page without a session is redirected to the staff
   sign-in and, after signing in, returns to the page asked for (#3).
2. A signed-in person outside the `ceramics` group sees "You don't have access to the
   ceramics console. Ask the Facilities Manager to add you to the ceramics group." and
   no drop-off (#3).
3. A token that is expired, for another client, an access token, or without the
   `ceramics` group never reaches a use case.
4. Waiting drop-offs are listed oldest first with ID, name, pieces, firing type, glaze
   type, a thumbnail and days waiting; bisque and glaze are each totalled in pieces (#3).
5. Opening a drop-off shows all its photos at full size, only to the group; a photo's
   console address without a session is a 401 "Sign in" page, not the photo (#3, #2).
6. One search box finds drop-offs by `AC-12`, `ac12`, `12` or any part of the name (#3);
   the search is sent as a POST, so the text never appears in a URL, the browser's
   history or a log.
7. Contact details appear only on console pages, never on a public page or in a log (#3).
8. Staff pick a reason from the console's list and may write a message of up to 1,000
   characters; a reason that needs a message refuses an empty one, next to the field,
   storing nothing (#5).
9. Before sending, staff see the email exactly as it will go out, and the sent email
   equals it (#5).
10. A rejection queues one "Your drop-off needs attention" email; the drop-off leaves the
    waiting list and can't join a load (#5).
11. A rejection can be undone the same Austin day, sending no email; the next day it
    can't (#5).
12. A failed email can be sent again from the drop-off's page (#4, part).
13. Every email needing attention (failed, or stuck pending or sending, and not history),
    studio-wide and oldest first, is listed at `/console/emails` with "Try sending
    again", and the console's band links to it whenever there is one, so a fired
    drop-off whose ready email never went out is never out of sight after its load
    leaves the loads list (#4, #7). The list shows IDs and states only.
14. A console POST without the right CSRF token or from another origin changes nothing.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest tests/web/console -q
uv run pytest --cov
uvx cfn-lint==1.57.1 infra/*.yaml
sam validate --lint -t infra/app.yaml
```

After the merge, once the deploy's smoke tests pass on stage and prod:

1. On stage, from a phone, open `https://ceramics-stage.asmbly.org/console`. You are
   sent to the staff sign-in; after signing in as a ceramics staff member you land on
   "Waiting to fire".
2. Make a drop-off on stage's form with made-up details (a name like "Test Potter",
   a mailbox the tester owns, a made-up phone), then find it by its number and by part of
   the name. Its photos open at full size.
3. Reject it with "Other" and no message: the message field says it's needed. Add a
   message, preview, send. The email arrives as previewed. Undo the rejection: it is
   waiting again and no email arrives.
4. Sign in as a staff user outside the `ceramics` group: "not allowed".
5. Copy a photo's console address into a private window: it says to sign in (401), and
   shows no photo.
6. Check the console's log group for the session: no name, address, phone or message.
7. With 30 or more waiting drop-offs on stage (made-up details), open the waiting list on
   two devices at once and scroll to the end: every thumbnail loads, and `api-5xx` stays
   quiet. This is the first time the console's role meets real IAM (`GetItem` and
   `Query` by leading key, the transactional `PutItem`, the S3 list fallback): a reject
   and an undo on stage exercise them.

## Rollout

- **What is done:** the merge deploys `asmbly-ceramics-stage`, then
  `asmbly-ceramics-prod`, adding the console function, its role and routes, and the
  staff sign-in parameters.
- **Check:** the smoke test's two console checks on each environment; then the stage
  checks under Verification, done by the maintainer and one ceramics staff member.
- **Who confirms:** the maintainer, and one ceramics staff member who signs in on stage.
- **Before prod:** the smoke test is unauthenticated, so none of the signed-in steps runs
  before prod deploys. Either turn on prod's required reviewer for this merge (decision
  0003's environments) and approve after the stage checks, or accept that the signed-in
  checks come after prod; the prod console stays unused until staff are told its address.
- **Undo:** a revert pull request. Its deploy removes the console function, role and
  routes; the table, bucket and drop-offs are untouched. Rejections made meanwhile stay
  in the records.

If asmbly-staff-login's client or its parameter is missing, the deploy's change set
fails while resolving `StaffClientId` and the stack stays as it was; nothing needs
undoing.

## Admin actions

- **Before the merge**, in asmbly-staff-login: the `ceramics` group exists
  (asmbly-staff-login#4); the `ceramics-staff` client exists, allowing the OAuth scopes
  `openid` and `email` (`sign_in_url` asks for both, and the test email needs the
  verified `email` claim; a client allowing `openid` only answers `invalid_scope`), with
  return URLs
  `https://ceramics.asmbly.org/console/auth/callback` and
  `https://ceramics-stage.asmbly.org/console/auth/callback` and sign-out URLs
  `https://ceramics.asmbly.org/console/signed-out` and
  `https://ceramics-stage.asmbly.org/console/signed-out`, and
  `/config/cognito/staff/ceramics-staff-app-client-id` is published
  (asmbly-staff-login#5 and its `apps/ceramics-staff.yaml` pull request). Check:
  `aws ssm get-parameter --name /config/cognito/staff/ceramics-staff-app-client-id`
  (read only) returns a value.
- **Before the stage check:** ceramics staff are in the `ceramics` group (Manage users,
  asmbly-staff-login#3), and one staff user outside it is available for the "not
  allowed" check.
- **After the merge:** confirm the shared alarms (logged errors, function errors), which
  now count the console too, reach the alarm topic's subscribers (phase 7's topic).

## Hand-off

Built on branch `feat/drop-off-and-firing-phases-7-9` (15 November 2026). Phase 9 can
rely on:

- **App factory.** `create_app(services: WebServices | None, settings, console:
  ConsoleServices | None = None)`; `create_from_environment` takes `APP_ROLE=console` and
  returns `composition.console_app(settings)`. `composition.build_console_services(settings,
  staff, clients, staff_tokens)` returns `(ConsoleServices, WebSettings)`; the console's
  `WebSettings.cookie_key` is the session key, read at start.
- **`web/console/services.py` `ConsoleServices`** (extend it): `staff_tokens`, `secrets`,
  `clock`, `studio` (`CurrentStudio`), `site_url` (with `callback_url` and
  `signed_out_url`), `waiting_list`, `find_drop_offs`, `view_drop_off`, `view_photo`,
  `preview_rejection`, `reject_drop_off`, `undo_rejection`, `retry_email`,
  `emails_needing_attention`.
- **`web/console/__init__.py` `console_routes()`**: add phase 9's routes to the list.
- **`web/console/auth.py`**: `require_staff(request) -> Staff` (a GET),
  `require_staff_post(request) -> (Staff, form)` (a POST: session, origin, CSRF, the
  bounded form), `require_staff_for_photo` (401 instead of a redirect).
  `web/console/common.py`: `Staff(member, token, csrf)`, `Answer`, `read_form`,
  `drop_off_id`, `not_found`, `render(request, template, context, staff, *, status,
  attention)` (the band's "Emails need attention (n)"), `phone_text`.
  `web/console/csrf.py`: `csrf_token(session_token, key)`, `check_csrf`, `check_origin`.
  `web/console/session.py`: the two cookies and the signed sign-in state.
- **Templates**: `console/layout.html` (the band, Sign out, the tab row with Loads at
  `/console/loads`, Weekly counts at `/console/counts`, Settings at `/console/settings`;
  pass `tab`; only `waiting` is marked current today: phase 9 adds the `aria-current`
  branches for its three tabs), `console/message.html` (a message, optional Sign in).
- **The drop-off page's email statuses and retry form** (`dropoffs.email_status`,
  `KIND_LABELS`, the form posting `occasion` and, from the emails list, `back=emails`).
  `retry` knows only `back=emails`: phase 9 extends it for the load page.
- **`use_cases/photos.py` `ViewPhoto`**, and `EmailNeedingAttention.drop_off_found`.
- **`adapters/aws/staff_tokens.py` `ThrottledSigningKeys`**, `CognitoStaffTokens`' default
  key set.
- **Infra**: `ConsoleFunction` (role statements `ReadRecords`, `QueryEmailsOfADropOff`,
  `QueryIndexes`, `WriteRecords`, `ReadKeptPhotos`, `ListKeptPhotos`, `ReadSessionKey`).
  Phase 9 must add: `ses:SendEmail` (the test email), `UpdateItem` on `COUNTER#load`,
  `LOAD#*` to `WriteRecords`' `LeadingKeys` (a load is put), and `STUDIO` to
  `QueryEmailsOfADropOff`'s `LeadingKeys` (or a statement of its own) for the settings
  history (`records.history` queries the table's `STUDIO` partition), changing the pins
  in `tests/repo/test_app_template.py`'s console tests with them. `ConsoleLogGroup`,
  `ConsoleLoggedErrorsFilter`, the console in `FunctionErrorsAlarm`, `ConsoleIntegration`,
  `ConsoleRoute`, `ConsoleProxyRoute`, `ConsolePhotosRoute`, `ConsoleInvokePermission`,
  the stage's `RouteSettings` for `ANY /console/{proxy+}` and the photos route, and the parameters `StaffIssuer`,
  `StaffSignInUrl`, `StaffClientId`. The smoke test's `console` and `console-photo`
  checks.

- **Behaviour to keep**: a console POST without a valid session answers the 401 "that
  wasn't saved" page, never a redirect; sign-out with no session or a stale one goes to
  `/console/signed-out`; a waiting-list row says whether it is waiting
  (`WaitingRow.waiting`), so a template never compares state strings; a Cancel link
  carries `class="cancel"` for the 44 px tap target.

Checked at hand-off (15 November 2026): `ruff check`, `ruff format --check`, `mypy` and
`pytest --cov` pass on the branch. Not yet checked: anything live. The console has not
been deployed, so the stage checks under Verification, the first meeting of the role
with real IAM and the admin actions in asmbly-staff-login are still to do.

Deferred: following the sign-in redirect to Cognito in the smoke test (see the prep
revisions); the console in `web/local.py` (the laptop app serves the form only). Left
for the run's docs step: `README.md`, `docs/architecture.md` and `CLAUDE.md` still say
the console isn't built.
