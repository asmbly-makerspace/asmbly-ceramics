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

**A skeleton.** It has its rules, its checks and its stories, and no app and nothing in
AWS yet. The next step is the technical plan for epic #1 (`/plan-tech`).

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

What was decided is in epic #1; the reasons are in
[decision 0001](docs/decisions/0001-the-ceramics-studio-has-its-own-repository.md), and
what is still open in [docs/architecture.md](docs/architecture.md#still-to-be-decided).

## Layout

```
CLAUDE.md               the rules, for people and AI agents
CONTRIBUTING.md         how a change gets to main
SECURITY.md             how to report a security problem
docs/                   architecture, decisions, runbooks (docs/README.md is the index)
.implementation_plans/  how each story is built, written by /plan-tech
.claude/                Claude Code's settings, skills and agents
.github/                pull request template, code owners, Dependabot, the ruleset, CI
src/asmbly_ceramics/    the app (empty until the plan's first phase)
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
```

None of them needs AWS credentials.

## How changes reach production

```
issue → branch → commits → checks → pull request → PR check → review → squash merge
```

Every change is a pull request to `main`. `PR check` is the required check, and every
pull request needs an approving review from the code owner
([CONTRIBUTING.md](CONTRIBUTING.md)).

Today a merge deploys nothing: there is no app yet. The plan that adds the first deploy
says what a merge deploys, where, and the smoke test that ends it, and updates this
section.

## Where to read more

- [CLAUDE.md](CLAUDE.md): the rules.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to make a change.
- [docs/README.md](docs/README.md): architecture, decisions and runbooks.
