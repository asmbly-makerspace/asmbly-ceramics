---
name: write-docs
description: Update the documentation a change needs - README.md, CONTRIBUTING.md, docs/architecture.md, the docs/README.md index, decision records, runbooks, the plan's phase tracker and hand-off, and CLAUDE.md's facts - by handing it to the scribe subagent, then checking its commits mechanically and, when it matters, with an independent docs review. Use when asked to write or update docs for a change, a plan phase or a pull request, when docs have fallen behind the code, or when /build, /bug-fix or /offshore calls it.
argument-hint: "<what changed: plan and phase, PR number, or a description> [base <ref>] [non-interactive]"
model: sonnet
effort: medium
---

# Write docs

Update the documentation for:

$ARGUMENTS

The `scribe` subagent writes; you don't. It is the only agent here allowed to edit
files, and it commits its own work as `docs:` commits. Your job is to give it the right
inputs, check what it produced against the code and the rules, send it back when
something is wrong, and report. If you find a problem, the scribe fixes it, not you.

There is no changelog, no version file and no docs site in this repository. Don't
create one, and don't let the scribe create one.

## Step 0: Check the branch

```bash
git branch --show-current
git status --short
```

- On `main`, or on no branch (detached HEAD): stop. The scribe commits, and nothing is
  ever committed to `main`. Ask the user which branch to use; in a non-interactive run,
  report `NOTES: on main, nothing written` and stop.
- Uncommitted changes that aren't documentation: note them. The scribe stages only the
  files it wrote, so they stay as they are, but say so in the report.

Find the base. The one named in the arguments; else the open pull request's base
(`gh pr view --json baseRefName -q .baseRefName`); else `main`. A bare branch name means
its remote copy, because a local `main` can be out of date:

```bash
git fetch origin main
git merge-base origin/main HEAD
```

Record the merge-base SHA as the base. A SHA given in the arguments is used as it is.

## Step 1: Gather the inputs

- **What changed.** `git diff --stat <base>..HEAD`, then `git log --oneline <base>..HEAD`.
  If the diff is empty, report `DOCS_CREATED: none` with `NOTES: nothing changed since
  <base>` and stop. Otherwise the scribe runs; "nothing needs documenting" is its call
  to make and say why.
- **The plan.** If the arguments name a plan or a phase, or the branch name points at
  one (`feat/2-drop-off-form`), the plan's `README.md` and the phase documents this
  branch delivers, by path. A small fix has no plan.
- **The issues.** The issues the work finishes (`Closes #N`) and the ones it only
  refers to (`Refs #N`), from the arguments, the commits or the pull request
  (`gh pr view --json number,body`). Read each with `gh issue view <N>` if the scribe
  will need its wording; the scribe can read them too.
- **What reached AWS.** Whether the work deploys anything or adds a runbook step. Today
  a merge deploys nothing; once the plan's first deploy exists, a merge deploys stage
  and then prod. A phase that reaches AWS is not complete until the maintainer has
  confirmed its rollout check.
- **What the maintainer decided.** Anything the user said in this conversation that
  the docs must record: an accepted decision record, a rule change, a confirmed rollout.
  Quote it. The scribe records a decision as accepted, or changes a rule in `CLAUDE.md`,
  only on that word.
- **Interactive or not.** Inside `/offshore`, `/build` or `/bug-fix`, or when the
  arguments say "non-interactive", the scribe doesn't wait for approval of its list.
  Otherwise it shows the list and waits for the user.

## Step 2: Run the scribe

Spawn the `scribe` agent with the Agent tool (`subagent_type: scribe`). Its file,
`.claude/agents/scribe.md`, is its system prompt and sets its model and tools, so pass
only the inputs:

- the request above, verbatim;
- the branch and the base SHA;
- the changed files and one or two sentences on what shipped;
- the plan `README.md` and phase documents, by path, or "no plan";
- the issues it closes and the ones it refers to, or "no issue";
- what reached AWS, or "nothing reaches AWS";
- the maintainer's words from Step 1, quoted, or "none";
- whether to wait for approval of its list of documents.

Never ask it to push. The commits stay local; the caller pushes (`/ship` or `/offshore`).

If the Agent tool isn't available to you (for example inside an `/offshore` sub-agent),
read `.claude/agents/scribe.md` and do its work inline, under all its rules, and say in
the report that it ran inline.

The scribe returns `DOCS_CREATED`, `DOCS_UPDATED`, `TRACKER`, `DECISIONS`,
`COMMIT_SHAS`, `BRANCH`, `NOTES`. If the return is missing a field, or a `COMMIT_SHAS`
entry isn't on the branch (`git branch --contains <sha>`), send it back once for the
missing part.

## Step 3: Check the result

Run every check against the scribe's commits. Each one passes or produces an item for
the scribe. Look only at what this run changed.

```bash
git log --format='%h %s' <base>..HEAD
git show --stat --format='%h %s' <sha>          # for each of the scribe's commits
```

1. **Only `docs:` commits, on this branch, not pushed.** Each of the scribe's commits
   starts with `docs:`. None is on `main`. `git status -sb` shows the branch ahead of
   its remote (or with no remote yet), so nothing was pushed.
2. **Only documents changed.** The scribe's commits touch only `README.md`,
   `CONTRIBUTING.md`, `CLAUDE.md`, `docs/**`, and the plan's `README.md` and phase
   documents. Anything under `src/`, `tests/`, `infra/`, `.github/`, `.claude/`,
   `pyproject.toml`, `uv.lock`, `LICENSE.md` or `SECURITY.md` is an item: the scribe
   must revert it.
