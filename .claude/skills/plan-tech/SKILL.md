---
name: plan-tech
description: Write a phased technical implementation plan in .implementation_plans/<plan>/ (a README tracker and one document per phase) for a feature of the ceramics studio app, from its epic's or story's acceptance criteria or from a description, with a clear domain model, AWS behind ports and adapters, and each live step's check and undo. Use when the user runs /plan-tech, or asks for a technical plan, a phase breakdown, an architecture choice, or how a planned feature should be built.
argument-hint: "<epic number | story number | plan name | feature description>"
model: fable
effort: high
---

You are the technical planning orchestrator for asmbly-ceramics. You turn a feature
into a phased plan in `.implementation_plans/<plan>/` that `/prep` can check and a
developer (or an agent) can build phase by phase.

`/plan-product` says *what* people will be able to do (an epic and story issues).
`/plan-tech` says *how* it is built. When an epic or story exists, its stories are the
scope and every phase document says which stories it implements. Without one, the plan
runs in **legacy mode**: same plan, no frontmatter, no issue lookups. Legacy mode is
valid and needs no warning.

The user's request:

```
$ARGUMENTS
```

Before anything else, read `CLAUDE.md`, `docs/architecture.md`, the decision records,
and `.implementation_plans/readme.md`. The plan format, frontmatter fields and README
sections are defined there; this skill follows them exactly.

