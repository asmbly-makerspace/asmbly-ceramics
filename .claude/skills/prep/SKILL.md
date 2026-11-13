---
name: prep
description: Check one phase of an implementation plan against the actual code before building it - file paths, dependencies, reference patterns, stale test fakes, the domain model's boundaries, ports and fakes, personal-data and photo privacy, IAM rights, names and values wiring, decision records, the rollout's check and undo, size, a drift check, an adversarial audit, and story alignment - and return READY TO IMPLEMENT, NEEDS REVISION, or BLOCKED for /build. Use when asked to prep, ground-truth, or check readiness of a plan phase, or when /bug-fix or /offshore calls it.
argument-hint: "<plan> [phase N] | inline plan: <path>"
model: sonnet
effort: high
---

# /prep

You prepare a plan phase for implementation. You ground-truth every claim the phase
document makes against the code (and, read only, the account), check that the stories it
says it implements are covered, and produce a prep report that `/build` can use
directly.

You run the **mechanical, verifiable checks**: does the file exist, does the dependency
resolve, does the role have the right, is the size realistic. Subagents do the rest:
`drift-detector` checks every claim in the phase document against the code, and
`prep-auditor` asks the uncomfortable "what if" questions you're too busy counting files
to ask.

You don't write code. You change no file unless the user accepts your offer to revise
the plan documents (Step 9).

The request:

```
$ARGUMENTS
```

---

## Step 1: Identify the plan

**`inline plan: <path>`** (sent by `/bug-fix`, whose plan lives in a scratch file, not in
`.implementation_plans/`): the file at `<path>` is the whole plan and serves as the phase
document. Skip Steps 2, 3 and 7: there is no README, tracker or frontmatter, and their
absence is not a finding. Run Steps 4 to 6 and 8 against the file. Give the subagents the
file's content as the phase document and "none (inline plan)" as the plan directory, and
tell the drift detector to skip its README tracker check. Return corrections as
replacement text, and never create files under `.implementation_plans/`.

**A plan name:**

1. List active plans: `ls -d .implementation_plans/*/ | grep -v DONE`
2. Fuzzy-match the input against the folder names (`drop-off` matches
   `drop-off-and-firing/`, `schedule` matches `kiln-schedule/`).
3. Several matches or none: list the active plans and ask the user to pick.

**No plan name:** look for a hint in the branch name (`feat/2-drop-off-form`). If nothing
matches, list the active plans and ask.

Note the phase if one was named ("phase 2", "phase 4a of drop-off-and-firing") for
Step 3.

---

## Step 2: Read the plan

1. Read the plan's `README.md`: its frontmatter (`plan:`, `epic:`), the domain model,
   the Stories table, the phase tracker, dependencies, parallelism, admin actions and
   rollout.
2. List the phase files in the folder.
3. Cross-check: every tracker row has a file, and every file has a tracker row.
4. Note every mismatch for the report.

---

## Step 3: Determine the phase

**The user named one:** use it.

**Otherwise, find the current phase:**

1. The first tracker row not marked `[x] Complete`.
2. Cross-check with git history: `git log --oneline origin/main -- <paths the phase
   creates>` and merged pull requests (`gh pr list --state merged --search "<plan>"`) may
   show a phase is done that the tracker doesn't mark.
3. Cross-check with the code: if phase 1 says "create `src/asmbly_ceramics/domain/load.py`"
   and it exists with the types the phase names, phase 1 is probably done even if the
   tracker says otherwise.

**Every phase looks complete:** "All phases in `<plan>` appear complete. Did you mean a
different plan?"

---

## Step 4: Load context

Read these every time. You need them to judge the plan against the rules; don't skip
this step.

| Phase domain | Read |
| --- | --- |
| Always | `CLAUDE.md`, `docs/architecture.md`, `.implementation_plans/readme.md`, the phase document, the plan README |
| `app` | `src/asmbly_ceramics/` (the domain, use cases, ports, AWS adapters, in-memory fakes) and their tests |
| `web` | the pages, templates and their tests under `src/asmbly_ceramics/web/`, and the use cases they call |
| `infra` | `infra/`, the decision records in `docs/decisions/`, and the runbook in `docs/runbooks/` the phase is a step of |
| `ci` | `.github/workflows/`, `.github/rulesets/main.json`, `tests/repo/` |
| `docs` | `docs/README.md` and the documents named |
| `implements` is non-empty | the epic issue and each story (Step 7) |

Read the decision records the phase could touch every time, whatever its domain: their
**Chosen** sections are binding (Step 5i).

---

## Step 5: Ground-truth the phase

