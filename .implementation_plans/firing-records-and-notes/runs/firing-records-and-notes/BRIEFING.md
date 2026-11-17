# Offshore briefing: firing records and notes

**Date:** 2026-11-17
**Result:** COMPLETE
**Run:** `firing-records-and-notes` on `feat/firing-records-and-notes`
**Pull request to main:** #44 (https://github.com/asmbly-makerspace/asmbly-ceramics/pull/44), draft until the orchestrator marks it ready after this briefing lands. PR check, Python and Templates are green on the head before the briefing commit. No review comments yet. The only thing blocking the merge is a code owner's review.
**Phases done:** 9 of 9 selected (9 in the plan)
**Merging deploys:** yes. `deploy.yml` deploys stage, runs the smoke test against the stage site, then deploys prod and runs it against the prod site. Undo is a revert pull request. Phase 4 changes the console role's two IAM conditions in `infra/app.yaml` (`QueryByPartition` for `LOAD#*`, `CountIds` for `COUNTER#note`); there are no new resources.
**Environment:** uv ready, GitHub gh (API), jq yes, sam no, AWS read access no

> **Your next step:** review pull request #44, do the "Before you merge" items below, work
> through the by-story steps in `MANUAL_QA.md`, and merge when you're satisfied. The run
> never merges, never deploys and never runs the manual QA: all three are yours.
>
> If you started the run with `/loop`, stop the loop now (Esc, or "stop the loop"). Later
> fires do nothing, but there's no reason to keep them running.

---

## Run health

