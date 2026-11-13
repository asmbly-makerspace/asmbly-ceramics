# 0002: The app is a Starlette app on Lambda, with DynamoDB, S3 uploads and SES, deployed with SAM

Status: proposed, 13 November 2026, with the plan for epic #1
([.implementation_plans/drop-off-and-firing/](../../.implementation_plans/drop-off-and-firing/README.md)).
It makes the choices [docs/architecture.md](../architecture.md#still-to-be-decided) left
open after [0001](0001-the-ceramics-studio-has-its-own-repository.md). It becomes
accepted when the maintainer approves the plan's pull request.

Epic #1 asks for a public drop-off form, a staff console, three emails with photos, and
the closing of finished drop-offs, for about 80 drop-offs and 6 firings a week. 0001
decided the language, the repository and the shape of the code (a domain model with AWS
behind ports) and left the framework, the hosting, the data store and the deploy to the
technical plan. The facts this record relies on were read from AWS's documentation on
13 November 2026; the plan's phase documents name each page.

## Pages are rendered on the server with Starlette and Jinja2

**Chosen:** a Starlette app (`src/asmbly_ceramics/web/`) that renders HTML with Jinja2,
autoescape on for every template. The only script in the browser is the drop-off form's
photo upload (it posts each photo straight to S3, below) and small conveniences that
the page works without, except for that upload.

**Why:** the app is pages and forms, not an API. Server-rendered pages keep the staff
token out of the browser's scripts, keep every check on the server, and need no build
step. Starlette is small, async, and runs under the Lambda Web Adapter as AsmblyMCPs'
servers do. FastAPI's gain is JSON APIs we don't have. A single-page app in the browser
would hold the staff token in script reach and double the code that checks input. The
facilities repository's `str.replace` pages are fine for one page and don't scale to
fifteen.

**Consequence, accepted:** the drop-off form needs JavaScript to upload photos (Lambda
can't receive 6 photos of 10 MB, below). Without it the page says so.

## Hosting: Lambda behind one HTTP API, one function per job

**Chosen:** Python 3.14 on arm64 Lambda, through the Lambda Web Adapter, behind one API
Gateway HTTP API per environment. Four functions, each with its own role:

| Function | Serves | May |
| --- | --- | --- |
| `asmbly-ceramics-<env>-form` | `/` and `/drop-off/...`, public | create new drop-offs, their outbox emails and submissions; issue upload slots; read settings and its own submissions, never a drop-off |
| `asmbly-ceramics-<env>-console` | `/console/...`, the `ceramics` group | read and change records, read photos, send a test email |
| `asmbly-ceramics-<env>-mailer` | the table's change stream | send the outbox's emails, read photos |
| `asmbly-ceramics-<env>-close` | a daily schedule | close finished drop-offs, delete their details and photos |

The addresses are `ceramics.asmbly.org` (prod) and `ceramics-stage.asmbly.org` (stage).
On 13 November 2026 neither name existed in the `asmbly.org` zone.

**Why:** the public form's role can then never read a photo, read or list a drop-off,
or change an existing email, whatever its code does: its ID page reads only the
submission it made, which carries a summary without contact details. An HTTP API is what AsmblyMCPs runs and costs less than a REST API; the
only REST feature we would use is AWS WAF, which an HTTP API can't have, and the rate
limit is enforced by the app instead (below). A container would run all week for 80
drop-offs.

**Consequence, accepted:** a request has 30 seconds and 6 MB each way (Lambda's
synchronous limit), so photos never pass through a function on the way in, and photos
staff open are re-encoded copies well under that. And IAM can't require
`attribute_not_exists` on a `PutItem`, so a form function whose code was taken over
(it decodes hostile images) could overwrite an existing drop-off item with a `Put`,
for example to change where its emails go. The mailer re-reads each drop-off by key,
so only an overwritten drop-off could be affected; that is accepted.

## The data store is one DynamoDB table; IDs come from a counter

**Chosen:** one on-demand DynamoDB table per environment,
`asmbly-ceramics-<env>-records`, with point-in-time recovery on and a recovery period
of 7 days, `DeletionPolicy: Retain`, and deletion protection. Drop-offs, loads, the
studio's settings and lists, their history, the email outbox, the ID counters and the
rate-limit counts are items in it. A change to several items is one
`TransactWriteItems` call with a version check on each, so two staff acting at once
can't both win. An ID is issued by an `UpdateItem ADD` on the counter item, then
written with `attribute_not_exists`, so no two drop-offs share an ID; a retry can skip
a number, never repeat one.

**Why:** pay per request, nothing to run, strong reads on the table, atomic counters and
transactions. A relational database would cost money while idle and need a network
setup; S3 has no atomic counter.

**Consequence, accepted:** a transaction holds at most 100 items, so a load holds at
most 48 drop-offs (firing it changes each drop-off and writes its email). Today's
largest load is 28. And a closed drop-off's personal details can be restored from the
table's backups for up to 7 days after it closes; [#7](https://github.com/asmbly-makerspace/asmbly-ceramics/issues/7)'s
deletion is complete after that.

## Photos go straight to S3 and are re-encoded on submit

**Chosen:** the form asks the server for up to 6 upload slots. Each is a presigned S3
POST to `uploads/<random>/<n>` in the private bucket `asmbly-ceramics-<env>-photos-<account>` (bucket names are global),
valid for 15 minutes, with `content-length-range` 1 byte to 10 MB and
`Content-Type` starting `image/`. On Submit the server reads each upload, checks with
Pillow that it is really a JPEG, PNG or WebP image (refusing anything else, HEIC
included, and Pillow's decompression bombs), turns it upright, and saves two copies
without their EXIF data (so no location leaves the studio): `dropoffs/AC-n/<k>.jpg`
(at most 2048 pixels on the long side) and `dropoffs/AC-n/<k>-thumb.jpg`. A lifecycle
rule deletes whatever is left under `uploads/` after a day. Staff see photos only through
the console, which reads them from S3 and returns them to a signed-in member of the
`ceramics` group. The bucket blocks all public access, enforces bucket-owner ownership,
encrypts with SSE-S3, and denies requests without TLS.

**Why:** a 10 MB photo can't pass through Lambda six at a time, and a presigned GET
link for staff would let anyone holding it open the photo, which #2 forbids. Re-encoding
also makes the emails small: six photos fit well inside SES's 40 MB message limit.

**Consequence, accepted:** the form's photo field accepts `image/jpeg,image/png,image/webp`
so that an iPhone sends JPEG; a HEIC file that still arrives is refused next to the
field. That iPhones convert under that `accept` list rests on WebKit's bug tracker, not
Apple's documentation; the form is checked on a real iPhone before the switch (#8).

## The rate limit is counted in the table

**Chosen:** 10 submissions per device in 10 minutes (#2), where the device is a random
`__Host-device` cookie the form sets, and 30 per source address in 10 minutes, so that
clearing the cookie doesn't lift the limit while a studio's shared network isn't
blocked. Both are counted in DynamoDB under a keyed hash (HMAC with a secret from
Parameter Store) of the cookie or the address, never the value itself, and expire with
TTL. The address is the **last** value of `X-Forwarded-For`, which API Gateway's HTTP
API appends; anything earlier in the header is the caller's own text and is ignored, and
uvicorn doesn't read proxy headers at all. The limiter fails closed: if the table can't
be reached, no upload slot is issued and no drop-off accepted.

**Why:** AWS WAF's rate rules can't be attached to an HTTP API, and API Gateway's
throttling is per route, not per caller.

Note from phase 1d: the `RateLimiter` port counts in a rolling window, not a fixed one,
and phase 4's table design follows it.

## Staff sign-in is checked by the app on every request

**Chosen:** asmbly-staff-login gives this app a public client, `ceramics-staff`, with
the code flow and PKCE. The console exchanges the code on the server and keeps the ID
token in a `__Host-session` cookie (HttpOnly, Secure, SameSite=Lax). Every console
request checks the token's signature against the pool's keys (PyJWT, keys cached for an
hour), `iss`, `aud` (this app's client), `token_use=id`, `exp`, and that
`cognito:groups` holds `ceramics`; a token without the claim is in no group. Someone
not signed in goes to the staff sign-in and back; someone signed in but not in the group
sees "not allowed" and is told to ask the Facilities Manager. Every form that changes
something carries a CSRF token tied to the session, and the server also checks `Origin`.
The issuer, the sign-in address and the client ID come from asmbly-staff-login's
`/config/cognito/staff/*` values, resolved when the stack deploys.

**Why:** server-rendered forms need a cookie; the class photo page's browser-held token
suits a script-driven page. API Gateway's JWT authorizer could check the signature but
not send someone to sign in or show "not allowed", so the app checks everything itself,
in one place.

**Consequence, accepted:** web clients' refresh tokens last 60 minutes today, so staff
sign in again about hourly unless asmbly-staff-login lengthens it (its add-an-app open
question 2). Removing someone from the group takes effect when their token expires
(at most an hour).

## Email goes through an outbox

**Chosen:** each email (received, ready for pickup, needs attention) is an item in the
table, written in the same transaction as the change that causes it, keyed by the
drop-off and the kind so that the same email can't be queued twice. The mailer function
reads the table's stream, filtered to items whose new image has `status = pending`,
composes the message from the settings in force when it sends, and sends it with SES v2
from the console's sending address, with the drop-off's photos inline. A failure marks
the item `failed` with the error code (never the message), shows on the load's and the
drop-off's pages with "Try sending again", and counts toward a CloudWatch alarm that
notifies the maintainers. Sending is allowed to the app's roles only from addresses at
`asmbly.org` (`ses:FromAddress`), on the `asmbly.org` identity, which AsmblyMCPs'
`mcp-bootstrap` stack owns; that right is agreed in AsmblyMCPs before the first deploy.

**Why:** sending inside a request would lose a failed email, couldn't be retried, and
would race the 30-second limit when a load of 28 is fired. The stream gives at-least-once
delivery, so the mailer claims an item with a conditional update before sending.

## The deploy: SAM, a bootstrap stack, stage then prod

**Chosen:** AWS SAM, as AsmblyMCPs. A bootstrap stack, `asmbly-ceramics-bootstrap`,
deployed by a person by hand, holds the GitHub OIDC deploy role, the role CloudFormation
deploys with, the permissions boundary every function role carries, the artifacts
bucket, and the two API Gateway custom domain names with their certificates and their
records in the `asmbly.org` zone, which another project owns. The app stacks,
`asmbly-ceramics-stage` and `asmbly-ceramics-prod`, map their API to those names. A merge
to `main` deploys stage, runs the smoke test against it, then deploys prod and runs it
again. The bootstrap's roles live under the IAM path `/asmbly-ceramics-bootstrap/` and
the app's under `/asmbly-ceramics-app/`, so a stack can never edit the roles that deploy
it; CloudFormation's role may create only resources tagged `Project=asmbly-ceramics`
(`aws:RequestTag`) and change only resources carrying that tag (`aws:ResourceTag`) where
the service supports those keys, is limited to `asmbly-ceramics-` names everywhere, and
is denied everything on resources tagged with another project. Every resource carries
`Project=asmbly-ceramics`, `Component`, `Environment`, `Owner=it-volunteers` and
`ManagedBy` (`sam` for the app stacks, `cloudformation` for the bootstrap).

**Why:** the same tool and the same shape as the sibling repositories, with the tag
conditions `CLAUDE.md` asks for, which AsmblyMCPs lacks (AsmblyMCPs#9). A stage
environment lets staff try the console before the switch and catches a bad deploy
before prod.

**Consequence, accepted:** stage sends real email to whoever uses its form, from the
same identity. Neither form's address is secret before the switch: both names appear in
Certificate Transparency logs as soon as the bootstrap's certificates are issued. Anyone
can make a drop-off giving any email address, which then receives one "We received your
drop-off" email, from the studio's address, with the photos the sender uploaded. That is
inherent in #2's form without sign-in; it is limited by the per-device and per-address
limits and by each email going only to the one address typed. No gate is added for
stage; the maintainer can ask for one (the plan's open questions).

## The scheduled close runs daily, Austin time

**Chosen:** an EventBridge Scheduler schedule, `asmbly-ceramics-<env>-close`, runs the
close function every day at 03:17 America/Chicago, with retries and a dead-letter queue.

**Why:** Scheduler takes a time zone; EventBridge's scheduled rules run in UTC only and
are now AWS's legacy option.

## What has and has not been seen to work

Nothing is built. On 13 November 2026 the plan's research read AsmblyMCPs,
asmbly-staff-login and the facilities repository, and AWS's documentation for each
behavior above; the plan names each page. Not yet seen: an iPhone's upload under the
`accept` list above, S3's answer to a too-large POST (the documentation lists
`EntityTooLarge` without tying it to `content-length-range`), and SES sending from this
account for another project.
