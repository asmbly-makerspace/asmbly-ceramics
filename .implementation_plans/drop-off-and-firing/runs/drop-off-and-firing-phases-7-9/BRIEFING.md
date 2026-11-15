# Offshore briefing: drop-off-and-firing, phases 7 to 9

**Date:** 15 November 2026
**Result:** COMPLETE
**Run:** `drop-off-and-firing-phases-7-9` on `feat/drop-off-and-firing-phases-7-9` (worktree `.claude/worktrees/offshore-drop-off-and-firing-phases-7-9`; remove it after the merge with `git worktree remove .claude/worktrees/offshore-drop-off-and-firing-phases-7-9`)
**Pull request to main:** #33, green, draft until the run marks it ready (not merged)
**Phases done:** 3 of 3 selected (phases 7, 8 and 9 of the plan)
**Merging deploys:** yes: stage, then the smoke test, then prod. It fails at the change set until the "Before you merge" items are done.
**Environment:** uv ready, GitHub gh, jq yes, sam yes, AWS read access yes

> **Your next step:** review pull request #33, do the "Before you merge" items below, work
> through the by-story steps in `MANUAL_QA.md`, and merge when you're satisfied. The run
> never merges, never deploys and never runs the manual QA: all three are yours.
>
> If you started the run with `/loop`, stop the loop now (Esc, or "stop the loop"). Later
> fires do nothing, but there's no reason to keep them running.

---

## Run health

| Metric | Value |
| --- | --- |
| Total run time | 10h 52m (08:21 to 19:13 UTC) |
| Sub-agent retries | Not recorded in the checkpoint |
| Guardrail blocks | 2 (changing the session claims or the runs' state from the shell; changing the repository's settings, variables or secrets) |
| Phase review rounds | 7 (phase 7: 3, phase 8: 3, phase 9: 1) |
| Cold reviews | Phase 7: fixed. Phase 8: fixed. Phase 9: fixed. Whole branch: fixed |
| Pull request rounds | 0 |
| Commits on the branch | 6 (target: 3 phases + 3 + 0 pull request rounds = 6) |

## Phases

| Phase | Title | Status | Commit | Review rounds | Cold review | Time |
| --- | --- | --- | --- | --- | --- | --- |
| phase-7-first-deploy | First deploy: stage and prod | Done | `1266532` | 3 | fixed | 4h 48m |
| phase-8-console-waiting-and-reject | Console: sign-in, waiting list, rejection | Done | `8493547` | 3 | fixed | 2h 58m |
| phase-9-console-loads-settings-close | Console: loads, settings, counts, the close | Done | `40553ed` | 1 | fixed | 2h 23m |

After the phases: the final cold review fix is `10563be`, the docs are `1fb2307`, the manual QA document is `391a320`.

## Before you merge

- [ ] **Bootstrap stack (done):** `asmbly-ceramics-bootstrap` was created by the maintainer on 15 November 2026 (19 resources, certificates issued, termination protection on). Done when the stack shows as created.
- [ ] **GitHub environments (done):** `stage` and `prod` exist, limited to `main`.
- [ ] **Runbook steps 5 to 8 (not done):** step 5's scripts were prepared for the maintainer; the guardrail blocked the run from setting GitHub secrets itself. Do steps 5 to 8 in `docs/runbooks/` before merging, because a merge deploys.
- [ ] **Staff sign-in (asmbly-staff-login):** the `ceramics` group and the `ceramics-staff` client (scopes `openid`, `email`) must exist there. Done when the console sign-in works on stage.
- [ ] **Session key:** set the console's `session-key` parameter by hand.
- [ ] **Prod reviewer:** switch a required reviewer on for the `prod` environment, or plan to do the sign-in checks right after the prod deploy.
- [ ] **Sending right:** the maintainer agreed the app sends from `asmbly.org`. The SES identity lives in AsmblyMCPs' `mcp-bootstrap`; moving it (for example to staff-login) is the maintainer's separate task and needs no change here, since the identity is named, not an ARN.
- [ ] **Issue #20 question 2:** still open; answer it before merge. Question 1 is settled and merged in #29.

## After you merge

- [ ] Watch the deploy to stage, then the smoke test, then prod.
- [ ] Check that the close's alarms reach the alarm topic.
- [ ] Stage's first `close_run` must prove the `GSI1` `LeadingKeys` condition; the fallback is in phase 9's Rollout.
- [ ] If the prod reviewer is off, run the console sign-in checks after prod.

