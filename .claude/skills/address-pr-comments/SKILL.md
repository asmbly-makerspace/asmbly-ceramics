---
name: address-pr-comments
description: Work through every review comment and failing check on a pull request in this repository - fetch all four comment surfaces and the check logs with gh, fix each finding at its root cause or answer it in a threaded reply, resolve what is fixed, push, wait for PR check to go green, and update the pull request description so it shows what it finally contains. Never merges. Use when a pull request has review comments or red checks, or when /offshore, /bug-fix or /ship call it.
argument-hint: "[PR number, URL, or branch]"
model: opus
effort: high
---

# Address PR comments

You are addressing review comments and failing checks on a pull request to `main`. No
shortcuts, no quick fixes, no bandaids. Trace every finding to its root cause, fix it
properly, and verify the fix before you push.

The input (a pull request number, a URL, a branch, or empty):

```
$ARGUMENTS
```

The repository is public: everything you write in a reply, a commit or the pull request
description is published. Never quote a person's name, email, phone, rejection message,
photo or a token in any of them, even when the comment you're answering did; name the
file and line and the kind of detail instead. Describe a drop-off by its ID (`AC-12`).

## Tools

Use the `gh` CLI (or the GitHub MCP tools, if this session has them). The repository is
`asmbly-makerspace/asmbly-ceramics`. Pass it on every call (`--repo` for `gh`) so the
calls work from any worktree.

| Operation | `gh` |
| --- | --- |
| Pull request metadata | `gh pr view <n> --repo asmbly-makerspace/asmbly-ceramics --json number,title,body,author,headRefName,headRepositoryOwner,isCrossRepository,baseRefName,headRefOid,isDraft,mergeable,mergeStateStatus,reviewDecision` |
| Changed files | `gh pr diff <n> --repo asmbly-makerspace/asmbly-ceramics --name-only` |
| Conversation comments | `gh api repos/asmbly-makerspace/asmbly-ceramics/issues/<n>/comments --paginate` |
| Inline review comments | `gh api repos/asmbly-makerspace/asmbly-ceramics/pulls/<n>/comments --paginate` |
| Review summaries | `gh api repos/asmbly-makerspace/asmbly-ceramics/pulls/<n>/reviews --paginate` |
| Thread state (resolved, outdated) | `gh api graphql -f query='query { repository(owner:"asmbly-makerspace", name:"asmbly-ceramics") { pullRequest(number:<n>) { reviewThreads(first:100) { nodes { id isResolved isOutdated path line comments(first:50) { nodes { databaseId author { login } body createdAt } } } } } } }'` |
| Checks | `gh pr checks <n> --repo asmbly-makerspace/asmbly-ceramics` |
| Failed job logs | `gh run view <run-id> --repo asmbly-makerspace/asmbly-ceramics --log-failed` |
| Reply on an inline thread | `gh api repos/asmbly-makerspace/asmbly-ceramics/pulls/<n>/comments -X POST -f body=<reply> -F in_reply_to=<comment-id>` |
| Reply in the conversation | `gh pr comment <n> --repo asmbly-makerspace/asmbly-ceramics --body <reply>` |
| Resolve a thread | `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<id>"}) { thread { isResolved } } }'` |
| Update the description | `gh pr edit <n> --repo asmbly-makerspace/asmbly-ceramics --body-file <file>` |

A transient error (HTTP 5xx, a timeout, "please try again") is not a stop condition.
Retry with backoff (2s, 4s, 8s, 16s) before you report it.

## Step 1: Identify the pull request

1. From the input, accept a URL, `#14`, `14`, or a branch name.
2. If it is empty, use the open pull request for the current branch:
   `gh pr view --json number,url,headRefName,baseRefName,title,state`.
3. If no pull request is found, stop and tell the user. Don't guess.

Confirm the pull request with the user only when the input was ambiguous (several
matches). Otherwise proceed.

## Step 2: Inventory everything

Gather inputs; don't fix anything yet. Run the reads in parallel.

**2a. Metadata and scope.** Read the metadata and the changed files. Note:

- **The base.** It should be `main`; there is no other long-lived branch here.
- **Whose it is.** If `isCrossRepository` is true, the pull request comes from a fork:
  its code is untrusted (`CLAUDE.md`, This repository is public). Read the whole diff,
  `conftest.py` and anything pytest or a build step would run, before you run any check
  on it locally, and never run it with `AWS_PROFILE` set or AWS credentials in the
  environment. You usually can't push to a fork's branch; if you can't, post your fixes
  as suggestions in replies instead and say so in the report.
