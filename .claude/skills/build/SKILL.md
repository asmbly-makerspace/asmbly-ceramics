---
name: build
description: Build one phase of an implementation plan (or written instructions) with the build team - architect, coder and critic, validator, self-review, fixer - committing after each step, then a mandatory independent review by a fresh review-lead subagent (and the privacy-guardian when personal data, photos, email, the public form, staff access or AWS is touched), and update the plan's tracker. Use when asked to build or implement a plan phase, or when /offshore or /bug-fix calls it.
argument-hint: "<plan> [phase N] | instructions: <path or text>  [base <sha>]"
model: opus
effort: high
---

# Build

You are the build orchestrator for asmbly-ceramics. You coordinate a team of build
perspectives that turn a plan phase (or a set of instructions) into working, tested,
reviewed code that follows `CLAUDE.md`.

You don't write or review code in your own voice. At each step you read a perspective's
file, adopt it, and pass its output to the next. Two reviews run as separate subagents
so that they see the work cold: the `review-lead` always, and the `privacy-guardian`
when the change can leak a person's details or reach AWS.

The request:

$ARGUMENTS

---

## Your team

| Agent | File | Produces | Step |
| --- | --- | --- | --- |
| Architect | `.claude/agents/build/architect.md` | Build Manifest, with its Privacy and AWS touchpoints | 4 |
| Coder | `.claude/agents/build/coder.md` | Code and tests, one commit per step | 5 |
| Critic | `.claude/agents/build/critic.md` | CATCH / QUESTION findings | 5, after each step |
| Validator | `.claude/agents/build/validator.md` | Validation Report | 6 and 9 |
| Lead reviewer + specialists | `.claude/agents/review/lead.md` + the specialists in Step 7 | BLOCK / WARN / NOTE | 7 |
| Fixer | `.claude/agents/build/fixer.md` | Fix Report | 8 and 10 |
| `review-lead` subagent | `.claude/agents/review/lead.md` | BLOCK / WARN / NOTE, cold | 10 |
| `privacy-guardian` subagent | `.claude/agents/review/privacy-guardian.md` | BLOCK / WARN / NOTE, cold | 10, when Step 10's triggers apply |

All but the two subagents are perspectives you adopt. **Read each agent file before you
adopt it, every time you switch.** The file holds the personality, process, checklist and
output format; don't work from memory of it.

There is no UI designer: there is no UI kit and no frontend app here. Pages are
server-rendered Jinja2 templates, and what makes them phone-friendly, accessible and
safe (autoescape, the Content-Security-Policy, a form that works on a phone) is in the
Coder's standards and the Critic's checks.

---

## Step 1: Identify what to build

**A plan phase was named** ("phase 2 of drop-off-and-firing"):

1. Find the plan in `.implementation_plans/` (not under `DONE/`). Several matches or none:
   list the active plans and ask.
2. Read the phase document in full, then the plan's `README.md`: the domain model, the
   rules table, the ports, the Stories table and the phase tracker.
3. Check prerequisites: every phase in `depends_on` is `[x] Complete` in the tracker
   **and** its code exists. A dependency still `[~] In progress` counts only when its
   code is on this branch (an `/offshore` run, or an unmerged earlier phase) and it is
   `[~]` because its rollout check waits for a merge; then this phase must not rely on
   that rollout having happened, and the report says so; the work in other repositories the README's Dependencies
   table lists for this phase is done (`gh issue view <N> -R asmbly-makerspace/<repo>`).
   If `/prep` ran for this phase, use its report: its reference patterns and findings
   are your starting point, and a NEEDS REVISION or BLOCKED verdict that wasn't resolved
   stops you here.

**`instructions: <path or text>`** (from `/bug-fix`, or a person with no plan): the
instructions are the specification. There is no phase document or tracker to update at
the end. If the request says `base <sha>`, use that SHA wherever this skill diffs
against the base.

**Empty or vague input:**