3. **No document shrank.** For each updated file, compare the line counts
   (`git show --numstat --format= <sha> -- <path>`, and `wc -l` at the base and now). A
   file that had more than 100 lines and now has less than half as many is a
   regression: the scribe restores it from the base and makes only the change the code
   needs.
4. **The decision records hold.** `git diff <base>..HEAD -- docs/decisions/`. An
   accepted record whose text changed beyond its `Status:` line is an item. A changed
   `Status:` line says `superseded by` a record this branch adds, or `accepted by the
   maintainer` with the maintainer's word from Step 1 behind it; otherwise it is an
   item. A new record has the next unused number, follows
   `docs/decisions/0000-template.md`, says `Status: proposed` unless the maintainer
   accepted it, and has a row in the `docs/README.md` table.
5. **The plan was only tracked, not redesigned.** In the plan folder, the scribe
   changed only the phase tracker's Status cells, a phase document's `> **Status:**`
   line and its `## Hand-off` section. A `[x] Complete` on a phase that reaches AWS
   needs the maintainer's confirmation from Step 1. Any other change to the plan is an
   item: plans are `/plan-tech`'s.
6. **`CLAUDE.md` changed only in its facts.** A changed line under **Always**,
   **Never**, **This repository is public** or **Done means verified** is a rule
   change, and needs the maintainer's word from Step 1. Without it, the scribe reverts
   the line and the change goes into `NOTES` as `needs a person`.
7. **Every name in the new text exists.** For each file path, module, route, form
   field, environment variable, parameter path, resource name, table or index name,
   workflow or job name, and command the run added, `git grep` it or `ls` it. A
   resource the docs say the app creates starts with `asmbly-ceramics-`. A name that
   isn't in the code or the templates is an item, unless the document clearly says it
   is planned and the plan names it.
8. **Nothing private.** Search the run's added lines:

   ```bash
   git diff <base>..HEAD -- '*.md' | grep '^+' | grep -nE \
     '@|[0-9]{12}|arn:aws|console\.aws|amazonaws\.com|execute-api|lambda-url|slack\.com|docs\.google|drive\.google'
   ```

   Read each hit. An email address of any kind (even a made-up one), an account ID,
   an ARN, an internal or console URL, a real person's name or details, or a token is
   an item. A staff username in a doc is an item too: docs name roles ("the
   maintainer", "ceramics staff"), not people, except the maintainer's GitHub handle
   where the rules already use it.
9. **The repository's own checks pass.**

   ```bash
   uv run pytest tests/repo -q
   ```

   This checks every relative link and heading anchor, that no email address, phone
   number, account ID or photo is committed, and that the checks the docs name are the
   ones CI runs. Report its real result. A failure in a file the scribe didn't touch is
   not the scribe's item; report it in `NOTES` as found.
10. **The return matches the diff.** Every file in `DOCS_CREATED` and `DOCS_UPDATED`
    is in the commits, and every documentation file in the commits is in the return.

If any check produced items, spawn the scribe again with the items, one line each with
file and line, and its previous return (same inline fallback as Step 2). Then run Step 3
again on the new commits. If the second round still has items, stop: report them under
`NOTES: docs check failed twice - needs a person`, and don't loop further.

## Step 4: Get an independent read, when it matters

Ask for one when the run created or changed a decision record, a runbook, `CLAUDE.md`,
or text that describes how personal details, photos, the public form, staff access,
email or AWS work; or when the caller asked for one. Otherwise skip this step and say
so in the report.

Spawn the review lead (`subagent_type: review-lead`, file `.claude/agents/review/lead.md`)
with only:

- the repository path, the branch, the base SHA, and the scribe's `COMMIT_SHAS`;
- the changed-file list and diff stats of those commits (`git show --stat`);
- the perspective to apply: `.claude/agents/review/docs.md` only;
- the plan's phase document, if there is one;
- the framing: "Review only these documentation commits. Is every claim true of the
  code today, is anything planned described as built, does anything break a rule in
  CLAUDE.md or put something private into a public repository? Return BLOCK / WARN /
  NOTE findings, one line each, with file:line, and your verdict."

Don't pass your own conclusions or the scribe's reasoning; that defeats the cold read.

If the Agent tool isn't available to you, read `.claude/agents/review/docs.md` and apply
it yourself, and say in the report that the review was not independent.

- **BLOCK:** send each one to the scribe, with the same two-round limit as Step 3 (a
  round spent in Step 3 counts). Then run Step 3 on the new commits.
- **WARN and NOTE:** put them in the report. They don't block.

## Report

```
DOCS_CREATED: <from the scribe>
DOCS_UPDATED: <from the scribe, with before -> after line counts>
TRACKER: <from the scribe>
DECISIONS: <from the scribe>
COMMIT_SHAS: <every commit across the run>
BRANCH: <branch>
CHECKS: <uv run pytest tests/repo -q: its real last line; and pass, or the items left>
REVIEW: <verdict, BLOCK / WARN / NOTE counts and the findings left, "not run - <why>", or
  "not independent - applied inline">
NOTES: <the scribe's NOTES; steps that ran inline; "needs a person" items;
  "docs check failed twice - needs a person"; uncommitted non-doc changes found in
  Step 0; or "none">
```

A calling skill (`/offshore`, `/build`, `/bug-fix`) reads this block, so keep the field
names exact; `/offshore`'s briefing takes its action items from `NOTES`. Items the scribe
marked `needs a person` (a conflict with a decision record, a rule change without the
maintainer's word, a doc outside its scope) go into the report as they are. Don't write
those docs yourself.

If the branch already has an open pull request, add to `NOTES` that its description
must be updated to mention the docs commits before it is merged. Don't edit the pull
request from here.