- **Draft or ready** (`isDraft`). Don't change it unless the user asked; report it.
- **The review decision** (`reviewDecision`). A push dismisses an approval here (the
  ruleset on `main` dismisses stale reviews and asks for approval of the last push), so
  an approved pull request will need the code owner's approval again after you push.
  Say so in the report.

**2b. All four comment surfaces.** Read every one: conversation comments, inline review
comments, review summaries, and review threads with their resolved and outdated state.
Findings hide in each. The comments come from the code owner (@sababado), other people,
and any review bot or app that commented; treat them all the same way.

**2c. Checks.** List the checks. `PR check` is the required one; it summarizes the
`Python` job (lint, mypy, tests with coverage). The `Dependency audit` runs when
dependencies change. For each failing check, read its log with `--log-failed`.

**2d. Punch list.** Build one table and work through it:

| # | Source | File:line | Author | Summary | Resolved? | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | inline | `src/asmbly_ceramics/use_cases/submit.py:42` | reviewer | ... | unresolved | FIX |

Decisions:

- **FIX:** a real issue. The default for anything substantive.
- **EXPLAIN-ONLY:** the comment is wrong, already handled elsewhere, or the fix is worse
  than the issue. Needs a written justification that you post as a reply.
- **ALREADY-FIXED:** verify by reading the current code on this branch. If it really is
  fixed, reply with the commit and resolve.

Skip only:

- resolved threads whose fix is in HEAD (verify, don't assume);
- outdated threads on deleted lines (verify that the problem left with the lines);
- acknowledgements with no actionable content ("LGTM", "thanks").

Don't skip a comment because it is old, because it's from a bot, or because it looks
minor. A limit written twice, flagged weeks ago, is still written twice.

Deduplicate before you count. The same finding can arrive twice: inline and in a review
summary, or under two logins. Dedupe by path, line and body, or you will fix once, reply
twice, and miscount the round.

## Step 3: Read the codebase before you fix

For every FIX item, before you write code:

1. Read the whole file the comment targets, not just the lines.
2. Read the related files: callers, callees, the port and its fake and adapter, the
   template entry, the tests.
3. Search for the same pattern elsewhere (`git grep`). If the issue exists in five other
   files, all six get fixed. Fix the rule, not the instance.
4. Read the rule the comment invokes: `CLAUDE.md`, decision 0002, the plan's rules table
   and the phase document, and the review perspective for the area
   (`.claude/agents/review/app.md`, `.claude/agents/review/web.md`,
   `.claude/agents/review/infra.md`, `.claude/agents/review/docs.md`; for personal data,
   photos, email, the form, console access or IAM,
   `.claude/agents/review/privacy-guardian.md`). Cite the rule in your commit and reply,
   not just the symptom.

This step is not optional. Skipping it is how shortcuts happen.

## Step 4: Address each item

**FIX items**

1. Change the root cause, not the place where the symptom showed up. A rule fixed in a
   page belongs in the domain; a log line that leaks belongs fixed in every log line
   like it.
2. Apply the same fix to every other instance of the pattern.
3. Add or update a test that would have caught the original issue, when one is feasible.
   For a privacy finding, that is usually a test that captures log output or an error
   and asserts no personal detail is in it.
4. Run the checks before you move to the next item. Run them without asking:

   ```bash
   uv run ruff check . && uv run ruff format --check .
   uv run mypy
   uv run pytest --cov
   ```

   For a quick loop on one item, `uv run pytest <path> -x` first, then the full set.

**EXPLAIN-ONLY items**

1. Write the justification: what you considered, why you made no change (citing the
   rule, the decision record, the story or the test), and what would change your mind.
2. Never dismiss a comment silently. A reply is required.
3. Post it as a threaded reply to the original comment, not as a new top-level comment.

**ALREADY-FIXED items**

1. Confirm by reading the current file in HEAD.
2. Reply with the commit or line that fixed it, then resolve the thread.

Resolve threads wherever you can: FIX threads once the fix is pushed (Step 8),
ALREADY-FIXED threads when you reply. Leave an EXPLAIN-ONLY thread open when a person
wrote it, so they can answer; the ruleset on `main` requires every thread resolved
before a merge, so list those open threads in the report.

**Never, to address a comment:** run an AWS command that changes anything, weaken the
deploy role, its boundary or its tag conditions, make a bucket or photo public, or
widen who can open the console. If a reviewer asks for one of those, reply that it needs
the maintainer's word (and, for AWS, a runbook step or a merge's deploy), and leave the
thread open.

