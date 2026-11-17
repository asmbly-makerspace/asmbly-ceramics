# Operations: the app stacks

The app's stacks, `asmbly-ceramics-stage` and `asmbly-ceramics-prod`, come from
`infra/app.yaml` and change only through a merge to `main` and its **Deploy** run
(`.github/workflows/deploy.yml`). This runbook says what a merge does, how to roll one
back, and the few steps the maintainer takes by hand. Run a by-hand step only when the
maintainer asks for it, in the conversation, for that step; they need his own
credentials (`AWS_PROFILE=asmbly`, us-east-2), since the deploy roles can't do them.

Never read a drop-off's details or photos with the CLI. Counts and names only.

## What a merge deploys

1. **Deploy stage**: builds the functions (`sam build`), checks the built mailer
   composes every email (`scripts/compose_check.py`), deploys `asmbly-ceramics-stage`,
   then runs `scripts/smoke.py` against `https://ceramics-stage.asmbly.org`.
2. **Deploy prod**: the same against `asmbly-ceramics-prod` and
   `https://ceramics.asmbly.org`, only after stage's smoke test passed.

Only the newest commit on `main` deploys: an older run notices a newer commit and
stops with "A newer commit is on main; it deploys itself." The run's summary shows each
environment's site, version and smoke result. Check: both smoke tests pass, and
`/health` shows the merge's short commit.

The smoke test never submits a drop-off and never sends an email. It prints S3's answer
to an oversized upload (the first run settles what that answer is).

## What to check on stage after a merge

The smoke tests don't open a load or a note. After a merge that changes loads, the
firing log or notes, walk this on stage (`https://ceramics-stage.asmbly.org/console`)
with made-up drop-offs only, before staff rely on prod:

1. A load page and the settings page open. A load started with a made-up drop-off can
   start firing and be marked fired; its emails are queued as before.
2. A test load with no drop-offs starts, fires with no email, takes a firing record, and
   has its fired time corrected; the load's history shows each change.
3. Settings › Kilns takes a kiln's counts; a made-up load fired afterwards suggests the
   next firing numbers. The firing log filters to tests, and its CSV opens in a
   spreadsheet.
4. A note with a glaze type, a clay body and a ruling is written on a load, edited and
   removed. The notes search finds it by glaze type, and the firing log's notes column
   counts it.

**Undo:** revert, as below. Event and note items already written stay in the table,
unread. A revert that predates the studio's new lists drops them on the next settings
save; staff set any they changed again.

## Roll back a change

**Do:** open a pull request that reverts the change, and merge it on the maintainer's
word. Its **Deploy** run puts the previous version back.
**Check:** both smoke tests pass, with the revert's commit in `/health`.
**Undo:** revert the revert.

The table and the photo bucket are never deleted by a deploy (`Retain`), so a rollback
loses no data. A revert of the pull request that added `deploy.yml` itself (phase 7)
removes the workflow, so no Deploy runs after it and the stacks stay as they are: take
the form offline (below) instead.

## Take the form offline at once

