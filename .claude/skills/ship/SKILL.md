---
name: ship
description: Take a finished change in this repo to a merge-ready pull request - run the checks, get a cold review of anything that touches personal data, photos, email, the public form, staff access or AWS, open the pull request, wait for CI, and merge only when the maintainer says so. Use when asked to ship, open a PR, merge, or release a change.
---

# Ship a change

Never push to `main`, and merge only when the maintainer (@sababado) says so in this
conversation, for this pull request.

Today a merge deploys nothing: there is no app and no deploy workflow yet. When the plan
for epic #1 adds one, a merge deploys to production, and this skill gains a step to
watch that run and its smoke test. Update it in the same pull request that adds the
workflow.

## 1. Check the work

```bash
git status --short
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

Fix what fails. Don't skip a test, lower the coverage floor, or use `--no-verify`.

## 2. Get a cold review, when the change can leak or lock out

If the change touches how a person's details or photos are stored, shown, emailed,
logged or deleted; the public drop-off form's checks or limits; who can open the staff
console; the emails the app sends; IAM, infrastructure or `.github/workflows/`; have it
reviewed by an agent that didn't write it. Spawn a fresh `general-purpose` agent with
only:

- the repository path, the branch, and the base (`git merge-base HEAD origin/main`);
- `git diff --stat <base>..HEAD` and the list of changed files;
- the plan's phase document, if there is one;
- "Read CLAUDE.md first. Review this branch cold for anything that could: show a
  person's name, email, phone number or photo to anyone but signed-in ceramics staff;
  log, print or commit any of them, a token or a secret; make a photo or a bucket
  publicly readable; let a request from the public form through unchecked (type, size,
  count, rate) or put its text unescaped into a page or an email; send email from
  outside `asmbly.org` or to anyone but the person who dropped off; let someone outside
  the `ceramics` staff group into the console; grant rights outside the
  `asmbly-ceramics-` prefix or over another project's resources; or put AWS or web
  framework code into the domain model. Return BLOCK / WARN / NOTE findings, one line
  each, with file:line, at most 20."

Don't give it your reasoning or what you think is fine: that defeats the cold read. Fix
every BLOCK, re-run step 1, and list what you deferred in the pull request. If you
can't spawn an agent, say in the pull request that the review was not independent.

## 3. Branch, commit, push

```bash
git switch -c <type>/<short-description>      # for example feat/2-drop-off-form
git add <the files you changed>
git commit -m "<type>: <what changed>"         # Conventional Commits
git push -u origin HEAD
```

Check `git diff --staged` before committing: no `.env`, no secret, no AWS account ID, no
real person's name, email address, phone number or photo, nothing unrelated. The
repository is public; a pushed commit is public at once.

## 4. Open the pull request

```bash
gh pr create --title "<type>: <what changed>" --body-file <file>
```

Write the body from `.github/PULL_REQUEST_TEMPLATE.md` and fill in every section. In
**Risk**, name what the change does to people's personal details and photos, the
public form, who can open the console, the emails sent, AWS and IAM, and anything newly
logged. Use `Closes #<issue>` for the issue it finishes, `Refs #<issue>` otherwise.

## 5. Wait for CI

```bash
gh pr checks --watch
```

`PR check` is the required check. If a job fails, read it
(`gh run view <run-id> --log-failed`), fix the cause, and push again.

## 6. Merge, on the maintainer's word

Report that CI is green and stop. `main` requires a code owner's approving review, and
a pull request opened under the maintainer's account can't be approved by him, so it
merges through his bypass of the rules on `main`. Only he has that bypass.

First make sure the pull request shows what it finally contains: if commits were added
after it was opened, update its description or add a comment that summarizes them.

Then, when the maintainer says to merge this pull request:

```bash
SHA=$(gh pr view --json headRefOid --jq .headRefOid)   # the commit that was reviewed
gh pr merge --admin --squash --delete-branch --match-head-commit "$SHA"
```

`--match-head-commit` makes the merge fail if anything was pushed after the review.
Never use `--admin` without the maintainer's word for this pull request, and never for a
pull request someone else opened: that one needs his review instead.

## 7. Report

Say what was merged (or that it is waiting for the maintainer), CI's result, the cold
review's findings and what was deferred. If any step was skipped or failed, say which.
