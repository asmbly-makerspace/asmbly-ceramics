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
| [0003](decisions/0003-one-function-boundary-per-environment.md) | Proposed: one function boundary per environment, each on its own names; the HTTP API and event-source mappings take their tags in the create request (mappings' tags only on create, no import); the bootstrap owns the access-log policy |

## Runbooks

Production tasks, each with its check and its undo. Run one only when the maintainer
asks for it.

| Runbook | What it does |
| --- | --- |
| [aws-bootstrap](runbooks/aws-bootstrap.md) | Deploy the bootstrap stack (deploy roles, boundary, addresses) and set up the GitHub environments. Once, by hand. |

## Plans

How each story is built is in `.implementation_plans/`
([format](../.implementation_plans/readme.md)). Epic #1's plan is
[drop-off-and-firing](../.implementation_plans/drop-off-and-firing/README.md).