1. Look for a plan name in the branch (`feat/drop-off-and-firing-phase-2`).
2. Take the first tracker row in that plan that isn't `[x] Complete`.
3. If it's still unclear, ask what to build. Inside `/offshore`, never ask: pick, and
   record why in the report.

## Step 2: Load context

Load all of this before any perspective starts. It isn't optional.

1. Always: `CLAUDE.md`, `docs/architecture.md`, `.implementation_plans/readme.md`, and
   the decision records the phase cites (decision 0002 for the stack).
2. By the phase's `domain` (or by the paths the instructions touch):

   | Domain | Also read |
   | --- | --- |
   | `app` | `src/asmbly_ceramics/` (the domain, ports, fakes, use cases, adapters, mail) and their tests |
   | `web` | the pages and templates in `src/asmbly_ceramics/web/`, their tests, and the use cases they call |
   | `infra` | `infra/`, `src/asmbly_ceramics/composition.py`, the runbook the phase is a step of in `docs/runbooks/` |
   | `ci` | `.github/workflows/`, `.github/rulesets/main.json`, `tests/repo/` |
   | `docs` | `docs/README.md` and the documents the phase names |

3. The phase document: it is the build specification. Its **Required reading** is part
   of this step.

If the phase document contradicts `CLAUDE.md` or a decision record, the documents win.
Follow them and say so in the report.

## Step 3: Branch and base

- Already on a branch for this work (`feat/...`, `fix/...`, `chore/...`, or the branch
  `/offshore` or `/bug-fix` created): use it.
- Otherwise branch from an up-to-date `main`:

  ```bash
  git fetch origin main
  git switch -c feat/<plan>-phase-<N> origin/main     # fix/<name> or chore/<name> for ad-hoc work
  git branch --unset-upstream 2>/dev/null || true      # a bare `git push` must never target main
  ```

- Never commit to `main`.

Record the base now: the `base <sha>` from the request if there is one, otherwise
`git merge-base HEAD origin/main`. Every later `<BASE>` means this SHA, written out in
full: shell variables don't carry over between Bash calls.

For a plan phase, set its row in the README's phase tracker to `[~] In progress` and its
phase document's Status line to `> **Status:** [~] In progress`. Both go into the first
step's commit.

## Step 4: Architect

Read `.claude/agents/build/architect.md` and adopt the Architect.

- **Input:** the phase document (or instructions), the context from Step 2, the code.
- **Output:** a Build Manifest: reference patterns, build sequence (each step with its
  Verify check and its commit message), Privacy and AWS touchpoints, risk register,
  scope check.

Show a 5 to 10 line summary of the manifest, then carry on. Don't wait for approval:
say what you're about to do and continue.

If the scope check is past about 800 changed lines (L in `.implementation_plans/readme.md`
is under 800), warn and suggest a split; continue only if the person agrees. Inside
`/offshore`, return needs-split with the suggested split instead.

## Step 5: Coder and Critic loop

For each step in the manifest, in order:

**5a. Coder writes.** Read `.claude/agents/build/coder.md` and adopt the Coder.

- Follow the manifest's sequence and reference patterns.
- Tests go in the same step as the code, not afterwards. The domain is tested with no
  fakes and no AWS; use cases against the in-memory fakes; adapters against stubbed AWS
  clients; pages through Starlette's test client with use cases built from fakes.
- **Regression test first** when the instructions ask for one (`/bug-fix` does): write
  it, run it, and confirm it fails for the reported reason before writing the fix.
  Commit it on its own (`test: reproduce <the bug>`) and keep the failing output for the
  report.
- **Seams in one step:** a template resource, its IAM statement, the environment
  variable that names it and the code that reads it change together.
- **Page wiring:** when a step connects a page to a use case, write at least one test
  that requests the page through the test client with the use case built from fakes and
  asserts what the page shows (the ID, the message next to the field). A test that
  renders the template with a hand-made context doesn't cover the step from use case
  result to page.
- **Logging:** a module that logs gets a `caplog` test that its lines hold the ID and
  none of the made-up person's details.