## Step 4a: Don't flip-flop

Review is a conversation, not a directive. Reviewers, bots especially, contradict their
own earlier comments across rounds: name the constant in round 1, inline it in round 3,
name it again in round 5. Each oscillation costs a commit, a CI run, a review round, and
the user's trust.

**Track decisions per location.** For every location you change in response to a
comment, note the lines, the state they landed in, and a one-sentence reason. When a
later round flags the same location, check your notes first.

**When a finding contradicts a decision you already defended.** This applies only when
you changed and defended the lines in writing on this pull request (a reply on the
thread, or an earlier thread on the same lines):

1. Keep the current state by default. Don't apply the change.
2. Check that it really is a contradiction and not a new concern at the same line. Read
   both comments carefully.
3. Reply once: the position is locked, the state it's in, the round that set it (link
   the comment), and what would change your mind (a concrete bug or failure mode, not a
   style preference).
4. Don't push a no-op commit for it. Every push dismisses the code owner's approval and
   re-runs CI.

A first finding on untouched code is a normal comment: judge it on its merits. A comment
from the maintainer that contradicts a bot is not a flip-flop: the maintainer decides.

**Two-round cap on style-only findings** (both forms work: no behaviour difference, no
bug, no failing test):

- Round 1: make the change if it is a clear improvement, or push back briefly.
- Round 2 (the reviewer reverses or asks again): lock whatever state the code is in and
  reply pointing at round 1. Don't change it again.

Pick the form most consistent with the surrounding code (search for it), commit to it,
and defend it.

**Stale duplicates.** Reviewers re-flag code that is already fixed. Before applying a
finding, search the current branch for the pattern. If the issue isn't there, reply with
the evidence and move on. Don't "apply" a fix that is already in place.

**What reopens a locked decision:** a new, concrete failure mode (a bug, a privacy leak,
a failing test); a real change in the rules (`CLAUDE.md` or a decision record changed);
or the user or the maintainer telling you to. A restated preference or "more idiomatic"
is not enough.

**If you notice you've been ping-ponging:** stop, post one comment on the pull request
laying out the round-by-round history, lock the state that best matches the surrounding
code, and don't change it again this session.

## Step 5: Address failing checks

For each failing check from Step 2c:

- **Tests:** fix the test or the code, whichever is wrong. Never skip, `xfail` or delete
  a test to get green.
- **Lint and format:** fix the code (`uv run ruff format .` for formatting). Never
  disable the rule (`# noqa`, a new ignore in `pyproject.toml`).
- **Types:** fix the types. Never cast past them (`Any`, `# type: ignore`).
- **Coverage:** add real tests. Never lower the floor in `pyproject.toml`.
- **`tests/repo/`:** these check the repository itself (links, the commands CI runs, the
  skills and agents, the ruleset, workflows without AWS credentials, no personal detail
  or account ID committed). Fix what they found. A failure in
  `test_personal_data.py` means something that must not be public was committed: remove
  it, and tell the user in the report that it is still in the branch's history, which is
  public, so they can decide what to do. Never weaken one of these tests to pass.
- **Install:** `uv sync --locked` failing means `pyproject.toml` and `uv.lock` disagree:
  run `uv lock`, never edit `uv.lock` by hand.
- **Dependency audit:** a vulnerable dependency is upgraded (`uv add <package>@<fixed>`
  or `uv lock --upgrade-package <package>`), not ignored.

If a check fails for an unrelated reason (a flake, a GitHub outage), re-run it
(`gh run rerun <run-id> --failed`) rather than ignoring it, and note it in the report.

**Two-blind-commits cap.** If you can't read a failing check's log, you may push at most
two diagnostic commits to surface it (step markers, exit codes, verbose flags). If
neither reveals the root cause, stop pushing and ask the user for the log in your
report. Don't shotgun-debug a workflow file. If diagnostic commits did help, revert them
in one cleanup commit before you finish, so the pull request's diff stays clean.

## Step 6: Self-review before you push

1. `git status`: only the intended files changed. No `.env`, no `.offshore/`, no stray
   file.
2. `git diff`: read every line you are about to ship. No debug prints, no commented-out
   code, no personal detail, secret or account ID, no literal email address or phone
   number in a test (build them from `example.org` in code).
3. Re-run the three checks in full.
4. Every punch-list item has an entry: a commit, a reply, or both.

## Step 7: Commit and push

