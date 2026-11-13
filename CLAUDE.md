# asmbly-ceramics: rules for AI agents

Read this file first, then the document for the area you change. When a plan or a
prompt disagrees with these documents, the documents win and you say so.

| Area | Path | Read first |
| --- | --- | --- |
| What this repository is for, and where it stands | `README.md`, epic #1 | [docs/architecture.md](docs/architecture.md) |
| Why it is set up this way | `docs/decisions/` | [decision 0001](docs/decisions/0001-the-ceramics-studio-has-its-own-repository.md) |
| The app (none yet; it comes with the plan for epic #1) | `src/asmbly_ceramics/` | [Planned shape](#planned-shape-not-built-yet) |
| Plans for a story | `.implementation_plans/` | [.implementation_plans/readme.md](.implementation_plans/readme.md) |
| CI | `.github/workflows/` | [README.md](README.md#how-changes-reach-production) |
| Production tasks (none yet) | Asmbly's AWS account, profile `asmbly`, us-east-2 | [docs/README.md](docs/README.md#runbooks) |

Past decisions are in [docs/decisions/](docs/decisions/0001-the-ceramics-studio-has-its-own-repository.md).
Don't reverse one without writing a new decision record that says why.

## This repository is public

Anyone can read every file, commit, issue and pull request here, and anyone can open a
pull request. So, on top of the rules below:

- **No secrets, ever**: no key, token, password, client secret or `.env` file, not even
  in a test or an example. Secrets live in AWS (Parameter Store or Secrets Manager),
  set by hand, and the code reads them at run time.
- **No AWS account ID.** Nothing needs one in a file: a deploy takes it from its GitHub
  environment. Name a resource by its name, not its ARN.
- **No internal addresses that shouldn't be public**: no console or admin URLs of other
  systems, no private Slack or Drive links, no staff-only page's address. The public
  drop-off form's address and `asmbly.org` pages are fine.
- **No personal details**: see the rules below. A public repository makes them stricter,
  not looser. Example data uses made-up names, `example.org` addresses built in code, and
  no real photo.
- **A pull request from a fork is untrusted code.** CI runs it without any credentials
  (`pull_request`, never `pull_request_target`), and nothing it changes is run with AWS
  rights before a code owner has reviewed it.

`tests/repo/test_personal_data.py` fails on an email address, a phone number, an AWS
account ID or a photo committed to the repository.

## What this repository serves

Asmbly Makerspace's ceramics studio: a phone-friendly **drop-off form** anyone can use
without signing in, which gives each drop-off an ID (`AC-1`, `AC-2`, …) on screen, and a
**staff console** where ceramics staff build kiln loads, fire them, reject drop-offs
and manage the studio's settings. People get an email with their drop-off's photos when
it is received, fired, or rejected. It replaces the studio's ClickUp drop-off form.
About 80 drop-offs and 6 firings a week. Epic #1 has the stories (#2 to #9) and what was
decided; [decision 0001](docs/decisions/0001-the-ceramics-studio-has-its-own-repository.md)
has the reasons.

- **People who drop off** are members or anyone else; there is no sign-in and no
  membership check on the form. They give a name, an email and a phone number, which
  are personal data.
- **Ceramics staff** sign in through Asmbly's staff sign-in, which asmbly-staff-login
  (a private repository in the same organization) owns.
  Only the `ceramics` staff group may open the console. This repository holds no rights
  over the staff sign-in; the app's sign-in client is added there, by a pull request
  there.
- **Kilns, firing types, glaze types, rejection reasons, the pickup window and hours, and
  the sending address are data** that staff manage in the console (#6), not code.
- **Out of scope** (epic #1): payments or firing fees, importing anything from ClickUp,
  membership checks, pickup tracking or shelf locations, the dip glaze mix log.

## Planned shape (not built yet)

There is no app and nothing in AWS yet. This section says what the plan for epic #1 must
respect; the framework, the hosting, the data store and the deploy are decided by
`/plan-tech` and recorded in a decision record, not here
([still to be decided](docs/architecture.md#still-to-be-decided)).

- **A domain model at the center.** Drop-offs, loads, kilns, firing types, glaze types,
  rejection reasons and settings, with their states (a drop-off is waiting, in a load,
  fired, rejected or closed; a load is loading, firing or fired) and the rules between
  them, as plain Python in `src/asmbly_ceramics/` that imports no AWS library and no web
  framework. The stories' rules ("a fired load can't be changed") live there, once, with
  tests that need no AWS.
- **AWS behind ports.** Storage of records, photo storage (S3), email (SES), staff
  sign-in (tokens from the staff sign-in), the clock and ID numbering are each an
  interface the domain and the use cases call, with an AWS adapter and an in-memory fake
  for tests. A new feature (the kiln schedule, #9; a glaze log later) adds a use case and,
  if it must, an adapter, without reworking the others.
- **Settings as data.** Nothing a story calls a setting is a constant in the code.

## Done means verified

Before you say a change is done, run the checks for what you touched and report the
real results, including failures:

```bash
uv run ruff check . && uv run ruff format --check .   # every change
uv run mypy                                            # every change
uv run pytest --cov                                    # every change; the coverage floor is in pyproject.toml
```

`tests/repo/` checks the repository itself: that every relative link in the Markdown
resolves, that these commands are the ones CI runs, that the skills and agents are
well formed, that the ruleset file and CODEOWNERS say what this file says about `main`,
that no workflow gets AWS credentials, and that no personal detail, account ID or photo
is committed. If you couldn't run a check, say which one and why.

## Rules

**Always**

- Read the code or the document you're changing, and its tests, before editing. Don't
  guess at an AWS behavior (S3, SES, Cognito tokens); read AWS's documentation, or look
  at the account with a read-only command.
- Add or update tests with every behavior change. The domain's rules are tested without
  AWS, against the in-memory fakes.
- Treat everything the public form sends as hostile: check every field on the server
  (type, length, format, the number of photos, each photo's real type and size) before
  anything is stored or sent, and escape it wherever it is shown or put in an email.
  Limits from #2 (1 to 6 photos, 10 MB each, 10 submissions per device in 10 minutes)
  are enforced by the server, not only the page.
- Keep photos private: the bucket blocks all public access, and staff see photos only
  through the console, signed in. A photo's storage address alone gets "access denied"
  (#2). Never make a bucket, an object or a URL public to make something work.
- Send email only from an address at `asmbly.org`, the one set in the console (#6), and
  only to the person who made the drop-off, or to the signed-in staff member for a test
  email.
- Check, on every console request, that the caller's token is valid and that they are
  in the `ceramics` staff group. Anyone else signed in sees "not allowed" (#3).
- Start every AWS resource name this repository creates with `asmbly-ceramics-` (in a
  template, from one parameter). The deploy role, which the first deploy's plan designs,
  will be allowed to manage only names that start that way and resources carrying this
  repository's `Project` tag. The prefix is the repository's name and its `Project` tag
  value, so a name and its tag always agree; a shorter `ceramics-` would also match
  names other projects already use for their ceramics pieces. Any exception needs a
  decision record.
- Tag every AWS resource as the Asmbly AWS Tagging Guide says: `Project=asmbly-ceramics`,
  `Component=<part>`, `Environment=<prod or stage>`, `Owner=it-volunteers`, and
  `ManagedBy=<the tool that deploys it>`. Give the deploy role tag conditions from the
  start (`aws:RequestTag` on create, `aws:ResourceTag` afterwards).
- Say in the pull request's **Risk** section what the change does to people's personal
  details, the public form, who can open the console, the emails sent, and AWS.
- Keep changes scoped to the task. Note unrelated problems instead of fixing them silently.

**Never**

- Log, print, return in an error, or put in an issue, a commit, a pull request, a test
  fixture or a run summary: a person's name, email address or phone number, a
  rejection message's text, a photo or its contents, a token, or a request body that
  holds any of them. Log drop-offs by ID (`AC-12`), loads by their ID, and staff by
  username. AWS's error text can quote what was sent: log its error code, not its
  message.
- Keep personal details longer than the stories say: #7 deletes the name, email, phone,
  rejection message and photos once a drop-off closes.
- Commit secrets, `.env` files, an AWS account ID, a real person's details, or a photo
  ([This repository is public](#this-repository-is-public)).
- Touch another project's resources in Asmbly's AWS account: AsmblyMCPs' stacks
  (`mcp-*`), asmbly-staff-login's (`staff-login-*`, which hold the staff sign-in), the
  facilities automation, and anything that carries another project's `Project` tag.
  Never grant anything here rights over them. The sending rights on the `asmbly.org`
  email domain and the app's sign-in client are asked for in those repositories (epic
  #1's work in other repositories), not taken from here.
- Run AWS commands that change anything. Changes reach the live app only through a
  merge and its deploy, or a step of a runbook in `docs/runbooks/` that the maintainer
  asked for, in this conversation, for that step. Read-only commands with
  `AWS_PROFILE=asmbly` in us-east-2 are fine; never read a drop-off's personal details
  or photos with them.
- Give this repository rights over the staff sign-in, or create a sign-in client
  anywhere but asmbly-staff-login.
- Weaken the deploy role, its permissions boundary or its tag conditions (once a plan
  adds them) without the maintainer asking for it.
- Edit `uv.lock` by hand. Use `uv add` and `uv lock`.
- Lower the coverage floor, skip or delete a failing test, or bypass hooks (`--no-verify`).
- Push to `main`. Open a pull request, and merge it only when the maintainer (@sababado)
  says so in the conversation, for that pull request. Every pull request needs a code
  owner's approving review. One opened under his account has no second approver, so it
  can only be merged with his bypass of the rules on `main`, which only he has
  (`gh pr merge <number> --admin --squash --match-head-commit <sha>`). Never use
  `--admin` without his word, and never on a pull request someone else opened: that one
  needs a review instead.

## Tracking

Work is tracked in GitHub Issues on this repository; there is no other tracker. Epic #1
lists the stories (#2 to #9) and the work they need in asmbly-staff-login, AsmblyMCPs
and the facilities repository, which is tracked there. A commit or pull request that
finishes an issue says `Closes #2`; earlier partial work says `Refs #2`. If you find
follow-up work you won't do now, open an issue for it. Issues are public: describe a
problem with a drop-off by its ID, never by the person.

`/plan-product` writes stories, `/plan-tech` turns a story into a plan in
`.implementation_plans/`, and `/prep` checks a phase of it against the code before it
is built.

## Commits and pull requests

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`.
- Commit after each logical step; don't hold a large change uncommitted.
- Fill in every section of the pull request template, including **Risk**.
- CI must be green. `PR check` is the required check. Merges are squash merges and need
  a code owner's approving review.
- Before a merge, the pull request's description or a comment on it must show what it
  finally contains: update it when commits are added after it was opened.
- Today a merge deploys nothing. The plan that adds the first deploy also adds, here,
  what a merge deploys and the smoke test to watch after it.
