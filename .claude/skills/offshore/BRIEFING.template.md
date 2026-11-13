# Offshore briefing: <plan title>

**Date:** <date>
**Result:** <COMPLETE | STOPPED: one-line reason>
**Branch:** `feat/<plan>`
**Pull request to main:** #<N>, green, ready for your review (not merged) | #<N>, draft, stuck: <reason> | none: <reason>
**Phases done:** <N> of <selected> selected (<total> in the plan)
**Merging deploys:** nothing | <what a merge deploys, to which environment>
**Environment:** uv <ready | failed>, GitHub <gh | none>, jq <yes | no (the hook read with awk)>, sam <yes | no>, AWS read access <yes | no>

> **Your next step:** review pull request #<N>, do the "Before you merge" items below, work
> through the by-story steps in `MANUAL_QA.md`, and merge when you're satisfied. The run
> never merges, never deploys and never runs the manual QA: all three are yours.
>
> If you started the run with `/loop`, stop the loop now (Esc, or "stop the loop"). Later
> fires do nothing, but there's no reason to keep them running.

---

## Run health

| Metric | Value |
| --- | --- |
| Total run time | <Xh Ym> |
| Sub-agent retries | <count, or 0> |
| Guardrail blocks | <count of BLOCK lines in `.offshore/guardrails.log`, or 0> |
| Phase review rounds | <total across phases> |
| Cold reviews | <per phase and final: clean / fixed / stuck> |
| Pull request rounds | <N> |
| Commits on the branch | <N> (target: phases + 3 + pull request rounds, plus at most 4) |

## Phases

| Phase | Title | Status | Commit | Review rounds | Cold review | Time |
| --- | --- | --- | --- | --- | --- | --- |
| phase-1-<slug> | <title> | Done | `<sha>` | 2 | clean | 41m |
| phase-2-<slug> | <title> | Blocked (see below) | parked on `offshore/<plan>/phase-2-<slug>` | 0 | — | 18m |
| phase-3-<slug> | <title> | Skipped: depends on phase 2 | — | — | — | — |
| phase-4-<slug> | <title> | Not selected for this run | — | — | — | — |

## Before you merge

- [ ] <each admin action the plan puts before the merge: who does it, what, where (a
  runbook in `docs/runbooks/`, another repository's issue), and how to tell it's done.
  "None" if there are none.>

## After you merge

- [ ] <what the merge deploys and the smoke test to watch, from the plan's Rollout; each
  admin action the plan puts after the merge. "Nothing: a merge deploys nothing yet" if
  that is true.>

## Decisions made

- **<topic>:** chose <X> over <Y> because <reason>. See `<path>:<line>`.

## Plan amendments

- **<phase-id> (new):** split from <phase-id> because <reason>.
- **<phase-id> amended:** <what prep changed and why>.

## Deferrals and blockers

- **<item>:** <context in one or two sentences>. Options: (a) ... (b) ... Recommendation: ...
  Earlier attempt: `git log --oneline origin/main..offshore/<plan>/<phase-id>`.

## Skipped for the environment

- **<check>:** skipped because <reason>. Run it with: `<command>`.

## Integration gate

- Result: <clean | fixes applied | stuck>
- Failures found and fixed: <list, or "none">
- Tests: <N passed, as pytest printed it>; coverage <NN%> against the floor in
  `pyproject.toml`

## Review summary

- Phase reviews: <per phase: rounds and final verdict, APPROVED or CHANGES REQUESTED>
- Cold reviews (`review-lead`, `privacy-guardian`): <per phase and for the whole branch:
  clean, fixed (what kind of finding, never a person's detail), or stuck>
- Pull request: <rounds; comments fixed and answered; or "no comments">
- Findings fixed: <N>. Answered without a change: <N>. Deferred: <N>, listed above.

## Rollback

Before the merge, each phase and each pull request round is one commit on the branch, so
one revert drops one unit:

```bash
git log --oneline origin/main..feat/<plan>
git revert <sha>
```

After the merge, `main` holds the whole pull request as one squash commit; undo it with a
revert pull request, and, if it deployed, follow the undo in the plan's Rollout.

If the branch has far more commits than the target in Run health, a squash step was
skipped (see "Squash recipe" in the offshore skill).

## Action items for you

- [ ] Review pull request #<N> to main, especially <the riskiest change, with a path and
  lines: anything that stores, shows, emails or logs a person's details or photos, the
  public form's checks, the console's access check, IAM>.
- [ ] Work through `MANUAL_QA.md`.
- [ ] <each blocked, review-stuck, or skipped phase, and what it needs from you>
- [ ] <missing tools, leftover stashes, doc regressions, a stuck pull request>
- [ ] <follow-up issues opened during the run, by number>

<!--
Briefing rules. Keep them: the maintainer reads this first thing.

- No essays. Each bullet is one or two sentences.
- Every section stays, even when empty: write "None". This matters most for Before you
  merge, Decisions made, Deferrals and blockers, and Skipped for the environment.
- Run health is mandatory. If everything went smoothly, say so.
- Action items are specific and checkable. Not "review the code", but "Review #42,
  especially the photo size check in `src/asmbly_ceramics/web/drop_off.py:85-120`".
- Report what happened, from the checkpoint and the logs. Never estimate a number.
- This file is public: drop-offs by ID (AC-12), staff by username, no person's name,
  email, phone number, rejection message or photo, no account ID, no internal address.
-->