## Decisions made

- **Phase 5 as a dependency:** counted as done for building 7 to 9, because its code is merged (#28); only the hand-run bootstrap waits, which is a before-merge action.
- **Phase size:** no split below about 5,000 changed lines, because the maintainer accepted that on 13 November 2026. The repository still says 800.
- **Request bound:** a contextvar deadline plus botocore hooks (14s work, 22s cleanup), because the use cases are synchronous.
- **Action SHA pinning:** deferred to #31, because the SHAs could not be resolved in the run.
- **`requirements.txt` and Dependabot:** kept committed, and the CI error names the regeneration command, so `sam build` reproduces from the lock.
- **Console session:** a sealed cookie, because rotating the key signs everyone out.
- **JWKS refresh failure:** keep the held keys on refresh; the first fetch still fails closed, so a bad refresh doesn't sign out a valid session.
- **Decision 0004:** accepted by the maintainer in the conversation; the docs mark it accepted.
- **SES sending right:** see "Before you merge".
- **Close retries:** a function dead-letter queue plus an Errors alarm, because the Scheduler invokes asynchronously and an event invoke config needs a bootstrap change.
- **Mark fired:** asks to confirm first, because a double tap would email everyone twice.
- **Deleted-item label:** one answer, "a deleted item", from review.
- **Close Query scope:** `LeadingKeys` on `GSI1`, proven by stage's first close, because AWS's documentation is indirect.
- **Form paused:** the console serves `/console/static` and `/console/health`, and the smoke test has a form-offline mode, so the console works while the form is paused.

## Plan amendments

None.

## Deferrals and blockers

- **Action SHA pinning:** deferred to #31.
- **Own schedule group for the close:** needs a bootstrap change; later.
- **Other follow-ups opened in the run:** #30, #31 and #32.
- **Guardrail blocks:** the run could not set GitHub secrets itself; the step is the maintainer's (see "Before you merge").

## Skipped for the environment

None.

## Integration gate

- Result: clean
- Failures found and fixed: none
- Tests: 2797; coverage 99.15% against the floor in `pyproject.toml`

## Review summary

- Phase reviews: phase 7, 3 rounds; phase 8, 3 rounds; phase 9, 1 round.
- Cold reviews (`review-lead`, `privacy-guardian`): phase 7 review-lead APPROVED, privacy-guardian FLAG (no blocks); phase 8 APPROVED and CLEAR; phase 9 CHANGES REQUESTED (1 block, fixed) and CLEAR; whole branch APPROVED and CLEAR, with fixes applied.
- Pull request: no rounds yet.
- Findings fixed: not counted in the checkpoint. Answered without a change: not counted. Deferred: 2, listed above.

## Rollback

Before the merge, each phase and each pull request round is one commit on the branch, so
one revert drops one unit:

```bash
git log --oneline origin/main..feat/drop-off-and-firing-phases-7-9
git revert <sha>
```

After the merge, `main` holds the whole pull request as one squash commit; undo it with a
revert pull request, and, if it deployed, follow the undo in the plan's Rollout.

The branch has 6 commits, which matches the target in Run health.

## Action items for you

- [ ] Review pull request #33, work through `MANUAL_QA.md`, merge when ready.
- [ ] Before merge: finish runbook steps 5 to 8.
- [ ] Before merge: the `ceramics` group and `ceramics-staff` client in asmbly-staff-login.
- [ ] Before merge: set `session-key`.
- [ ] Before merge: decide the prod reviewer, or plan the sign-in checks after prod.
- [ ] Before merge: answer #20 question 2.
- [ ] After the first deploy: check the close alarms reach the alarm topic.
- [ ] After the first deploy: confirm stage's first `close_run` proves the `GSI1` `LeadingKeys` condition.
- [ ] Later: a bootstrap change for the close's own schedule group.
- [ ] Later: decide whether to move the SES identity out of `mcp-bootstrap`.
- [ ] Follow-up issues opened during the run: #30, #31, #32.
- [ ] Remove the worktree `.claude/worktrees/offshore-drop-off-and-firing-phases-7-9` after the merge.
- [ ] The repository's 800-line phase limit still conflicts with your accepted ~5,000; update the docs or the limit.
