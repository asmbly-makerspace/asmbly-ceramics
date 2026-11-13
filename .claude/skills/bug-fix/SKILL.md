---
name: bug-fix
description: Plan, fix, review, document and open a pull request for a bug in one run. A cold bug-planner traces the reported symptom to its root cause, /prep checks the plan, /build writes a regression test that fails first and then the fix, the review-lead (and the privacy-guardian when personal data, photos, email, the public form, staff access or AWS is touched) review it cold, and the pull request to main is driven to green CI and left open. Never merges. Use when asked to fix a bug, or given a bug report or a bug issue number.
argument-hint: "<bug report or #issue> [--plan-only] [--no-pr] [--issue]"
model: opus
effort: high
---

# /bug-fix: plan, fix, review, document and open a pull request for a bug

The bug report: a description, log lines, screenshots, repro steps, and optionally a
GitHub issue (`#12` or its URL) and flags:

```
$ARGUMENTS
```

You are a **thin orchestrator**. The work happens in agents and skills: the
`bug-planner`, then `/prep`, `/build`, the cold reviewers and `/write-docs`. Keep your
own context small: read their structured returns, show the person what matters, and
keep the run moving. You don't write the fix yourself.

---

## The sequence

```
parse → branch → reproduce and plan (bug-planner) → plan checkpoint
      → prep → build (regression test first, then the fix)
      → review (review-lead + privacy-guardian when it applies + /review, ≤3 cycles)
      → write-docs (if needed) → pull request to main → drive to green → report
```

**Done means:** the reporter's exact scenario is fixed, a regression test failed before
the fix and passes after, the checks in `CLAUDE.md` pass, and the pull request to `main`
is green (`PR check` passing, every review comment fixed or answered) and left open for
the maintainer. A pushed branch or an opened pull request is not done.

### Flags

| Flag | Effect |
| --- | --- |
| `--plan-only` | Stop after the plan checkpoint (Step 3). |
| `--no-pr` | Stop after the review (Step 6): branch pushed, no pull request. |
| `--issue` | Open a GitHub issue for the bug after the plan checkpoint, and close it from the pull request. |

---

## Hard rules

- **Follow `CLAUDE.md`.** Pass "Read CLAUDE.md first and follow it" into every agent
  prompt.
- **Never merge.** The maintainer (@sababado) merges, on his word, for that pull request.
  No `gh pr merge`, with or without `--admin`.
- **Never push to `main`.** No `--no-verify`, no bare `--force`, no skipped, weakened or
  deleted tests, no lowered coverage floor.
- **Nothing changes AWS.** No `sam deploy`, no AWS command that changes anything.
  Read-only commands with `AWS_PROFILE=asmbly` in us-east-2 (CloudWatch Logs by drop-off
  ID, `describe-stacks`) are fine for diagnosis; never read a drop-off's personal
  details or photos with them.
- **The repository and its issues are public.** Never put a person's name, email, phone
  number, rejection message, photo, a token or an account ID into an issue, a commit, a
  pull request, a test fixture, a plan file or an agent prompt. Describe a drop-off by
  its ID (`AC-12`), a load by its ID, staff by username. Reproduce with made-up details
  and `example.org` addresses built in code.
- **Two rounds on style.** Style-only review findings get two rounds at most. Real bugs,
  privacy and security gaps, and failing tests always reopen the loop.
- **Retry transient failures** (network, GitHub, a flaky spawn) 4 times with backoff (2,
  4, 8, 16 seconds) in the same turn before escalating.
- **Ask only for decisions that are the maintainer's:** a product behavior the stories
  and docs don't settle, an accepted risk, keeping a detail longer than #7 allows, a scope
  split, an admin action, a change in another repository. Decide everything else, note
  it, and keep going.

### Agents and nesting

