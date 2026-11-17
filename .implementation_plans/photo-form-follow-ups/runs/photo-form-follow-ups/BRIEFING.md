# Offshore briefing: photo-form-follow-ups

**Date:** 2026-11-17
**Result:** COMPLETE
**Run:** `photo-form-follow-ups` on `claude/wizardly-bell-u8y238` (the session branch, restarted from `main` after the earlier pull request #52 merged; no worktree)
**Pull request to main:** #54 (https://github.com/asmbly-makerspace/asmbly-ceramics/pull/54), green on head `2898e92` before this briefing commit, to be marked ready for your review (not merged)
**Phases done:** 2 of 2 selected (2 in the plan)
**Merging deploys:** The Deploy workflow runs on any merge to `main`, but no application file, template, workflow or AWS resource changed in this branch, so it redeploys the same app.
**Environment:** uv ready, GitHub the GitHub tools (`gh` was not signed in), jq yes, sam no, AWS read access no

> **Your next step:** review pull request #54, do the "Before you merge" items below, work
> through the by-story steps in `MANUAL_QA.md`, and merge when you're satisfied. The run
> never merges, never deploys and never runs the manual QA: all three are yours.
>
> If you started the run with `/loop`, stop the loop now (Esc, or "stop the loop"). Later
> fires do nothing, but there's no reason to keep them running.

---

## Run notes

- The run's branch is the session branch `claude/wizardly-bell-u8y238`, not `feat/<run>`, because the session may push only to its own branch.
- `gh` was not signed in, so all GitHub work used the GitHub tools.
- You said in the conversation to merge this work; you merge after the run. The run itself never merges.

## Run health

| Metric | Value |
| --- | --- |
| Total run time | 2h 35m, from the first to the last checkpoint event (19:45 to 22:20 UTC) |
| Sub-agent retries | None recorded |
| Guardrail blocks | 0 |
| Phase review rounds | 2 (1 for phase 1, 1 for phase 2) |
| Cold reviews | Phase 1: clean. Phase 2: fixed. Final, whole branch: fixed |
| Pull request rounds | 1 |
| Commits on the branch | 7 before this briefing (target: 2 phases + 3 + 1 pull request round, plus at most 4) |

Everything went smoothly: no blocks, no stuck review, no parked branch.

## Phases

| Phase | Title | Status | Commit | Review rounds | Cold review | Time |
| --- | --- | --- | --- | --- | --- | --- |
| phase-1-agent-guidance-for-the-photo-inputs | The agents guidance describes the two photo inputs | Done | `70c7746` | 1 | clean (privacy-guardian skipped: docs only) | 20m |
| phase-2-upload-script-behaviour-tests | A behavioural test of the upload script | Done | `a981d77` | 1 | fixed | 39m |

## Before you merge

- [ ] None.

## After you merge

- [ ] Nothing new: a merge deploys stage then prod as always, and the same app is redeployed. Watch both smoke tests to the end.

## Decisions made

- **Branch:** chose the session branch `claude/wizardly-bell-u8y238` (restarted from `origin/main`) as the pull request head over `feat/<run>` because the session may push only to its own branch and #52 on it had already merged.
- **GitHub:** chose the GitHub tools over `gh` because `gh` was not signed in.
- **The upload script's test:** chose `node:test` running the script in `vm` on a stub of the page, started by pytest, with no CI change, over a browser or a JavaScript dependency, because it needs no dependency and no build step. Recorded as decision 0009 (proposed).
- **Node missing:** chose that the test fails rather than skips, because `CLAUDE.md` forbids skipped tests.
- **Privacy review of phase 1:** chose to skip `privacy-guardian` because the phase touched documents only.
- **Docs:** chose a Node 20+ note in `CONTRIBUTING.md` and nothing else, because the phases already updated the README, decision 0009 and its index row.
- **Pull request subscription:** the PR agent subscribed this session to #54 activity, because the session rule watches pull requests; the events are small, so it was kept.

## Plan amendments

- None.

## Deferrals and blockers

- **A test tying `photo_accept` in `form.html` to `FORMATS` in `adapters/images.py`:** nothing checks that the two photo inputs' accepted types agree with the formats the server inspects. Options: (a) add the test in a later pull request (b) leave it. Recommendation: (a).
- **Example names in `review/lead.md`:** it names `MAX_PHOTOS`, `domain/photos.py` and `web/upload.js` where the real names are `PHOTOS_MAX`, `domain/limits.py` and `web/static/upload.js`. Options: (a) fix the example (b) leave it. Recommendation: (a).
- **Cold NOTEs left unfixed:** smaller surviving mutants (the input cleared on a pick while busy, the preview image append, the `js` class, `showErrors([])` before an upload); pre-release Node versions fail the version check loudly; a Node on the runner image newer or older than 22.23.4 would change the TAP summary lines; `coder.md:131` wording about `getUserMedia`; `critic.md:49` still says the presigned POST type agrees with the domain. Options: (a) fix in a follow-up (b) accept. Recommendation: (b) except `critic.md:49`.
- **The phone check of the camera button on stage and prod (from the earlier pull request):** still not done by anyone. It needs an iPhone and an Android phone.

## Skipped for the environment

- **`sam validate` and `sam build`:** skipped because `sam` is not installed here and no template changed in this branch. Run it with: `sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml`.
- **Read-only AWS checks:** skipped because the run had no AWS read access and nothing reaches AWS.

## Integration gate

- Result: clean
- Failures found and fixed: none
- Tests: 3891 passed; coverage 99.34% against the floor in `pyproject.toml`

## Review summary

- Phase reviews: phase 1, 1 round, APPROVED; phase 2, 1 round, APPROVED.
- Cold reviews (`review-lead`, `privacy-guardian`): phase 1 clean (privacy skipped, docs only); phase 2 approved with privacy clear, 3 warnings fixed; whole branch approved with privacy clear, 3 warnings fixed.
- Pull request: 1 round; 0 comments fixed, 0 answered; the round ticked acceptance criterion 6 and recorded decision 0009 seen on the runner.
- Findings fixed: 6 warnings from the cold reviews (3 in phase 2, 3 in the final review). Answered without a change: 0. Deferred: the items listed above.

## Rollback

Before the merge, each phase and each pull request round is one commit on the branch, so
one revert drops one unit:

```bash
git log --oneline origin/main..claude/wizardly-bell-u8y238
git revert <sha>
```

After the merge, `main` holds the whole pull request as one squash commit; undo it with a
revert pull request. Nothing reaches AWS, so there is nothing else to undo.

## Action items for you

- [ ] Review pull request #54 to main, especially the new Node test of the upload script and the pytest wrapper that starts it (a test that fails, never skips, when Node is missing).
- [ ] Work through `MANUAL_QA.md`.
- [ ] Accept or reject decision 0009 (proposed).
- [ ] Add a Node preflight (`command -v node`, a no-Node rule beside the `sam` one) to `.claude/skills/offshore/SKILL.md`, and a Node line to "Done means verified" in `CLAUDE.md`. Not done here: you own the skill and rule files.
- [ ] Decide on the deferred test tying `photo_accept` in `form.html` to `FORMATS` in `adapters/images.py`.
- [ ] Fix the example names in `review/lead.md` (`PHOTOS_MAX`, `domain/limits.py`, `web/static/upload.js`), or leave them.
- [ ] Read the cold NOTEs left (see Deferrals) and decide which, if any, to take on.
- [ ] Run the phone check of the camera button on stage and prod from the earlier pull request, on an iPhone and an Android phone.
- [ ] Know that the PR agent subscribed this session to #54 activity.
- [ ] Follow-up issues opened during the run: none.

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