This is the core of prep. Don't trust the plan: verify every claim against the code and,
read only, the account.

### 5a. File paths and resources

For every path and resource in the phase document:

- **Files to create:** the parent directory exists, and the file does NOT (if it does,
  the plan may be stale).
- **Files to modify:** the file exists. Read it. The types, functions, ports, templates
  or resources the plan names are still in it.
- **To import from:** the module exists and defines what the plan expects.
- **Live resources it names**, once there are any: each exists with the name the plan
  says (`aws s3api head-bucket`, `aws cloudformation describe-stack-resources`,
  `aws ssm get-parameter --name <name>` for a non-secret value only, with
  `AWS_PROFILE=asmbly`, us-east-2). Never read a drop-off's details or photos, never read
  a secret's value, and never change anything.

```markdown
| Reference | Expected | Actual | Status |
| --- | --- | --- | --- |
| `src/asmbly_ceramics/domain/load.py` | Exists (modify `fire`) | Exists, `fire` line 88 | OK |
| `src/asmbly_ceramics/use_cases/schedule.py` | Doesn't exist (create) | Doesn't exist | OK |
| `src/asmbly_ceramics/ports/mailer.py` | Exists (import `OutgoingEmail`) | Renamed to `Message` | STALE |
```

### 5b. Dependencies