Spawn each registered agent with the Agent tool (`subagent_type: <name>`): the
`bug-planner`, the `review-lead` and the `privacy-guardian` are spawned by this skill
itself, so their read stays cold. If a skill run inside a `general-purpose` agent
(`/prep`, `/build`) can't spawn its own subagents, it runs them inline and says so; that
is expected here. The `/build` independent review and the `review-lead` this skill
spawns in Step 6 are deliberate double coverage (the second has the colder context), so
don't drop either.

If the Agent tool isn't available to you at all (you are yourself running inside an
agent), read each agent's file and apply it inline, and say in the report that the
planning and the reviews were not independent. Run `/bug-fix` in a top-level session
when you can.

---

## Step 0: Parse the request

1. **The report.** Pull out the symptom, expected vs. actual, the entry point (the
   drop-off form, the ID page, a console page and action, an email, the daily close),
   the drop-off or load IDs involved, and the repro steps.
   - **Screenshots on disk:** pass the paths to the planner. Never commit them.
   - **Screenshots pasted into the chat** reach only you. Transcribe every value,
     message, status code, URL path and ID you can see into the report, leaving out a
     person's name, email, phone and photo ("ID page: AC-12, 'We received 3 pieces';
     console waiting list: AC-12 missing"). That transcription is evidence, not a theory
     of the cause.
   - **Log lines:** include them with any token, address or personal detail removed.
     The app logs by ID; if a log line holds a person's details, that is a second bug:
     note it for the planner.
2. **Issue mode.**

   | Input | Mode | What changes |
   | --- | --- | --- |
   | `#N` or an issue URL | **Linked** | `gh issue view <N> --json title,body,labels,comments`; add its body, its acceptance criteria or "Done when" list, and the comments to the report. The pull request says `Closes #N`. |
   | `--issue` | **Created** | After the plan checkpoint, search first (`gh issue list --search "<words>" --state all`) so you don't duplicate one, then open one with `gh issue create` (with the `bug` label if the repository has it): the title, expected vs. actual, and repro steps, by drop-off ID, never by the person. Then as Linked. |
   | neither | **Unlinked** | No issue. The pull request's **Closes** section says `n/a: no issue for this bug`. Don't open one on your own. |

## Step 1: Branch

`fix/<short-slug>`, from `main`:

```bash
git fetch origin main
git switch -c fix/<short-slug> origin/main
git branch --unset-upstream 2>/dev/null || true   # a bare `git push` must never target main
```

Run this whatever branch you're on, including a `claude/...` branch the harness gave you:
`-c` from `origin/main` starts clean and keeps earlier work out. If the harness forbids
pushing any branch but its own, stay on the harness branch instead (reset it to
`origin/main` only if it has no commits of yours) and say so in the report. Never work on
`main` or on someone else's branch.

Record the base now: `git merge-base HEAD origin/main`. Every later `<BASE>` means this
SHA, written out in full: shell variables don't carry over between Bash calls.

## Step 2: Reproduce and plan

Spawn the `bug-planner` (`subagent_type: bug-planner`). Its file,
`.claude/agents/plan/bug-planner.md`, is its system prompt. Give it:

- the report from Step 0, verbatim, with your screenshot transcriptions;
- the absolute paths of any screenshots on disk;
- the issue body and comments, in Linked mode;
- the repository path and the branch.

Don't give it your own theory of the cause: it traces the code cold. It reproduces the
bug where it can (an existing test, a `python -c` against the in-memory fakes), traces
the symptom to its root cause, maps every place that shares the defect, and returns a
markdown plan whose first item is the regression test. It writes no files.

If its plan says it could not reproduce the bug and can't name a test that would, show
that to the person and ask for the missing detail before building.

## Step 3: Plan checkpoint

Show the person the plan as returned. Then:

- **Open questions, or a privacy or AWS decision that is the maintainer's:** ask
  (AskUserQuestion), with enough context to answer without scrolling back. Fold the
  answers into the plan.
- **None:** say you're starting the build and continue. Don't wait for an approval
  nobody asked to give.