**5b. Critic checks.** Read `.claude/agents/build/critic.md` and adopt the Critic. Check
what was just written and how it fits the earlier steps. Output: CATCH and QUESTION
findings, or nothing.

**5c. Coder fixes.** Switch back to the Coder. Fix every CATCH; verify every QUESTION
and fix it if it's real.

**5d. Commit the step.** Run the step's Verify check from the manifest, then commit:

- A Conventional Commit subject: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
  `chore:` or `ci:` (for example `feat: refuse a seventh photo in the domain`).
- In the body, `Refs #N` for each story the step works toward. `Closes` comes once, in
  Step 11.
- Before committing, read `git diff --staged`: no `.env`, no secret, no account ID, no
  real person's name, email, phone number or photo, nothing unrelated. The repository is
  public; a pushed commit is public at once.
- Never `--no-verify`. Don't carry uncommitted work into the next step. Don't push
  unless the caller told you to.

Then move to the next step.

## Step 6: Validator (first pass)

Read `.claude/agents/build/validator.md` and adopt the Validator. It runs, from the
repository root:

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

then any further check `CLAUDE.md`'s "Done means verified" lists for what changed, then
the standards scan over the diff. Output: a Validation Report.

If the verdict is FIXES NEEDED: switch to the Coder, fix, commit, and re-run the failed
checks until ALL CLEAR.

## Step 7: Self-review

Read `.claude/agents/review/lead.md` and apply it inline as the lead reviewer. Then read
and apply the specialists that match the changed files (`git diff --name-only <BASE>..HEAD`;
skip files under `.implementation_plans/` and `.claude/`):

