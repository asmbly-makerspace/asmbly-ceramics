# Implementation plans

A plan says how a piece of work is built, in phases. `/plan-tech` writes it, and
`/prep` checks a phase against the code before it is built. The stories it delivers live
in GitHub Issues, written by `/plan-product`.

The rules in [`CLAUDE.md`](../CLAUDE.md) win over a plan. When a plan asks for something
the rules forbid (a public photo, a name outside the `asmbly-ceramics-` prefix, a
person's details in a log, AWS code inside the domain model), say so and follow the
rules.

Plans are public like the rest of the repository: no account IDs, no secrets, no real
person's details, no internal addresses.

## Layout

```
.implementation_plans/<plan-name>/
├── README.md              # overview, stories, phase tracker, dependencies
├── phase-1-<slug>.md      # one document per phase
└── phase-2-<slug>.md
```

- The plan name is kebab-case and says what the work is: `drop-off-and-firing`,
  `kiln-schedule`. No "plan" or "implementation" in it.
- Phase files are `phase-N-<slug>.md`; sub-phases are `phase-Na-<slug>.md`.
- No screenshots or other images in a plan folder.
- When every phase is on `main`, move the folder to `DONE/` in a `chore:` pull request.

## README.md

Start with this frontmatter when the plan has an epic. Leave it out entirely when it
doesn't (legacy mode): no empty block, no `epic: null`.

```yaml
---
plan: drop-off-and-firing
epic: 1             # the epic issue's number
---
```

Then these sections:

- `# <Name>: implementation plan` and `**Created:** YYYY-MM-DD`.
- `## Overview`: the problem and the outcome, in a few sentences.
- `## Domain model`: the entities, their states and the rules between them that this
  plan adds or changes, and the ports (storage, photos, email, sign-in, clock, IDs) it
  uses or adds. A plan that adds a feature says how it fits the existing model without
  reworking it.
- `## Stories`: one row per story issue: `| Story | Title | Phases |`. A story that
  more than one phase delivers lists them all. Only the pull request that lands the
  last phase in that cell says `Closes #N`; earlier ones say `Refs #N`.
- `## Phase tracker`: `| Phase | Title | Domain | Size | Status |`, with Status
  `[ ] Pending` (written by `/plan-tech`), `[~] In progress` (set when work on the phase
  starts), or `[x] Complete` (set when it is merged and, if it reaches AWS, confirmed).
- `## Dependencies`: what must exist first (other plans, issues in other repositories,
  by-hand steps), and which phases depend on which.
- `## Parallelism`: for each pair of phases with no dependency between them, whether
  they can run at the same time, and the shared files or AWS resources that decide it.
- `## Admin actions`: everything a person with admin rights must do, and when: a stack
  deployed by hand, a GitHub environment or variable, a DNS record in a zone this
  repository doesn't own, a change in another repository, telling ceramics staff. Write
  "None" if there are none.
- `## Rollout`: the order in which phases reach the live app, and how people are told.
  Write "Nothing reaches AWS" if that is true.
- `## Related work`: other plans, open issues or pull requests (here, in
  asmbly-staff-login, in AsmblyMCPs, in the facilities repository) that touch the same
  resources or depend on this work. "None" if there are none.
- `## Out of scope` and `## Security` (personal data, photo privacy, the public form,
  who can open the console, email).

## Phase documents

Start with this frontmatter when the plan has an epic; leave it out in legacy mode.

```yaml
---
phase_id: 2                  # from the file name: 2, 2a
title: The drop-off form
epic: 1
implements: [2]              # story issues this phase contributes to; [] for pure infrastructure
depends_on: [1]              # phase_ids in this plan; direct predecessors only
domain: [app, web]           # any of: app, web, infra, ci, docs
estimated_size: M            # S (<150 lines), M (<400), L (<800); larger means split it
---
```

Then these sections:

- `# Phase N: <title>` and `> **Status:** [ ] Pending`.
- `## Required reading`: the documents and the existing code to read first, including
  the closest existing example to copy (here, or in a sibling repository).
- `## Goal`: what is true when this phase is done.
- `## Files to create` and `## Files to modify`: exact paths, and for each, what changes.
- `## Implementation details`: by domain.
  - **app:** the domain types and their rules, the use cases with their inputs, outputs
    and failures, the ports they call and the adapters and fakes that implement them,
    with signatures and type hints. What is logged (IDs and usernames only).
  - **web:** each page or endpoint: who may reach it (anyone, or the `ceramics` group),
    what it accepts and how each field is checked on the server, what it shows for each
    outcome, and how it works on a phone.
  - **infra:** resources with their logical IDs and names (`asmbly-ceramics-…`), tags,
    `DeletionPolicy`, IAM statements with their resources and conditions, parameters,
    outputs, and the deploy role's rights it needs.
  - **ci / docs:** what changes and why.
- `## Tests`: each test, by name, with what it proves. Every failure path a person can
  hit gets one.
- `## Acceptance criteria`: checkable statements, each traced to a story's criterion
  where there is one.
- `## Verification`: the commands from `CLAUDE.md` that apply, and how to see it work
  in production after the merge (what to open, what to submit with made-up details,
  and what should happen).
- `## Rollout`: for a phase that changes anything in AWS: what is done, the check that
  shows it worked, who confirms it, and the undo. "Nothing reaches AWS" otherwise.
- `## Admin actions`: this phase's share of the README's list, or "None".
- `## Hand-off`: filled in when the phase is done: what the next phase can rely on.
