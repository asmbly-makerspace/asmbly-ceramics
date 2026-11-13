# Offshore briefing: drop-off-and-firing, phase 1 (domain model)

**Date:** 2026-11-13
**Result:** COMPLETE
**Run:** `drop-off-and-firing-phase-1` on `feat/drop-off-and-firing-phase-1`
**Pull request to main:** #16 (https://github.com/asmbly-makerspace/asmbly-ceramics/pull/16), green, ready for your review (not merged)
**Phases done:** 4 of 4 selected (1a to 1d, split from the plan's phase 1)
**Merging deploys:** nothing (nothing reaches AWS)
**Environment:** uv ready, GitHub MCP tools (gh was not signed in), jq yes, sam no, AWS read access no

> **Your next step:** review pull request #16, do the "Before you merge" items below, work
> through the by-story steps in `MANUAL_QA.md`, and merge when you're satisfied. The run
> never merges, never deploys and never runs the manual QA: all three are yours.
>
> If you started the run with `/loop`, stop the loop now (Esc, or "stop the loop"). Later
> fires do nothing, but there's no reason to keep them running.

---

## Run health

Smooth: no retries, no guardrail blocks, one review round per phase.

| Metric | Value |
| --- | --- |
| Total run time | 2h 17m (16:43 to 19:00 UTC, from the checkpoint's first and last events) |
| Sub-agent retries | 0 |
| Guardrail blocks | 0 |
| Phase review rounds | 4 (one per phase) |
| Cold reviews | 1a fixed, 1b fixed, 1c fixed, 1d fixed, whole branch fixed |
| Pull request rounds | 0 |
| Commits on the branch | 7, plus this briefing (four phases, the final-review fixes, docs, manual QA) |

Each phase's own review, prep, critic and privacy steps ran inline in the phase
sub-agent, because it had no Agent tool. The cold reviews by `review-lead` and
`privacy-guardian` were the independent reads: after each phase, then over the whole
branch. The harness subscribed the orchestrator session to the pull request's activity
once; it was unsubscribed.

## Phases

| Phase | Title | Status | Commit | Review rounds | Cold review | Time |
| --- | --- | --- | --- | --- | --- | --- |
| phase-1a-domain-core-and-studio | Domain core: errors, IDs, limits, studio | Done | `fa4bbee` | 1 | fixed | 25m (includes prep and the split) |
| phase-1b-drop-offs-photos-outbox | Drop-offs, photos, outbox, closing | Done | `37e062f` | 1 | fixed | 21m |
| phase-1c-loads-waiting-search | Loads, waiting list, search | Done | `6cbf903` | 1 | fixed | 26m |
| phase-1d-ports-and-fakes | Ports and in-memory fakes | Done | `210e000` | 1 | fixed | 25m |

## Before you merge

- [ ] None. No admin action is needed before the merge.

## After you merge

- [ ] Nothing: a merge deploys nothing, and no admin action follows it.

## Decisions made

These were made unattended and need your word.

- **Firing type of a load:** a load refuses a firing-type change once it has members
  (`FiringTypeLocked`), instead of allowing it. This reverses a line in the plan and
  closes a hole in #4 where a mismatch could go unconfirmed.
- **Catalog items:** an item is deleted only once it is retired, so a delete can't race
  with a use of the item (phase 3 is to test this).
- **Settings history:** it never stores an address.
- **Rate limit:** a rolling window, not a fixed one.
- **Keeping a drop-off:** keep is all-or-nothing, and any commit failure calls
  `delete_drop_off`. Phases 4 and 7 must give the form `DeleteObject` rights plus a
  backstop for what a failed cleanup leaves.
- **Rejection message:** control characters are stripped, not refused.
- **Name search:** it folds NFC and casefold, and drops Cf (format) characters.
- **Merge request mid-run:** you asked "merge when green". The run did not merge, because
  offshore never merges and its guardrail blocks it. The pull request is left open and
  green.

## Plan amendments

- **phase-1a, 1b, 1c, 1d (new):** split from phase-1-domain-model because prep estimated
  about 2,000 lines against the size rule's 800 for an L phase.

## Deferrals and blockers

Findings left for later phases' `/prep`:

- **Settings use-count and index port shape:** phases 3 and 4 decide it.
- **Retention backstop for a fired drop-off whose ready email never sends:** your call.
- **Pending-email staleness, and `mark_cancelled` on FAILED:** not handled yet.
- **A rejected drop-off closes on the window even if its email never sent**, and close
  doesn't check the window itself.
- **`delete_item` race:** now solved by retired-only delete; phase 3 is to test it.
- **Phase 7 mailer:** `UpdateItem` against "Update means replace" needs a look.
- **Phase 8 search:** search text would sit in a GET query string. Prefer POST or
  no-referrer.
- **Phase 2 hasher:** use `NewType` keys.
- **Phase 4 sign-in:** the `NotAllowed` username must come from `cognito:username`. Also
  check the slot id shape in phase 4.
- **Import boundary:** add tests that nothing under `entry/` or `web/` imports
  `adapters.memory`.

## Skipped for the environment

- **sam and AWS read access:** not available in the run. Nothing in phase 1 needed them,
  since nothing reaches AWS.
- **`gh`:** not signed in; the GitHub MCP tools opened the pull request instead.

## Integration gate

- Result: clean
- Failures found and fixed: none
- Tests: 1169 passed (checkpoint's count); coverage 99.50% against the floor in
  `pyproject.toml`

## Review summary

- Phase reviews: one round each for 1a, 1b, 1c and 1d.
- Cold reviews (`review-lead`, `privacy-guardian`): 1a review-lead approved (3 WARN),
  privacy approved. 1b review-lead approved (6 WARN), privacy asked for changes (1 WARN),
  fixed. 1c review-lead found one doc BLOCK, fixed, re-review approved; privacy approved.
  1d review-lead approved (6 WARN, fixed); privacy approved. Whole branch: review-lead
  approved (10 WARN: 7 fixed, 3 deferred); privacy approved.
- Pull request: no comments.
- Findings fixed: the phase WARNs and the 7 of the final 10 above. Deferred: 3 from the
  final review, listed above, plus the later-phase items.

## Rollback

Before the merge, each phase and each pull request round is one commit on the branch, so
one revert drops one unit:

```bash
git log --oneline origin/main..feat/drop-off-and-firing-phase-1
git revert <sha>
```

After the merge, `main` holds the whole pull request as one squash commit; undo it with a
revert pull request. Nothing deployed, so there is no rollout to undo.

main gained one dependency commit (#15) after the branch was cut. The branch merges
cleanly with it; no rebase was done.

## Action items for you

- [ ] Review pull request #16 to main. It touches no AWS, no page and no email; the
  riskiest parts are the domain rules for personal details (closing, rejection message
  handling, retention) in phase 1b and the ports in phase 1d.
- [ ] Work through `MANUAL_QA.md` (21 steps, all local; there is no user-facing surface).
- [ ] Confirm or reverse the decisions listed under "Decisions made", starting with
  `FiringTypeLocked`, which reverses a plan line.
- [ ] Read the deferred findings above before each later phase's `/prep`; the retention
  backstop for a fired drop-off whose ready email never sends is your call.
- [ ] Merge when ready, outside the run. This probably needs your `--admin` bypass, which
  is used only on your word for this pull request.
