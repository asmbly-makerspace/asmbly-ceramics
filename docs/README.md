# Documentation

Start with the [README](../README.md) for what this repository is and where it stands,
and [CLAUDE.md](../CLAUDE.md) for the rules.

## Architecture

- [architecture.md](architecture.md): what the stories ask for, the planned shape, the
  work in other repositories, and what is still to be decided.

## Decisions

Each record says what was decided, why, and what would reopen it. Copy
[0000-template.md](decisions/0000-template.md) for a new one, with the next unused
number.

| Record | Decision |
| --- | --- |
| [0001](decisions/0001-the-ceramics-studio-has-its-own-repository.md) | The ceramics studio has its own repository: public, Python with uv, set up like the sibling repositories, staff sign in through asmbly-staff-login, a clean start with no ClickUp migration, no fees |

## Runbooks

Production tasks, each with its check and its undo. Run one only when the maintainer
asks for it.

None yet: there is nothing in AWS. The plan that first deploys the app adds the first
runbook (setting up the deploy role and the GitHub environment) to `docs/runbooks/`
and lists it here.

## Plans

How each story is built is in `.implementation_plans/`
([format](../.implementation_plans/readme.md)).