- **`--issue`:** open the issue now (Step 0).
- **`--plan-only`:** stop here.

Save the final plan to a file outside the repository: the session scratchpad if there is
one, otherwise `mktemp -d`. The plan is never committed.

## Step 4: Prep

Spawn a `general-purpose` agent:

```
Run /prep on an inline bug-fix plan: invoke Skill(skill: "prep", args: "inline plan: <plan path>").
The file is the whole plan: there is no plan directory, README, phase tracker or story
frontmatter, so skip the steps that read them and the story alignment step. Ground-truth
every path, type, port and resource the plan names against the code, and run the drift
detector and the auditor (inline if you can't spawn them). Branch: <branch>.
Read CLAUDE.md first and follow it. Don't write code.

Return only:
  { verdict: "READY TO IMPLEMENT" | "NEEDS REVISION" | "BLOCKED",
    amendments: <plan edits the findings require, as replacement text, or "none">,
    findings: <top findings, one line each>,
    inline_roles: <agents you ran inline instead of spawning> }
```

- **READY TO IMPLEMENT:** continue.
- **NEEDS REVISION:** apply the amendments to the plan file, tell the person in a line or
  two what changed, and continue. If an amendment changes behavior the person saw in
  Step 3, ask first.
- **BLOCKED:** tell the person what blocks it and stop.

## Step 5: Build

Spawn a `general-purpose` agent:

```
Implement the bug-fix plan at <plan path>: invoke Skill(skill: "build", args: "instructions: <plan path> base <BASE>").
Branch: <branch> (checked out). Base: <BASE>. Read CLAUDE.md first and follow it.
- Regression test first: write the test that reproduces the reported scenario, run it, and
  confirm it fails for the reported reason. Commit it on its own (`test: reproduce <bug>`).
  Then write the fix and confirm the same test passes.
- Test the domain and use cases against the in-memory fakes; never call AWS from a test.
- Use made-up details and example.org addresses built in code; no real person, no real photo.
- Commit after each logical step (Conventional Commits, `Refs #N` in Linked mode, no Closes
  lines). Don't push.
- Run `uv run ruff check . && uv run ruff format --check .`, `uv run mypy` and
  `uv run pytest --cov`, and report the real results.
- If the fix needs a new AWS resource, right or environment variable, change the template,
  the IAM statement and composition.py in the same step, and list anything an admin must do.
- Don't edit .implementation_plans/.

Return only:
  { result: "done" | "blocked", commits: <N>, files_changed: <N>,
    regression_test: "<path>::<name>", failed_before_fix: true | false,
    failure_before_fix: "<one line>",
    checks: { ruff: "pass" | "fail", mypy: "pass" | "fail", pytest: "<passed>/<total>, coverage <N>%" },
    independent_review: "subagent" | "inline",
    admin_actions: [<one line each>] | "none",
    notes: <deviations from the plan, or "none"> }