When the form must stop taking drop-offs now (abuse, a leak, a bad deploy that a revert
can't fix quickly):

**Do:** `aws lambda put-function-concurrency --function-name asmbly-ceramics-<env>-form --reserved-concurrent-executions 0`,
then set the GitHub environment `<env>`'s variable `FORM_OFFLINE` to `true`.
**Check:** `curl -s -o /dev/null -w '%{http_code}\n' https://<site>/health` no longer
answers 200 (API Gateway can't invoke the function; note the code it gives), and
`https://<site>/console/health` still does: the console has its own function, health
check and stylesheet (every `/console` path goes to it), so staff keep working.
**Undo:** `aws lambda put-function-concurrency --function-name asmbly-ceramics-<env>-form --reserved-concurrent-executions 5`,
then delete the variable `FORM_OFFLINE` (or set it to anything but `true`); check
`/health` answers 200.

While `FORM_OFFLINE` is `true`, each **Deploy**'s smoke test for that environment runs
only the console's checks and then checks the form's `/health` is *not* 200
(`scripts/smoke.py --form-offline`); without the variable, the smoke test fails at its
first check, `health`, on every deploy. Forgetting to delete it after the undo fails the
next smoke test at `form-offline`, which is how it is noticed. Whether a **Deploy** puts it back to 5 isn't known yet
(every deploy updates the function): the smoke test's `form-offline` check fails if
it did. While the form is meant to stay offline, check after each Deploy with
`aws lambda get-function-concurrency --function-name asmbly-ceramics-<env>-form` and set
it to 0 again if it changed. The first time on stage settles it; write the answer here.

The mailer keeps sending emails already queued. To stop it too, do the same for
`asmbly-ceramics-<env>-mailer`; the stream keeps its records for 24 hours, and the
mailer sends them if it's back within that time. After that the emails stay pending
until staff send them again from the console (phase 8).

## If the first create of a stack fails

A first create that is refused (a right the bootstrap lacks, decision 0003's
fail-closed cases) rolls back to `ROLLBACK_COMPLETE`. That stack can't be updated, only
deleted, and the deploy roles have no `cloudformation:DeleteStack` and no import. The
rollback keeps the table and the bucket (`Retain`), whose fixed names make the next
create fail too. So the maintainer recovers by hand, with his own credentials, one step
at a time as he asks for it. The examples are stage; prod is the same with `prod`.

### 1. Read why it failed

**Do:** `aws cloudformation describe-stack-events --stack-name asmbly-ceramics-stage --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]"`
and `aws cloudformation describe-stacks --stack-name asmbly-ceramics-stage --query "Stacks[0].StackStatus"`.
**Check:** the status is `ROLLBACK_COMPLETE`, and the events name the refused resource.
**Who confirms:** the maintainer. **Undo:** none: read only.

### 2. Check the retained table and bucket are empty

**Do:** `aws dynamodb scan --table-name asmbly-ceramics-stage-records --select COUNT` and
`aws s3api list-objects-v2 --bucket <the photo bucket> --max-keys 1 --query KeyCount`.
**Check:** `Count: 0` and `0`. A first create stores nothing; if either isn't empty,
stop and write it up: nothing below runs.
**Who confirms:** the maintainer. **Undo:** none: read only, counts only.

### 3. Delete the failed stack

**Do:** `aws cloudformation delete-stack --stack-name asmbly-ceramics-stage`, then
`aws cloudformation wait stack-delete-complete --stack-name asmbly-ceramics-stage`.
**Check:** `describe-stacks` says the stack doesn't exist.
**Who confirms:** the maintainer. **Undo:** none needed: it held nothing; the next
Deploy creates it again.

### 4. Delete the empty table and bucket

Only after step 2 found both empty.

**Do:** `aws dynamodb update-table --table-name asmbly-ceramics-stage-records --no-deletion-protection-enabled`,
`aws dynamodb delete-table --table-name asmbly-ceramics-stage-records`, then
`aws s3api delete-bucket --bucket <the photo bucket>`.
**Check:** `describe-table` and `head-bucket` say they don't exist.
**Who confirms:** the maintainer. **Undo:** none needed: both were empty; the next
create makes them again.

### 5. Fix the cause

**Do:** a reviewed pull request: to the bootstrap (then deployed by
[Later changes to the bootstrap stack](aws-bootstrap.md#later-changes-to-the-bootstrap-stack)), or to `infra/app.yaml`.
**Check:** its checks are green and it is merged on the maintainer's word.
**Who confirms:** the maintainer. **Undo:** revert that pull request.

### 6. Run Deploy again

**Do:** run **Deploy** (a merge to `main`, or by hand on `main`).
**Check:** the change set is all `Add`, and the smoke test passes.
**Who confirms:** the maintainer. **Undo:** [roll back](#roll-back-a-change).

### When the API's tags were refused

When decision 0003's API fallback applies (an integration, route or stage refused on
the API's tags), steps 1 to 4 are the same; then:

**Do:** recreate the stack by hand with rollback disabled (`sam deploy --disable-rollback`,
passing the execution role), so it stops at `CREATE_FAILED` with its API kept, and read
the API's ID from the stack's resources. The fix (step 5) is then the reviewed bootstrap
change that allows that ID, and the next **Deploy** updates the stack in place (a stack
whose create failed with rollback disabled can be updated). It isn't deleted again,
since a new API would have a new ID.
**Check:** the next Deploy's smoke test passes.
**Who confirms:** the maintainer. **Undo:** delete the stack and its empty table and
bucket (steps 3 and 4).

## Remove an environment

**Do:** `aws cloudformation delete-stack --stack-name asmbly-ceramics-<env>`, then
`aws cloudformation wait stack-delete-complete --stack-name asmbly-ceramics-<env>`.
**Check:** `describe-stacks` says the stack doesn't exist.
**Undo:** run **Deploy** again; it creates the stack and finds the retained table and
bucket in the way (see [the failed first create](#if-the-first-create-of-a-stack-fails)), so decide about them first.

The table and the bucket stay after the stack is gone, with any personal details and
photos in them, until they are deleted on purpose. Delete them only if the data is
truly not wanted: `aws dynamodb update-table --table-name asmbly-ceramics-<env>-records --no-deletion-protection-enabled`,
`aws dynamodb delete-table --table-name asmbly-ceramics-<env>-records`, then empty and
delete the photo bucket. Nothing in the workflow deletes data.

The same holds when a change replaces the table or the bucket (a new `TableName`, key
schema or `PhotoBucketSuffix`): the old one is retained, still holding what it held,
and #7's deletion doesn't reach it. Delete it by hand once its data has moved or closed.
Point-in-time recovery keeps a closed drop-off's details for up to 7 days more
(decision 0002), and the table's stream holds each change for 24 hours.

## When an alarm fires

Each alarm's name says the environment (`asmbly-ceramics-<env>-<name>`). Read the logs
by drop-off ID only; never open a drop-off's details with the CLI.

| Alarm | Look at | Then |
| --- | --- | --- |
| `email-failures` | the mailer's log group, `email_failed` lines: the drop-off's ID and the SES error code | staff use "Try sending again" in the console (phase 8) once the cause is fixed; a refused address is the person's to correct |
| `logged-errors` | the form's, the console's and the mailer's log groups, `level` `ERROR` lines: the event and `error_code` | a code that names AWS (`ThrottlingException`, `AccessDenied`) points at the stack; `photos_not_deleted` names a drop-off for the backstop (#19); the mailer's `mailer_start_failed` means it can't start (a `SettingsError.<variable>` code names the variable; Lambda retries the batch); the console's `jwks_unavailable` or `sign_in_unavailable` means the staff sign-in can't be reached (asmbly-staff-login's) |
| `mailer-dead-letters` | the mailer's log group around the alarm's time (`mailer_crashed` with the drop-off's ID) | the email stays pending; fix the cause, then staff retry it |
| `function-errors` | the function's log group around the alarm's time | a deploy's bad version: roll back |
| `close-errors` | the close's log group, `close_failed` lines (a drop-off's ID and an error code) or `close_aborted` (a code) | Lambda runs it again (closing is idempotent), and the next daily run tries every drop-off still due, so fix the cause; a drop-off that keeps failing keeps its details past #7's close until it is fixed |
| `close-dead-letters` | the close's log group around the alarm's time; the dead-letter queue `asmbly-ceramics-<env>-close-dlq`'s message count (`aws sqs get-queue-attributes`) | the run gave up after its retries, or the scheduler couldn't invoke the close: fix the cause; the next daily run closes what is due |
| `api-5xx` | the API's access log group (status only) and the form's and console's log groups | as for `function-errors`; with no errors logged, many people at once may have used up the form's 5 or the console's 25 reserved executions (the console's thumbnails are each a request; API Gateway answers for it) |

Each returns to OK by itself when the next five minutes are quiet.

## Things that don't change with a deploy

- `/asmbly-ceramics/<env>/initial-sending-address` is read only the first time the
  studio is stored (its first-use seeding). Changing it afterwards doesn't change the
  sending address (staff do that in the console), but the parameter must stay, and stay
  an `asmbly.org` address: every deploy resolves it, and all four functions (the form,
  the console, the mailer and the close) check it when they start.
- The alarm topic's email subscription is confirmed once, from the email AWS sends to
  `/asmbly-ceramics/<env>/alert-email`. Stage's and prod's alarms both go there; the
  alarm's name says which.