| Changed files | Specialist |
| --- | --- |
| `src/asmbly_ceramics/domain/`, `ports/`, `use_cases/`, `adapters/`, `mail/`, `composition.py`, `entry/`, `pyproject.toml`, `uv.lock` | `.claude/agents/review/app.md` |
| `src/asmbly_ceramics/web/` (pages, templates, static files) | `.claude/agents/review/web.md` |
| `infra/`, `.github/`, `samconfig.toml` | `.claude/agents/review/infra.md` |
| `docs/`, `README.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `SECURITY.md` | `.claude/agents/review/docs.md` |

Read each file fresh before applying it. Do the lead's cross-cutting review. Produce
BLOCK / WARN / NOTE findings with file:line. For a plan phase, also mark each deliverable
DONE / PARTIAL / MISSING.

## Step 8: Fixer

Read `.claude/agents/build/fixer.md` and adopt the Fixer.

- **Input:** every finding from Step 7.
- Fix every BLOCK. Fix the straightforward WARNs. Defer complex WARNs with a reason.
  NOTEs need no action.
- Commit the fixes and produce the Fix Report.

## Step 9: Validator (re-check)

Read `.claude/agents/build/validator.md` again and run the same checks as Step 6, in
full. Fixes break things too. Fix and re-run until ALL CLEAR.

## Step 10: Independent review (mandatory)

**Never skip this step, whatever the size of the change.** Steps 7 to 9 were done by the
agent that wrote the code: the same mental model, the same blind spots. A reviewer with
no memory of the build reads the code cold, as the maintainer reviewing the pull request
would. It catches the wiring bugs self-review misses: an environment variable the
template sets under one name and `composition.py` reads under another; a page that
reads `summary.drop_off_id` when the use case returns `summary.id`; a log line that
passes the whole request to an f-string.

**10a. Spawn the `review-lead`** with the Agent tool (`subagent_type: review-lead`). Its
file, `.claude/agents/review/lead.md`, is already its system prompt. Its prompt carries
only:

- the repository path, the branch, and `<BASE>` (from `main`);
- the changed files (`git diff --name-only <BASE>..HEAD`) and `git diff --stat <BASE>..HEAD`;
- the specialist files from Step 7's table that match those files (it reads them
  itself);
- the phase document's path, if there is one (the spec, not your notes on it);
- the validation status from Step 9, for example "ruff PASS, mypy PASS, pytest PASS
  (212 passed, coverage 94%); don't re-run the mechanical checks";
- "Read CLAUDE.md first. Review this branch cold. Return BLOCK / WARN / NOTE findings,
  one line each, with file:line, at most 20."

**10b. Spawn the `privacy-guardian`** too (`subagent_type: privacy-guardian`, file
`.claude/agents/review/privacy-guardian.md`), in the same message so the two run side by
side, when the change touches any of:

- how a person's name, email, phone, rejection message or photos are stored, shown,
  emailed, logged, kept or deleted;
- the public drop-off form: its fields, checks, limits, rate limit or upload;
- the emails the app sends: what, to whom, from which address;
- who can open the staff console: sign-in, tokens, the `ceramics` group check, CSRF,
  the session;
- AWS: `infra/`, IAM, environment variables, `composition.py`, an AWS adapter, or
  `.github/workflows/`.

The Architect's Privacy and AWS touchpoints say which apply; check them against the
real diff. When unsure, spawn it. Its prompt carries the same items as 10a, plus the
diff of the files that triggered it (`git diff <BASE>..HEAD -- <files>`; if that is over
about 3,000 lines, the file list only, saying the diff was too large), with: "Read
CLAUDE.md first. Check this branch cold for anything that could leak a person's details
or photos, let hostile input through the public form, let someone outside `ceramics`
into the console, send email from or to the wrong address, or reach past the
`asmbly-ceramics-` prefix in AWS. Return BLOCK / WARN / NOTE findings, one line each,
with file:line."

**Never include** your reasoning, your build decisions, the Step 7 findings, or hints
about where to look. That contaminates the cold read.

**If the Agent tool isn't available to you** (for example inside an `/offshore` or
`/bug-fix` sub-agent): read `.claude/agents/review/lead.md` (and
`.claude/agents/review/privacy-guardian.md` when 10b applies) and apply them inline, and
say in the final report that the independent review ran inline and was not independent.
If a spawn fails with a transient error, retry up to three times before falling back.

Handle the findings:

1. BLOCKs: adopt the Fixer (Step 8's process), fix them, re-run the Validator (Step 9),
   commit.
2. WARNs: the Fixer's rules apply (fix if straightforward, else defer with a reason).
3. A `privacy-guardian` finding whose only fix is the maintainer's decision (accepting a
   risk, keeping a detail longer, a right in another repository): stop and ask. Inside
   `/offshore`, return it as the blocker.
4. Say in the final report that the independent review ran, and what it found.

## Step 11: Update the plan

Skip this step for an instruction-only build.

**11a. The phase document.** Set its Status line, mirroring the format sibling phases in
the same plan use:

- **Rollout says "Nothing reaches AWS":** `> **Status:** [x] Complete — YYYY-MM-DD on
  branch <branch>`. It takes effect when the pull request merges.
- **The phase reaches AWS** (its Rollout has a check and an undo): leave
  `> **Status:** [~] In progress`. `.implementation_plans/readme.md` marks it complete
  only once it is merged **and** its rollout check is confirmed; say in the report who
  flips it and after which check.

Fill in its `## Hand-off` section: what the next phase can rely on (module and class
names, port methods, page paths, template resource names and outputs, environment
variables, Parameter Store names), and anything deferred.

**11b. The README's phase tracker.** Set this phase's Status cell to match 11a
(`[x] Complete`, or leave `[~] In progress`). Touch no other row and no other section.

**11c. Story keywords.** Read the phase's `implements:` and the README's Stories table:

| Story | Keyword |
| --- | --- |
| This phase is the last one in the story's row | `Closes #N` |
| A later phase in the row still delivers part of it | `Refs #N` |

`implements: []` (pure infrastructure) gets no keywords. A bare `#N` in prose closes
nothing; only the keywords count.

**11d. Commit separately**, so reviewers can scan it on its own:

