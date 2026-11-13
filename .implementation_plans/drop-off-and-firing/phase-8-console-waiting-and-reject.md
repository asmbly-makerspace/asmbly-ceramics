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

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md): the rules on personal details, staff access and AWS.
- [The plan's README](README.md): the domain model, ports and use cases this phase calls.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md),
  "Staff sign-in is checked by the app on every request".
- [Phase 3](phase-3-load-and-studio-use-cases.md) (`RetryEmail`) and
  [phase 2](phase-2-drop-off-use-cases.md) (`WaitingList`, `FindDropOffs`,
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
undo a rejection the same day, and retry a failed email. Anyone not signed in is sent to
the sign-in and back; anyone signed in but not in the group sees "not allowed". After
this phase #3 is done and #5 is done.

## Files to create

| Path | What |
| --- | --- |
| `src/asmbly_ceramics/web/console/__init__.py` | `console_routes(services: ConsoleServices) -> list[BaseRoute]`, mounted at `/console` by `create_app` |
| `src/asmbly_ceramics/web/console/auth.py` | Sign-in, callback, sign-out, signed-out routes; `require_staff` (the per-request check) |
| `src/asmbly_ceramics/web/console/session.py` | The `__Host-session` and `__Host-signin` cookies: set, read, clear; the signed sign-in state |
| `src/asmbly_ceramics/web/console/csrf.py` | `csrf_token(member)`, `check_csrf(request, member)`, `check_origin(request)` |
| `src/asmbly_ceramics/web/console/waiting.py` | `GET /console` |
| `src/asmbly_ceramics/web/console/dropoffs.py` | The drop-off page, its photos, the rejection preview, reject, undo, retry |
| `src/asmbly_ceramics/web/templates/console/layout.html` | The console's band, "Signed in as", Sign out, the tab row (Waiting (n), Loads, Weekly counts, Settings) |
| `src/asmbly_ceramics/web/templates/console/waiting.html` | The waiting list |
| `src/asmbly_ceramics/web/templates/console/drop_off.html` | One drop-off, with the reject panel and the email statuses |
| `src/asmbly_ceramics/web/templates/console/reject_preview.html` | The rejection email, exactly as it will go out, with Send rejection and Cancel |
| `src/asmbly_ceramics/web/templates/console/not_allowed.html` | The 403 page |
| `src/asmbly_ceramics/web/templates/console/signed_out.html` | The public "You're signed out" page |
| `tests/web/console/__init__.py` | |
| `tests/web/console/conftest.py` | A `console_client` fixture: `create_app` over the fakes, with a `StaffTokens` fake that accepts made-up tokens; `signed_in(client, groups=("ceramics",))` |
| `tests/web/console/test_auth.py` | Sign-in, callback, the per-request check, sign-out |
| `tests/web/console/test_csrf.py` | Forged requests |
| `tests/web/console/test_waiting.py` | The waiting list and search |
| `tests/web/console/test_dropoffs.py` | The drop-off page, photos, preview, reject, undo, retry |
| `tests/web/console/test_privacy.py` | Nothing personal on public pages or in logs |
| `tests/web/console/test_real_tokens.py` | The same per-request check through phase 4's real verifier, with tokens signed by a test key |

## Files to modify

| Path | Change |
| --- | --- |
| `src/asmbly_ceramics/web/app.py` | `WebServices` gains `console: ConsoleServices \| None`; `create_app` mounts `console_routes` when it is set (the form function's app has `None`, so `/console` is not served there) |
| `src/asmbly_ceramics/composition.py` | `build_console_services() -> ConsoleServices` and `console_app()` (the console function's ASGI app) |
| `src/asmbly_ceramics/web/app.py` (`create_from_environment`, from phase 7) | Accepts `APP_ROLE=console` and returns `composition.console_app()`; `entry/run.sh` is unchanged |
| `infra/app.yaml` | `ConsoleFunction`, its role, its log group, the routes, the three staff sign-in parameters, a `ConsoleErrorsAlarm` |
| `scripts/smoke.py` | Two console checks (below) |
| `tests/repo/test_app_template.py` (from phase 7) | Pins for the console's role and routes |
| `.implementation_plans/drop-off-and-firing/README.md` | Phase 8's status, when the work starts and when it is merged |

## Implementation details

### web: who may reach what

| Path | Method | Who | Calls |
| --- | --- | --- | --- |
| `/console` | GET | `ceramics` | `WaitingList`, `FindDropOffs` |
| `/console/drop-offs/{id}` | GET | `ceramics` | `ViewDropOff` |
| `/console/drop-offs/{id}/photos/{k}` | GET | `ceramics` | `PhotoStore.read` through `ViewDropOff`'s photo refs |
| `/console/drop-offs/{id}/photos/{k}/thumb` | GET | `ceramics` | the same, thumbnail |
| `/console/drop-offs/{id}/reject/preview` | POST | `ceramics`, CSRF | `PreviewRejection` |
| `/console/drop-offs/{id}/reject` | POST | `ceramics`, CSRF | `RejectDropOff` |
| `/console/drop-offs/{id}/undo-reject` | POST | `ceramics`, CSRF | `UndoRejection` |
| `/console/drop-offs/{id}/emails/{kind}/retry` | POST | `ceramics`, CSRF | `RetryEmail` |
| `/console/auth/sign-in` | GET | anyone | (starts sign-in) |
| `/console/auth/callback` | GET | anyone holding a valid `__Host-signin` | `StaffTokens.exchange`, `StaffTokens.verify` |
| `/console/sign-out` | POST | `ceramics`, CSRF | (clears the session) |
| `/console/signed-out` | GET | anyone | (static page) |

`{id}` must match `AC-[1-9][0-9]{0,8}`; anything else is 404 before any use case runs.
`{k}` is 1 to 6; `{kind}` is `received`, `ready` or `rejected`.

### web: the per-request check (`auth.require_staff`)

Every route above except sign-in, callback and signed-out goes through
`require_staff(request) -> StaffMember`, before anything else:

1. No `__Host-session` cookie: a GET is answered `302` to
   `/console/auth/sign-in?next=<the path and query>`; a POST gets `303` to the same
   (the form's data is not kept).
2. `StaffTokens.verify(token)` (phase 4) checks the signature against the pool's keys,
   `iss == STAFF_ISSUER`, `aud == STAFF_CLIENT_ID`, `token_use == "id"`, `exp` (with no
   leeway beyond 60 seconds), and that `cognito:groups` contains `ceramics`. It returns
   `StaffMember(username, email)` from `cognito:username` and `email` (when
   `email_verified` is true; otherwise `email` is `None`).
3. `NotSignedIn` (bad signature, wrong issuer or audience, wrong use, expired): the
   cookie is cleared and the request is redirected as in 1. The log line is
   `event=auth_rejected` with `reason` set to the reason (`expired`, `bad_audience`,
   `bad_use`, `bad_signature`, `bad_issuer`), never the token.
4. `NotAllowed` (a valid token without the group, or with no `cognito:groups` claim):
   `403` with `not_allowed.html`: "You don't have access to the ceramics console. Ask
   the Facilities Manager to add you to the ceramics group.", a link to the drop-off form
   (`/`) and a "Sign in as someone else" button (a POST to `/console/sign-out` carrying
   the CSRF token for this session, like every other console POST, so another site
   can't sign staff out). Logged as `event=not_allowed`, `user=<username>`.
5. `SignInUnavailable` (the pool's keys can't be fetched): `503` with "The staff
   sign-in can't be checked right now. Try again in a minute." Logged as
   `event=jwks_unavailable` at ERROR, which the console's error alarm counts.

Every console response, including the 302, 403 and 503, carries the headers from
`web/security.py` (`Content-Security-Policy` with `form-action 'self'`, `nosniff`,
`Cache-Control: no-store`, `Referrer-Policy: no-referrer`).

### web: sign-in and sign-out

- **`GET /console/auth/sign-in?next=...`**: makes a PKCE verifier (32 random bytes,
  base64url) and a state (32 random bytes), and sets `__Host-signin` (HttpOnly, Secure,
  SameSite=Lax, Path=/, Max-Age=600) to `{verifier, state, next, iat}` signed with
  HMAC-SHA256 under the session key (`SESSION_KEY_PARAMETER`, read through `Secrets`).
  `next` is kept only if it is a relative path starting with `/console` and not `//`,
  without a scheme or backslash; otherwise `/console`. Then `302` to
  `StaffTokens.sign_in_url(state=..., code_challenge=S256(verifier), redirect_uri=SITE_URL + "/console/auth/callback")`,
  which builds `<STAFF_SIGN_IN_URL>/oauth2/authorize?response_type=code&client_id=...&redirect_uri=...&scope=openid&state=...&code_challenge=...&code_challenge_method=S256`.
- **`GET /console/auth/callback?code=...&state=...`**: refuses (400, "Sign-in didn't
  finish. Try again.", with a link to sign in) when the `__Host-signin` cookie is
  missing, its signature fails, it is older than 10 minutes, or its state doesn't match
  (compared with `hmac.compare_digest`); an `error=` from Cognito gets the same page.
  Otherwise `StaffTokens.exchange(code, verifier, redirect_uri)` posts to
  `<STAFF_SIGN_IN_URL>/oauth2/token`, and the returned ID token is verified as in the
  per-request check. A member of the group gets `__Host-session` set to the ID token
  (HttpOnly, Secure, SameSite=Lax, Path=/, Max-Age = `exp - now`), `__Host-signin`
  cleared, and `303` to `next`. Someone outside the group gets the 403 page and no
  session cookie. The access and refresh tokens are discarded. Logged as
  `event=signed_in`, `user=<username>`.
- **`POST /console/sign-out`**: clears `__Host-session` and `303`s to
  `<STAFF_SIGN_IN_URL>/logout?client_id=<STAFF_CLIENT_ID>&logout_uri=<SITE_URL>/console/signed-out`.
  Logged as `event=signed_out`.
- **`GET /console/signed-out`**: "You're signed out of the ceramics console." with a
  "Sign in" link and a link to the drop-off form. No details.

The ID token is about 1 to 2 KB, under the 4 KB cookie limit. Tokens last 60 minutes and
are not refreshed (asmbly-staff-login's web clients get a 60-minute refresh token, its
add-an-app open question 2), so staff sign in again about hourly; the managed-login
session usually makes that one tap.

### web: forged requests (`csrf.py`)

- `csrf_token(member, token)` is HMAC-SHA256 under the session key of
  `sub + ":" + auth_time` from the verified token, base64url. Every console form has it
  as the hidden field `csrf`.
- `check_csrf` runs on every console POST after `require_staff`: a missing or wrong
  `csrf` field is `403` "This form has expired. Go back, reload the page and try
  again." and `event=csrf_refused`.
- `check_origin`: every console POST must carry `Origin` equal to `SITE_URL` (or, when
  the browser sends no `Origin`, a `Referer` starting with `SITE_URL + "/console"`);
  otherwise the same 403. SameSite=Lax on the session already keeps a cross-site POST
  from carrying the cookie; these two checks hold even if it didn't.

### web: the waiting list (`GET /console`)

Calls `WaitingList(now)` and, when `q` is set, `FindDropOffs(q)`. Shows, as in the
design's "Waiting to fire" screen:

- the heading "Waiting to fire", "Oldest first.", a "Find a drop-off" search box
  (`type=search`, placeholder "AC-12, 12 or part of a name"), and "Start a load"
  (a link to `/console/loads`, live from phase 9);
- three cards: Bisque (pieces, in n drop-offs), Glaze (pieces, in n drop-offs, then the
  split by glaze type, e.g. "38 house dip, 14 commercial"), Overdue (drop-offs waiting
  60 days or more), as the use case's totals give them;
- a Show filter (All, Bisque, Glaze, one per active firing type; `?firing=<item id>`),
  as links with `aria-pressed`;
- a table, oldest first: thumbnail (56 px, `/console/drop-offs/{id}/photos/1/thumb`,
  `alt="Photo of AC-12"`), ID (monospace), name, pieces, firing type (label and outline,
  not colour alone), glaze type or "—", days waiting ("today", "1 day", "n days", an
  "overdue" tag at 60 or more), and Open;
- no match: "No waiting drop-offs match that. Check the ID, or try part of the name."

`q` is at most 100 characters (longer is cut, not refused); it is passed to the use case
as typed and shown back escaped. The page is a single column under 40rem: the table sits
in a box that scrolls sideways, and the cards stack.

### web: one drop-off (`GET /console/drop-offs/{id}`)

Calls `ViewDropOff(id)`. Unknown ID: 404 "There's no drop-off AC-999." Shows:

- the ID (monospace, `ceramics-shade`), the name, the firing type tag, and the state
  ("Waiting n days", "In load L-4", "Fired Nov 9", "Rejected today: Has glaze issues",
  "Closed");
- every photo at full size (`/console/drop-offs/{id}/photos/{k}`, `alt="Photo k of n"`),
  stacked, each `max-width: 100%`;
- Details: pieces, firing, glaze type, dropped off (Austin time), email, phone. A closed
  drop-off shows "Closed on <date>; its contact details and photos were deleted." and
  none of them;
- Emails: each of the drop-off's emails with its status (Sent, Waiting to send,
  Failed: "Sending failed (code)") and, for a failed one, "Try sending again" (a POST
  form to `.../emails/{kind}/retry`);
- when waiting: "Add to a load" (a link to `/console/loads`) and "Reject…";
- when rejected today: "Undo rejection" with "Undoing sends no email; contact the person
  directly." When rejected on an earlier day: no undo.

"Reject…" opens the panel on the same page (`?reject=1`), without a script: a Reason
select (the active rejection reasons, from `ViewStudio` through the use case's result),
a Message textarea (`maxlength=1000`, "(required for Other)" or "(optional)" from the
reason's `needs_message`), and "Preview the email", a GET form to
`/console/drop-offs/{id}/reject`.

### web: the rejection preview, reject and undo

- **`POST .../reject/preview`** (form fields `reason`, `message`, the CSRF token; a POST
  so the message, which is personal data, never sits in a URL, browser history or a log
  of query strings) calls
  `PreviewRejection(id, reason, message)`. Refusals are shown next to the field on the
  drop-off page's panel, with the typed message kept: unknown or retired reason ("Pick a
  reason from the list."), a reason that needs a message and none ("Write a message: this
  reason needs one."), a message over 1,000 characters ("Keep the message to 1,000
  characters; it has n."), a drop-off that isn't waiting ("AC-12 isn't waiting: it's in
  load L-4."). On success, `reject_preview.html` shows the composed email exactly as
  `mail/compose.py` builds it (To, From, Subject, then the HTML body inside a sandboxed
  frame-free box: the composed HTML is rendered by the composer with autoescape, then
  inserted as markup, with the photos as `/console/drop-offs/{id}/photos/{k}/thumb`
  in place of the `cid:` references), and a POST form with the reason and message as
  hidden fields, the CSRF token, "Send rejection" and "Cancel" (a link back).
- **`POST .../reject`** calls `RejectDropOff(id, reason, message, by=member.username)`,
  which re-checks everything (the preview is a convenience, the domain decides) and
  commits the rejection and the outbox email in one transaction. Success: `303` to the
  drop-off page with "AC-12 was rejected. The email is on its way." A conflict (someone
  changed it meanwhile): the page again with "AC-12 changed while you were looking.
  Check it and try again." and nothing stored. Logged `event=rejected`,
  `drop_off_id=AC-12`, `user`, `reason=<reason item id>`; never the message.
- **`POST .../undo-reject`** calls `UndoRejection(id, by, now)`. A rejection from an
  earlier Austin day: "A rejection can only be undone on the day it was made." Success:
  `303` with "AC-12 is waiting again. No email was sent." The rejection email already
  queued or sent is not recalled.
- **`POST .../emails/{kind}/retry`** (hidden field `occasion`: empty for received and ready, the rejection's time for a rejected email) calls `RetryEmail(id, kind, occasion, staff)`; success `303`
  with "The email to AC-12 will be sent again."; an email that isn't failed: "That
  email isn't failed." Logged `event=email_retried`.

### web: photos

`GET .../photos/{k}` and `.../thumb` answer, after `require_staff`, with the JPEG bytes
from `PhotoStore.read(ref)`, `Content-Type: image/jpeg`,
`Cache-Control: no-store` (a shared kiln tablet keeps no photo after sign-out),
`X-Content-Type-Options: nosniff` and
`Content-Disposition: inline; filename="AC-12-k.jpg"`. A closed drop-off or a missing
photo is 404. The request without a valid session never reaches `PhotoStore`: it gets
the sign-in redirect. The full-size copies are at most 2048 pixels (phase 2), well under
Lambda's 6 MB response; the Lambda Web Adapter returns them base64-encoded.

### web: phones and tablets

The console uses the same layout partials as the form (phase 6): the purple band with the
logo, "Ceramics console", "Signed in as <username>", Sign out; then the tab row. Under
40rem the band wraps, the tabs scroll sideways, cards stack, the drop-off page puts the
details under the photos, and every button and link is at least 44 px tall.

### web: what is logged

One line per request from phase 6's middleware (`event=request`, path template, status,
`user` when signed in), plus the events above. `drop_off_id`, `load_id`, `user`, `reason` and `error_code`
are the only identifying fields; no name, email, phone, message, query string, cookie or
token is logged. `q` is never logged.

### app: `composition.build_console_services()`

Builds, from the environment: `Records`, `IdNumbers`, `PhotoStore`, `Clock`, `Secrets`
and `StaffTokens` (phase 4's `CognitoStaffTokens(issuer=STAFF_ISSUER,
client_id=STAFF_CLIENT_ID, sign_in_url=STAFF_SIGN_IN_URL)`), then the use cases above
into `ConsoleServices`. It doesn't build a `Mailer`: in this phase the console sends
nothing itself (rejections go through the outbox). It refuses to start when any
`STAFF_*` variable is empty.

```python
@dataclass(frozen=True)
class ConsoleServices:
    staff_tokens: StaffTokens
    secrets: Secrets
    clock: Clock
    site_url: str
    waiting_list: WaitingList
    find_drop_offs: FindDropOffs
    view_drop_off: ViewDropOff
    preview_rejection: PreviewRejection
    reject_drop_off: RejectDropOff
    undo_rejection: UndoRejection
    retry_email: RetryEmail
    photos: PhotoStore
```

Phase 9 adds its use cases to this dataclass.

### infra: `infra/app.yaml`

New parameters, resolved from asmbly-staff-login's values when the stack deploys:

```yaml
  StaffIssuer:
    Type: AWS::SSM::Parameter::Value<String>
    Default: /config/cognito/staff/issuer
  StaffSignInUrl:
    Type: AWS::SSM::Parameter::Value<String>
    Default: /config/cognito/staff/sign-in-url
  StaffClientId:
    Type: AWS::SSM::Parameter::Value<String>
    Default: /config/cognito/staff/ceramics-staff-app-client-id
```

The execution role already has `ssm:GetParameters` on `parameter/config/cognito/staff/*`
(phase 5). If `ceramics-staff-app-client-id` doesn't exist yet, the change set fails to
create and nothing changes; that is why the client is an admin action before the merge.

New resources (names from `ProjectSlug` and `AppEnv`, tags from the stack):

```yaml
  ConsoleLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub /aws/lambda/${ProjectSlug}-${AppEnv}-console
      RetentionInDays: !If [IsProd, 90, 14]

  ConsoleFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub ${ProjectSlug}-${AppEnv}-console
      CodeUri: ../src
      Handler: asmbly_ceramics/entry/run.sh
      MemorySize: 1024
      Timeout: 29
      ReservedConcurrentExecutions: 5
      Layers: [!Ref WebAdapterLayerArn]
      LoggingConfig: {LogGroup: !Ref ConsoleLogGroup}
      Environment:
        Variables:
          APP_ROLE: console
          SESSION_KEY_PARAMETER: !Sub /${ProjectSlug}/${AppEnv}/session-key
          AWS_LAMBDA_EXEC_WRAPPER: /opt/bootstrap
          PORT: "8080"
          AWS_LWA_READINESS_CHECK_PATH: /health
          STAFF_ISSUER: !Ref StaffIssuer
          STAFF_SIGN_IN_URL: !Ref StaffSignInUrl
          STAFF_CLIENT_ID: !Ref StaffClientId
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Sid: Records
              Effect: Allow
              Action: [dynamodb:GetItem, dynamodb:Query, dynamodb:PutItem, dynamodb:UpdateItem, dynamodb:ConditionCheckItem]
              Resource: [!GetAtt RecordsTable.Arn, !Sub '${RecordsTable.Arn}/index/*']
            - Sid: Transactions
              Effect: Allow
              Action: dynamodb:TransactWriteItems   # authorised per item action above; listed for clarity
              Resource: !GetAtt RecordsTable.Arn
            - Sid: ReadKeptPhotos
              Effect: Allow
              Action: s3:GetObject
              Resource: !Sub '${PhotoBucket.Arn}/dropoffs/*'
            - Sid: ReadSessionKey
              Effect: Allow
              Action: ssm:GetParameter
              Resource: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/${ProjectSlug}/${AppEnv}/session-key'
      Events:
        Console:
          Type: HttpApi
          Properties: {ApiId: !Ref HttpApi, Method: ANY, Path: /console}
        ConsoleAnything:
          Type: HttpApi
          Properties: {ApiId: !Ref HttpApi, Method: ANY, Path: '/console/{proxy+}'}

  ConsoleErrorsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${ProjectSlug}-${AppEnv}-console-errors
      # the same shape as phase 7's FormErrorsAlarm: Lambda Errors > 0 in 5 minutes,
      # or the log metric filter level=ERROR; AlarmActions and OKActions: AlarmTopic
```

The shared environment variables (`APP_ENV`, `APP_VERSION`, `TABLE_NAME`,
`PHOTO_BUCKET`, `SITE_URL`, `INITIAL_SENDING_ADDRESS`, `LOG_LEVEL`) come from phase 7's
`Globals`; the console function adds `SESSION_KEY_PARAMETER`
(`!Sub /${ProjectSlug}/${AppEnv}/session-key`) itself. The session key is the console's
alone: the form function's role can't read it, and the console's role reads no other
key (not `hash-key`, not `form-key`). `kms:Decrypt` for the SecureString through SSM comes from the function
boundary (phase 5). `dynamodb:TransactWriteItems` is checked by DynamoDB against the
`Put`/`Update`/`ConditionCheck` rights on the items, as phase 4's adapter uses it; phase
4's tests name the exact actions, and this statement must match them. The role's path
(`/asmbly-ceramics-app/`) and boundary come from `Globals`.

No `ses:SendEmail` here: the console sends its first email (the test email) in phase 9,
which adds the right then. The routes `ANY /console` and `ANY /console/{proxy+}` take
precedence over the form's `$default` route, so the form function never sees a console
path.

### infra: `scripts/smoke.py`

Two new checks, after the form's, against each environment, with no credentials:

1. `GET <SITE_URL>/console` answers `302`, its `Location` starts with the sign-in
   address `https://<auth-domain>/oauth2/authorize?` (the smoke test reads the expected
   host from the deploy's `STAFF_SIGN_IN_URL` stack output, `StaffSignInHost`, added in
   this phase), and carries `client_id=` and `code_challenge_method=S256`. The
   `__Host-signin` cookie is set.
2. `GET <SITE_URL>/console/drop-offs/AC-1/photos/1` without a cookie answers `302` to
   `/console/auth/sign-in`, never `200`, and no image bytes.

## Tests

`tests/web/console/test_auth.py`:

- `test_a_console_page_without_a_session_redirects_to_sign_in_with_next`
- `test_sign_in_sets_a_signed_state_cookie_and_redirects_to_the_authorize_endpoint`:
  `response_type=code`, `scope=openid`, `code_challenge_method=S256`, the redirect URI.
- `test_callback_with_a_wrong_state_is_refused_and_sets_no_session`
- `test_callback_with_an_old_or_tampered_signin_cookie_is_refused`
- `test_callback_for_a_group_member_sets_the_session_and_returns_to_next`
- `test_callback_for_someone_outside_the_group_shows_not_allowed_and_sets_no_session`
- `test_next_pointing_off_site_is_replaced_by_the_console` (parametrized: `//evil.example`,
  `https://evil.example`, `/\\evil`, `javascript:x`, `/form`)
- `test_an_expired_token_clears_the_cookie_and_redirects`
- `test_a_token_for_another_client_is_refused`
- `test_an_access_token_is_refused` (`token_use=access`)
- `test_a_token_without_groups_is_not_allowed`
- `test_a_token_with_other_groups_only_is_not_allowed`
- `test_not_allowed_names_the_facilities_manager_and_links_to_the_form`
- `test_unavailable_signing_keys_answer_503`
- `test_sign_out_clears_the_session_and_goes_to_the_staff_logout`
- `test_sign_out_without_the_csrf_token_is_refused` (also from the not-allowed page)
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

`tests/web/console/test_dropoffs.py`:

- `test_the_drop_off_page_shows_every_photo_and_the_contact_details`
- `test_an_unknown_or_malformed_id_is_404` (`AC-999`, `AC-0`, `ac-12`, `AC-12x`)
- `test_photos_are_served_to_staff_with_private_caching_and_nosniff`
- `test_photos_without_a_session_redirect_and_never_read_the_store` (the fake
  `PhotoStore` records no read)
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
   console address without a session is a redirect, not the photo (#3, #2).
6. One search box finds drop-offs by `AC-12`, `ac12`, `12` or any part of the name (#3).
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
13. A console POST without the right CSRF token or from another origin changes nothing.

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
5. Copy a photo's console address into a private window: it goes to the sign-in, not the
   photo.
6. Check the console's log group for the session: no name, address, phone or message.

## Rollout

- **What is done:** the merge deploys `asmbly-ceramics-stage`, then
  `asmbly-ceramics-prod`, adding the console function, its role and routes, and the
  staff sign-in parameters.
- **Check:** the smoke test's two console checks on each environment; then the stage
  checks under Verification, done by the maintainer and one ceramics staff member.
- **Who confirms:** the maintainer, and one ceramics staff member who signs in on stage.
- **Undo:** a revert pull request. Its deploy removes the console function, role and
  routes; the table, bucket and drop-offs are untouched. Rejections made meanwhile stay
  in the records.

If asmbly-staff-login's client or its parameter is missing, the deploy's change set
fails while resolving `StaffClientId` and the stack stays as it was; nothing needs
undoing.

## Admin actions

- **Before the merge**, in asmbly-staff-login: the `ceramics` group exists
  (asmbly-staff-login#4); the `ceramics-staff` client exists with return URLs
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
- **After the merge:** confirm the console's error alarm reaches the alarm topic's
  subscribers (it uses phase 7's topic).

## Hand-off

Filled in when the phase is done. Phase 9 relies on:

- `console_routes`, `ConsoleServices` (to extend), `require_staff`, `csrf_token`,
  `check_csrf`, `check_origin`, the console layout and its tab row;
- `ConsoleFunction`, its role (to gain `ses:SendEmail`), its log group and alarm;
- the drop-off page's email statuses and retry form, reused on the load's page;
- `build_console_services()` and `console_app()`.