For each prerequisite the phase declares (`depends_on`, and the README's Dependencies):

- Is the earlier phase marked `[x] Complete`, and does the code confirm it? Look for the
  files, types, use cases, ports, templates and outputs it should have produced. A phase
  still `[~] In progress` whose code is on this branch and that waits only for its
  rollout check (an `/offshore` run, or an unmerged earlier phase) is satisfied for code;
  if this phase needs that rollout to have happened in AWS, it is BLOCKED until it has.
- Do the domain errors, limits, settings, port methods and environment variables this
  phase uses from earlier phases exist with those names?
- Is the work it needs in another repository done (`gh issue view <N> -R
  asmbly-makerspace/<repository>`: the sign-in client in asmbly-staff-login, the sending
  rights in AsmblyMCPs), and deployed where that matters?
- Are the by-hand steps it relies on listed under Admin actions, with when they must
  happen?

### 5c. Reference patterns

Find the closest existing example of what this phase builds, so `/build` can copy it.
Give two to four paths, each with one line on why it fits:

- **app:** a use case with similar ports and outcomes in `src/asmbly_ceramics/use_cases/`;
  a port and its fake in `ports/` and `adapters/memory/`; an AWS adapter with its stub
  tests in `adapters/aws/` and `tests/`.
- **web:** a page with the same reach (public, or the `ceramics` group) and the same
  shape (a form, a list, an action) in `web/`, with its template and tests.
- **infra / ci:** a resource or workflow step here, or in a sibling repository
  (AsmblyMCPs' and asmbly-staff-login's `infra/bootstrap.yaml` and
  `.github/workflows/deploy.yml`). Copy the pattern, not the names.

### 5d. Stale fake sweep

When a phase renames, moves or re-signatures a type, a use case, a port, a fake or a
template's logical ID, existing tests and fakes often still use the old one. The tests
keep passing against a fake that no longer matches the port, then the build fails, or
worse, the adapter does something the fake never did.

1. From Files to create and Files to modify, list every type, function, port method,
   module and logical ID the phase creates, moves, renames or re-signatures.
2. Grep for the old names:
   `grep -rn "<old name>" tests/ src/asmbly_ceramics/ infra/`, and for patches of the old
   path: `grep -rn "patch(.*<old_module>\|monkeypatch.setattr(.*<old_module>" tests/`.
3. For a port whose contract changes, check that its in-memory fake in
   `adapters/memory/` and the tests in `tests/adapters/` change with it in this phase.

Each stale hit is a finding:
`- **HIGH** [Stale fake] — `<test file>:<line>` uses `<old name>`, which phase <N> renames to `<new name>`. → **fix-before-build**: add the test to Files to modify`

If nothing moves or is renamed, write "N/A".

### 5e. Boundaries

- The domain and use cases the phase writes import no AWS library (`boto3`,
  `botocore`) and no web framework (Starlette, Jinja2).
- Every new port has an in-memory fake and an AWS adapter (in this phase or a named
  later one), and the use case tests use the fake.
- Every rule a story states is in the domain, once, not re-decided in a page or an
  adapter.
- Entry points (pages, the scheduled close, the mailer) only translate a request into a
  use case call and its result into a response.
- Nothing a story calls a setting (kilns, firing types, glaze types, rejection reasons,
  the pickup window and hours, the sending address) is a constant.

A breach is a HIGH finding.

### 5f. Personal data, photos and email

- No log line, error, test fixture, issue text or public page holds a name, email,
  phone, rejection message, photo or token. Logs carry `AC-12`, the load's ID and the
  staff username, and AWS error codes, never AWS's message.
- Photos stay private: no public bucket, object or address; staff see them only through
  the console, signed in.
- Personal details are deleted when a drop-off closes (#7), photos and thumbnails
  included, and nothing keeps a copy longer.
- Emails go only from the console's `asmbly.org` address, to the person who dropped off
  or the signed-in staff member for a test.
- Every console page and action checks the token and the `ceramics` group.
- Every field from the public form is checked on the server (type, length, format, the
  number of photos, each photo's real type and size, the rate limit) and escaped where
  it is shown or emailed.

A breach is a HIGH finding.

### 5g. Rights and names

For every AWS action the phase's adapters or deploy need, check that the role that will
run it is given that right in this phase or an earlier one, scoped by the
`asmbly-ceramics-` prefix or the `Project` tag (with `aws:RequestTag` on create and
`aws:ResourceTag` afterwards), and that nothing grants a right over another project's
resources (`mcp-*`, `staff-login-*`, the facilities automation). A missing right is a
HIGH finding (it fails at run time); an extra one is a HIGH finding too.

Every new resource starts with `asmbly-ceramics-` (from one parameter) and carries the
tags `CLAUDE.md` lists. A missing prefix or tag is a HIGH finding.

For every name that crosses a boundary (an output a workflow reads, an environment
variable an adapter reads, a Parameter Store name, a staff sign-in value), check that
both sides use the same name. A mismatch is a HIGH finding.

### 5h. Rollout and infrastructure as code

For a phase that reaches AWS: its `## Rollout` has what is done, a check with its
expected output, who confirms it, and an undo with its own check. Anything missing is a
HIGH finding.

Every resource, parameter and permission the phase needs comes from a template or the
deploy workflow. A by-hand step (a bootstrap stack, a GitHub environment, a DNS record
in a zone this repository doesn't own, a change in another repository) is listed under
Admin actions with the reason a template can't do it. A by-hand step without that reason
is a MED finding: replace it with a template or workflow step.

### 5i. Decision records

Read the index of `docs/decisions/` and, for each record whose status is `accepted` or
`proposed`, its **Chosen** sections. Compare them with the phase's files and
implementation details. A phase that goes against a chosen design (a second data store,
a public photo URL, a frontend framework, email outside the outbox) is a HIGH
`[Decision]` finding: the verdict is at best NEEDS REVISION until the user changes the
design or writes a new decision record that supersedes the old one. A choice the phase
must respect but doesn't break is one line in Plan Health.

### 5j. Size

Estimate the changed lines, counting tests:

- a domain module with its rules and tests: ~150-300 lines;
- a use case with its tests against the fakes: ~100-200;
- a port, its fake and the fake's contract tests: ~80-150;
- an AWS adapter with stub tests: ~150-250;
- a page with its template, field checks and tests: ~200-350;
- a template's resources and their `tests/repo/` pins: ~100-250.

| Estimate | Verdict |
| --- | --- |
| < 400 lines | OK |
| 400–800 | LARGE: say so, and watch the scope |
| > 800 | TOO LARGE: recommend a split, with the split points |

If the estimate falls outside the frontmatter's `estimated_size` (S under 150, M under
400, L under 800), add a LOW finding.

---

## Step 6: Specialists

Run these every time. You don't get to decide a specialist isn't needed: the point of
prep is that the mechanical and the adversarial checks run automatically, so the person
only sees decisions worth their time.

**How to spawn.** Each is a registered subagent: its agent file is its system prompt and
sets its model and tools. Pass only the inputs listed under **Provide**; don't paste the
agent file into the prompt or spawn a `general-purpose` agent in its place.

**Order matters.** The auditor reads the drift report so it doesn't repeat mechanical
findings. Wait for the drift detector to return before you spawn the auditor.

### 6a. Drift detector (always)

Spawn it with the Agent tool (`subagent_type: drift-detector`).

**Provide:**
- the full phase document;
- the plan directory (or "none (inline plan)");
- the repository root.

If the Agent tool isn't available to you (for example inside an `/offshore` sub-agent),
read `.claude/agents/prep/drift-detector.md`, apply it inline, and say in your report
that it ran inline.

It returns a drift report (Critical / High / Medium / Low). Critical and High items
usually mean the phase document needs revision before `/build`. Fold its findings into
Plan Health and Findings; don't repeat them in the auditor's section.

### 6b. Prep auditor (always, after drift)

Spawn it with the Agent tool (`subagent_type: prep-auditor`). Its job is not to rerun
your checks or the drift detector's. It asks the questions nobody thought to ask: hidden
assumptions, failure and undo, the people and their data, the public form, rework,
blast radius and ambiguity.

**Provide:**
- the plan name and the phase;
- the phase document;
- the README tracker (or "none (inline plan)");
- your Step 5 findings;
- the drift report from 6a;
- a short summary of what exists in the code versus what the plan assumes.

If the Agent tool isn't available to you, read `.claude/agents/prep/auditor.md`, apply
it inline, and say so in your report.

It returns a punch list of HIGH / MED / LOW findings, each with an action tag. Pass them
through as written.

---

## Step 7: Story alignment

Check that the stories the phase says it implements are covered by its deliverables.

### 7a. When it runs

The phase document has frontmatter when all three hold:

1. The first non-empty line is exactly `---` at column 0 (ignore a UTF-8 BOM; treat CRLF
   as LF).
2. A closing `---` appears within the first 30 lines.
3. The text between them parses as YAML (strict: duplicate keys are an error) into a
   non-empty mapping.

If any fails, the phase is in legacy mode (`.implementation_plans/readme.md` allows
it): skip this step silently, with no warning and no Story Alignment section.

### 7b. Validate the frontmatter

- **`implements` missing** → `Story Alignment: N/A — infrastructure phase (no implements key)`. Stop.
- **`implements: []`** → `Story Alignment: N/A — infrastructure phase (implements: [])`. Stop.
- **Not a list** (a scalar, a string, a mapping) → CLASS_A. Stop.
- **An element that isn't a positive integer** (`#2`, `"2"`, `AC-2`) → CLASS_A. Stop. A
  wrong-shaped number would fail its fetch as an operational error, get skipped, and
  produce a false ALIGNED on partial data; that is why the shape is checked first.
- **The phase has no `epic:`, or it differs from the README's `epic:`** → CLASS_A. Stop.
- **No plan README, or a README without `epic:` frontmatter** → CLASS_A: the phase lists
  stories but the plan isn't linked to an epic. Stop.

### 7c. Fetch each story

Loop over every number. Don't stop at the first error: the user should see every problem
in one run. For each:

```bash
gh issue view <n> --json number,title,state,labels,body
gh api repos/{owner}/{repo}/issues/<epic>/sub_issues --jq '.[].number'   # once per run
gh issue view <epic> --json body                                          # once per run
```

Record exactly one outcome per story:

| Outcome | When |
| --- | --- |
| **CLASS_A — not_found** | `gh` returns a clean "Could not resolve to an Issue" (a 404). |
| **CLASS_A — not_a_story** | The issue exists but isn't labeled `story`. |
| **CLASS_A — wrong_epic** | The story is neither a sub-issue of the phase's epic nor in the epic body's `## Stories` list. |
| **CLASS_B — closed** | The story exists and belongs, but is closed. Keep evaluating its criteria and add a warning. |
| **OPERATIONAL — unreachable** | A network error, timeout, auth failure, rate limit, or any error that isn't a clean 404, after 4 retries with waits of 2, 4, 8 and 16 seconds. |
| **OK** | The story exists, belongs, and is open. |

- Cache each outcome by number for this run. Never fetch the same story twice or retry
  beyond the rule above.
- An ambiguous error is OPERATIONAL, never CLASS_A: blocking by mistake is worse than
  skipping by mistake for an advisory check.
- **An unreachable GitHub is an environment problem, not an alignment problem. It never
  blocks and never downgrades the verdict.**

### 7d. Precedence

1. **Any CLASS_A** → `Story Alignment: BLOCKED`, and the prep verdict is BLOCKED. List
   every CLASS_A and OPERATIONAL story so the user can fix everything in one pass. Don't
   run the matching.
2. **Every story OPERATIONAL** → `Story Alignment: SKIPPED — GitHub unreachable`. No
   downgrade.
3. **Some OPERATIONAL, some OK or closed** → run the matching on the reachable stories
   and add the `PARTIAL-EVAL` note ("N of M stories unreachable"). Findings are advisory
   only: no downgrade on incomplete data.
4. **All OK or closed** → run the matching and apply the downgrade rule (7i).

If every reachable story has no parseable criteria, emit `Story Alignment: NOT EVALUATED
— no criteria found in any reachable story` (with the PARTIAL-EVAL note if some were
unreachable). Never emit ALIGNED on zero criteria. No downgrade; recommend
`/plan-product --review <plan>` to add criteria. Warnings still render.

### 7e. Parsing contracts

**A story's acceptance criteria** (the body format `/plan-product` writes):

1. Find the heading whose text is exactly `Acceptance criteria` (`## Acceptance
   criteria`; match it case-insensitively, without a trailing colon). Don't match `AC` or
   `**Acceptance criteria:**`.
2. Every top-level bullet (`- ` or `* ` at column 0) until the next heading is one
   criterion. Sub-bullets continue their parent. Strip task markers (`[ ] `, `[x] `,
   `[X] `).
3. No heading: the story has no parseable criteria.

**The phase's deliverables** (the phase document format in
`.implementation_plans/readme.md`): every top-level bullet, numbered item or table row
under these headings, in this order:

1. `## Files to create` and `## Files to modify` (each row or bullet is one deliverable);
2. `## Implementation details` (each top-level bullet or `###` subsection's first
   paragraph is one deliverable);
3. `## Tests` (each named test is one deliverable);
4. `## Acceptance criteria` (each item is one deliverable);
5. `## Rollout` (the step, when there is one).

A deliverable's "first sentence" runs to the first period that isn't inside backticks or
parentheses; with no period, it is the first line. None of these headings →
`Story Alignment: NOT EVALUATED — phase has no parseable deliverables`. No downgrade.

### 7f. Matching rubric

Decide coverage in two steps: classify the criterion, then apply that type's check.
Criteria here are usually plain statements ("After Submit the page shows an ID like
`AC-1`") or "Given … when … then …". The **outcome** is the then-clause, or the main
clause; the rest are the conditions.

**Step A: classify** (first match wins):

1. **Negative:** the outcome says `can't`, `cannot`, `must not`, `is refused`, `is
   denied`, `gets "access denied"`, `sees "not allowed"`, `is not sent`, `nothing is
   saved`, or `is never`.
2. **Data-shape:** the outcome's main verb is structural (`is`, `are`, `contains`,
   `includes`, `shows`, `has`, `carries`, `holds`) followed by a list of fields ("the
   email holds the ID, the firing type and the photos"). `is` plus a participle (`is
   stored`, `is sent`) is passive voice on an action: Functional.
3. **NFR:** names a non-functional category (time, size, retention, accessibility, a
   phone screen) and a measurable target (a number with units, "within 24 hours", "on a
   375-pixel-wide screen").
4. **Conditional:** a condition that changes the outcome: a bad or missing field, a
   photo too large or not a photo, a repeat, a wrong state (`AC-12` not waiting, a load
   already fired), someone outside the `ceramics` group, an email that fails, a setting
   changed. A condition that only sets up the actor ("Given I'm on the form") doesn't
   count. Without Given/When/Then: it starts with `If`, `When`, `After`, `Once`,
   `Unless`, and a comma introduces the result.
5. **Functional:** everything else.

A hybrid takes its first match. A criterion that is both Negative and Conditional runs
both checks and is covered if either passes; this is the only OR across types.

**Step B: verb signal** (one input to Step C, not a gate):

The primary verb is the prohibited verb for Negative, the structural verb for
Data-shape (match it with the `include` synonyms), none for NFR, and the main verb of the
outcome for Conditional and Functional (without Given/When/Then, the last finite verb of
the main clause: "Staff can **reject** a drop-off"; `can` is an auxiliary). If the
outcome joins verbs with `and`/`or`, check each; the criterion is covered if any verb
is, and each uncovered verb is a sub-finding.

A deliverable's first sentence **names the verb** when it contains:

1. a token with the same stem as the verb (case-insensitive), or
2. a derivational form:

   | Verb | Forms |
   | --- | --- |
   | reject | rejection |
   | submit | submission |
   | close | closing, closure |
   | delete | deletion |
   | notify | notification |
   | validate | validation |
   | log | logging, logged, log line |
   | fire | firing, fired |
   | retire | retirement |
   | upload | upload (as a noun) |

3. or a synonym:

   | Verb | Synonyms |
   | --- | --- |
   | drop off | submit, send the form |
   | list | show, display, render, appear |
   | add | put in, assign, scan into |
   | remove | take out, drop from |
   | reject | refuse, needs attention |
   | undo | reverse, restore, put back |
   | email | send, notify, mail |
   | delete | remove, purge, erase, close |
   | retire | hide, deactivate |
   | change | edit, update, set |
   | refuse | reject, deny, decline, block |
   | include | contain, hold, carry, show |
   | check | validate, verify, refuse |
   | count | total, tally, report |

Otherwise the signal is **absent**. When an obvious deliverable reads as uncovered, the
fix is usually a new synonym row, not a weaker rule.

**Step C: coverage by type**

| Type | Covered when |
| --- | --- |
| Functional | A deliverable names the same outcome a person notices and has the verb signal. Without the signal, two or more shared **salient nouns** still cover it, with a `WEAK MATCH` warning. Salient nouns exclude stopwords and implementation nouns (`module`, `class`, `function`, `port`, `adapter`, `fake`, `handler`, `template`, `table`, `item`, `resource`, `stack`, `test`). |
| NFR | A deliverable names the same category and a compatible target ("closing deletes the photos the next night" covers "photos are deleted within 2 days of closing"; "photos are cleaned up" doesn't). |
| Conditional | A deliverable names the condition (or its inverse) and a deliverable names the outcome, with the verb signal on the outcome. One deliverable can do both. |
| Negative | A deliverable names a refusal **and** the specific thing refused: a page, an action, a field or an object ("the console's waiting list answers 'not allowed' to a signed-in person outside `ceramics`", "a photo over 10 MB is refused next to the photo field"). Generic nouns ("access", "the page", "it") don't count. |
| Data-shape | A deliverable names the structure (the email, the page, the record) and every field the criterion puts in backticks. Unquoted field names are informal and not required. |

Stopwords: a, an, the, is, are, be, been, was, were, of, for, with, in, on, at, to, from,
and, or, but, by, that, which, this, these, those, it, its.

The rubric is meant to be repeatable: two careful runs on the same input reach the same
result. Use standard stemming and part-of-speech judgment; don't invent stem rules.

**Step D: single-domain override.** When `domain` is exactly `[app]`, a Functional
criterion is covered by a deliverable that describes the use case or domain rule behind
the outcome and has the verb signal ("`reject` moves a waiting drop-off to rejected and
queues the rejection email" covers "Staff can reject a waiting drop-off and the person
gets an email" in an app-only phase). Other types and other domains: no override.

### 7g. Implicit infrastructure, siblings and contribution

**Implicit infrastructure.** A deliverable that fails the rubric is exempt from the
unjustified count only if both hold:

1. it sits under `## Files to create` or `## Files to modify` for a port, a fake, an
   adapter, a template, a workflow or a test helper, or its first sentence starts with
   `Port:`, `Fake:`, `Adapter:`, `Infra:`, `Template:`, `IAM:`, `Workflow:`, `Test:`
   (case-insensitive);
2. its first sentence contains a noun that also appears in some criterion of the phase's
   stories (same stem; plurals and possessives collapse).

The test is mechanical: no judgment about whether a criterion "needs" the deliverable.

**Sibling coverage.** For a criterion this phase doesn't cover:

1. List the phase documents directly in the plan folder (not recursively).
2. If any sibling has no valid frontmatter, mark the criterion **coverage unknown
   (sibling without frontmatter)** and don't count it as uncovered.
3. If a sibling's `implements` lists the same story and one of its deliverables covers
   the criterion by the rubric, or the README's Stories row for that story names the
   sibling, mark it **covered (phase <N>)**.
4. Otherwise it is **uncovered**.

Read siblings' static `implements` and deliverables; never fetch stories again for them.
`depends_on` plays no part in coverage.

**Contribution rule.** For each story in `implements`, this phase should cover at least
one of its criteria itself (implicit infrastructure naming the story's nouns counts). If
siblings cover all of a story's criteria and this phase contributes nothing, record
**CONTRIB_GAP** for that story with this recommendation, and don't conclude on your own
that the story should be removed:

> Verify this phase contributes to #<N>. If the work lives entirely in phase <M>, remove
> <N> from this phase's `implements:` and its README Stories row. If this phase does
> contribute, rewrite a deliverable so it names the criterion directly.

**Unjustified deliverables.** A deliverable that maps to no criterion of any listed story
and isn't implicit infrastructure may be over-scope.

### 7h. Roll up to one state

Count across OK and closed stories (OPERATIONAL stories count zero):

- `U`: uncovered criteria (sibling-covered and coverage-unknown ones don't count)
- `J`: unjustified deliverables
- `G`: stories with CONTRIB_GAP
- `Z`: 1 if any story has none of its criteria covered by this phase or its siblings,
  else 0

Evaluate top to bottom; the first match is the state:

| Condition | State |
| --- | --- |
| `U ≥ 3` or `Z = 1` or (`G ≥ 1` and `U ≥ 1`) | `MISALIGNED` |
| `U = 2` or `J ≥ 1` or (`G ≥ 1` and `U = 0`) | `PARTIAL` |
| `U = 1` and `J = 0` and `G = 0` | `PARTIAL-MINOR` |
| `U = 0` and `J = 0` and `G = 0` | `ALIGNED` |

**Warnings** (a closed story, coverage unknown, a story with no criteria among stories
that have some, `WEAK MATCH`) render as bullets under the state line. They never change
the state: every criterion covered with two closed-story warnings is `ALIGNED (with
warnings)`.

Render the **recommended actions** block (add a deliverable, move the criterion to a
sibling phase, or edit the story's criterion) whenever at least one criterion is
uncovered, PARTIAL-MINOR included.

### 7i. Classes and the downgrade rule

- **CLASS_A (blocking): the data is wrong.** A story not found, not labeled `story`, or
  in another epic; `implements` not a list or with a malformed element; a phase `epic:`
  that disagrees with the README; a README without `epic:`. The verdict is BLOCKED.
  Every CLASS_A finding names the phase document's path; the fix is to edit
  `implements:` (or the README) by hand and run `/prep` again.
- **OPERATIONAL (never blocking):** GitHub couldn't be reached. Report SKIPPED or
  PARTIAL-EVAL and tell the user to run `/prep` again once access is back; results can
  differ between runs.
- **CLASS_B (advisory): coverage.** The state from 7h:

| State | Effect on the verdict |
| --- | --- |
| ALIGNED | none |
| PARTIAL-MINOR | none (informational) |
| PARTIAL | READY TO IMPLEMENT becomes NEEDS REVISION |
| MISALIGNED | READY TO IMPLEMENT becomes NEEDS REVISION |
| NOT EVALUATED, N/A, SKIPPED | none |

Class B never produces BLOCKED and never upgrades a verdict.

---

## Step 8: Report

Combine your findings, the drift report and the audit into one report. **Be terse.** The
user will ask for depth on anything that looks important; your job is the punch list,
not the deep dive.

### Verdict

| Verdict | When |
| --- | --- |
| **BLOCKED** | A prerequisite phase or another repository's work isn't done, a phase file is missing, a Class A error, or a drift Critical that makes the phase impossible as written |
| **NEEDS REVISION** | Any HIGH finding marked `fix-before-build`; a boundary or privacy breach; a missing or extra right; a missing prefix or tag; a name mismatch; an incomplete rollout; a stale fake; a decision-record breach; a TOO LARGE estimate; or Story Alignment PARTIAL or MISALIGNED |
| **READY TO IMPLEMENT** | None of the above |

### Brevity rules (not negotiable)

- **Skip clean sections.** A clean ground-truth is one line:
  `**Ground-truth:** clean (paths, boundaries, rights and dependencies verified).` Don't
  print a table of things that passed.
- **Skip empty sections.** No reference patterns worth naming: omit the section. Never
  print `[None]`.
- **Don't restate drift findings.** Plan Health gets a one-line summary and a count; the
  findings list gets one line each.
- **Pass auditor findings through as-is.** They are already in punch-list form. Don't
  reformat them into prose or add commentary.
- **No header without content.** A section of one line or less folds into the one above.
- **No personal details.** The report names drop-offs by ID and staff by username.

### Template

```markdown
## Prep report: <plan> — phase <N>

**Phase:** <N> — <title> · **Domain:** <app/web/infra/ci/docs> · **Branch:** <current>
**Plan progress:** <X of Y complete> · **Estimated size:** ~<N> lines (<OK | LARGE | TOO LARGE>)
**Reaches AWS:** yes / no

### Plan health
<One paragraph at most. Drift: clean, or "N items: <one-line summary>". Decisions:
respected, or the breach. Tracker/file mismatches from Step 2. Anything run inline.>

### Reference patterns
- `<path>` — <why>

### Findings
**Findings:** <H> HIGH, <M> MED, <L> LOW
- **HIGH** [Category] — <finding>. → **<action>**: <remediation>
- **MED** ...
- **LOW** ...

### Story alignment
<One state line, warnings beneath it, and the recommended actions block if any criterion
is uncovered. For CLASS_A: BLOCKED with each error and the phase document's path. Omit
when Step 7 was skipped.>

---

### Context loaded
- [x] CLAUDE.md · [x] docs/architecture.md · [x] .implementation_plans/readme.md · [x] <others>

### Verdict: READY TO IMPLEMENT | NEEDS REVISION | BLOCKED
<One line on why, one line on the next action.>
```

Drift findings use the category `[Drift]`, decision findings `[Decision]`, and your own
Step 5 findings the same one-line shape as the auditor's (`[Path]`, `[Dependency]`,
`[Stale fake]`, `[Boundary]`, `[Privacy]`, `[Rights]`, `[Names]`, `[Rollout]`, `[Size]`).
Don't add findings the agents and your checks didn't produce.

**What good looks like:** a clean phase with two LOW findings is about 15 lines; a phase
with 5 HIGH and 8 MED findings is about 30. If the report passes 60 lines with fewer than
ten MED-or-higher findings, you are over-explaining. Trim.

### Story alignment examples

```
READY TO IMPLEMENT
  Story Alignment: ALIGNED

READY TO IMPLEMENT
  Story Alignment: PARTIAL-MINOR — 1 criterion not covered (#2):
    - "The form works with the phone's camera and photo library"  ← below the downgrade threshold
  Recommended actions:
    - Add a deliverable that names this outcome, OR
    - Move it to a sibling phase and update `implements:`, OR
    - Edit the story's criterion if it was descoped on purpose

READY TO IMPLEMENT
  Story Alignment: ALIGNED (with warnings)
    - #3 is closed; remove it from `implements:` if it already shipped

NEEDS REVISION (downgraded by coverage)
  Story Alignment: PARTIAL — 2 criteria not covered (#5):
    - "Marking a load fired twice sends nothing the second time"  ← no deliverable names the repeat
    - "A failed email shows in the console by the drop-off's ID"  ← no deliverable for the failure
  Recommended actions:
    - Add a deliverable that names the missing outcome (preferred), OR
    - Move the criterion to a sibling phase and update `implements:`, OR
    - Edit the story's criterion if it was descoped on purpose

NEEDS REVISION (downgraded by CONTRIB_GAP)
  Story Alignment: PARTIAL — phase 6 covers all of #2's criteria; this phase covers none:
    - CONTRIB_GAP for #2
  Recommended actions:
    - Verify this phase contributes to #2
    - If the work lives entirely in phase 6, remove 2 from this phase's `implements:`
    - If this phase does contribute, rewrite a deliverable to name the criterion directly

BLOCKED
  Story Alignment: BLOCKED
    - CLASS_A: #12 does not exist. Remove or replace it in `implements:`.
    - CLASS_A: #10 is not labeled `story`.
    - OPERATIONAL: #4 unreachable (network). Run /prep again once access is back.
  Phase doc: .implementation_plans/drop-off-and-firing/phase-6-drop-off-form.md
  Matching was skipped; it runs on the next /prep after the fix.

READY TO IMPLEMENT
  Story Alignment: SKIPPED — GitHub unreachable
  Run /prep again once GitHub is reachable; results can differ between runs.

READY TO IMPLEMENT
  Story Alignment: PARTIAL-EVAL — 1 of 3 stories unreachable. Reachable stories: ALIGNED.
  Run again after access is restored for a complete check.
```

---

## Step 9: Next steps

- **READY TO IMPLEMENT:** tell the user to run `/build` on this phase, which uses this
  report's reference patterns and findings, sets the tracker row to `[~] In progress` in
  its first commit, and ends with an independently reviewed branch for `/ship`. Change
  nothing yourself.
- **NEEDS REVISION:** list the specific edits the phase document (or README) needs
  before building, and offer to make them. Make them only when the user accepts, then
  run the checks in Step 5 again on what you changed.
- **BLOCKED:** say what blocks it and how to unblock it (finish a prior phase, merge the
  work in asmbly-staff-login or AsmblyMCPs, fix `implements:`, update stale references).

---

## Errors

- **Plan folder not found:** list the active plans and ask.
- **No active plans:** "No active implementation plans in `.implementation_plans/`. All
  plans are in `DONE/`."
- **Phase file missing:** "Phase <N> is in the README but `<expected path>` doesn't
  exist." BLOCKED.
- **Ambiguous plan match:** list the matches and ask.
- **Wrong branch:** note the mismatch but don't block; the user may be about to create
  the right branch.
- **A transient tool failure** (`gh` or AWS timing out, a 5xx): retry at least 4 times
  with waits of 2, 4, 8 and 16 seconds before you report it. It is never a reason to stop
  short.

---

## Rules

- **Read the files, not summaries.** The README drifts, phase documents drift; the code
  and the account are the truth.
- **The drift detector and the auditor always run.** Give the auditor your findings and
  the drift report; don't hand it your checklist to redo.
- **Don't implement.** Prep prepares; `/build` builds.
- **Load the context every time.** `CLAUDE.md`, `docs/architecture.md` and the domain's
  files, every run.
- **Ground-truthing is the value.** A plan checked only against itself looks fine. Check
  every path, every dependency, every right and every name against the code.
- **Read-only AWS only.** Never read a drop-off's personal details or photos, or a
  secret's value, and never change anything.
- **Public by default.** Nothing in the report, or in any edit you make, holds a
  person's details, an account ID, a secret or an internal address.
