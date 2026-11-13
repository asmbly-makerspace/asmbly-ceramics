---
name: prep
description: Check one phase of an implementation plan against the actual code before building it - file paths, dependencies, reference patterns, stale test fakes, the domain model's boundaries, ports and fakes, personal-data and photo privacy, IAM rights, names and values wiring, the rollout's check and undo, size, an adversarial audit, and story alignment - and return READY TO IMPLEMENT, NEEDS REVISION, or BLOCKED. Use when asked to prep, ground-truth, or check readiness of a plan phase.
argument-hint: "<plan> [phase N]"
model: sonnet
effort: high
---

You prepare a plan phase for implementation. You check every claim the phase document
makes against the code (and, read only, the account), hand the adversarial thinking to
the auditor, and produce a readiness report the builder can use directly. You don't
write code.

The request:

$ARGUMENTS

---

## Step 1: Identify the plan

**A plan name:** list active plans (`ls -d .implementation_plans/*/ | grep -v DONE`) and
match the input against them (`drop-off` → `drop-off-and-firing/`). Several matches or
none: list them and ask the user to pick.

**No plan name:** look for a hint in the branch name (`feat/2-drop-off-form`). If
nothing matches, list active plans and ask.

Note the phase if one was named ("phase 2"); otherwise Step 3 finds it.

## Step 2: Read the plan

1. Read the plan's `README.md`: the domain model, the phase tracker, the Stories table,
   dependencies, admin actions and rollout.
2. List the phase files. Check that every tracker row has a file and every file has a
   row. Mismatches are findings.

## Step 3: Determine the phase

If the user named one, use it. Otherwise take the first tracker row not marked
`[x] Complete`, then confirm against reality: if the phase creates a file that already
exists, that phase is probably done even if the tracker says otherwise. Check
`git log --oneline origin/main -- <paths>` for commits that delivered it.

If every phase looks complete, say so and ask whether a different plan was meant.

## Step 4: Load context

Always read `CLAUDE.md`, `docs/architecture.md` and `.implementation_plans/readme.md`.
Then, by the phase's `domain` (or by the paths it touches, in legacy mode):

| Domain | Also read |
| --- | --- |
| `app` | `src/asmbly_ceramics/` (the domain, use cases, ports, adapters, fakes) and their tests |
| `web` | the pages and their tests, and the use cases they call |
| `infra` | `infra/`, the decision records, and the runbook the phase is a step of |
| `ci` | `.github/workflows/`, `.github/rulesets/main.json` |
| `docs` | `docs/README.md` and the documents named |

You need this to judge the plan against the rules. Don't skip it.

## Step 5: Ground-truth the phase

This is the core of prep. Don't trust the plan: verify every claim against the code and,
read only, the account.

### 5a: File paths and resources

For every path and resource in the phase document:

- **Files to create:** the parent directory exists, and the file does not (if it does,
  the plan is stale).
- **Files to modify:** the file exists, and the types, functions, ports or resources the
  plan names are still in it.
- **Live resources it names**, once there are any: it exists with the name the plan
  says (`aws s3api head-bucket`, `aws cloudformation describe-stack-resources`, with
  `AWS_PROFILE=asmbly`, us-east-2). Never read a drop-off's details or photos, and never
  change anything.

```markdown
| Reference | Expected | Actual | Status |
| --- | --- | --- | --- |
| `DropOff.reject` | In `src/asmbly_ceramics/domain/drop_off.py` | Found, line 42 | OK |
```

### 5b: Dependencies

