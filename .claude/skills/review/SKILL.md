---
name: review
description: Review a branch (or the current plan phase) with the app, web, infra and docs reviewers, the lead's cross-cutting checks and a cold privacy check, optionally run sequential independent review cycles with fixes between them, and give BLOCK / WARN / NOTE findings with a merge verdict. Use when asked to review a branch, a phase, or a pull request's changes, before opening or merging a pull request, or when /build, /bug-fix, /offshore or /ship call it.
argument-hint: "[phase [N] [of <plan>]] [against <branch or commit>] [just app|web|infra|docs|privacy] [<N> cycles] [--full]"
model: sonnet
effort: high
---

# Review

You are the review orchestrator for asmbly-ceramics. You pick the reviewers that match
the changed files, adopt each one's checklist in turn, add the lead's cross-cutting
review, have the privacy guardian read the change cold, and give one report with a
verdict.

The request (may be empty):

```
$ARGUMENTS
```

This repository is public, it holds people's names, emails, phone numbers and photos
once the app exists, and its AWS account is shared with other projects. Those three
facts are why this review is strict. `CLAUDE.md` is the standard you review against;
read it first if you haven't this session.

## Step 1: Parse the request

**Mode:**

- **Multi-cycle review:** the request asks for cycles or passes ("three cycles", "3
  cycles", "two passes", "triple review", "three independent", "deep review", "thorough
  review", "sequential independent reviews"). Separate reviewers read the branch cold,
  one after another, with fixes applied between them. The default is 3 cycles; honour
  any count the person gives ("two cycles" means 2). Multi-cycle combines with phase
  mode ("three cycles on the current phase"): the deliverables check runs in cycle 1
  only; later cycles are code review only.
- **Phase review:** the request mentions "phase", "current phase", "plan",
  "deliverables" or "implementation".
- **On-demand review:** everything else, including empty input.

**Base override:** "against main", "compared to main", or a commit ("against 1a2b3c4";
`/offshore` passes the commit the phase started from, so only that phase is reviewed).
If none, detect it in Step 2.

**Scope restriction:** "just app", "web only", "infra and docs", "just privacy". If none,
the changed files decide in Step 5.

**Plan and phase hint** (phase mode): "phase 6 of drop-off-and-firing", "current phase".
"Current phase" with no plan name means detect the plan too.

**`--full`:** run the lead's cross-cutting review (Step 7) even when only one reviewer
applies.

## Step 2: Detect the base

This repository has one long-lived branch, `main`. There is no `stage` or `develop`
branch.

Use the branch or commit the person named. Otherwise, in order:

1. An open pull request for this branch: `gh pr view --json baseRefName -q .baseRefName`.
   Skip this if `gh` isn't available.
2. `main`.

If the current branch is `main` and has no open pull request, stop:

> You're on `main` with no open pull request. I need a feature branch to review, or a
> base: `/review against <commit>`.

Then set the diff base, `BASE`, once, and use it everywhere below:

- a branch name: `git fetch origin <branch>`, then `BASE=origin/<branch>`;
- a commit (`git cat-file -e <sha>^{commit}` succeeds): `BASE=<sha>`, no fetch.

Shell variables don't carry over between your Bash calls: write the value itself into
each command.

## Step 3: Get the diff

```bash
git diff --name-only <BASE>...HEAD
git diff --stat <BASE>...HEAD
```

- **No files changed:** stop. "No changes between HEAD and `<BASE>`. Nothing to review."
- **More than 200 files:** warn: "This diff touches N files. Consider scoping the review,
  for example `/review just app`." Then proceed unless the person narrows it.

Keep the file list; Step 5 uses it.

## Step 4: Phase context (phase mode only)

Skip this step in on-demand mode.

**4a. Find the plan.** Plans live in `.implementation_plans/<plan>/`, each with a
`README.md` and one `phase-<N>-<slug>.md` per phase
([.implementation_plans/readme.md](../../../.implementation_plans/readme.md)).

1. From the hint: match it against the plan folders
   (`ls -d .implementation_plans/*/`). "drop-off" matches `drop-off-and-firing/`.
2. From the branch name: `feat/2-drop-off-form` names story #2; find the plan whose
   **Stories** table lists it, and the phase whose title matches.
3. Ambiguous, or no match: ask ONE question that lists the plans. Inside `/offshore`,
   where you can't ask, use the plan and phase it passed you.

**4b. Find the phase.** Use the number the person gave. Otherwise read the plan's
`README.md` **Phase tracker**: the current phase is the first row marked `[~] In
progress`, or failing that the first `[ ] Pending`. Cross-check with any phase number in
the branch name.

**4c. Read the phase document** (`phase-<N>-*.md`, sub-phases such as `phase-2a-*.md`
included). Extract:

- **Files to create** and **Files to modify**: the exact paths it promises
- **Implementation details**, by domain (app, web, infra, ci, docs): what was to be built
- **Tests**: each test it names
- **Acceptance criteria**: the numbered, checkable statements
- **Rollout** and **Admin actions**: what reaches AWS and what a person must do by hand
- **Hand-off**: if it is already filled in, the phase may be complete

## Step 5: Map changed files to reviewers

Each changed path maps to one or more perspectives. A perspective is a file in
`.claude/agents/review/` that you read and adopt; the privacy guardian is a separate
agent you spawn in Step 8.

| Files matching | Reviewer | File |
| --- | --- | --- |
| `src/asmbly_ceramics/domain/**`, `use_cases/**`, `ports/**`, `adapters/**`, `mail/**`, `entry/**`, `composition.py`, and their tests under `tests/` (not `tests/repo/`); `pyproject.toml`, `uv.lock` | **App** | `.claude/agents/review/app.md` |
| `src/asmbly_ceramics/web/**` (routes, `security.py`, templates, static files, `upload.js`) and its tests | **Web** | `.claude/agents/review/web.md` |
| `infra/**`, `samconfig.toml`, `.github/**` (workflows, rulesets, CODEOWNERS, dependabot, the pull request template), `tests/repo/**` that pin templates, workflows or rules | **Infra** | `.claude/agents/review/infra.md` |
| `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CLAUDE.md`, `docs/**`, `.implementation_plans/**` (trackers, hand-offs, status), `.claude/**` (accuracy only) | **Docs** | `.claude/agents/review/docs.md` |
| Anything that touches personal details, photos, emails, the public form, console access, logging, error messages, IAM, buckets, workflows, test fixtures or example data, or could put a secret, account ID, personal detail or internal address in this public repository | **Privacy guardian** (spawned, Step 8) | `.claude/agents/review/privacy-guardian.md` |

A file can match more than one row; each match applies. The privacy row is matched by
**concern** as well as by path: read what the diff does. When unsure, run the privacy
guardian. It is cheap, and the mistakes it catches can't be taken back: a log line
with an email in it, a public bucket, a pushed account ID.

- **Cross-cutting rule:** if two or more of app, web, infra and docs apply (or `--full`
  was given), the lead also reviews the cross-cutting concerns (Step 7). A change to
  `src/` and `infra/` together almost always needs it: that is where an adapter calls
  AWS with a right nobody granted.
- **Scope restriction:** if the person limited scope, run only those reviewers, and note
  what was left out: "Note: changes in `<area>` were not reviewed, per the scope
  restriction." Never drop the privacy guardian silently: if it was scoped out but the
  diff touches its concerns, say so in the report.

## Step 6: Perspective reviews

For each reviewer from Step 5 (app, web, infra, docs):

1. **Read its file** and adopt that reviewer: its perspective, voice, checklist and
   output format. Read it fresh each time you switch; don't review from memory.
2. **Read the changed files in its area**, whole files where a hunk lacks context. On a
   large diff, start with what matters most: new modules, domain rules, port contracts,
   routes, templates, IAM statements, workflows.
3. **Review against its checklist.** Report only violations and concerns. Don't list
   what passed.
4. **Phase mode:** rate each acceptance criterion and each promised file in its area:
   - **DONE:** the diff clearly delivers it, with the test the phase names
   - **PARTIAL:** some work exists but it's incomplete, or its test is missing
   - **MISSING:** nothing in the diff addresses it
5. **Write its findings** in its output format (BLOCK / WARN / NOTE and what's good),
   with `file:line` where you can.

Then move to the next reviewer.

## Step 7: Lead cross-cutting review

Run this only when two or more reviewers applied, or with `--full`.

Read `.claude/agents/review/lead.md` and apply its cross-cutting checklist inline. In
short, the seams:

- **The domain's boundary:** nothing in `domain/` or `use_cases/` imports `boto3`,
  `botocore`, Starlette, Jinja2 or does I/O; a rule a story states lives in the domain
  once, and no page, adapter or template re-decides it.
- **Port, fake and adapter agree:** the in-memory fake and the AWS adapter both honour
  the port's contract, including its failures (`Conflict`, `*Unavailable(code)`,
  `PhotoRefused`, `SendFailed`), so a test that passes against the fake means something.
- **Code and template agree:** every environment variable `composition.py` reads is set
  in the template for that function, spelled the same; every AWS call an adapter makes is
  granted to that function's role, on that resource, and to nothing else.
- **Page and domain agree:** the form's limits (pieces, photos, 10 MB, the rate limit,
  1,000 characters) come from the domain's constants, not a second copy in a template or
  `upload.js`.
