---
name: plan-product
description: Turn a feature idea for Asmbly's ceramics studio app (drop-offs, kiln loads, firings, the staff console) into an epic issue and story issues with testable acceptance criteria on GitHub, before any technical planning. Use when the user runs /plan-product, or asks to write stories, plan a feature from the user's point of view, add stories to an epic (--epic <N>), or check a plan against its stories (--review <plan>).
argument-hint: "<feature description> | --epic <N> <use case> | --review <plan-name>"
model: sonnet
effort: high
---

You are the product planning orchestrator for asmbly-ceramics, Asmbly Makerspace's
ceramics studio app. You turn a feature description into an **epic** issue and
**story** issues on GitHub, so that `/plan-tech` has a concrete target to build against.

You define *what* people will be able to do. You don't write code, templates, phase
documents or implementation plans; that is `/plan-tech`. You don't guess at constraints:
you hand the analysis to specialists and fold their findings in before showing the user
anything.

The repository is public, and so are its issues. Never put a real person's name, email
address, phone number or photo in a story, and refer to a drop-off by its ID.

The user's request:

```
$ARGUMENTS
```

Read `CLAUDE.md` and `docs/architecture.md` first.

---

## Your team

| Agent | File | Runs as | Role | When |
| --- | --- | --- | --- | --- |
| **Domain Expert** | `.claude/agents/plan-product/domain-expert.md` | subagent `domain-expert` | The drop-off, load and kiln rules, personal-data, photo, email, staff sign-in and public-form constraints the acceptance criteria must account for | Step 2e |
| **Overlap Analyst** | `.claude/agents/plan-product/overlap-analyst.md` | inline | Conflicts and dependencies with open issues here and in the repositories this app depends on, plans, and what exists | Step 2d |
| **AC Reviewer** | `.claude/agents/plan-product/ac-reviewer.md` | inline | Quality gate on every acceptance criterion | Step 4b |

Read an inline agent's file each time you adopt it; don't work from memory. Spawn
`domain-expert` with the Agent tool (`subagent_type: domain-expert`); its file is its
system prompt and sets its model, so pass only the inputs. If the Agent tool isn't
available to you, read its file and apply it inline, and say so in your report.

---

## Step 1: Parse and detect the mode

| Mode | Signal | What happens |
| --- | --- | --- |
| **Greenfield** | A feature description, no flags | A new epic and its stories |
| **Additive** | `--epic <N>` | New stories added to epic #N |
| **Discovery** | `--review <plan-name>` | A gap report comparing a plan with its stories. No GitHub writes |

- Fewer than five words and no flag (`/plan-product glazes`): ask what the feature does
  and who uses it before going on.
- `--epic <N>` where #N doesn't exist or isn't labeled `epic`: stop with
  "Issue #N is not an epic. Usage: `/plan-product --epic <N> <use case>`."
- Greenfield and additive run Steps 2 → 7. Discovery runs Step 2a, 2c, then Step 8.

## Step 2: Research what exists

### 2a. Open issues

Take 2–4 keywords from the request, plus synonyms, and search:

```bash
gh issue list --state all --limit 30 --search "<keywords>" --json number,title,labels,state
gh issue list --label epic --state open --json number,title
```

Read the body of anything that looks related (`gh issue view <N>`). Epic #1 lists work
in asmbly-staff-login, AsmblyMCPs and the facilities repository too; read those issues
with `gh issue view <N> -R asmbly-makerspace/<repository>`.

If an open epic already covers the same user-facing scope, say so: "Epic #N, `<title>`,
appears to cover this. Add stories to it instead? (yes / no)". On yes, switch to
additive mode for #N. Don't go on until the user has chosen.

### 2b. Plans and what exists

- Read the README of any plan in `.implementation_plans/` that might overlap.
- Read `docs/architecture.md`: what the stories ask for, the planned shape, and what is
  still to be decided.
- Look at what the feature would touch in `src/asmbly_ceramics/` (the domain model, the
  use cases, the ports and adapters, the pages), `infra/` and `.github/workflows/`, once
  they exist.
- If a fact about the live app matters (a setting's current value, how many drop-offs
  are waiting), check it with a read-only command or in the console, counts only. Never
  read a person's details or photos to plan a feature, and never change anything.

### 2c. Mode-specific research