For each prerequisite the phase declares (`depends_on`, the README's Dependencies):

- Is the earlier phase marked complete, and does the code confirm it?
- Is the work it needs in another repository done (`gh issue view <N> -R
  asmbly-makerspace/<repository>`), and deployed where that matters?
- Are the by-hand steps it relies on listed under Admin actions?

### 5c: Reference patterns

Find the closest existing example of what this phase builds, so the builder can copy it:
a use case, a port and its fake, an adapter, a page, a template or a workflow step, here
or in a sibling repository. Give two to four paths, each with one line on why it fits.

### 5d: Stale fake sweep

When the phase renames, moves or changes a type, a use case, a port or a template's
logical ID, existing tests and fakes may still use the old one. Grep `tests/` and
`src/asmbly_ceramics/` for each old name. Each hit is a HIGH finding. If nothing moves,
note "N/A".

### 5e: Boundaries

- The domain and use cases the phase writes import no AWS library and no web framework.
- Every new port has an in-memory fake and an AWS adapter (in this phase or a named
  later one), and the use case tests use the fake.
- Every rule a story states is in the domain, not re-decided in a page or adapter.
- Nothing a story calls a setting is a constant.

A breach is a HIGH finding.

### 5f: Personal data, photos and email

- No log line, error, test fixture or public page holds a name, email, phone, rejection
  message, photo or token.
- Photos stay private: no public bucket, object or address.
- Emails go only from the console's `asmbly.org` address, to the person who dropped off
  or the signed-in staff member.
- Every console page checks the `ceramics` group.

A breach is a HIGH finding.

### 5g: Rights and names

For every AWS action the phase's adapters or deploy need, check that the role that will
run it is given that right in this phase or an earlier one, scoped by the
`asmbly-ceramics-` prefix or the `Project` tag, and that nothing grants a right over
another project's resources. A missing right is a HIGH finding (it fails at run time);
an extra one is a HIGH finding too. For every name that crosses a boundary (an output a
workflow reads, an environment variable an adapter reads, a staff sign-in value), check
that both sides use the same name.

### 5h: Rollout

For a phase that reaches AWS: its `## Rollout` has what is done, a check with its
expected output, who confirms it, and an undo with its own check. Anything missing is a
HIGH finding.

### 5i: Size

| Estimate | Verdict |
| --- | --- |
| < 400 lines | OK |
| 400–800 | LARGE: say so, and watch the scope |
| > 800 | Recommend a split, with the split points |

## Step 6: Specialists

Run these every time. You don't get to decide a specialist isn't needed.

**How to spawn.** Spawn each with the Agent tool (`subagent_type: drift-detector`,
`subagent_type: prep-auditor`). Its agent file is its system prompt and sets its model and
tools, so the prompt carries only the inputs listed below. If the Agent tool isn't
available to you, read its file in `.claude/agents/prep/`, apply it inline, and say so in
your report.

**Order matters.** The auditor reads the drift report so it doesn't repeat mechanical
findings. Wait for the drift detector to return before you spawn the auditor.

### 6a: Drift detector

Provide: the full phase document, the plan directory, and the repository root. It
returns a drift report (Critical / High / Medium / Low). Fold its findings into Plan
Health and Findings; don't repeat them in the auditor's section.

### 6b: Auditor

Provide: the plan name and phase, the phase document, the README tracker, your Step 5
findings, and the drift report. It returns a punch list of HIGH / MED / LOW findings with
an action tag each. Pass them through as written.

## Step 7: Story alignment

Run this step only when the phase document starts with YAML frontmatter. On a legacy
phase document, skip it silently: no warning, no section in the report.

**Fetch.** For each number in `implements:`, run
`gh issue view <n> --json number,title,state,labels,body`. The story's acceptance
criteria are the `- [ ]` and `- [x]` lines under `## Acceptance criteria` in its body.

**Class A: frontmatter errors (BLOCKING).** Any of these makes the verdict BLOCKED. Name
the phase document's path in the finding so the user knows which file to fix.

- `implements:` is not a list, or an element isn't a positive integer.
- An issue doesn't exist.
- An issue isn't labeled `story`.
- An issue isn't a sub-issue of the phase's `epic:` and isn't listed in the epic's body.
  Check with `gh api repos/{owner}/{repo}/issues/<epic>/sub_issues --jq '.[].number'`,
  then the epic's body.
- The phase document has frontmatter but its plan has no README.

**Operational errors never block.** If `gh` can't reach GitHub or returns an error
without a clear 404, mark that story SKIPPED, don't retry it within this run, and tell the
user to re-run `/prep` when access is back.

**Class B: coverage (ADVISORY).** For each story, match each criterion to a deliverable in
this phase (Files to create or modify, Implementation details, Tests, Acceptance
criteria, Rollout). A criterion that another phase in the README's Stories row delivers
counts as covered (note "covered by phase N"). Also flag deliverables that serve no
criterion and aren't infrastructure the criteria need. Then pick exactly one state:

| State | When | Effect on the verdict |
| --- | --- | --- |
| ALIGNED | Every criterion covered, no unjustified deliverables | None |
| PARTIAL-MINOR | 1 uncovered criterion, 0 unjustified deliverables | None (informational) |
| PARTIAL | 2+ uncovered criteria, or 1+ unjustified deliverables | READY → NEEDS REVISION |
| MISALIGNED | 3+ uncovered, or a story with no criteria covered | READY → NEEDS REVISION |
| NOT EVALUATED | No story had parseable criteria | None |
| N/A | `implements: []` or no `implements:` key (infrastructure phase) | None |

Class B never produces BLOCKED, and never upgrades a worse verdict.

## Step 8: Report

Combine your findings, the drift report, and the audit. **Be terse.** The punch list is
the value.

- A clean section is one line: `**Ground-truth:** clean (paths, boundaries and dependencies verified).`
- Omit a section with nothing useful in it.
- Pass the auditor's lines through unchanged.

```markdown
## Prep report: <plan> — Phase <N>

**Phase:** <N> — <title> · **Domain:** <app/web/infra/...> · **Branch:** <current>
**Plan progress:** <X of Y complete> · **Estimated size:** ~<N> lines (<OK/LARGE/SPLIT>)
**Reaches AWS:** yes / no

### Plan health
<One paragraph at most.>

### Reference patterns
- `<path>` — <why>

### Findings
**Findings:** <H> HIGH, <M> MED, <L> LOW
- **HIGH** [Category] — <finding>. → **<action>**: <remediation>

### Story alignment
<Only when Step 7 ran.>

### Context loaded
- [x] CLAUDE.md · [x] docs/architecture.md · [x] .implementation_plans/readme.md · [x] <others>

### Verdict: READY TO IMPLEMENT / NEEDS REVISION / BLOCKED
<One line on why, one line on the next action.>
```

**Verdict rules:**

- **BLOCKED:** a prerequisite phase or another repository's work isn't done, a Class A
  error, or a drift Critical that makes the phase impossible as written.
- **NEEDS REVISION:** any HIGH finding with `fix-before-build`, a boundary or privacy
  breach, a missing or extra right, a name mismatch, an incomplete rollout, a stale
  fake, a size over 800 lines, or Class B PARTIAL or MISALIGNED.
- **READY TO IMPLEMENT:** none of the above.

## Step 9: Next steps

- **READY TO IMPLEMENT:** build the phase under `CLAUDE.md`, using the reference patterns
  and findings above, set its tracker row to `[~] In progress` in the first commit, and
  finish with `/ship`.
- **NEEDS REVISION:** list the edits the phase document needs, and offer to make them.
- **BLOCKED:** say what blocks it and how to unblock it.

## Rules

- Read the files, not summaries. The README drifts, phase documents drift, the code and
  the account are the truth.
- Don't implement. Prep prepares.
- Read-only AWS only. Never read a drop-off's personal details or photos.
- If the branch doesn't match the plan, note it but don't block.
