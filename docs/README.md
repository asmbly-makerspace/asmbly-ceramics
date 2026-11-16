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
[drop-off-and-firing](../.implementation_plans/drop-off-and-firing/README.md).