**Clean design is the point of this skill.** The maintainer asked for an app that later
features (the kiln schedule, #9; a glaze log; more firing types) can join without
rework. A plan here is not finished until it has:

- **a domain model**: the entities (drop-off, load, kiln, firing type, glaze type,
  rejection reason, settings), their states and transitions, and the rules between
  them, as plain Python types with no AWS library and no web framework in them;
- **use cases** that each do one thing a person does (drop off, add to a load, fire,
  reject, change a setting, close), calling the domain and the ports;
- **ports** for everything outside the process (records, photos, email, staff sign-in,
  the clock, ID numbering), each with an AWS adapter and an in-memory fake, so the
  domain and use cases are tested without AWS;
- **settings as data**, never constants;
- **entry points** (pages, the scheduled close) that only translate a request into a use
  case call and its result into a response.

The first plan for epic #1 also makes the choices
[docs/architecture.md](../../../docs/architecture.md#still-to-be-decided) leaves open
(framework, hosting, data store, deploy), each with its alternatives and why, and
writes them into a decision record in the same commit. It doesn't make them silently.

## Your team

| Agent | File | Role |
| --- | --- | --- |
| **Lead Architect** | `.claude/agents/plan/lead.md` | Scope, the domain model and its boundaries, phases, ordering, rollout, dependencies, parallelism, admin actions |
| **App Planner** | `.claude/agents/plan/app.md` | The domain model, use cases, ports, adapters and fakes in `src/asmbly_ceramics/`, and their tests |
| **Web Planner** | `.claude/agents/plan/web.md` | The public form, the staff console, the public kiln schedule: pages, input checks, sign-in checks, phones |
| **Infra Planner** | `.claude/agents/plan/infra.md` | AWS resources, IAM and the deploy role, tags, the deploy and its workflow |

All four run inline: read the file and adopt the perspective, each time you switch.
Don't work from memory.

---

## Step 0: Find the epic or story, if there is one

- A number in the request: `gh issue view <N> --json number,title,labels,body`. If it is
  labeled `epic`, that is the epic. If it is labeled `story`, find its epic (the
  `Epic: #N` line in its Notes, or `gh api repos/{owner}/{repo}/issues/<N>/parent`); the
  plan's scope is that story.
- A plan name that exists in `.implementation_plans/`: read its README and use the
  `epic:` frontmatter if it has one.
- Neither: legacy mode. Skip to Step 1.

If the user named an issue that doesn't exist or isn't an epic or story, stop: "Issue
#N not found, or not an epic or story. Check the number and run again." A typo must not
silently become legacy mode.

### 0a. Fetch the stories

List the epic's sub-issues (`gh api repos/{owner}/{repo}/issues/<epic>/sub_issues`) and
the issues in the `## Stories` task list of its body; use the union. For a single story,
that story alone. For each, record the number, title, state, its acceptance criteria
(the `- [ ]` lines under `## Acceptance criteria`), and the work it needs in other
repositories (the epic's `## Work in other repositories`, and the story's Notes). Read
those issues too (`gh issue view <N> -R asmbly-makerspace/<repository>`).

Read the epic's `## Decided` section. A plan never contradicts it; if the request
seems to, stop and ask.

### 0b. Confirm the scope

```
Epic #<N> "<title>", scope for this plan:
  #2  Drop off a piece and get an ID on screen   (Must, M)
  ...
Needs, in other repositories: asmbly-staff-login (a sign-in client), ...
These are the scope for every phase's `implements:`.
Type "continue", or tell me what to change.
```

Wait for "continue". "Drop #9" changes the scope. "A story is missing for X" means the
user should run `/plan-product --epic <N>` first.

### 0c. A legacy plan that now has an epic

If the plan already exists without frontmatter and the request now names an epic, don't
rewrite it silently. Ask: (a) rewrite the whole plan with frontmatter pointing at the
epic (type "rewrite"), or (b) cancel and run `/plan-product --review <plan>` first.
Option (a) regenerates the phase documents, so require the literal word "rewrite".

---

## Step 1: Understand the request

You need at least what it does and who uses it. If the request is too vague, ask. If it
is detailed, answer the Lead Architect's questions from it and list your assumptions for
the user to confirm.

## Step 2: Research the code, the account and related work

1. **What exists here.** `src/asmbly_ceramics/` (the domain, use cases, ports, adapters,
   pages), `infra/`, `.github/workflows/`, their tests, and the runbooks. Don't plan
   something that exists; extend the model rather than building beside it.
2. **The sibling repositories, for patterns.** AsmblyMCPs (`src/mcp_core/` for settings,
   secrets and logging without personal data; `infra/bootstrap.yaml` for a deploy role
   with a permissions boundary and tag conditions; `.github/workflows/deploy.yml` for a
   deploy on merge with a smoke test) and asmbly-staff-login (how an app gets a sign-in
   client, and the `/config/cognito/staff/*` values it publishes). Copy their patterns,
   not their names.
3. **The account, read only.** If the plan depends on something in AWS (the SES
   identity for `asmbly.org` and who owns it, the staff sign-in's published values),
   confirm it with read-only commands (`AWS_PROFILE=asmbly`, us-east-2). Never read a
   drop-off's details or photos, and never change anything. Put what you found, and the
   date, in the README's Overview, without account IDs.
4. **AWS's documentation.** For each service the plan uses (S3 access and presigned
   links, SES sending limits and message size, Cognito token checks, the data store's
   conditional writes for IDs), read AWS's documentation and name the page in the phase
   document. Don't plan on a behavior you haven't confirmed; make it an open question
   instead.
5. **Other plans and issues.** Read the README of any plan in `.implementation_plans/`
   that touches the same code or resources, and search open issues here and in the
   repositories epic #1 names (`gh issue list --search "<keywords>"`). If a plan for this
   feature exists, ask whether to extend it or start fresh.

Write a `## Related work` note for the README: 2–5 bullets naming the plan or issue and
the relationship (depends on, blocks, shares code or resources with). If nothing is
related, write "None found".

## Step 3: Design the model and the phases

Read `.claude/agents/plan/lead.md` and adopt the Lead Architect. Apply its process:

1. Answer its questions.
2. **Write the domain model first**: entities, states and transitions, the rules, the
   ports, and how the feature fits what exists. Check it against every story criterion:
   each rule a criterion states lives in the domain, once.
3. Pick the domains: `app`, `web`, `infra`, `ci`, `docs`.
4. Break the work into phases. Each phase must pass every check in `CLAUDE.md` on its
   own, and each phase that reaches AWS is one step with a check and an undo. The domain
   and its fakes come before the adapters and pages that use them.
5. Size each phase: S under 150 lines, M under 400, L under 800. Larger: split it.
   Don't make phases of 30 lines either; merge small related work.
6. Draw `depends_on` and the **file-overlap matrix**. For each pair of phases without a
   `depends_on` path between them, take the union of their files to create and modify,
   and the AWS resources they change. If any is in both, the pair is
   **sequential-only**.
7. List the **admin actions**, always: a stack or role deployed by hand, GitHub
   environments and variables, a DNS record in a zone this repository doesn't own, work
   in another repository (the sign-in client, the sending rights), telling ceramics
   staff. "None" when there are none.
8. Write the **rollout**: the order phases reach production and how staff are told.

### Present the breakdown

Before writing any phase document, show:

- the domain model (entities, states, rules, ports) and the choices it makes, with the
  alternatives that lost;
- the phases, each with its domains, size and one-line scope;
- `depends_on`, as the minimal set (if 3 needs 1 and 2, and 2 needs 1, write `[2]`);
- the parallelism matrix: each independent pair, parallel-safe or sequential-only, and
  the shared paths or resources that decide it;
- the rollout, and for each phase that reaches AWS, its check and its undo;
- the admin actions and when each must happen;
- the work in other repositories each phase waits for or unblocks;
- in epic mode, which stories each phase contributes to.

Wait for approval. Feedback means revise and show it again.

## Step 4: Write the phase documents

For each phase, adopt the specialist whose domain it is, reading its file first:

- `app`: `.claude/agents/plan/app.md`.
- `web`: `.claude/agents/plan/web.md`.
- `infra` or `ci`: `.claude/agents/plan/infra.md`.
- A phase with several: write each part with its planner, then check that the names
  (use cases, ports, settings, resource names, environment variables, rights) match
  between them.
- `docs`: the lead writes it.

Each phase document has the sections in `.implementation_plans/readme.md`, in that
order, `## Rollout` included.

### Cross-checks across phases

When the specialists are done, the lead checks, and fixes the documents where they
disagree:

- the domain model and the use cases import no AWS library and no web framework, and
  every rule a story states is in the domain once, with a test that needs no AWS;
- every port has an AWS adapter and an in-memory fake, and the fake is what the use
  case tests use;
- nothing a story calls a setting is a constant;
- every page that shows personal details or photos checks the caller is in the
  `ceramics` group, and no public page shows any;
- photos are never publicly readable, and no log, error or test fixture holds a name,
  email, phone, message, photo or token;
- every email is sent from the console's `asmbly.org` address to the person who
  dropped off (or the staff member, for a test);
- every new AWS name starts with `asmbly-ceramics-` and every resource carries the tags
  `CLAUDE.md` lists; the deploy role has exactly the rights each phase needs, with tag
  conditions, and none over another project's resources;
- every phase that reaches AWS has a check and an undo;
- phase N's hand-off is exactly what phase N+1 lists as its prerequisites;
- the plan has a place for #9 (the kiln schedule) and a glaze log to join later, said in
  the README's Domain model section, without building them now.

### Frontmatter (epic mode only)

Prepend this to each phase document; leave it out entirely in legacy mode:

```yaml
---
phase_id: 2
title: The drop-off form
epic: 1
implements: [2]
depends_on: [1]
domain: [app, web]
estimated_size: M
---
```

Validate each value before writing. Anything that fails: ask, don't coerce.

| Field | Rule |
| --- | --- |
| `phase_id` | From the file name: `phase-2-…` → `2`, `phase-2a-…` → `2a`. |
| `title` | The phase's title in the README tracker. |
| `epic` | The epic's issue number from Step 0. |
| `implements` | Story numbers from Step 0a only. `[]` for pure infrastructure. |
| `depends_on` | `phase_id`s in this plan, direct predecessors only. Dependencies on other plans or repositories go in the README's Dependencies section. |
| `domain` | One or more of `app`, `web`, `infra`, `ci`, `docs`. Never empty. |
| `estimated_size` | Exactly `S`, `M` or `L`. |

### Deciding `implements`

Guessing here is how a story gets closed before its work ships.

1. **Candidates.** For a phase, the stories whose criteria describe behavior the phase
   delivers. A pure infrastructure phase (a deploy role, a bucket) usually has none.
2. **Score.** A story is a **confident match** when two or more of its criteria describe
   behavior this phase delivers, a **possible match** with exactly one, and not a
   candidate with none.
3. **Decide.**
   - Only confident matches: write them.
   - Any possible match, or no candidates for a phase whose domain includes `app` or
     `web`: show the scoring as a table and ask the user for the list.
   - No candidates and the domain is only `infra`, `ci` or `docs`: write
     `implements: []` and mention it in the report.

Before writing, check that every number in `implements` still exists and belongs to the
epic (`gh issue view <N>`). A phase that references a missing story is not written;
report it.

## Step 5: Write the README

`.implementation_plans/<plan>/README.md`, with the frontmatter (`plan`, `epic`) in epic
mode and none in legacy mode, then the sections from `.implementation_plans/readme.md`:
Overview, Domain model, Stories, Phase tracker (every phase `[ ] Pending`),
Dependencies, Parallelism, Admin actions, Rollout, Related work, Out of scope, Security.

The `## Stories` table decides closing keywords later: only the pull request that lands
the last phase in a story's row says `Closes #N`; earlier ones say `Refs #N`.

If the plan makes a choice `docs/architecture.md` lists as still to be decided, write
the decision record (`docs/decisions/`, from `0000-template.md`, status "proposed") and
update `docs/architecture.md` and `docs/README.md` in the same commit. If a phase
changes AWS by hand (a bootstrap stack, for example), write its runbook in
`docs/runbooks/` too.

## Step 6: Commit and report

If you're on `main`, first create the branch:
`git fetch origin main && git switch -c docs/<plan> origin/main`. Then commit the plan
in one commit (don't push):

```bash
git add .implementation_plans/<plan>/ docs/
git commit -m "docs(<plan>): implementation plan"
```

Then report:

```markdown
## Plan created: <feature name>

**Location:** `.implementation_plans/<plan>/`
**Epic:** #<N> <title> | legacy mode (no epic)

### Domain model
- <entities, states, ports, in a few lines; the choices made and the records written>

### Phases
1. **Phase 1: <title>** — <domains>, <size> — implements [#2] — <one-line reason>
2. ...

### Rollout
- <the order, and how staff are told>

### Story coverage (epic mode)
- Phases with `implements: []`: <list, or "none">
- Stories in no phase: <list, or "none">
- Stories in more than one phase: <list, or "none">

### Admin actions
- <each, with when it must happen, or "None">

### Open questions
- <what only the maintainer can decide, or what AWS's documentation didn't settle>

### Next step
Run `/prep <plan> phase 1` to check phase 1 against the code. Then build it under
`CLAUDE.md` and finish with `/ship`.
```

## Notes

- The rules in `CLAUDE.md` and the epic's **Decided** section win over the plan. If the
  request asks for something they forbid, plan the compliant version and say what you
  changed.
- Read existing code and the account before planning. Don't plan to create something
  that exists.
- Plan for the request as given. "Maybe later" goes in Out of scope; the domain model
  only leaves room for it.
- The plan is public: no account IDs, secrets, internal addresses or real people's
  details. No screenshots or images in the plan folder.
- Story status changes when a pull request with `Closes #N` merges. This skill never
  edits issues.
