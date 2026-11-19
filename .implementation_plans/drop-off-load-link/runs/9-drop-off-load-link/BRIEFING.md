# Offshore briefing: link a drop-off's page to its load

**Result:** the work is complete; the pull request is open, not merged.

## What was done

- The console's drop-off page shows "Load: L-n", linking to `/console/loads/L-n`, whenever
  the drop-off has a load (in a load, fired, or closed). Waiting drop-offs show nothing.
- 3 tests added in `tests/web/console/test_dropoffs.py`.
- Gate: ruff, ruff format, mypy and the full pytest run passed (3896 tests, 99.34%).
- Cold reviews: review-lead APPROVED (no BLOCK or WARN); privacy-guardian CLEAR.

## Decisions

- No plan was written (plan-product, plan-tech and prep skipped): a one-line template
  change, built and checked before the run started.
- The pull request's head is `ccr-9f25ab82-thi7rd`, not `feat/<run>`: this session may
  push only to that branch.
- The run slug `9-drop-off-load-link` is only a name; `9` is not an issue number. The
  commit says `Refs #3`.
- Reviewer notes not acted on: the load ID shows twice (state line and new line); the
  link is gated on `load_id`, not `view.load`; closed drop-offs also show the link (not
  tested).

## Action items

- Review the pull request, work through `MANUAL_QA.md`, merge when ready. Merging
  deploys stage then prod (Deploy workflow); the undo is a revert pull request.
- Nothing in AWS or in other repositories needs doing.