```

- `failed_before_fix: false` means the test doesn't reproduce the bug. Send it back once
  to fix the test; then stop and tell the person.
- **blocked:** a fixable problem (a wrong path in the plan, a missing fake method) gets
  the plan fixed and this step re-run once. Anything else: tell the person and stop.

## Step 6: Review

Run review cycles until clean, at most three. Size them by
`git diff --shortstat <BASE>..HEAD`: up to 300 changed lines, 1 cycle; 301 to 600, 2;
more, 3. Stop early when a cycle finds nothing above NOTE.

Each cycle:

1. **Independent review: spawn it yourself.** Spawn the `review-lead`
   (`subagent_type: review-lead`) with only the repository path, the branch, `<BASE>`,
   the changed-file list, `git diff --stat <BASE>..HEAD`, the specialist files that match
   the diff (the table in `/build` Step 7: `.claude/agents/review/app.md`,
   `.claude/agents/review/web.md`, `.claude/agents/review/infra.md`,
   `.claude/agents/review/docs.md`), and "Read CLAUDE.md first. Review this branch cold.
   Return BLOCK / WARN / NOTE findings, one line each, with file:line, at most 20." No
   reasoning, no plan, no build notes: it reviews cold.

   **In the same message, spawn the `privacy-guardian`** (`subagent_type: privacy-guardian`,
   file `.claude/agents/review/privacy-guardian.md`) when the diff touches how a person's
   details or photos are stored, shown, emailed, logged, kept or deleted; the public
   form's fields, checks, limits or upload; the emails sent; console sign-in, the
   `ceramics` group check or CSRF; or AWS (`infra/`, IAM, `composition.py`, an AWS
   adapter, `.github/workflows/`). When unsure, spawn it. Give it the same inputs plus
   the diff of the files that triggered it (`git diff <BASE>..HEAD -- <files>`).
2. **Review and fix agent.** Spawn a `general-purpose` agent:

   ```
   Invoke Skill(skill: "review", args: "against <BASE>"). Then fix every real finding from that
   review AND from these independent findings: <review-lead's and privacy-guardian's findings,
   verbatim>. Read .claude/agents/build/fixer.md for how to fix. BLOCKs, bugs, privacy and
   security gaps and failing tests are always fixed, each with a test; straightforward WARNs
   are fixed. No one is present to answer /review's "Part B: Awaiting your decision": for each candidate, fold it
   in if it is small and in scope, otherwise list it under `declined` with a real reason (a
   contract, a test, a design choice or a tradeoff; "minor" is not a reason). A finding whose
   only fix is the maintainer's decision goes under `for_the_maintainer`, unfixed.
   Read CLAUDE.md first and follow it. Re-run the three uv checks after fixing. Commit the
   fixes. Don't push.

   Return only:
     { verdict: "APPROVED" | "CHANGES REQUESTED", fixed: [<one line each>],
       declined: [<finding: reason>], for_the_maintainer: [<finding>],
       checks: { ruff, mypy, pytest }, commits: <N> }
   ```

3. Anything under `for_the_maintainer` is never decided silently: stop and ask.

List every `declined` item under "Flagged for you" in the report.

After the last cycle, if a BLOCK is still open, tell the person what remains and why, and
stop before the pull request.

**`--no-pr`:** push the branch (`git push -u origin fix/<short-slug>`), report, and stop.

## Step 7: Docs (only if needed)

| Run `/write-docs` when the fix... | Skip it when the fix... |
| --- | --- |
| changes what a person dropping off or ceramics staff see, receive or can do | only touches tests, CI or `.claude/` |
| changes a page's address, a setting, an email's content, an environment variable or a Parameter Store name | is a refactor with no behavior change |
| contradicts or fills a gap in `README.md`, `docs/` or a runbook | |

When it runs, spawn a `general-purpose` agent that invokes
`Skill(skill: "write-docs", args: "<bug summary: expected vs. actual, root cause, fix>; branch <branch> base <BASE> non-interactive")`,
with "Read CLAUDE.md first and follow it. Commit the doc changes; don't push." Check
that what the docs now say matches the code. Record the decision either way ("docs:
updated `docs/...`" or "docs: skipped, <reason>").

## Step 8: Pull request

1. **Sync with `main`:** `git fetch origin main`; if it moved, merge `origin/main` in and
   re-run the three uv checks.
2. **Check what goes public:** `git diff <BASE>..HEAD` holds no `.env`, secret, account
   ID, real person's details or photo.
3. **Push:** `git push -u origin fix/<short-slug>`. Retry network errors 4 times.
4. **Open the pull request** to `main`, ready for review (not a draft: the fix is
   complete and checked):

   ```bash
   gh pr create --base main --head fix/<short-slug> --title "fix: <what changed>" --body-file <file>
   ```

   Write the body file outside the repository, from `.github/PULL_REQUEST_TEMPLATE.md`,
   and fill every section:

   - **Summary:** the bug (expected vs. actual), the root cause with path:line, and the
     fix, by drop-off ID, never by the person.
   - **Closes:** `Closes #N` in Linked or Created mode; `n/a: no issue for this bug`
     otherwise. GitHub closes the issue when the pull request merges.
   - **Risk:** what the fix does to people's personal details and photos, the public
     form, who can open the console, the emails sent, AWS and IAM, and anything newly
     logged; every admin action (a Parameter Store value, a change in another
     repository); and, once merges deploy, the check after deploy and the undo.
   - **Test plan:** the regression test (failed before, passes after, with the failure
     line), the three uv checks with their results, the reviews run (`review-lead`,
     `privacy-guardian` or "not needed, because ..."), and how to see the fix after it
     merges with made-up details.