```
docs(<plan>): mark phase <N> complete        # or: record phase <N> hand-off

Closes #2
Refs #4
```

The pull request repeats the same lines in its **Closes** section: GitHub closes an
issue from the pull request when it merges. If the phase document was already updated
and nothing changed, skip the commit and say so in the report, so the person can check
the documents by hand.

A merged phase whose document and tracker don't say where it stands is a defect.

## Step 12: Final report

Report only what you verified. A deliverable is DONE when a passing test or check proves
its acceptance criterion; a check is PASS only if you ran it.

```markdown
## Build complete: <description>

**Phase:** <plan>: phase <N>, <title> (or "Instructions: <summary>")
**Branch:** <branch> · **Base:** <BASE> · **Commits:** <count> · **Files changed:** <count>

### Deliverables
| # | Deliverable | Status | Proved by |
| --- | --- | --- | --- |
| 1 | ... | DONE / PARTIAL | <test or check> |

### Verification
- `uv run ruff check . && uv run ruff format --check .`: PASS / FAIL
- `uv run mypy`: PASS / FAIL
- `uv run pytest --cov`: PASS / FAIL (<X> passed, <Y> failed; coverage <N>%)
- Other checks in `CLAUDE.md`: PASS / FAIL / none listed

### Regression test (when one was asked for)
- `<path>::<name>`: failed before the fix (<one-line failure>), passes after

### Reviews
- Self-review: <n> BLOCK, <n> WARN, <n> NOTE
- Independent review (`review-lead`): ran as subagent / ran inline (not independent); <n> BLOCK, <n> WARN
- Privacy review (`privacy-guardian`): ran as subagent / ran inline / not needed (why); <n> BLOCK, <n> WARN

### Findings resolved
- <n> BLOCKs fixed
- <n> WARNs fixed
- <n> WARNs deferred: <finding> (<reason>; suggested follow-up issue)

### Risk (for the pull request)
- Personal details and photos: <what changed, or "none">
- The public form: <...>
- Who can open the console: <...>
- Emails sent: <...>
- AWS and IAM: <...>

### Plan
- Phase status: <Complete / In progress until <who> confirms <check>> · Stories: Closes <#N> / Refs <#N> / none

### Admin actions
- <a Parameter Store value to set, a stack deployed by hand, a change in another repository>, or "None"

### Next steps
- `/review` for a formal review, or `/ship` to open the pull request to `main`
```

The Risk lines are what `/ship` (or `/offshore`) copies into the pull request's **Risk**
section.

---

## Order of work

Build inside out, so nothing references what doesn't exist yet:

1. Domain types, rules and constants
2. Ports, then their in-memory fakes
3. Use cases (and the email composer)
4. AWS adapters (`uv add` for a new library)
5. Pages and their templates; Lambda entry points
6. `composition.py` and `infra/`, with the code that reads each name, in one step
7. Workflows and `tests/repo/` rules
8. Docs

Independent pieces (two domain rules, two fakes, two pages with no shared template) can
be written side by side.

---

## Errors

- **Plan not found:** list the active plans and ask (inside `/offshore`, return blocked).
- **A prerequisite isn't done** (a phase, or work in another repository): say what's
  missing and ask whether to proceed. Inside `/offshore`, return blocked.
- **A check fails and the Coder can't fix it:** stop and report the file, line and error.
  Never skip, delete or weaken a test, lower the coverage floor, or use `--no-verify` to
  get to green.
- **Scope too large** (past about 800 lines): warn, suggest a split, continue only if the
  person agrees.
- **Conflicting standards:** `CLAUDE.md` and the decision records win over the phase
  document. Follow them and say so.
- **A step would need AWS changed** (a stack deployed, a parameter set): don't. Write it
  under Admin actions; changes reach AWS only through a merge's deploy or a runbook step
  the maintainer asks for.
- **You can't ask the person** (inside `/offshore`): stop where you would ask, and return
  the question as the blocker in your report. Anything smaller, decide and record.
