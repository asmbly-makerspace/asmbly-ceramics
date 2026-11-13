# Contributing

This page covers how to make a change here and get it to `main`. It is short on
purpose: each step links to the document with the details. If this page and one of those
documents ever disagree, the linked document is right; fix this page.

The repository is public, and anyone may open a pull request. The code stays Asmbly
Makerspace's ([LICENSE.md](LICENSE.md)). Security problems go to
[SECURITY.md](SECURITY.md), never to a public issue.

## Start here

1. Read the [README](README.md) to learn what this repository is for and where it stands,
   and [docs/architecture.md](docs/architecture.md) for what is planned and what is still
   to be decided.
2. Read [CLAUDE.md](CLAUDE.md). It is written for AI agents, but its rules are the
   project's rules and apply to you too, [This repository is public](CLAUDE.md#this-repository-is-public)
   above all.
3. Set up your machine: [Prerequisites](README.md#prerequisites), then
   [Run the checks](README.md#run-the-checks).
4. Find the issue for your change in
   [GitHub Issues](https://github.com/asmbly-makerspace/asmbly-ceramics/issues), or
   open one. There is no other tracker.

## From issue to `main`

```
issue → plan → branch → commits → checks → pull request → PR check → review → squash merge
```

1. **Plan.** A story (#2 to #9) is built from a plan in `.implementation_plans/`, which
   `/plan-tech` writes and `/prep` checks phase by phase
   ([.implementation_plans/readme.md](.implementation_plans/readme.md)). A small fix
   needs no plan.
2. **Branch.** Never commit to `main`. Name the branch `<type>/<short-description>`, for
   example `feat/2-drop-off-form`.
3. **Write the change and its tests.** Every behavior change comes with a test. Commit
   after each logical step, using [Conventional Commits](https://www.conventionalcommits.org/):
   `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`.
4. **Run the checks.** For every change:

   ```bash
   uv run ruff check . && uv run ruff format --check .
   uv run mypy
   uv run pytest --cov
   ```

5. **Open a pull request.** Fill in every section of the
   [template](.github/PULL_REQUEST_TEMPLATE.md), including **Risk**. Write
   `Closes #<issue>`, or `Refs #<issue>` if the issue isn't finished.
6. **Get CI green.** `PR check` is the required check. If your pull request changes
   dependencies, the [Dependency audit](.github/workflows/dependency-audit.yml) runs too.
   A first-time contributor's pull request waits for a maintainer to approve its CI run.
7. **Get a review.** Every pull request needs an approving review from the code owner,
   @sababado ([CODEOWNERS](.github/CODEOWNERS)). A new push cancels an earlier approval.
   If you add commits after opening the pull request, update its description so it shows
   what it finally contains.
8. **Merge.** Pull requests are squash-merged. Today a merge deploys nothing; once the
   app exists, it deploys to production ([How changes reach production](README.md#how-changes-reach-production)).
9. **If it goes wrong, revert.** Run `gh pr revert <number>` and merge the revert.

In Claude Code, `/ship` does steps 4 to 7 and stops before the merge.

## Working with an AI agent

Most changes here are written with Claude Code. The repository gives the agent its
rules, so it can do the work. You are still the one who answers for the result.

- **CLAUDE.md is the agent's rulebook.** Claude Code reads it at the start of every
  session. When your prompt disagrees with the docs, the agent follows the docs and tells
  you, as intended. If a rule is wrong, change the rule rather than arguing with the agent.
- **Use the skills.** These are step lists the agent follows, and you can read and
  follow them yourself:

  | Command | Use it to |
  | --- | --- |
  | `/plan-product` | Turn an idea into an epic and stories with testable acceptance criteria ([SKILL.md](.claude/skills/plan-product/SKILL.md)) |
  | `/plan-tech` | Write the phased technical plan for an epic or a story ([SKILL.md](.claude/skills/plan-tech/SKILL.md)) |
  | `/prep` | Check one phase of a plan against the code before building it ([SKILL.md](.claude/skills/prep/SKILL.md)) |
  | `/build` | Build one phase (or written instructions) with tests, validated and independently reviewed ([SKILL.md](.claude/skills/build/SKILL.md)) |
  | `/review` | Review a branch with the specialist reviewers and get BLOCK / WARN / NOTE findings and a verdict ([SKILL.md](.claude/skills/review/SKILL.md)) |
  | `/write-docs` | Update the docs a change needs ([SKILL.md](.claude/skills/write-docs/SKILL.md)) |
  | `/bug-fix` | Trace a bug to its cause, fix it with a regression test, review it, and open a green pull request ([SKILL.md](.claude/skills/bug-fix/SKILL.md)) |
  | `/address-pr-comments` | Fix or answer every review comment and failing check on a pull request ([SKILL.md](.claude/skills/address-pr-comments/SKILL.md)) |
  | `/offshore` | Run a whole plan unattended, from stories to a green pull request and a briefing, without merging ([SKILL.md](.claude/skills/offshore/SKILL.md)) |
  | `/ship` | Run the checks, get a cold review, open the pull request, and wait for CI ([SKILL.md](.claude/skills/ship/SKILL.md)) |
  | `/rigor` | Tell the agent to stop cutting corners ([SKILL.md](.claude/skills/rigor/SKILL.md)) |

  While `/offshore` runs, [a guardrail hook](.claude/hooks/offshore-guardrails.sh)
  blocks questions, pushes to `main`, merges, deploys, AWS changes and the shortcuts
  `CLAUDE.md` forbids. It does nothing in an ordinary session.

- **Read the whole diff.** Do it before you push or ask for a review, as you would with
  a colleague's work. Look hardest at the agent's [Never](CLAUDE.md#rules) list: anything
  newly logged or printed, anything that stores, shows or emails a person's details or
  photos, the public form's checks, who can open the console, IAM, and tests that were
  skipped or deleted.
- **Ask for results, not reassurance.** The agent must run the checks and report what
  they printed ([Done means verified](CLAUDE.md#done-means-verified)). If it says it
  couldn't run one, run that check yourself.
- **Approve commands with care.** [.claude/settings.json](.claude/settings.json)
  pre-approves only checks and read-only commands, so anything else asks you first.
  Read each command before you approve it. The agent doesn't merge without the
  maintainer's word, and it doesn't run AWS commands that change anything.
- **A pull request the agent opens is yours.** GitHub sees it as opened from your
  account, and you answer for it in review.
- **Keep the agent's instructions current.** If your change alters how something should
  be done, update `CLAUDE.md` or the skill in the same pull request. The agent only
  knows what those files say.

## Standards

Ruff and mypy enforce most of the Python style. Their settings are in
[pyproject.toml](pyproject.toml): Python 3.14, strict types, absolute imports only, and
timezone-aware datetimes. Fix the code instead of silencing the check. The rest:

- **People's details stay out of the repository and the logs.** Drop-offs by ID
  (`AC-12`), staff by username, in issues, commits, pull requests, logs and test data.
  Never a name, an email address, a phone number or a photo.
- **Clean design.** The domain (drop-offs, loads, kilns, settings and their rules) is
  plain Python with no AWS or web framework in it; storage, photos, email and sign-in
  sit behind interfaces with an AWS adapter and a test fake
  ([The shape of the code](CLAUDE.md#the-shape-of-the-code)).
- **Infrastructure.** AWS resource names start with `asmbly-ceramics-`, and every
  resource carries the tags [CLAUDE.md](CLAUDE.md#rules) lists.
- **Tests.** Every behavior change gets a test. The coverage floor is in
  `pyproject.toml`: raise it, never lower it. Don't skip or delete a failing test, and
  don't use `--no-verify`.
- **Dependencies.** Use `uv add`; don't edit `uv.lock` by hand.
- **Secrets.** Never commit `.env`, a secret, or an AWS account ID.
- **Scope.** Keep a pull request to its task. If you notice an unrelated problem, open an
  issue for it instead of fixing it on the side.

## Changes that need a decision record

Some changes are decisions as well as code. They need a record in
[docs/decisions/](docs/decisions/), written in the same pull request, and the
maintainer's agreement:

- the framework, the hosting, the data store or the deploy, the first time each is
  chosen or whenever it changes;
- keeping a person's details or photos longer, showing them to anyone but ceramics
  staff, or sending email from outside `asmbly.org`;
- a sign-in on the drop-off form, a membership check, or fees (all ruled out by epic #1);
- a resource name outside the `asmbly-ceramics-` prefix;
- reversing an earlier decision.

To write one, copy [0000-template.md](docs/decisions/0000-template.md) and use the next
unused number.

## Production

- There is no production yet. When there is, it runs in Asmbly's AWS account (profile
  `asmbly`, region `us-east-2`), which also runs AsmblyMCPs, asmbly-staff-login, the
  facilities automation and other projects. Never touch their resources.
- Read-only AWS commands are fine. Make a change in AWS only through a merge's deploy or
  a [runbook](docs/README.md#runbooks) task the maintainer asks for.