- **Settings are data:** nothing #6 calls a setting became a constant.
- **Names and tags:** every new resource name starts with `asmbly-ceramics-` from the one
  parameter, carries the five tags, and is within the deploy role's tag conditions.

**Phase mode:** check that criteria spanning areas are wired end to end (a use case, its
route, its template entry, its role's right, its test), not just present in each.

## Step 8: Privacy check

Spawn the privacy guardian whenever Step 5's privacy row applies, which is most changes
to `src/`, `infra/` and `.github/`. Spawn it with the Agent tool
(`subagent_type: privacy-guardian`). Its file is its system prompt and sets its model
and read-only tools.

**Provide only:**

- the repository path, the branch, and `BASE`
- the changed-file list and `git diff --stat <BASE>...HEAD`
- the phase document's path (phase mode)
- "Review this branch cold against your checklist. Return your findings and verdict in
  your output format."

Don't paste your findings, your reasoning, or what you think is fine. Its value is that
it reads the change without your conclusions.

If the Agent tool isn't available to you (for example inside an `/offshore` sub-agent),
read `.claude/agents/review/privacy-guardian.md` and apply it inline, and say in the
report that it ran inline, so it was not independent. If a spawn fails with a transient
error, retry up to three times before falling back.

Its BLOCK findings count as BLOCKs in the verdict, and its WARNs as WARNs.

## Step 9: Sequential independent review cycles (only if requested)

Skip this step unless the person asked for more than one cycle. Steps 5 to 8 are enough
for most changes.

Steps 5 to 8 are **Cycle 1**. Then spawn `N - 1` more reviewers, **one at a time**.
Between cycles you fix the obvious findings, so each later cycle reviews the post-fix
state and spends its attention on what is still wrong.

**Why sequential, not parallel:** parallel reviewers all rediscover the same surface
issues, and reconciling them turns into deduplication. Sequential cycles each start from
a cleaner baseline, so what cycle N finds survived cycle N-1's fixes.

### Per-cycle loop

For each cycle from 2 to N:

1. **Spawn the cycle reviewer** (below), fresh, with nothing from earlier cycles.
2. **Wait for its findings.**
3. **Fix between cycles**, in this order:
   - **BLOCKs:** fix before the next cycle. If a BLOCK is contested or needs the
     person's input, pause and ask; don't push it to the next cycle. Inside `/offshore`,
     where you can't ask, record it as unresolved and let the verdict say so.
   - **Obvious WARNs:** small, mechanical fixes (a missing test case, a type, a typo, a
     fake that doesn't raise what the port says, a log line that should use the ID).
     Apply them: option 1 of the Address-or-Defer rule.
   - **Subtle WARNs and NOTEs:** skip only with a real reason (option 2). Otherwise
     collect the finding for the decision pause at the end (option 3). Don't file a
     follow-on phase document or an issue yourself.
   - **Style findings:** after cycle 2, don't act on a style-only finding that reverses
     an earlier fix. Record it in the rollup instead of flip-flopping.
4. **Commit the fixes** on the branch, never on `main`, as
   `chore: address independent review #<N> findings` (name the plan in the body when
   there is one), listing what was fixed and what was deferred with its reason. Never
   commit a new follow-on phase document here.
5. **Run the checks** to confirm the fixes hold:

   ```bash
   uv run ruff check . && uv run ruff format --check .
   uv run mypy
   uv run pytest --cov
   ```

6. Move to the next cycle.

### Address-or-Defer rule

For every WARN or NOTE, you **propose** a disposition. There are three, and you may take
only the first two on your own:

1. **Address it now**, in this change. Cheap, mechanical, clearly in scope.
2. **Record a real reason not to fix it.** A real reason cites a contract, a test, a
   decision record, a story's criterion, or a tradeoff, with a reference. "It's small",
   "stylistic preference" and "we'll get to it" are not reasons; those findings belong
   in option 1 or option 3.
3. **Defer it**, to a follow-on phase document or a GitHub issue. This needs the
   person's explicit go-ahead before anything is created. Don't write a phase document,
   add to a plan's tracker, open an issue, or change any other plan document on your own.

Present each option-3 candidate as one decision point:

- **(a) Fold into this pull request:** the extra work (line estimate, files touched,
  scope risk)
- **(b) Defer it:** a follow-on phase document (which plan, what it covers) or an issue
  on this repository (its title; issues are public, so a drop-off is named by its ID,
  never by the person)
- **(c) Skip with a real reason:** the proposed reason and the reference behind it

Then wait for the person to pick. "(b), go" means write the document or open the issue.
"(a)" means fold the work in. "(c)" means record the reason and move the row to Part A
of the rollup.

Filing the deferral yourself feels efficient. Don't: the person may prefer to expand this
pull request instead of sequencing the work, and filing it takes that choice away. If
you want to skip a finding without option 1, option 2 or surfacing it as an option-3
candidate, stop and ask. If you can't ask (inside `/offshore`), leave every candidate in
Part B and create nothing.

### How to spawn each cycle

Spawn the `review-lead` subagent with the Agent tool (`subagent_type: review-lead`).
Its file is its system prompt; it has no Edit or Write tools.

**Provide:**

- the repository path, the branch name, and `BASE`
- the phase document's path (phase mode)
- the validation status, for example "ruff PASS, mypy PASS, 214 tests passing, coverage
  above the floor; don't re-run the checks"
- `git diff --stat <BASE>...HEAD`
- the perspective files that match the changed files (Step 5), from
  `.claude/agents/review/`; its own file is already its system prompt
- the cycle framing (below)
- the output demand: "Return a punch list with BLOCK / WARN / NOTE severity, one line per
  finding, file:line where it applies, at most 20 findings, most severe first. Mark
  anything you think should be deferred rather than fixed, with the reason."

The prompt must:

1. Say this is a cold, fresh review, and forbid assuming earlier reviewers caught
   everything.
2. Say earlier reviews ran and their fixes are applied: "Prior independent reviews ran
   and their findings were addressed before you started. You're reviewing the current
   state of the branch: what's still wrong, or what they missed."
3. Contain **none** of your reasoning, your findings, earlier cycles' findings, or hints
   about where to look in this diff. The focus areas below are generic categories; keep
   them generic.

**Middle cycles** (cycle 2 of 3, for example): "This is independent review pass <N>. The
earlier passes ran and their fixes are applied. Find what's still wrong or what they
missed." Focus: state transitions the domain allows that the story forbids, two staff
acting at once (version checks, conditional writes), a retried email or a repeated
submit, the path from a page through its use case to the adapter and its IAM right, call
sites a refactor missed.

**Final cycle:** "This is the final independent review pass (cycle N of N). Earlier
passes found structural problems that are now fixed. Find what they missed, and what's
structurally fragile even if it works today. Look in the corners." Focus: hostile input
on the public form (sizes, types, counts, markup, a forged `X-Forwarded-For`), personal
details reaching a log, an error, a URL or a fixture, a fake that behaves better than
AWS does, empty and missing values, time zones around midnight in Austin, hand-off notes
that promise what doesn't exist.

If the Agent tool isn't available to you (inside an `/offshore` sub-agent, for example),
read `.claude/agents/review/lead.md` and apply it inline for each cycle, and say in the
report that the cycles ran inline, so they were not independent. If a spawn fails with a
transient error, retry up to three times before falling back.

### Reconciliation

After every cycle has returned and its fixes are committed:

1. List what was fixed between each pair of cycles.
2. Highlight final-cycle catches: a finding that survived N-1 cycles is the real value.
3. Adjust the verdict if any cycle's BLOCKs remain unresolved.
4. Compile the deferrals rollup (Step 10). Every WARN and NOTE not fixed in this change
   appears there.

### When to recommend multi-cycle

Recommend it for large changes (over 1,000 lines), and for anything that changes how
personal details or photos are stored, shown, emailed or deleted, the public form's
checks, the console's sign-in and group check, IAM or the deploy role, or the close
(#7), and for the final pass before a phase's pull request is merged. Don't recommend it
for trivial changes, work in progress, or a quick feedback pass. If the person asks for
it on a tiny change, run it anyway.

## Step 10: The report

```markdown
## Review: <one line on what changed>

**Mode:** On-demand | Phase review: <plan> phase <N>: <title> [+ multi-cycle (sequential)]
**Base:** `<BASE>` (from the pull request | default `main` | named)
**Files changed:** <count>
**Reviewers:** <app, web, infra, docs, lead, privacy guardian (spawned | inline)>
**Cycles run:** <N> (sequential independent, with fixes between cycles)
```

Omit the "Cycles run" line for a single-cycle review.

**Phase mode:** add the completeness section.

```markdown
---

### Phase Completeness: <plan> phase <N>

| # | Acceptance criterion or promised file | Status |
| --- | --- | --- |
| 1 | <criterion> | DONE / PARTIAL / MISSING |

- Phase status updated in the phase document and the README tracker: yes / no
- Hand-off filled in: yes / no
- `Closes #N` only if this is the last phase in the story's **Stories** row, `Refs #N` otherwise: right / wrong / missing
- Admin actions this phase needs are in the pull request's **Risk** section: yes / no / none needed

**Assessment:** All criteria met / N criteria need attention / Phase not ready for hand-off
```

**Then the findings:**

```markdown
---

### Cross-Cutting Findings
<The lead's findings. Or: "Not applicable: one reviewer applied.">

### Privacy Check
<The guardian's findings and verdict. Or: "Not needed: nothing in the privacy row." Add "(ran inline)" if it did.>

---

### App Review
<Findings. Or: "No app files changed." Or: "No issues found.">

### Web Review
<Same rules.>

### Infra Review
<Same rules.>

### Docs Review
<Same rules.>
```

**Multi-cycle only:** add the reconciliation.

```markdown
---

### Cycle Reconciliation

**Cycle 1 (orchestrator):** N findings (B BLOCK, W WARN, X NOTE)
- Fixed before cycle 2: <list>
- Deferred (see rollup): <list>

**Cycle 2 (independent):** N findings (B BLOCK, W WARN, X NOTE)
- Fixed before cycle 3: <list>
- Deferred (see rollup): <list>

**Cycle 3 (independent):** N findings (B BLOCK, W WARN, X NOTE)
- Fixed: <list>
- Deferred (see rollup): <list>

**Final-cycle catches** (the final cycle found them; earlier cycles missed them):
- <list>

**Cross-confirmed findings** (more than one cycle flagged them):
- <list>

**Cycle 1 blind spots** (a later cycle caught them; the standard pass missed them):
- <list>
```

If both "Final-cycle catches" and "Cycle 1 blind spots" are empty, one cycle would have
been enough. If either holds a BLOCK, recommend multi-cycle for similar changes.

**Deferrals rollup:** required whenever the review produced WARN or NOTE findings.

```markdown
---

### Deferrals Rollup

#### Part A: Already disposed

| # | Finding | Cycle | Disposition | Reference |
| --- | --- | --- | --- | --- |
| 1 | <summary, file:line> | Cycle N | Fixed in this pull request / Real reason not to fix | <commit SHA or cited reason> |

#### Part B: Awaiting your decision

**Candidate 1: <summary, file:line>** (flagged by cycle N)

- **(a) Fold into this pull request:** <line estimate, files touched, scope risk>
- **(b) Defer it:** <a phase document under `<plan>` covering <one sentence>, or an issue titled "<title>">
- **(c) Skip with a real reason:** proposed: "<reason>"; reference: <code, test, decision or story>

Recommendation: <a | b | c>, because <one line>. Tell me which and I'll do it.
```

Write "No items in this part." for an empty part. A Part A row without a Reference isn't
disposed: move it to Part B. While Part B has candidates, don't create a phase document,
add to a plan tracker, open an issue, or change any other plan document. After the
person picks: (a) fold the work in, re-run the checks, and review the new code once;
(b) write the document or open the issue; (c) move the row to Part A.

**Close with:**

```markdown
---

### Verdict: APPROVED / CHANGES REQUESTED / NEEDS DISCUSSION

### What's Good
- <things done well, across all reviewers, briefly>
```

**Verdict logic:**

- **APPROVED:** no BLOCKs, from any reviewer or the privacy guardian. In phase mode,
  every criterion DONE.
- **CHANGES REQUESTED:** any BLOCK. In phase mode, any criterion MISSING.
- **NEEDS DISCUSSION:** a finding that needs the maintainer's judgment (an accepted risk,
  a change to a decision record, a story's wording), or PARTIAL criteria with unclear
  scope.

The verdict is advice. Only the maintainer (@sababado) decides a merge, for that pull
request, in the conversation; this review never merges, approves on GitHub, or pushes
to `main`.

**Formatting rules:**

- A reviewer section with no findings is one line: "No issues found."
- An area with no changed files is one line: "No <area> files changed."
- NOTEs are one line each. Don't pad a clean review; say it's clean and stop.
- Never quote a person's details in the report, even from a fixture you are flagging:
  name the file and line, and say what kind of detail it is.

**Scale each explanation to the fix:**

- **Simple fix** (use a constant, log the ID, add a test case): one sentence with the
  problem and the fix.
  > **web/routes.py:88**: The 6-photo limit is written again as `6`. Use
  > `MAX_PHOTOS` from `domain/photos.py`. Ref: `CLAUDE.md`, Planned shape.
- **Moderate fix** (missing check, wrong pattern, a fake that disagrees with its port):
  two or three sentences: the problem, the risk, the fix.
- **Complex fix** (a privacy leak, a role that reaches another project, a rule decided in
  two places): lead with the problem and the fix, then describe the failure: what
  request, what leaks or breaks, and who sees it.

A developer scanning the review should see what to do first. The explanation supports
the fix; it doesn't bury it.

## Error handling

- **Not a git repository:** "This doesn't appear to be a git repository."
- **On `main` with no pull request:** see Step 2.
- **No changes:** see Step 3.
- **`gh` not available:** skip pull request detection; use `main`.
- **Ambiguous plan name:** ask ONE question listing the plans.
- **Plan not found:** "Couldn't find a plan matching '<hint>'. Plans: <list>."
- **Phase document not found:** "Plan '<name>' has no phase <N> document. Available:
  <list>."
- **Very large diff (200+ files):** warn and suggest scoping, then proceed.

## Notes

- Read each reviewer's file before its review. The files distill the rules from
  `CLAUDE.md`, decision 0002 and the plan; read those sources when a finding needs more
  context, and cite them.
- In phase mode, the phase document says what should have been built and the diff shows
  what was built. Check both the rules and completeness.
- Outside the between-cycle fixes in Step 9, don't change code. Flag the issue and
  describe the fix.
- Read only. Don't run an AWS command that changes anything, and never read a drop-off's
  personal details or photos, even read-only, to check a finding.
- Write each section in its reviewer's voice: the lead is blunt, the app reviewer is
  clinical, the web reviewer reads every field as hostile, the infra reviewer is exact
  about names and rights, the docs reviewer is warm but firm, the privacy guardian is
  calm and reads as someone who wants the data.
