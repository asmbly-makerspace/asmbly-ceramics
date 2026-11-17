# asmbly-ceramics

Asmbly Makerspace's ceramics studio: drop-offs, kiln loads and firings.

Someone dropping off a piece fills in a phone-friendly form, without signing in, and
gets an ID like `AC-12` on screen to write on their slip. Ceramics staff sign in to a
console to see what's waiting, build kiln loads, fire them and reject drop-offs, and
people get an email with their photos when their drop-off is received, fired or
rejected. It replaces the studio's ClickUp drop-off form.

This repository is public; the code is Asmbly Makerspace's ([LICENSE.md](LICENSE.md)).
If you find a security problem, please report it privately ([SECURITY.md](SECURITY.md)).

## Status

**The domain, the use cases, the AWS adapters, the drop-off form, the staff console, the
daily close and their deploy are built.** `src/asmbly_ceramics/` holds the domain model, the ports with
in-memory fakes, the use cases (submit a drop-off, the email composer and outbox, the
waiting list, search, rejection, kiln loads, settings, the daily close, counts), AWS
adapters (DynamoDB, S3, SES, Cognito tokens, Parameter Store) and the public drop-off
form and the staff console (`web/`, `web/console/`: Starlette pages, the photo upload
script and the security headers; the console is the waiting list, search, one drop-off
and its photos, rejection, loads with their firing record, notes and history, the notes
search, the firing log and its CSV, settings and their history, counts, and the emails needing attention). They are tested without AWS. `infra/bootstrap.yaml` is the bootstrap stack (deploy roles,
permissions boundary, the two addresses), which the maintainer deploys by hand with
[its runbook](docs/runbooks/aws-bootstrap.md). The stack `asmbly-ceramics-bootstrap`
exists in AWS and the GitHub environments `stage` and `prod` exist (`main` only); the
runbook's later steps (the environments' secrets and variables, the app's keys, the two
addresses, the boundary check) are not done yet, so no deploy has succeeded.
`infra/app.yaml` is the app's stack (the records table, the private photo bucket, the
form and the console behind an HTTP API, the mailer, the daily close at 03:17 Austin
time, and their alarms), which a merge to `main` deploys to stage and then prod once the bootstrap
is in place. The prod form's address isn't published until the switch from ClickUp
(#8), and the console needs the `ceramics` group and the app's sign-in client from
asmbly-staff-login. The plan's remaining phase is in
[.implementation_plans/drop-off-and-firing/](.implementation_plans/drop-off-and-firing/README.md). The firing record and log (#42) and firing
notes (#17) are built from
[.implementation_plans/firing-records-and-notes/](.implementation_plans/firing-records-and-notes/README.md).

| Story | What changes for people |
| --- | --- |
| #2 | Someone drops off a piece and gets an ID on screen |
| #3 | Ceramics staff sign in and see what's waiting |
| #4 | Staff build a kiln load and fire it, and people hear it's ready |
| #5 | Staff reject a drop-off with a reason and a message |
| #6 | Staff manage the studio's settings in the console |
| #7 | Finished drop-offs close, and personal details are deleted |
| #8 | The studio switches from ClickUp |
| #9 | Members see the kiln schedule |
| #17 | Staff keep firing notes they can look up later |
| #42 | Staff keep a firing record on each load, and read each kiln's firing log |

What was decided is in epic #1; the reasons are in
[decision 0001](docs/decisions/0001-the-ceramics-studio-has-its-own-repository.md), and
what is still open in [docs/architecture.md](docs/architecture.md#still-to-be-decided).

## Layout

```
CLAUDE.md               the rules, for people and AI agents
CONTRIBUTING.md         how a change gets to main
SECURITY.md             how to report a security problem
docs/                   architecture, decisions, runbooks (docs/README.md is the index)
infra/                  CloudFormation templates: bootstrap.yaml (deployed by hand) and
                        app.yaml (SAM, deployed by a merge; samconfig.toml at the root)
scripts/                the deploy's smoke test, parameter list and compose check
.implementation_plans/  how each story is built, written by /plan-tech
.claude/                Claude Code's settings, skills and agents
.github/                pull request template, code owners, Dependabot, the ruleset, CI
src/asmbly_ceramics/    the app: domain/, ports/, use_cases/, mail/, adapters/ (memory/, aws/, the
                        system clock and the photo inspector) and web/ (the drop-off form's
                        pages) and web/console/ (the staff console), composition.py and
                        entry/ (what Lambda starts)
tests/                  the app's tests; tests/repo/ checks the repository itself
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/). It installs the Python version in `.python-version`
  (3.14) and the tools in `pyproject.toml`.
- [GitHub CLI](https://cli.github.com/), signed in, to work with issues and pull
  requests.

## Run the checks

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
uvx cfn-lint==1.57.1 infra/*.yaml   # after a template change
sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml   # after an app template change
uv export --frozen --no-dev --no-emit-project -o src/requirements.txt  # after a dependency change
```

None of them needs AWS credentials.

## Try the drop-off form

```bash
uv run uvicorn asmbly_ceramics.web.local:app --reload
```

Then open http://127.0.0.1:8000/ in a phone-sized window. It runs on the in-memory
fakes: nothing reaches AWS and no email is sent. `web/local.py` is for this only; it is
never a deployed entry point.

## How changes reach production

```
issue → branch → commits → checks → pull request → PR check → review → squash merge
```

Every change is a pull request to `main`. `PR check` is the required check, and every
pull request needs an approving review from the code owner
([CONTRIBUTING.md](CONTRIBUTING.md)).

A merge to `main` deploys:

```
merge → Deploy: stage → smoke test → prod → smoke test
```

**Deploy** (`.github/workflows/deploy.yml`) deploys `asmbly-ceramics-stage` with SAM,
runs `scripts/smoke.py` against `https://ceramics-stage.asmbly.org`, then deploys
`asmbly-ceramics-prod` and runs it against `https://ceramics.asmbly.org`; a failed step
stops what follows. Watch the run in the repository's Actions tab to the end of both
smoke tests. Only the newest commit on `main` deploys. The rollback is a revert pull
request; taking the form offline at once is in
[the operations runbook](docs/runbooks/operations.md).

## Where to read more

- [CLAUDE.md](CLAUDE.md): the rules.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to make a change.
- [docs/README.md](docs/README.md): architecture, decisions and runbooks.