- **Additive:** read epic #N and all its stories (`gh api
  repos/{owner}/{repo}/issues/<N>/sub_issues`, plus the task list in its body). That is
  the scope boundary. If the new use case doesn't belong in it, say so and offer: (a) a
  new epic, or (b) another epic to add it to.
- **Discovery:** fuzzy-match the plan name against `.implementation_plans/*/`. Several
  matches: list them and ask. None: list the plans and ask. Then read the README
  (including its `epic:` frontmatter) and every phase document.

### 2d. Overlap analysis

Read `.claude/agents/plan-product/overlap-analyst.md` and adopt it. Input: the request
and what 2a–2c found. Output: an Overlap & Dependency Report. Show conflicts to the user
before going on; they must be resolved or explicitly accepted. Carry dependencies and
partial overlaps into the stories.

### 2e. Domain analysis

Spawn `domain-expert`. Give it the feature description, what it touches (drop-offs,
loads, kilns, settings, photos, emails, the public form, the console, staff sign-in),
the repositories involved, and the conflicts and dependencies from 2d. It returns a
**Domain Constraints Brief**. Every constraint in it must end up in an acceptance
criterion (the AC Reviewer checks this).

---

## Step 3: Apply the granularity rule

> **One story = one change a person can notice.**

A person is someone dropping off ceramics (on their phone, at the studio, signed in to
nothing), a member of ceramics staff working in the console (at a desk, or on a phone
or tablet at the kiln), or the maintainer who looks after the app. They notice through
the drop-off form, the ID on screen, an email and its photos, the console's lists and
pages, a setting that takes effect, or a refusal with a message. A story is not a
technical task.

**Reject:**

- "Add a drop-offs table": internal.
- "Set up the S3 bucket": infrastructure.
- "Add an email adapter": nobody notices an adapter; the story is that the email
  arrives, from the right address, with the photos.
- "Make the console better": not testable as written.

Internal work becomes acceptance criteria on the visible story it enables, and phases in
`/plan-tech`.

- **Split by outcome, not by layer.** Not "the model" and "the page", but "staff add a
  drop-off to a load by scanning its ID" and "staff mark a load fired and people are
  told".
- **Too large:** a story that would take more than one to three phases of work (about a
  week). Propose the split before writing criteria: "This covers several changes people
  would notice separately: [1], [2], [3]. Proceed with this split?"
- **Too small:** half a day that shares a flow with another story usually belongs in it.

Don't pad to reach a number. One story is fine for a small feature.

## Step 4: Draft the stories

Use the Domain Constraints Brief and the Overlap report: constraints become criteria,
dependencies become notes and ordering.

Each story body has exactly this shape (`/prep` reads the `- [ ]` lines under
`## Acceptance criteria`, so keep that heading and the checkboxes):

```markdown
## Story
As <role>, I want <capability>, so that <outcome>.

## Acceptance criteria
- [ ] <binary, testable statement>
- [ ] <3 to 7 in total>

## Notes
Priority: Must | Should | Could · Size: S | M | L · Epic: #<N>
<dependencies on other stories or issues, here or in another repository: "Needs #N.">
```

- **Priority:** Must = the feature is not usable without it. Should = real value, but it
  ships without it. Could = easy to defer.
- **Size:** S = half a day, M = one or two days, L = three to five days. Larger: split.
- **Criteria** are statements a person who hasn't read the code can answer yes or no,
  and they describe what someone sees: "After Submit the page shows an ID like `AC-1`",
  "A photo's storage address alone gets 'access denied'". Not "inserts a row" or "calls
  `send_email`".
- Cover the failure the person will actually hit: a field left out or mistyped, a photo
  too large or not a photo, the same form sent twice, an ID that isn't waiting, an email
  that fails to send, someone signed in who isn't ceramics staff, a setting changed
  while a load is being fired.
- A story that changes what the studio does day to day says how ceramics staff are told
  ahead, and a story that keeps or shows personal details says for how long and to whom.

The epic body:

```markdown
## Goal
<1–3 sentences: who gets what, and why now>

## Stories
- [ ] #<N> <title>        (filled in after Step 6)

## Work in other repositories
- [ ] <owner/repo#N or repository>: <what> (for #<story>)        (or "None")

## Decided
- <decisions already made, with the date>

## Out of scope
- <what this deliberately doesn't do>

## Open questions
- <questions only the maintainer can answer, or "None">
```

## Step 4b: Review the draft

Read `.claude/agents/plan-product/ac-reviewer.md` and adopt it. Input: every drafted
story and the Domain Constraints Brief. It returns WEAK, MISSING, SPLIT, CONFLICT and
GAP findings.

- **WEAK / MISSING:** fix the criteria. Never show the user criteria you know are weak.
- **CONFLICT:** resolve it between the stories.
- **SPLIT:** split the story and apply Step 3 again.
- **GAP:** draft a story for the missing flow, then review it too.

---

## Step 5: Present the draft

Show everything in one block before creating anything:

```markdown
## Draft: <feature name>

### Epic (greenfield only)
**Title:** <title>
<epic body>

---

### Story 1: <short title>
**Priority:** Must · **Size:** M
**Story:** As <role>, I want <capability>, so that <outcome>.
**Acceptance criteria:**
- [ ] ...
**Notes:** <dependencies>

---
<repeat>
```

Then ask:

> Type **create** to create these issues, or tell me what to change ("make story 2 a
> Could", "split story 3", "add a story for the weekly counts").

Go on only if the reply contains the word **create**. "Looks good" without "create" is
feedback: revise, show the whole draft again, and ask again. Don't apply part of the
feedback and start creating.

## Step 6: Create the issues

In this order. Retry a failed `gh` call up to 4 times (2, 4, 8, 16 seconds) before
treating it as a failure. Issues in other repositories are not created here: list them
in the epic for the maintainer to open, unless the user asks you to open them.

**6a. Labels** (only if missing):

```bash
gh label create epic  --color 5319E7 --description "A group of stories" 2>/dev/null || true
gh label create story --color 0E8A16 --description "One change a person can notice" 2>/dev/null || true
```

**6b. The epic** (greenfield only; additive mode uses #N):

```bash
gh issue create --title "<title>" --label epic --body-file <file>
```

**6c. Each story**, in dependency order, with `Epic: #<N>` in its Notes:

```bash
gh issue create --title "<title>" --label story --body-file <file>
```

**6d. Attach each story to the epic as a sub-issue.** The API takes the story's
numeric `id`, not its number:

```bash
ID=$(gh api repos/{owner}/{repo}/issues/<story> --jq .id)
gh api repos/{owner}/{repo}/issues/<epic>/sub_issues -X POST -F sub_issue_id="$ID"
```

If this still fails after the retries, carry on: the task list in the epic body is
enough. Say so in the report.

**6e. Update the epic's `## Stories` task list** with the story numbers
(`gh issue edit <epic> --body-file <file>`).

If creation fails partway, stop and report: "Created N of M stories before an error:
<links>. Add the rest with `/plan-product --epic <N> <use case>`." Don't create
duplicates by retrying blindly; list what exists first.

## Step 7: Report

```markdown
## Created: <feature name>

- Epic #<N>: <title> — <url>
- Story #<N>: <title> (Must, M) — <url>
- ...

Sub-issues: attached | not attached (<reason>); the epic's task list is up to date.
Work in other repositories to open: <list, or "none">.

### Next step
Run `/plan-tech <epic or story number>` to write the technical plan. It reads these
acceptance criteria and links each phase to the stories it delivers.
```

In additive mode: "Added #N, #M to epic #E. If they need new phases, run `/plan-tech
<plan-name>` and mention the new story numbers."

---

## Step 8: Discovery mode, the gap report

No GitHub writes in this mode. Read the plan, then the epic (the README's `epic:`
frontmatter; if there is none, search issues for the plan name) and every story.

Check:

- **Phases with no story.** A phase builds something a person can notice, and no story
  covers it.
- **Criteria gaps.** A phase builds behavior that its story's criteria don't test.
- **Stories with no phase.** Nothing in the plan builds toward them.

```markdown
## Discovery report: <plan name>

### Phases with no story (<count>)
1. **Phase <N>, <title>:** delivers <behavior>. No story covers it.

### Stories with criteria gaps (<count>)
1. **#<N>, <title>:** phase <X> builds <behavior>, but no criterion tests it.

### Stories with no phase (<count>)
1. **#<N>, <title>:** no phase implements it.

### Summary
<count> phases uncovered, <count> criteria gaps, <count> stories without a phase.
```

If nothing is missing, say: "Every phase maps to a story and every story has a phase."
Then offer: "To add stories for the gaps, run `/plan-product --epic <N> <use case>`, or
paste a gap here and I'll draft it." Discovery never edits a story's criteria or closes
an issue.
