# 0004: The form's role may clean up its own photos and seed the studio, and the photo bucket is named with a random suffix

Status: proposed, 15 November 2026, with phase 7 of the plan for epic #1
([phase 7](../../.implementation_plans/drop-off-and-firing/phase-7-first-deploy.md)).
It amends [0002](0002-how-the-app-is-built-and-deployed.md): the form function's row in
"Hosting" (what the form may do) and the bucket's name in "Photos go straight to S3".
It becomes accepted when the maintainer says so; the plan's Admin actions ask for his
word on each of the four points before phase 7 merges.

Decision 0002 says the public form may "create new drop-offs, their outbox emails and
submissions; issue upload slots; read settings and its own submissions, never a
drop-off", and names the photo bucket `asmbly-ceramics-<env>-photos-<account>`. Building
the use cases (phases 2a and 2b), the adapters (phase 4) and the template (phase 7)
showed four places where the form's role, or the bucket's name, can't be what 0002
says. The reviews of phases 2b and 4 asked for them to be recorded here rather than
only in a pull request's Risk section.

## The form may delete photos under `dropoffs/`

**Chosen:** the form function's role has `s3:DeleteObject` (with `s3:PutObject`) on
`dropoffs/*` in its environment's photo bucket. It never has `s3:GetObject` there, and
never `s3:ListBucket` except under `uploads/`, so it can't read or list kept photos.

**Why:** a submit keeps the photos (`dropoffs/AC-n/<k>.jpg` and its thumbnail) before it
commits the drop-off. When the commit fails, or `keep` fails half way, the submit
deletes what it wrote, by the 12 keys it knows (phase 2b, step 7; phase 4), so no photo
is left without a record. A request cut off by its deadline still runs that cleanup: the
deletes run under a later cleanup deadline (`asmbly_ceramics.deadline.cleanup`). 0002 gave deleting kept photos to the close only.

**Consequence, accepted:** a form function whose code was taken over (it decodes hostile
images) could delete existing drop-offs' photos, by guessing `AC-n` keys. It still
couldn't read them. A photo a failed cleanup leaves behind has no record, so the close
never deletes it; the backstop for those (#19) is decided and built before prod takes
real drop-offs, so no photo outlives #7.

**Revisit if:** the submit can commit before it keeps the photos, or the backstop
(#19) shows the cleanup isn't needed.

## The form may put the studio's first settings

**Chosen:** the form's role has `dynamodb:PutItem` on items whose partition key is
`STUDIO` (`STUDIO/CURRENT` and `STUDIO/HISTORY#…`), for phase 2a's first-use seeding:
the first read of an empty table stores the starting studio, its sending address from
`INITIAL_SENDING_ADDRESS`, with a conditional put that does nothing once it exists.

**Why:** in phase 7 the form is the only function that reads the studio before anything
else does (the mailer is built with `seed=False`: an email exists only after a submit,
which read the studio first). The console comes in phase 8. Seeding from the deploy
would give the deploy role rights over the table's data, which no other part of the
design needs.

**Consequence, accepted:** a taken-over form function could rewrite the studio's
settings and lists (a `Put` over the existing item). The sending address stays limited
to `asmbly.org`: the domain checks it, and the mailer's role may send only with
`ses:FromAddress` `*@asmbly.org`.

**Revisit if:** the console (phase 8) or a deploy step can seed the studio without
data rights, after which the form's `STUDIO` right can go.

## The form's `PutItem` on drop-offs and emails can't require a new item

**Chosen:** restating what 0002 already accepts: the form's role has `dynamodb:PutItem`
on `DROPOFF#*`, `EMAIL#*` and `SUBMISSION#*` items, which a submit's transaction needs.
IAM has no condition that requires `attribute_not_exists` on a put, so the right also
allows overwriting an existing item.

**Why:** a transaction is authorized item by item as the actions it holds (DynamoDB's
"Using IAM with DynamoDB transactions"); there is no narrower right that still lets a
submit create its items.

**Consequence, accepted:** a taken-over form function could rewrite an existing
drop-off's email address and queue an email that sends that drop-off's photos there.
The mailer re-reads each drop-off by key, so only an overwritten drop-off is affected. It can't read
the item it overwrites: every put the form (and the mailer) may make carries
`dynamodb:ReturnValues` `NONE` (`StringEqualsIfExists`), which also covers
`ReturnValuesOnConditionCheckFailure` (AWS's "Using IAM with DynamoDB transactions",
example 4), and those puts are allowed only inside a `TransactWriteItems`
(`dynamodb:EnclosingOperation`, the same page's example 2), so neither `ALL_OLD` answer
is allowed and no plain put can be used to probe an item.

**Revisit if:** DynamoDB offers a condition key that sees a put's condition expression.

## The photo bucket is named with a random suffix, not the account ID

**Chosen:** the bucket is `asmbly-ceramics-<env>-photos-<suffix>`, where the suffix is
eight random lowercase hexadecimal characters per environment, the template parameter
`PhotoBucketSuffix` in `samconfig.toml`. Changing it replaces the bucket.

**Why:** the presigned POST the form hands the browser names the bucket in its `url`
(`https://<bucket>.s3.us-east-2.amazonaws.com/`), and the page's Content-Security-Policy
names it in `connect-src`. With the account ID in the name, the public form would show
the account ID to anyone who opens it, which CLAUDE.md keeps out of every file. Bucket
names are global, so something must keep the name unique; a random suffix does that
without saying anything about the account. The bootstrap's names (`${ProjectSlug}-*-photos-*`)
already match it.

**Consequence, accepted:** the bucket's name is public (it always was, in the form), so
anyone can try requests against it; every one without the functions' roles gets
"access denied" (all public access blocked, TLS only, no `Allow` in its policy). The
suffix keeps the account ID out of the bucket's name and out of every file; it doesn't
make the account ID secret. Each presigned POST also carries the form role's temporary
access key ID (`X-Amz-Credential`), from which AWS's `sts get-access-key-info` gives the
account ID to anyone. Nothing in the design relies on the account ID being secret.

**Revisit if:** the photos move behind the app's own upload endpoint, so the bucket's
name is never shown.

## What has and has not been seen to work

Checked on 15 November 2026, without AWS changes: the template (`infra/app.yaml`) passes
`cfn-lint` and `sam validate --lint`, and `tests/repo/test_app_template.py` pins each
right above. Not yet seen: the first stage deploy, which shows the per-item
authorization of the submit's transaction and S3's answer to an oversized upload.