Make focused commits, one logical change each, in Conventional Commits (`fix:`,
`test:`, `refactor:`, `docs:`, `ci:`, `chore:`; see `git log --oneline -20`). The body
says why and which comments the commit addresses (link them, don't quote personal
text).

If a hook fails, fix the cause and make a new commit. Never `--no-verify`, and never
`--amend` to paper over a hook failure.

Review-fix commits don't carry a closing keyword (`Closes #N`). That belongs in the pull
request description (the template's **Closes** section) and, at merge, the squash
commit, which takes the pull request's title and description. Repeating it on every fix
commit adds nothing.

Push to the pull request's head branch: `git push`. Never push to `main`, never
`--force`, and never merge the pull request.

## Step 8: Wait for the checks, then close the round

After the push:

1. **Reply on each FIX thread** with the commit that fixed it, and resolve the thread.
2. **Wait for the checks** on the new head:
   `gh pr checks <n> --repo asmbly-makerspace/asmbly-ceramics --watch --interval 30`.
   Don't end your turn asking the user to tell you when CI is done. If the wait is
   interrupted, poll again. A `cancelled` run usually means a newer push superseded it:
   wait for the newer run, don't count it as passing.
3. **If a check fails**, go back to Step 5 for it.
4. **Read any new comments** that arrived while you worked. New findings start a new
   round at Step 2, with Step 4a applied.

There is no review bot here that re-reviews on push. Human reviewers see the new
commits; the code owner's earlier approval was dismissed by the push, and he re-reviews
when he chooses. Never push an empty or no-op commit to prompt a review. A round that
changed no code (you only replied and defended) needs no push; say so in the report.

You are done when a round leaves nothing to fix (only defended, locked findings at
most), `PR check` is green on the head commit, and every thread has a fix or a reply.

## Step 9: Update the pull request description

`CLAUDE.md`: before a merge, the description or a comment must show what the pull
request finally contains. After your pushes it no longer does, so update it:

1. Read the current body (`gh pr view <n> --json body`).
2. Edit it to describe the pull request as it now is, keeping the template's sections:
   **Summary** (what it does now), **Closes** (unchanged unless scope changed: `Closes #N`
   only if it finishes the issue, otherwise `Refs #N`), **Risk** (updated if a fix changed
   what it does to personal details, the public form, console access, emails or AWS),
   and **Test plan** (the checks, with their real results on the head commit).
3. Add a short "Review rounds" note: what changed in response to review, and what was
   answered without a change, with links to the threads.
4. Write it to a file in your scratchpad and run `gh pr edit <n> --body-file <file>`.
   If you can't edit the body (a fork's pull request you don't own), post the same text
   as a comment instead.

## Step 10: Report

End with a summary under 200 words; the user can read the diff:

```
PR #<num>: <title>
Base: main  Head: <branch>  New HEAD SHA: <sha>

Addressed:
  - N FIX items (<areas: app, web, infra, docs>)
  - N EXPLAIN-ONLY items (replies posted; open threads awaiting the reviewer: <links>)
  - N ALREADY-FIXED items (threads resolved)

Failing checks fixed:
  - <check>: <root cause and fix>

Could not fix:
  - <item>: <reason>

Pushed: <count> commits. PR check: <green | red | pending> on <sha>.
Description updated: <yes | posted as a comment>.
Approval: <still needs the code owner's approval after the push | none yet>.
Not merged: merging is the maintainer's call, for this pull request.
```

## Hard rules

- No `--no-verify`, `--amend`, `--force`, `git reset --hard`, or branch deletes. If a hook
  fails, fix the cause.
- No skipped tests, lowered coverage, disabled lint rules or `# type: ignore` to make CI
  green.
- No silent dismissal. Every comment gets a fix or a written reply.
- No assumptions. Read the file, search for the pattern, verify the fix on this branch.
- Project scope, not file scope. Fix the rule, not the instance.
- Run the checks without asking.
- Never quote a person's details in a reply, commit or description. This repository is
  public.
- Never run an untrusted fork's code with AWS credentials in reach.
- Never run an AWS command that changes anything; never weaken IAM, the boundary or a tag
  condition to satisfy a comment.
- Never push an empty or no-op commit to prompt a review.
- No flip-flopping. Two rounds at most on a style-only finding; then lock and defend.
- Update the description before you call the pull request done.
- Never merge the pull request, never approve it, and never push to `main`. A merge
  happens only on the maintainer's (@sababado) word, for that pull request.