5. Give the person the link.

## Step 9: Drive it to green

```bash
gh pr checks <n> --watch
```

- **Conflicts** (`gh pr view <n> --json mergeStateStatus` shows `DIRTY`): merge
  `origin/main` in, re-run the checks, push.
- **A failing check:** read it (`gh run view <run-id> --log-failed`) and find the root
  cause. Fix it in a `general-purpose` agent that invokes
  `Skill(skill: "address-pr-comments", args: "<n>")`; it pushes its own fixes. A check
  that is red on `main` too isn't this pull request's: say so once on the pull request
  and in the report.
- **Review comments** from the maintainer or anyone else: the same
  `address-pr-comments` agent; every comment gets a fix or a reply with a reason.
- **Commits added after the pull request opened:** update its description (or add a
  comment) so it shows what it finally contains.
- Never push an empty commit to start a run again.

Repeat until `PR check` (the required check) is green on the head commit and every
comment is fixed or answered. **Don't merge.** Report that it is ready and stop; the
maintainer merges it, on his word.

## Step 10: Report

```markdown
## Bug fixed: <title>

**Pull request:** <link>: <green | waiting on X> (not merged; the maintainer merges)
**Root cause:** <one or two lines, with path:line>
**Fix:** <one line per phase>
**Verified:** `<regression test>` failed before the fix (<failure line>) and passes after; ruff <result>, mypy <result>, pytest <passed/total, coverage N%>
**Review:** <cycles run>; review-lead <subagent | inline>; privacy-guardian <subagent | inline | not needed, why>; <BLOCK/WARN fixed>; <declined, with reasons>
**Docs:** <what was written, or "skipped: reason">
**Issue:** <#N, closed by the pull request when it merges | none>
**Admin actions:** <what the maintainer or another repository must do, or "none">
**Flagged for you:** <out-of-scope problems (suggested follow-up issues), declined findings with reasons, decisions made on your behalf>
```

---

## What this encodes

- **Reproduce before you plan, and the regression test first.** It reproduces the
  reporter's scenario with made-up details and fails before the fix. Without that,
  nothing proves the fix fixes the report.
- **Fix the rule, not the screen.** When a page and the domain disagree about a limit,
  the bug is that there are two. The rule lives in the domain once; the page reads it.
- **Fix the pattern, not the instance,** within scope. When the same defect is in a
  sibling use case or page, the planner names it; the person decides whether it belongs
  here or in a follow-up issue.
- **State outlives the fix.** Drop-offs, loads, outbox items and photos written while the
  bug was live may still be wrong, and an email already sent can't be unsent. Fix the
  records, or say why they can't matter. Personal details already deleted by the close
  stay deleted.
- **The seams are where bugs hide.** A fix in the code that needs a new environment
  variable, IAM action or Parameter Store name isn't done until the template has it too.
- **A leak is its own bug.** A person's details in a log or an error found while fixing
  something else gets fixed here or reported at once; it is never left for later
  silently.

Example: `/bug-fix #14` plans moving the photo limit the form's hint text copied ("up to
8 photos") onto the domain's `MAX_PHOTOS`, with a regression test that requests the form
page and finds "up to 6 photos", failing before the fix.
