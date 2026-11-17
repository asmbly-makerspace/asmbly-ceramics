# Documentation

Start with the [README](../README.md) for what this repository is and where it stands,
and [CLAUDE.md](../CLAUDE.md) for the rules.

## Architecture

- [architecture.md](architecture.md): what is built today, what the stories ask for, the shape of the code, the
  work in other repositories, and what is still to be decided.

## Decisions

Each record says what was decided, why, and what would reopen it. Copy
[0000-template.md](decisions/0000-template.md) for a new one, with the next unused
number.

| Record | Decision |
| --- | --- |
| [0001](decisions/0001-the-ceramics-studio-has-its-own-repository.md) | The ceramics studio has its own repository: public, Python with uv, set up like the sibling repositories, staff sign in through asmbly-staff-login, a clean start with no ClickUp migration, no fees |
| [0002](decisions/0002-how-the-app-is-built-and-deployed.md) | Proposed: Starlette pages on Lambda behind an HTTP API, one DynamoDB table, photos uploaded straight to a private S3 bucket, email through an outbox and SES, sign-in checked by the app, SAM with a bootstrap stack, stage then prod |
| [0003](decisions/0003-one-function-boundary-per-environment.md) | Accepted: one function boundary per environment, each on its own names; the HTTP API and event-source mappings take their tags in the create request (mappings' tags only on create, no import); the bootstrap owns the access-log policy |
| [0004](decisions/0004-the-form-role-and-the-photo-bucket-name.md) | Accepted: amends 0002: the form's role may delete photos under `dropoffs/` (the submit's cleanup) and put the studio's first settings; its `PutItem` on drop-offs and emails can't require a new item; the photo bucket is named with a random suffix, not the account ID |
| [0006](decisions/0006-the-console-may-delete-a-drop-offs-photos.md) | Accepted: amends 0002: the console's role may delete photos under `dropoffs/`, so staff can delete a waiting drop-off made by mistake and its photos go at once |
| [0005](decisions/0005-the-http-apis-are-the-bootstraps.md) | Proposed: amends 0003: the bootstrap creates the stage and prod HTTP APIs and the execution role changes only their routes, stages and mappings, by ID; reads and deletes CloudFormation makes before a create or in a rollback are allowed by name; the bootstrap template is uploaded to S3 |
| [0007](decisions/0007-firing-notes-are-kept-with-their-load-and-are-not-personal-data.md) | Proposed: a firing note's text is kept with its load and the close never touches it, because a note is not personal data; the server refuses text shaped like an email address or a phone number |
| [0008](decisions/0008-the-form-caps-received-emails-per-day-and-per-recipient.md) | Proposed: adds to 0002: the form queues at most 300 received emails a day per environment (a studio setting) and 3 drop-offs per recipient a day (under a keyed hash of the normalized address), refuses past either with one friendly sentence, and an alarm goes off at 100 emails the mailer sends in a clock hour |
| [0009](decisions/0009-the-upload-script-is-tested-with-nodes-own-test-runner.md) | Proposed: adds to 0002: the drop-off form's upload script is tested with Node's built-in test runner on a hand-written DOM stub, started by pytest; no npm package, no build step, no CI change; Node 20 or later is a development requirement, and the test fails, never skips, without it |

## Runbooks

Production tasks, each with its check and its undo. Run one only when the maintainer
asks for it.

| Runbook | What it does |
| --- | --- |
| [aws-bootstrap](runbooks/aws-bootstrap.md) | Deploy the bootstrap stack (deploy roles, boundary, addresses) and set up the GitHub environments. Once, by hand. |
| [operations](runbooks/operations.md) | The app stacks: what a merge deploys, the rollback (a revert pull request), taking the form offline, a failed first create, removing an environment. |

## Plans

How each story is built is in `.implementation_plans/`
([format](../.implementation_plans/readme.md)). Epic #1's plan is
[drop-off-and-firing](../.implementation_plans/drop-off-and-firing/README.md). The firing
record, the firing log and firing notes (#42, #17) are in
[firing-records-and-notes](../.implementation_plans/firing-records-and-notes/README.md).