| Metric | Value |
| --- | --- |
| Total run time | 5h 53m (2026-11-16 19:17Z to 2026-11-17 01:10Z) |
| Sub-agent retries | 1 (phase 5's first agent was lost when the container restarted; a new agent resumed from its commits). The container restarted twice in all. |
| Guardrail blocks | 1 (`.offshore/firing-records-and-notes/guardrails.log`): creating the pull request through the REST API was blocked by the hook; the draft was opened with the GitHub tool instead. |
| Phase review rounds | 17 (1, 1, 2, 1, 3, 2, 2, 2, 3) |
| Cold reviews | Every phase and the final branch review: fixed. No phase stuck. |
| Pull request rounds | 0 |
| Commits on the branch | 15: 3 plan commits that came with the branch, 9 phases, the final review fixes, the docs and the manual QA. The briefing commit makes 16. |

All phase agents ran prep, build and review inline, because they had no Agent tool. That is
why the orchestrator ran independent cold reviews (`review-lead` and `privacy-guardian`)
after each phase. A subagent also subscribed the session to #44's events; the orchestrator
unsubscribed.

## Phases

| Phase | Title | Status | Commit | Review rounds | Cold review | Time |
| --- | --- | --- | --- | --- | --- | --- |
| phase-1-load-record-and-steps | The load: test firings, who moved it, the firing record | Done | `6c72632` | 1 | fixed (3 WARN) | 33m |
| phase-2-studio-cones-clays-programs-counts | The studio: cones, clay bodies, default programs, kiln counts | Done | `509132d` | 1 | fixed (3 WARN) | 34m |
| phase-3-load-history-and-notes-domain | The domain: a load's history and firing notes | Done | `62814e0` | 2 | fixed | 37m |
| phase-4-records-events-notes-ranges | Records: events, notes and date ranges, in the fake and DynamoDB | Done | `ddf98c3` | 1 | fixed (3 WARN) | 27m |
| phase-5-use-cases-record-and-log | Use cases: test loads, history, the firing record, corrections, the firing log | Done | `b2f6d21` | 3 | fixed (7 WARN) | 37m |
| phase-6-console-load-page | Console: the load page's steps, firing record, test and history | Done | `21d16c4` | 2 | fixed (5 WARN; privacy flagged a missing test) | 31m |
| phase-7-console-firing-log-and-settings | Console: the firing log, its CSV, and the new settings | Done | `5db368b` | 2 | fixed (a BLOCK) | 40m |
| phase-8-use-cases-notes | Use cases: firing notes | Done | `7ec99d3` | 2 | fixed (6 WARN) | 27m |
| phase-9-console-notes | Console: notes on a load and the notes search | Done | `410d320` | 3 | fixed (a BLOCK) | 50m |

## Before you merge

- [ ] A code owner's approving review of #44 (not given). The pull request is opened under
  the maintainer's account, so it can only merge with his bypass, which CLAUDE.md allows only
  on his word.
- [ ] Confirm that CI's PR check ran `sam validate --lint` and `sam build` on `infra/app.yaml`. The run could not (sam is not installed here); CI is green, but check the steps ran.
- [ ] Decision record 0007 is proposed. Accept it, change it or reject it before the merge.

## After you merge

- [ ] Watch both smoke tests to the end: stage, then prod. Phase 4 changes two IAM conditions in `infra/app.yaml`, so open a load page and the settings page on stage once the stage deploy is done.
- [ ] Do the stage walk-through on a phone: an empty test load, fire, record, correct the time, history, a note, the notes search and the firing log with its CSV.
- [ ] Enter each kiln's counts once.
- [ ] Check each firing type's default program.
- [ ] Tell ceramics staff about the firing record, the firing log and kiln counts, and notes and the notes search.
- [ ] Flip the plan tracker to `[x]` for phases 1, 2, 4, 5, 6, 7 and 9, each after its stage check passes. Phases 3 and 8 reach no AWS resource by themselves.

## Decisions made

- **Work:** ran plan `firing-records-and-notes` (all 9 phases), found on the branch the run was given, because that branch held only that plan. See `CHECKPOINT.json`, first `decision` event.
- **Story closing:** phase 7 refs #42; phase 9 closes #17 and #42, because #42's firing-log criterion includes the notes count column built in phase 9. See `CHECKPOINT.json`.
- **Product calls left to you:** the firing-number suggestion prefill, whether an empty test firing counts, and whether removed notes keep their text. These are story-wording decisions. See "Action items".
- **Pull request subscription:** the orchestrator unsubscribed the session from #44's activity, by the rule that the orchestrator holds no PR subscriptions.

## Plan amendments

None.

## Deferrals and blockers

None blocked. Open product calls and follow-ups are in "Action items for you".

## Skipped for the environment

- **`sam validate --lint -t infra/app.yaml` and `sam build -t infra/app.yaml`:** skipped because the sam CLI is not installed. Run it with: `sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml`.
- **AWS read access:** not available in this run, so nothing was checked against the account.

## Integration gate

- Result: clean
- Failures found and fixed: none
- Tests: 3723 tests; coverage 99.30% against the floor in `pyproject.toml`. The sam steps were skipped (see above).

## Review summary

- Phase reviews: rounds per phase 1, 1, 2, 1, 3, 2, 2, 2, 3; all ended APPROVED.
- Cold reviews (`review-lead`, `privacy-guardian`): every phase fixed. Two BLOCKs (phases 7 and 9) and many WARNs were fixed. The final branch review was APPROVED with 0 BLOCK and 7 WARN, fixed. `privacy-guardian` flagged one WARN on the final review: removed notes keep their text. It is deferred to you.
- Pull request: no comments, 0 rounds.
- Findings fixed: 2 BLOCK and the WARNs listed above (the checkpoint counts 3, 3, 3, 7, 5, 6 for phases 1, 2, 4, 5, 6, 8 and 7 for the final review; phases 3, 7 and 9 did not record a count). Answered without a change: 0. Deferred: 1 (the removed-notes WARN), plus the follow-ups below.

## Rollback

Before the merge, each phase and each pull request round is one commit on the branch, so
one revert drops one unit:

```bash
git log --oneline origin/main..feat/firing-records-and-notes
git revert <sha>
```

After the merge, `main` holds the whole pull request as one squash commit; undo it with a
revert pull request, and, if it deployed, follow the undo in the plan's Rollout.

The branch has 15 commits against a target of 12 plus at most 4, so no squash step was skipped.

## Action items for you

- [ ] Review pull request #44 to main, especially `infra/app.yaml` (the console role's `QueryByPartition` `LOAD#*` and `CountIds` `COUNTER#note` conditions: IAM) and the notes feature (phases 8 and 9), which stores free text that a person may type a name into.
- [ ] Work through `MANUAL_QA.md`.
- [ ] A code owner's approving review is needed to merge; it has not been given.
- [ ] Your word is needed to merge (CLAUDE.md); the run did not merge.
- [ ] After the merge's deploy: watch the stage and prod smoke tests and do the stage walk-through.
- [ ] After the merge: enter each kiln's counts once, and check each firing type's default program.
- [ ] After the merge: tell ceramics staff about the firing record, the log and the notes.
- [ ] After the merge: flip the trackers of phases 1, 2, 4, 5, 6, 7 and 9 to `[x]`.
- [ ] Decision record 0007 is proposed and needs your decision.
- [ ] Product calls: (a) firing-number suggestions are prefilled as real values on a loading load, so two loads on one kiln get the same number; (b) whether an empty unnumbered test firing counts toward firing numbers; (c) removed notes keep their text, so a name typed into a note stays stored.
- [ ] The plan documents carry a claude.ai design link. It is already in the public issue bodies; decide whether it stays.
- [ ] Read the diff of `CLAUDE.md` and the agent kit (`.claude/`): the edits are additions only.
- [ ] Confirm CI ran the sam validate and build steps (the run could not).
- [ ] Open issues for the follow-ups: #32 (settings and firing view read per render; already open), the note double-tap duplicate, the note form's field cap above 20 items per list, fall-back-hour handling, a CSV byte-order mark for Excel, and the "New elements" confirm being a reveal.
- [ ] Remove nothing: no worktree was used, and no parked branch exists.

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
