# Offshore briefing: harden outgoing email

**Date:** 2026-11-17
**Result:** COMPLETE
**Run:** `harden-outgoing-email` on `feat/harden-outgoing-email` (worked in the main checkout, no worktree; the branch was renamed from the harness's `claude/*` session branch)
**Pull request to main:** #50 (https://github.com/asmbly-makerspace/asmbly-ceramics/pull/50), green (PR check, Python and Templates passed, including the first `sam validate` and `sam build`), no comments, no conflicts, ready for your review (not merged)
**Phases done:** 3 of 3 selected (3 in the plan)
**Merging deploys:** yes. The Deploy workflow deploys `asmbly-ceramics-stage`, then `asmbly-ceramics-prod`, and runs `scripts/smoke.py` against each (the smoke test submits nothing). The undo is a revert pull request ([the operations runbook](../../../../docs/runbooks/operations.md)).
**Environment:** uv ready, GitHub REST only (GraphQL blocked; the pull request was opened with the GitHub MCP tool), jq yes, sam no, AWS read access no

> **Your next step:** review pull request #50, do the "After you merge" items below, work
> through the by-story steps in `MANUAL_QA.md`, and merge when you're satisfied. The run
> never merges, never deploys and never runs the manual QA: all three are yours.
>
> The run did not merge: the user typed "merge when gren" mid-run, but the rules say a merge
> needs the maintainer's word for that pull request in the conversation. The maintainer or
> the user can ask for the merge of #50 afterwards.
>
> If you started the run with `/loop`, stop the loop now (Esc, or "stop the loop"). Later
> fires do nothing, but there's no reason to keep them running.

---

## Run health

| Metric | Value |
| --- | --- |
| Total run time | 2h 41m (05:15:49Z to 07:56:35Z) |
| Sub-agent retries | None recorded in the checkpoint |
| Guardrail blocks | 1 (a `gh api` POST to the pulls endpoint, at 07:52:35Z; the pull request was opened with the GitHub MCP tool instead) |
| Phase review rounds | 5 (phase 1: 1, phase 2: 1, phase 3: 3) |
| Cold reviews | Phase 1 fixed, phase 2 fixed, phase 3 fixed (stopped at the three-round cap), whole branch fixed |
| Pull request rounds | 0 (no comments) |
| Commits on the branch | 7 before this briefing's commit (target: 3 phases + 3 + 0 pull request rounds, plus at most 4) |
| PR subscription | The pull request sub-agent's own subscription to #50 was cancelled |

## Phases

| Phase | Title | Status | Commit | Review rounds | Cold review | Time |
| --- | --- | --- | --- | --- | --- | --- |
| phase-1-outbox-claim-recovery | The mailer: a claim whose outcome is unknown | Done | `bfef521` | 1 | fixed | 19m |
| phase-2-daily-cap-and-send-alarm | The form: a daily cap on received emails, and an alarm on the send volume | Done | `fc68e4b` | 1 | fixed | 35m |
| phase-3-per-recipient-limit | The form: a limit per recipient address | Done | `141409e` | 3 | fixed (capped) | 51m |

What each phase does:

- **Phase 1:** the mailer recovers a claim whose outcome is unknown. Closes #22; refs #21 (part 2).
- **Phase 2:** a daily cap of 300 received emails per environment per day, as a studio setting, plus one metric filter and an email-volume alarm. Closes #30.
- **Phase 3:** a limit of 3 drop-offs per recipient address per day, through a keyed hash. Closes #18.

After the phases: `4cb51a4` (fixes from the final cold review), `f6d3c0d` (docs), `8557a75` (manual QA document).

## Before you merge

- [ ] None. Nothing in the plan has to be done before the merge.

## After you merge

- [ ] Watch the Deploy workflow to the end: stage, its smoke test, then prod and its smoke test (`scripts/smoke.py`, which submits nothing).
- [ ] Stage checks, as the plan's README describes them. Use your own inbox. Phase 1: a received email arrives once. Phase 2: count stage drop-offs of the last 24 hours (N), set the cap to N+1, confirm the next one is refused, confirm the email-volume alarm exists, then set the cap back to 300. Phase 3: the 4th drop-off from one address is refused; this needs a second inbox or 24 hours.
- [ ] Set the three phase trackers to `[x]` once each stage check passes.
- [ ] Whoever talks to staff: tell them about the new setting (the daily cap) and the limit of 3 drop-offs per address a day.

## Decisions made

- **Plan front matter:** no epic or implements fields in the plan files.
- **Refused hits count against the cap (phase 2):** accepted as design and recorded in decision 0008, over not counting them, because it is an availability trade-off consistent with the device limiter and staff can raise the setting.
- **Phase 3 review cap:** stopped re-reviewing after three fix rounds; the whole-branch review covers it. The last BLOCK was a one-line docs inconsistency, fixed, and the whole-branch review re-read it.
- **`daily_cap` refusal level:** WARNING, with no second alarm, so it can't mask the shared logged-errors alarm. The email-volume alarm is the signal.
- **Follow-up:** opened #49 (rate limiter `PutItem` retry counts a hit twice) because it predates this branch.

## Plan amendments

- None.

## Deferrals and blockers

- **#21 parts 1 and 3, and #32:** not in this run; they stay open for a separate run.
- **Dedicated alarm for a slowly reached cap:** a cap reached slowly (under 100 emails an hour) closes the form with no alarm. Options: (a) accept it, (b) add a dedicated alarm. Recommendation: decide when you accept decision 0008.

## Skipped for the environment

- **`sam validate --lint` and `sam build`:** skipped locally because `sam` is not installed. CI ran them on #50 and they passed. Run them with: `sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml`.
- **AWS read checks:** skipped because the run had no AWS read access. Run them with: `AWS_PROFILE=asmbly`, region us-east-2, read-only commands only.

## Integration gate

- Result: clean
- Failures found and fixed: none at the gate. The whole-branch cold review then found one bug, fixed (see the review summary).
- Tests: 3834 passed; coverage 99.33% against the floor in `pyproject.toml`

## Review summary

- Phase reviews: phase 1, 1 round; phase 2, 1 round; phase 3, 3 rounds (the cap), last BLOCK a docs line, fixed.
- Cold reviews (`review-lead`, `privacy-guardian`): phase 1 fixed (4 test-gap warnings); phase 2 fixed (3 warnings); phase 3 fixed (capped at three rounds); whole branch: one BLOCK in the limiter, where a slow submit erased the hits of faster submits, so overlapping submits bypassed the limit. Fixed, and the re-review approved. Privacy review: clear every time.
- Pull request: no comments.
- Findings fixed: all of the above. Answered without a change: 0 recorded. Deferred: #49, and the open choice about a dedicated alarm, listed above.

## Rollback

Before the merge, each phase and each follow-up is one commit on the branch, so one revert
drops one unit:

```bash
git log --oneline origin/main..feat/harden-outgoing-email
git revert <sha>
```

The phase commits are `bfef521` (phase 1), `fc68e4b` (phase 2) and `141409e` (phase 3).
Phase 3 depends on phase 2, so revert phase 3 first.

After the merge, `main` holds the whole pull request as one squash commit; undo it with a
revert pull request ([the operations runbook](../../../../docs/runbooks/operations.md)).

## Action items for you

- [ ] Review pull request #50 to main, especially the per-recipient limit (phase 3: the keyed hash of the address and what is stored) and the limiter fix from the final review.
- [ ] Work through `MANUAL_QA.md`.
- [ ] Decide on decision 0008: its status is proposed and needs the maintainer's word before it becomes accepted.
- [ ] Trade-off for 0008: refused attempts keep an address (or the cap, or the form) closed for as long as they continue, and the console has no remedy for it.
- [ ] Trade-off for 0008: a refusal tells a caller who already knows an address that it was used 3 times in 24 hours.
- [ ] Trade-off for 0008: the keyed hash outlives a deleted or refused drop-off by about 2 days.
- [ ] Trade-off for 0008: a daily cap reached slowly (under 100 emails an hour) closes the form with no alarm. The `daily_cap` refusal logs at WARNING so it can't mask the shared logged-errors alarm; a dedicated alarm is an option.
- [ ] Stage checks and trackers: run the stage checks above after the merge, then set the three trackers to `[x]`.
- [ ] Staff: tell them about the new setting and the limit of 3 drop-offs per address a day.
- [ ] Missing tools: `sam` and AWS read access were unavailable locally; CI covered `sam`.
- [ ] Follow-up issue opened during the run: #49 (rate limiter `PutItem` retry counts a hit twice; predates this branch).
- [ ] #21 parts 1 and 3 and #32 stay open for a separate run.
- [ ] To merge #50, say so in the conversation: "Review pull request #50, work through MANUAL_QA.md, merge when ready".

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
